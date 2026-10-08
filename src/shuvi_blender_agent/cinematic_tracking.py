"""Level 8 M6: managed TRACK_TO camera follows a changing subject orientation."""

from dataclasses import dataclass

from .cinematic_shots import CinematicShotOperations, ShotPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string
from .verification import compare

TRACK_NAME = "Shuvi_M6_Subject_Track"
TRACK_TYPE = "TRACK_TO"
TRACK_AXIS = "TRACK_NEGATIVE_Z"
UP_AXIS = "UP_Y"


@dataclass(frozen=True)
class TrackingPreview:
    shot: ShotPreview

    @classmethod
    def parse(cls, data):
        return cls(ShotPreview.parse(data))


@dataclass(frozen=True)
class TrackingApply:
    preview: TrackingPreview
    expected_tracking_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera",
                "subject",
                "azimuth_degrees",
                "elevation_degrees",
                "margin",
                "make_active",
                "expected_tracking_revision",
            },
        )
        return cls(
            TrackingPreview.parse(
                {key: val for key, val in data.items() if key != "expected_tracking_revision"}
            ),
            string(data["expected_tracking_revision"], "expected_tracking_revision", limit=64),
        )


@dataclass(frozen=True)
class TrackingRelease:
    camera: ObjectTarget
    expected_tracking_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"camera", "expected_tracking_revision"})
        return cls(
            ObjectTarget.parse(data["camera"]),
            string(data["expected_tracking_revision"], "expected_tracking_revision", limit=64),
        )


