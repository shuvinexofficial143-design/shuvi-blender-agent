"""Level 7 M10: bounded animation QA, one-session recovery and source acceptance."""

from dataclasses import dataclass

from .animation import AnimationInspect
from .animation_keyframes import TRANSFORM_CHANNELS, AdvancedAnimationOperations
from .animation_nla import ManagedNLAOperations
from .animation_recipe_library import (
    AnimationRecipeAction,
    AnimationRecipeCatalog,
    AnimationRecipeLibraryOperations,
    RECIPE_SPECS,
)
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, string
from .verification import compare

MAX_RECOVERY_OBJECTS = 16


@dataclass(frozen=True)
class AnimationQAInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class AnimationRecoveryCapture:
    target: ObjectTarget
    expected_animation_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_animation_revision"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_animation_revision"], "expected_animation_revision", limit=64),
        )


@dataclass(frozen=True)
class AnimationRecoveryRestore:
    target: ObjectTarget
    expected_animation_revision: str
    recovery_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_animation_revision", "recovery_revision"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_animation_revision"], "expected_animation_revision", limit=64),
            string(data["recovery_revision"], "recovery_revision", limit=64),
        )


@dataclass(frozen=True)
class Level7Acceptance:
    recipe: AnimationRecipeAction

    @classmethod
    def parse(cls, data):
        return cls(AnimationRecipeAction.parse(data))


