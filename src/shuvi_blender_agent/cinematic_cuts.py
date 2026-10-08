"""Level 8 M9: reversible Blender timeline camera-binding hard cuts."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, string
from .verification import compare

FIRST = "Shuvi_M9_Shot_A"
SECOND = "Shuvi_M9_Shot_B"
MAX_EXISTING_MARKERS = 256


@dataclass(frozen=True)
class CutPreview:
    camera_a: ObjectTarget
    camera_b: ObjectTarget
    start_frame: int
    cut_frame: int
    end_frame: int

    @classmethod
    def parse(cls, data):
        fields(data, {"camera_a", "camera_b", "start_frame", "cut_frame", "end_frame"})
        start = integer(data["start_frame"], "start_frame", 1, 99_992)
        cut = integer(data["cut_frame"], "cut_frame", 1, 99_996)
        end = integer(data["end_frame"], "end_frame", 1, 100_000)
        if cut - start < 4 or end - cut < 4 or end - start > 720:
            raise AgentError(
                ErrorCode.INVALID_REQUEST,
                "Two hard-cut shots require at least four frames each and <=720 total",
            )
        return cls(
            ObjectTarget.parse(data["camera_a"]),
            ObjectTarget.parse(data["camera_b"]),
            start,
            cut,
            end,
        )


@dataclass(frozen=True)
class CutApply:
    preview: CutPreview
    expected_cut_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera_a",
                "camera_b",
                "start_frame",
                "cut_frame",
                "end_frame",
                "expected_cut_revision",
            },
        )
        return cls(
            CutPreview.parse(
                {key: value for key, value in data.items() if key != "expected_cut_revision"}
            ),
            string(data["expected_cut_revision"], "expected_cut_revision", limit=64),
        )


@dataclass(frozen=True)
class CutRelease:
    expected_cut_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_cut_token"})
        return cls(string(data["expected_cut_token"], "expected_cut_token", limit=64))


class CameraCutOperations:
    """Create exactly two new bound scene markers; never adopt foreign markers."""

    def __init__(self, objects: ObjectOperations):
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned = {}

    @staticmethod
    def _pointer(obj):
        if obj is None:
            return None
        return int(obj.as_pointer()) if hasattr(obj, "as_pointer") else id(obj)

    def _state(self, scene):
        markers = scene.timeline_markers
        if len(markers) > MAX_EXISTING_MARKERS + 2:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many scene timeline markers")
        items = []
        for marker in markers:
            name = string(marker.name, "marker name", limit=128)
            items.append(
                {
                    "name": name,
                    "frame": int(marker.frame),
                    "camera_pointer": self._pointer(marker.camera),
                    "selected": bool(marker.select),
                }
            )
        items.sort(
            key=lambda row: (
                row["frame"],
                row["name"],
                -1 if row["camera_pointer"] is None else row["camera_pointer"],
            )
        )
        return {
            "scene_pointer": self._pointer(scene),
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "markers": items,
        }

    @staticmethod
    def _expected_marker(name, frame, camera_pointer):
        return {
            "name": name,
            "frame": frame,
            "camera_pointer": camera_pointer,
            "selected": False,
        }

    def _plan(self, action: CutPreview):
        camera_a, before_a = self.inspector.target(action.camera_a)
        camera_b, before_b = self.inspector.target(action.camera_b)
        if (
            camera_a is camera_b
            or camera_a.type != "CAMERA"
            or camera_b.type != "CAMERA"
            or camera_a.data is None
            or camera_b.data is None
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Two distinct existing camera objects required"
            )
        scene = self.bpy.context.scene
        if not hasattr(scene, "timeline_markers"):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene timeline markers unavailable")
        if not hasattr(scene.timeline_markers, "new") or not hasattr(
            scene.timeline_markers, "remove"
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Timeline marker mutation API unavailable")
        state = self._state(scene)
        blockers = set()
        if len(state["markers"]) > MAX_EXISTING_MARKERS:
            blockers.add("SCENE_MARKER_COUNT_LIMIT")
        if not scene.frame_start <= action.start_frame < action.cut_frame <= action.end_frame:
            blockers.add("INVALID_SCENE_SHOT_FRAMES")
        if action.end_frame > scene.frame_end:
            blockers.add("CUT_OUTSIDE_SCENE_FRAME_RANGE")
        for item in state["markers"]:
            if item["name"] in (FIRST, SECOND):
                blockers.add("RESERVED_CAMERA_MARKER_NAME_EXISTS")
            if item["frame"] in (action.start_frame, action.cut_frame):
                blockers.add("MARKER_FRAME_COLLISION")
            if (
                item["camera_pointer"] is not None
                and action.start_frame <= item["frame"] <= action.end_frame
            ):
                blockers.add("EXISTING_CAMERA_CUT_OVERLAP")
        plan = {
            "camera_a_id": before_a["object_id"],
            "camera_b_id": before_b["object_id"],
            "camera_a_revision": before_a["revision"],
            "camera_b_revision": before_b["revision"],
            "scene_state": state,
            "start_frame": action.start_frame,
            "cut_frame": action.cut_frame,
            "end_frame": action.end_frame,
            "segments": [
                {"camera_id": before_a["object_id"], "start": action.start_frame,
                 "end": action.cut_frame - 1},
                {"camera_id": before_b["object_id"], "start": action.cut_frame,
                 "end": action.end_frame},
            ],
            "marker_names": [FIRST, SECOND],
            "transition": "HARD_CAMERA_CUT",
            "changes_existing_markers": False,
            "changes_camera_transforms": False,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "source_only": True,
            "real_runtime_verified": False,
            "mutation_performed": False,
        }
        plan["cut_revision"] = revision(plan)
        return scene, camera_a, camera_b, plan

    def preview(self, request: Request, action: CutPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[3]
        )

    def _create(self, scene, name, frame, camera):
        marker = scene.timeline_markers.new(name, frame=frame)
        return marker

    @staticmethod
    def _configure(marker, name, frame, camera):
        marker.name = name
        marker.frame = frame
        marker.camera = camera
        marker.select = False

    def apply(self, request: Request, action: CutApply):
        scene, camera_a, camera_b, plan = self._plan(action.preview)
        if plan["cut_revision"] != action.expected_cut_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera cut plan changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe camera marker collisions")
        original = self._state(scene)
        old_active = scene.camera
        old_frame = scene.frame_current
        made = []

        def rollback():
            for marker in reversed(made):
                if marker not in scene.timeline_markers:
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Cut marker identity was lost")
                scene.timeline_markers.remove(marker)
            if (
                self._state(scene) != original
                or scene.camera is not old_active
                or scene.frame_current != old_frame
            ):
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Camera cut rollback unverified")

        try:
            first = self._create(scene, FIRST, plan["start_frame"], camera_a)
            made.append(first)
            self._configure(first, FIRST, plan["start_frame"], camera_a)
            second = self._create(scene, SECOND, plan["cut_frame"], camera_b)
            made.append(second)
            self._configure(second, SECOND, plan["cut_frame"], camera_b)
            actual_state = self._state(scene)
            expected_markers = sorted(
                [
                    *original["markers"],
                    self._expected_marker(FIRST, plan["start_frame"], self._pointer(camera_a)),
                    self._expected_marker(SECOND, plan["cut_frame"], self._pointer(camera_b)),
                ],
                key=lambda row: (
                    row["frame"],
                    row["name"],
                    -1 if row["camera_pointer"] is None else row["camera_pointer"],
                ),
            )
            expected = {
                "scene": original["scene_pointer"],
                "markers": expected_markers,
                "count": len(original["markers"]) + 2,
                "old_camera_preserved": True,
                "old_frame_preserved": True,
                "camera_a_revision": plan["camera_a_revision"],
                "camera_b_revision": plan["camera_b_revision"],
                "marker_ownership": True,
            }
            actual = {
                "scene": actual_state["scene_pointer"],
                "markers": actual_state["markers"],
                "count": len(scene.timeline_markers),
                "old_camera_preserved": scene.camera is old_active,
                "old_frame_preserved": scene.frame_current == old_frame,
                "camera_a_revision": self.inspector.snapshot(camera_a)["revision"],
                "camera_b_revision": self.inspector.snapshot(camera_b)["revision"],
                "marker_ownership": (
                    len(made) == 2
                    and first in scene.timeline_markers
                    and second in scene.timeline_markers
                ),
            }
            verified = compare(expected, actual)
            if verified.matched:
                token = revision(
                    {
                        "scene": actual_state,
                        "a": self._pointer(camera_a),
                        "b": self._pointer(camera_b),
                    }
                )
                self._owned[token] = {
                    "scene": scene,
                    "first": first,
                    "second": second,
                    "camera_a": camera_a,
                    "camera_b": camera_b,
                    "after": actual_state,
                    "original": original,
                }
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "cut_token": token,
                        "before": original,
                        "after": actual_state,
                        "created_bound_markers": 2,
                        "real_runtime_verified": False,
                    },
                    verification=verified.to_dict(),
                )
        except Exception as exc:
            try:
                rollback()
            except Exception as recovery_error:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Camera cut creation rollback not verified"
                ) from recovery_error
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Camera cut marker creation interrupted"
            ) from exc

        rollback()
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"rolled_back": True, "recovery_verified": True, "before": original},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Camera cut readback mismatch"),
            verified.to_dict(),
        )

    def release(self, request: Request, action: CutRelease):
        owned = self._owned.get(action.expected_cut_token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Camera cuts not owned by this session")
        scene = self.bpy.context.scene
        if scene is not owned["scene"]:
            raise AgentError(ErrorCode.STALE_STATE, "Scene changed since cut creation")
        markers = scene.timeline_markers
        first, second = owned["first"], owned["second"]
        if first not in markers or second not in markers:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Owned camera marker identity changed")
        if self._state(scene) != owned["after"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera marker timeline edited externally")
        original_state = self._state(scene)
        old_active, old_frame = scene.camera, scene.frame_current

        def restore_release():
            # Only recreate our two originally owned markers when a removal
            # partially succeeded; never mutate any foreign marker.
            retained = [marker for marker in markers if marker not in (first, second)]
            original_foreign = owned["original"]["markers"]
            foreign_now = self._state(scene)["markers"]
            foreign_expected = [row for row in foreign_now if row["name"] not in (FIRST, SECOND)]
            if foreign_expected != original_foreign or len(retained) != len(original_foreign):
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Foreign timeline changed during recovery"
                )
            fresh = []
            for old, name, camera in (
                (first, FIRST, owned["camera_a"]),
                (second, SECOND, owned["camera_b"]),
            ):
                if old in markers:
                    fresh.append(old)
                    continue
                target_frame = (
                    next(row["frame"] for row in owned["after"]["markers"] if row["name"] == name)
                )
                new = self._create(scene, name, target_frame, camera)
                self._configure(new, name, target_frame, camera)
                fresh.append(new)
            if (
                self._state(scene) != original_state
                or scene.camera is not old_active
                or scene.frame_current != old_frame
            ):
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Cut release rollback unverified")
            owned["first"], owned["second"] = fresh

        try:
            markers.remove(second)
            markers.remove(first)
            now = self._state(scene)
            expected = {
                "timeline": owned["original"],
                "original_camera_preserved": True,
                "original_frame_preserved": True,
                "removed_own_markers": 2,
            }
            actual = {
                "timeline": now,
                "original_camera_preserved": scene.camera is old_active,
                "original_frame_preserved": scene.frame_current == old_frame,
                "removed_own_markers": (
                    int(first not in markers) + int(second not in markers)
                ),
            }
            verified = compare(expected, actual)
            if verified.matched:
                del self._owned[action.expected_cut_token]
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": original_state,
                        "after": now,
                        "removed_own_markers": 2,
                    },
                    verification=verified.to_dict(),
                )
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Cut release readback mismatch")
        except Exception as exc:
            try:
                restore_release()
            except Exception as recovery_error:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Camera cut release rollback unverified"
                ) from recovery_error
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Camera cut release interrupted; restored owned markers"
            ) from exc

    def tools(self):
        return [
            Tool("cinema.cut_preview", SafetyClass.READ_ONLY, CutPreview.parse, self.preview),
            Tool("cinema.cut_apply", SafetyClass.MUTATION, CutApply.parse, self.apply),
            Tool("cinema.cut_release", SafetyClass.MUTATION, CutRelease.parse, self.release),
        ]