class CameraTrackingOperations:
    """Only the exact created constraint can be removed in this runtime session."""

    def __init__(self, objects: ObjectOperations):
        self.shots = CinematicShotOperations(objects)
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned: dict[str, tuple[object, object, str]] = {}

    def _plan(self, action: TrackingPreview):
        camera, subject, before, subject_before, base = self.shots._plan(action.shot)
        blockers = set(base["blockers"])
        # Avoid a dependency cycle where the target's own transform depends on
        # the camera that is about to track the target.
        parent = subject
        seen = set()
        for _ in range(32):
            if parent is None:
                break
            if parent is camera or id(parent) in seen:
                blockers.add("TARGET_CAMERA_PARENT_CYCLE")
                break
            seen.add(id(parent))
            if any(getattr(item, "target", None) is camera for item in parent.constraints):
                blockers.add("TARGET_DEPENDS_ON_CAMERA_CONSTRAINT")
            parent = parent.parent
        else:
            blockers.add("TARGET_PARENT_CHAIN_TOO_DEEP")
        if getattr(camera.data, "shift_x", 0) != 0 or getattr(camera.data, "shift_y", 0) != 0:
            blockers.add("NONZERO_CAMERA_LENS_SHIFT")
        if not hasattr(camera.constraints, "new") or not hasattr(camera.constraints, "remove"):
            blockers.add("OBJECT_CONSTRAINT_API_UNAVAILABLE")
        if before["object_id"] in self._owned:
            blockers.add("TRACKING_ALREADY_MANAGED")
        if not hasattr(self.bpy.context, "view_layer"):
            blockers.add("VIEW_LAYER_UNAVAILABLE")
        plan = dict(base)
        plan.pop("plan_revision")
        plan.update(
            {
                "base_shot_revision": base["plan_revision"],
                "constraint_name": TRACK_NAME,
                "constraint_type": TRACK_TYPE,
                "track_axis": TRACK_AXIS,
                "up_axis": UP_AXIS,
                "target_id": subject_before["object_id"],
                "subject_animation_present": subject.animation_data is not None,
                "follow_behavior": "EVALUATED_ORIENTATION_ONLY_CAMERA_POSITION_FIXED",
                "blockers": sorted(blockers),
                "ready": not blockers,
                "source_only": True,
                "real_runtime_verified": False,
                "evaluated_tracking_verified": False,
                "mutation_performed": False,
            }
        )
        plan["tracking_revision"] = revision(plan)
        return camera, subject, before, subject_before, plan

    @staticmethod
    def _readback(constraint, subject):
        return {
            "name": constraint.name,
            "type": constraint.type,
            "target_matches": constraint.target is subject,
            "track_axis": constraint.track_axis,
            "up_axis": constraint.up_axis,
            "mute": bool(constraint.mute),
            "influence": float(constraint.influence),
        }

    @staticmethod
    def _expected_constraint():
        return {
            "name": TRACK_NAME,
            "type": TRACK_TYPE,
            "target_matches": True,
            "track_axis": TRACK_AXIS,
            "up_axis": UP_AXIS,
            "mute": False,
            "influence": 1.0,
        }

    def preview(self, request: Request, action: TrackingPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[4]
        )

    def apply(self, request: Request, action: TrackingApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if plan["tracking_revision"] != action.expected_tracking_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera tracking plan changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe camera or subject tracking cycle")

        old_location = list(camera.location)
        old_rotation = list(camera.rotation_euler)
        old_active = self.bpy.context.scene.camera
        created = None

        def rollback():
            if created is not None:
                if created not in camera.constraints:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Tracking constraint identity lost"
                    )
                camera.constraints.remove(created)
            camera.location = old_location
            camera.rotation_euler = old_rotation
            self.bpy.context.scene.camera = old_active
            self.bpy.context.view_layer.update()
            if self.inspector.snapshot(camera)["revision"] != before["revision"]:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Tracking creation rollback not verified"
                )

        try:
            camera.location = list(plan["camera_location"])
            camera.rotation_euler = list(plan["camera_rotation_euler"])
            created = camera.constraints.new(type=TRACK_TYPE)
            created.name = TRACK_NAME
            created.target = subject
            created.track_axis = TRACK_AXIS
            created.up_axis = UP_AXIS
            created.mute = False
            created.influence = 1.0
            if action.preview.shot.make_active:
                self.bpy.context.scene.camera = camera
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(camera)
            subject_after = self.inspector.snapshot(subject)
            expected = {
                "constraint": self._expected_constraint(),
                "constraint_count": 1,
                "target_id": subject_before["object_id"],
                "subject_revision": subject_before["revision"],
                "location": plan["camera_location"],
                "rotation": plan["camera_rotation_euler"],
                "lens": plan["lens_mm"],
                "active_camera": (
                    True if action.preview.shot.make_active else old_active is camera
                ),
                "camera_revision_changed": True,
            }
            actual = {
                "constraint": self._readback(created, subject),
                "constraint_count": after["constraint_count"],
                "target_id": after["constraints"][0]["target_id"],
                "subject_revision": subject_after["revision"],
                "location": after["transform"]["location"],
                "rotation": after["transform"]["rotation_euler"],
                "lens": after["camera"]["lens"],
                "active_camera": self.bpy.context.scene.camera is camera,
                "camera_revision_changed": after["revision"] != before["revision"],
            }
            verification = compare(expected, actual)
            if (
                verification.matched
                and len(camera.constraints) == 1
                and camera.constraints[0] is created
            ):
                tracked_revision = revision(
                    {
                        "camera_revision": after["revision"],
                        "subject_id": subject_before["object_id"],
                        "constraint": actual["constraint"],
                    }
                )
                self._owned[after["object_id"]] = (created, subject, tracked_revision)
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "tracking_revision": tracked_revision,
                        "target_id": subject_before["object_id"],
                        "follow_behavior": plan["follow_behavior"],
                        "real_runtime_verified": False,
                    },
                    verification=verification.to_dict(),
                )
        except Exception as exc:
            try:
                rollback()
            except Exception as rollback_error:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Tracking creation failed; rollback not verified",
                ) from rollback_error
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Tracking creation interrupted; inspect state"
            ) from exc

        rollback()
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"before": before, "after": after, "rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Tracking constraint readback mismatch"),
            verification.to_dict(),
        )

    def release(self, request: Request, action: TrackingRelease):
        camera, before = self.inspector.target(action.camera)
        owned = self._owned.get(before["object_id"])
        if owned is None or action.expected_tracking_revision != owned[2]:
            raise AgentError(
                ErrorCode.STALE_STATE, "Tracking constraint is not owned by this runtime session"
            )
        constraint, subject, tracking_revision = owned
        if (
            len(camera.constraints) != 1
            or camera.constraints[0] is not constraint
            or not compare(self._expected_constraint(), self._readback(constraint, subject)).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed tracking constraint was modified")
        if (
            revision(
                {
                    "camera_revision": before["revision"],
                    "subject_id": self.inspector.identity(subject),
                    "constraint": self._readback(constraint, subject),
                }
            )
            != tracking_revision
        ):
            raise AgentError(ErrorCode.STALE_STATE, "Tracking identity/readback is stale")

        old_active = self.bpy.context.scene.camera
        old_location = list(camera.location)
        old_rotation = list(camera.rotation_euler)
        def restore_release():
            # Recreate only the agent-owned constraint when removal was
            # interrupted after it disappeared. Never delete foreign state.
            if constraint not in camera.constraints:
                if len(camera.constraints) != 0:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "Other camera constraints appeared during release recovery",
                    )
                restored = camera.constraints.new(type=TRACK_TYPE)
                restored.name = TRACK_NAME
                restored.target = subject
                restored.track_axis = TRACK_AXIS
                restored.up_axis = UP_AXIS
                restored.mute = False
                restored.influence = 1.0
                self._owned[before["object_id"]] = (restored, subject, tracking_revision)
            self.bpy.context.view_layer.update()
            if self.inspector.snapshot(camera)["revision"] != before["revision"]:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Tracking release rollback not verified"
                )

        try:
            camera.constraints.remove(constraint)
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(camera)
            verification = compare(
                {
                    "constraint_count": 0,
                    "location": old_location,
                    "rotation": old_rotation,
                    "active_unchanged": True,
                    "revision_changed": True,
                },
                {
                    "constraint_count": after["constraint_count"],
                    "location": after["transform"]["location"],
                    "rotation": after["transform"]["rotation_euler"],
                    "active_unchanged": self.bpy.context.scene.camera is old_active,
                    "revision_changed": after["revision"] != before["revision"],
                },
            )
            if verification.matched:
                del self._owned[before["object_id"]]
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after, "removed_own_constraint": True},
                    verification=verification.to_dict(),
                )
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED, "Tracking removal readback mismatch"
            )
        except Exception as exc:
            try:
                restore_release()
            except Exception as rollback_error:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Tracking release rollback unverified"
                ) from rollback_error
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Tracking release interrupted; original state restored"
            ) from exc

    def tools(self):
        return [
            Tool(
                "cinema.track_preview", SafetyClass.READ_ONLY, TrackingPreview.parse, self.preview
            ),
            Tool("cinema.track_apply", SafetyClass.MUTATION, TrackingApply.parse, self.apply),
            Tool("cinema.track_release", SafetyClass.MUTATION, TrackingRelease.parse, self.release),
        ]