class AnimationAcceptanceOperations:
    def __init__(
        self,
        advanced: AdvancedAnimationOperations,
        recipes: AnimationRecipeLibraryOperations,
        nla: ManagedNLAOperations,
    ):
        self.advanced = advanced
        self.animation = advanced.animation
        self.inspector = advanced.inspector
        self.recipes = recipes
        self.nla = nla
        self._recovery = {}

    def _state(self, object_id):
        return self.animation.inspect(
            Request("animation.inspect", {"object_id": object_id}),
            AnimationInspect(object_id),
        ).data

    @staticmethod
    def _check(name, passed, reason):
        return {
            "name": name,
            "status": "PASS" if passed else "BLOCKED",
            "reason": None if passed else reason,
        }

    @staticmethod
    def _serial_snapshot(snapshot):
        return [
            {"data_path":path, "index":index, "points":snapshot[(path, index)]}
            for path, index in sorted(snapshot)
        ]

    @staticmethod
    def _frame_integrity(state):
        channels = state["channels"]
        mapping = [(channel["data_path"], channel["index"]) for channel in channels]
        topology = len(mapping) == 9 and set(mapping) == TRANSFORM_CHANNELS
        complete = bool(channels) and bool(state["unique_frames"])
        for channel in channels:
            frames = [point["frame"] for point in channel["points"]]
            if (
                len(frames) != len(set(frames))
                or sorted(frames) != state["unique_frames"]
                or len(frames) != channel["point_count"]
            ):
                complete = False
        bounded = all(
            frame.is_integer() and 1 <= frame <= 100_000
            for frame in state["unique_frames"]
        )
        return topology, complete, bounded

    def _evaluate(self, object_id):
        state = self._state(object_id)
        topology, complete, bounded = self._frame_integrity(state)
        checks = [
            self._check(
                "SESSION_OWNED_UNSHARED_ACTION",
                state["action_name"] is not None
                and state["managed_session_action"]
                and state["action_users"] == 1
                and state["action_api"] == "LEGACY",
                "No supported session-owned unshared legacy Action",
            ),
            self._check(
                "EXACT_NINE_TRANSFORM_CHANNELS",
                topology,
                "Transform channel set is partial, duplicated or foreign",
            ),
            self._check(
                "COMPLETE_UNIQUE_FRAME_KEYS",
                complete,
                "Each channel must have one key at every common frame",
            ),
            self._check(
                "BOUNDED_INTEGER_FRAMES",
                bounded and bool(state["unique_frames"]),
                "Frames must be unique integers in 1..100000",
            ),
            self._check(
                "MANAGED_MUTATION_SAFETY",
                state["managed_mutation_ready"] and not state["blockers"],
                "Animation mutation safety blockers are present",
            ),
            self._check(
                "SOURCE_RUNTIME_BOUNDARY",
                state["source_only"] is True and state["real_runtime_verified"] is False,
                "Source evidence cannot claim Blender runtime verification",
            ),
        ]
        result = {
            "object_id": object_id,
            "animation_revision": state["animation_revision"],
            "curve_count": state["curve_count"],
            "point_count": state["point_count"],
            "frame_count": state["unique_frame_count"],
            "nla_track_count": state["nla_track_count"],
            "blockers": state["blockers"],
            "checks": checks,
            "check_count": len(checks),
            "qa_status": "READY"
            if all(check["status"] == "PASS" for check in checks)
            else "BLOCKED",
            "scope": "SESSION_OWNED_TRANSFORM_ACTION_SOURCE_QA",
            "source_only": True,
            "real_runtime_verified": False,
            "production_ready": False,
        }
        result["qa_revision"] = revision(result)
        return result

    def qa_inspect(self, request: Request, action: AnimationQAInspect):
        data = self._evaluate(action.object_id)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def capture(self, request: Request, action: AnimationRecoveryCapture):
        obj, _object_before, before, curves = self.advanced._managed(
            action.target, action.expected_animation_revision
        )
        qa = self._evaluate(action.target.object_id)
        if qa["qa_status"] != "READY":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Action is not recovery-safe")
        if (
            action.target.object_id not in self._recovery
            and len(self._recovery) >= MAX_RECOVERY_OBJECTS
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Recovery capture limit reached")
        snapshot = self.advanced._snapshot(curves)
        token = revision(
            {
                "object_id": action.target.object_id,
                "animation_revision": before["animation_revision"],
                "snapshot": self._serial_snapshot(snapshot),
            }
        )
        self._recovery[action.target.object_id] = {
            "action": obj.animation_data.action,
            "snapshot": snapshot,
            "animation_revision": before["animation_revision"],
            "recovery_revision": token,
        }
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": action.target.object_id,
                "captured_animation_revision": before["animation_revision"],
                "recovery_revision": token,
                "curve_count": len(snapshot),
                "point_count": before["point_count"],
                "replaces_prior_capture_for_object": True,
                "scope": "IN_MEMORY_CURRENT_SESSION_MANAGED_ACTION_ONLY",
                "mutation_performed": False,
                "source_only": True,
                "real_runtime_verified": False,
            },
        )

    def restore(self, request: Request, action: AnimationRecoveryRestore):
        obj, object_before, before, curves = self.advanced._managed(
            action.target, action.expected_animation_revision
        )
        saved = self._recovery.get(action.target.object_id)
        if saved is None or saved["recovery_revision"] != action.recovery_revision:
            raise AgentError(ErrorCode.SAFETY_DENIED, "No matching current-session recovery capture")
        if saved["action"] is not obj.animation_data.action:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Captured Action identity no longer matches")
        if before["animation_revision"] == saved["animation_revision"]:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Animation already matches captured revision")

        prior_snapshot = self.advanced._snapshot(curves)
        expected = {
            "animation_revision": saved["animation_revision"],
            "snapshot": self._serial_snapshot(saved["snapshot"]),
        }
        after = None
        try:
            self.advanced._restore(obj, saved["snapshot"])
            after = self._state(action.target.object_id)
            actual = {
                "animation_revision": after["animation_revision"],
                "snapshot": self._serial_snapshot(
                    self.advanced._snapshot(self.advanced._curve_map(obj))
                ),
            }
            verification = compare(expected, actual)
            if verification.matched:
                self._recovery.pop(action.target.object_id, None)
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "object_before": object_before,
                        "before": before,
                        "after": after,
                        "capture_consumed": True,
                        "source_only": True,
                        "real_runtime_verified": False,
                    },
                    verification=verification.to_dict(),
                )
        except Exception:
            # Partial edits are possible even when a Blender adapter throws.
            verification = compare(expected, {"animation_revision": "RESTORE_INTERRUPTED"})

        # Never call a mismatched restore successful. Recover the immediate prior state.
        try:
            self.advanced._restore(obj, prior_snapshot)
            rolled = self._state(action.target.object_id)
            recovery = compare(
                {
                    "animation_revision": before["animation_revision"],
                    "snapshot": self._serial_snapshot(prior_snapshot),
                },
                {
                    "animation_revision": rolled["animation_revision"],
                    "snapshot": self._serial_snapshot(
                        self.advanced._snapshot(self.advanced._curve_map(obj))
                    ),
                },
            )
            if not recovery.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Recovery rollback readback mismatch")
        except Exception as exc:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Recovery restore failed; prior Action state cannot be verified",
            ) from exc
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "rolled_back": True,
                "recovery_verified": True,
                "capture_consumed": False,
            },
            AgentError(ErrorCode.VERIFICATION_FAILED, "Recovery target did not match capture"),
            verification.to_dict(),
        )

    def acceptance(self, request: Request, action: Level7Acceptance):
        recipe = action.recipe
        self.inspector.target(recipe.delegate.target)
        object_id = recipe.delegate.target.object_id
        qa = self._evaluate(object_id)
        require_revision(recipe.delegate.expected_animation_revision, qa["animation_revision"])
        catalog = self.recipes.catalog(
            Request("animation.recipe_catalog", {}), AnimationRecipeCatalog()
        ).data
        nla = self.nla._state(object_id)
        preview = None
        preview_error = None
        try:
            preview = self.recipes.timeline.preview(request, recipe.delegate).data
        except AgentError as exc:
            preview_error = exc.code.value
        catalog_valid = (
            catalog["library_version"] == 1
            and catalog["recipe_count"] == len(RECIPE_SPECS) == 3
            and {item["recipe_id"] for item in catalog["recipes"]} == set(RECIPE_SPECS)
            and all(item["recipe_version"] == 1 for item in catalog["recipes"])
        )
        checks = [
            self._check("TRANSFORM_ACTION_QA", qa["qa_status"] == "READY", "Transform QA blocked"),
            self._check("NO_UNMANAGED_NLA", nla["track_count"] == 0, "NLA strips require separate QA"),
            self._check("FIXED_VERSIONED_RECIPES", catalog_valid, "Versioned recipe catalog differs"),
            self._check(
                "FRESH_NONMUTATING_RECIPE_PREVIEW",
                preview is not None and preview["mutation_performed"] is False,
                preview_error or "Recipe preview was not ready",
            ),
            self._check(
                "SOURCE_RUNTIME_BOUNDARY",
                qa["real_runtime_verified"] is False
                and nla["real_runtime_verified"] is False
                and catalog["real_runtime_verified"] is False,
                "Source/runtime evidence boundary violated",
            ),
        ]
        result = {
            "object_id": object_id,
            "animation_revision": qa["animation_revision"],
            "qa_revision": qa["qa_revision"],
            "nla_revision": nla["nla_revision"],
            "catalog_revision": catalog["catalog_revision"],
            "recipe_id": recipe.recipe_id,
            "recipe_preview_revision": preview["workflow_revision"] if preview else None,
            "checks": checks,
            "check_count": len(checks),
            "source_acceptance_status": "READY"
            if all(check["status"] == "PASS" for check in checks)
            else "BLOCKED",
            "scope": "MANAGED_TRANSFORM_AND_RECIPE_SOURCE_ACCEPTANCE_ONLY",
            "other_slices_require_separate_evidence": [
                "POSE_BONE",
                "CAMERA_OPTICS",
                "CONSTRAINT_VISIBILITY",
                "NLA_PLAYBACK",
            ],
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
            "production_ready": False,
            "mutation_performed": False,
        }
        result["acceptance_revision"] = revision(result)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, result)

    def tools(self):
        return [
            Tool(
                "animation.qa_inspect",
                SafetyClass.READ_ONLY,
                AnimationQAInspect.parse,
                self.qa_inspect,
            ),
            Tool(
                "animation.recovery_capture",
                SafetyClass.READ_ONLY,
                AnimationRecoveryCapture.parse,
                self.capture,
            ),
            Tool(
                "animation.recovery_restore",
                SafetyClass.MUTATION,
                AnimationRecoveryRestore.parse,
                self.restore,
            ),
            Tool(
                "animation.level7_acceptance",
                SafetyClass.READ_ONLY,
                Level7Acceptance.parse,
                self.acceptance,
            ),
        ]
