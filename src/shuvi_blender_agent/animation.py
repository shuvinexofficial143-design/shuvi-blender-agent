"""Timeline controls and bounded keyframes on actions created by this session."""

from dataclasses import dataclass

from .animation_state import action_curves
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .models import ObjectTarget, Transform
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string

MAX_ANIMATION_CURVES = 64
MAX_ANIMATION_POINTS = 1024
MAX_ANIMATION_AUX_ITEMS = 64


@dataclass(frozen=True)
class AnimationInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class FrameRange:
    start: int
    end: int
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"start", "end", "expected_scene_revision"})
        start = integer(data["start"], "start", 1, 100_000)
        end = integer(data["end"], "end", start, 100_000)
        if end - start > 10_000:
            raise invalid("Frame range exceeds 10000 frames")
        return cls(start, end, string(data["expected_scene_revision"], "revision", limit=64))


@dataclass(frozen=True)
class SetFrame:
    frame: int
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"frame", "expected_scene_revision"})
        return cls(
            integer(data["frame"], "frame", 1, 100_000),
            string(data["expected_scene_revision"], "revision", limit=64),
        )


@dataclass(frozen=True)
class InsertKeyframe:
    target: ObjectTarget
    frame: int
    transform: Transform
    interpolation: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "frame", "transform", "interpolation"})
        if data["interpolation"] not in ("LINEAR", "BEZIER", "CONSTANT"):
            raise invalid("Unsupported interpolation")
        return cls(
            ObjectTarget.parse(data["target"]),
            integer(data["frame"], "frame", 1, 100_000),
            Transform.parse(data["transform"]),
            data["interpolation"],
        )


class AnimationOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned_actions = {}

    def inspect(self, request: Request, action: AnimationInspect) -> Result:
        obj = self.inspector.resolve(action.object_id)
        snapshot = self.inspector.snapshot(obj)
        animation = snapshot["animation"]
        if animation.get("unsupported_structure") or animation["details_truncated"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Exact animation inspection exceeds supported structure or bounds",
            )

        ad = obj.animation_data
        action_obj = ad.action if ad is not None else None
        curves = action_curves(obj)
        if len(curves) > MAX_ANIMATION_CURVES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Animation curve limit exceeded")

        point_count = 0
        unique_frames = set()
        interpolation_counts = {}
        channels = []
        for channel in animation["channels"]:
            data_path = bounded_text(channel["data_path"], limit=256)
            index = channel["index"]
            if type(index) is not int or not 0 <= index <= 1024:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Animation channel index is invalid")
            points = []
            for point in channel["points"]:
                co = point["co"]
                if (
                    not isinstance(co, list)
                    or len(co) != 2
                    or not all(
                        type(value) in (int, float)
                        and -float("inf") < value < float("inf")
                        for value in co
                    )
                ):
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Animation point is invalid")
                interpolation = bounded_text(point["interpolation"], limit=64)
                point_count += 1
                if point_count > MAX_ANIMATION_POINTS:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Animation point limit exceeded")
                frame = float(co[0])
                unique_frames.add(frame)
                interpolation_counts[interpolation] = interpolation_counts.get(interpolation, 0) + 1
                points.append(
                    {
                        "frame": frame,
                        "value": float(co[1]),
                        "interpolation": interpolation,
                    }
                )
            channels.append(
                {
                    "data_path": data_path,
                    "index": index,
                    "point_count": channel["point_count"],
                    "points": points,
                }
            )

        drivers_count = len(getattr(ad, "drivers", ())) if ad is not None else 0
        nla_track_count = len(getattr(ad, "nla_tracks", ())) if ad is not None else 0
        if drivers_count > MAX_ANIMATION_AUX_ITEMS or nla_track_count > MAX_ANIMATION_AUX_ITEMS:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Animation auxiliary structure limit exceeded",
            )

        action_users = getattr(action_obj, "users", 0) if action_obj is not None else 0
        if type(action_users) is not int or action_users < 0:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Action user count is invalid")
        if action_obj is None:
            action_api = "NONE"
        elif getattr(ad, "action_slot", None) is not None and hasattr(action_obj, "layers"):
            action_api = "SLOTTED"
        else:
            action_api = "LEGACY"

        managed_session_action = (
            action_obj is not None and self._owned_actions.get(action.object_id) is action_obj
        )
        blockers = []
        if obj.library is not None or obj.override_library is not None or not obj.is_editable:
            blockers.append("NONLOCAL_OR_READ_ONLY_OBJECT")
        if len(obj.constraints):
            blockers.append("OBJECT_CONSTRAINTS_PRESENT")
        if self.bpy.context.mode != "OBJECT":
            blockers.append("OBJECT_MODE_REQUIRED")
        if drivers_count:
            blockers.append("DRIVERS_PRESENT")
        if nla_track_count:
            blockers.append("NLA_TRACKS_PRESENT")
        if action_obj is not None and not managed_session_action:
            blockers.append("FOREIGN_ACTION")
        if action_obj is not None and action_users != 1:
            blockers.append("SHARED_ACTION")

        frames = sorted(unique_frames)
        state = {
            "object_id": snapshot["object_id"],
            "object_revision": snapshot["revision"],
            "action_name": (
                bounded_text(action_obj.name, limit=256) if action_obj is not None else None
            ),
            "action_api": action_api,
            "action_users": action_users,
            "managed_session_action": managed_session_action,
            "curve_count": len(channels),
            "point_count": point_count,
            "unique_frame_count": len(frames),
            "unique_frames": frames,
            "frame_range": {"start": frames[0], "end": frames[-1]} if frames else None,
            "interpolation_counts": dict(sorted(interpolation_counts.items())),
            "channels": channels,
            "drivers_count": drivers_count,
            "nla_track_count": nla_track_count,
            "blockers": blockers,
            "managed_mutation_ready": not blockers,
            "source_only": True,
            "real_runtime_verified": False,
        }
        state["animation_revision"] = revision(
            {
                "action_name": state["action_name"],
                "action_api": action_api,
                "action_users": action_users,
                "channels": channels,
                "drivers_count": drivers_count,
                "nla_track_count": nla_track_count,
            }
        )
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, state)

    def set_range(self, request: Request, action: FrameRange) -> Result:
        before = self.inspector.summary()
        require_revision(action.expected_scene_revision, before["revision"])
        scene = self.bpy.context.scene
        scene.frame_end = max(scene.frame_end, action.end)
        scene.frame_start = action.start
        scene.frame_end = action.end
        after = self.inspector.summary()
        return self.objects._result(
            request, before, after, {"frames": {"start": action.start, "end": action.end}}
        )

    def set_frame(self, request: Request, action: SetFrame) -> Result:
        before = self.inspector.summary()
        require_revision(action.expected_scene_revision, before["revision"])
        scene = self.bpy.context.scene
        if not scene.frame_start <= action.frame <= scene.frame_end:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Frame is outside configured range")
        scene.frame_set(action.frame)
        after = self.inspector.summary()
        return self.objects._result(request, before, after, {"frames": {"current": action.frame}})

    def insert(self, request: Request, action: InsertKeyframe) -> Result:
        obj, before = self.inspector.target(action.target)
        if obj.animation_data is None:
            self.objects._editable(obj)
        else:
            ad = obj.animation_data
            owned = self._owned_actions.get(action.target.object_id)
            if owned is None or owned != ad.action or ad.action.users != 1:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED, "Only session-created unshared actions may be keyed"
                )
            if (
                obj.library is not None
                or obj.override_library is not None
                or not obj.is_editable
                or len(obj.constraints)
                or self.bpy.context.mode != "OBJECT"
                or len(ad.drivers)
                or len(ad.nla_tracks)
            ):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe animation target")
        if before["animation"]["details_truncated"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Animation inspection is truncated")
        curves = action_curves(obj)
        frames = {float(point.co[0]) for curve in curves for point in curve.keyframe_points}
        if action.frame in frames:
            raise AgentError(
                ErrorCode.AMBIGUOUS_TARGET, "Frame already has keys; overwrite is disabled"
            )
        if len(frames) >= 64 or before["animation"]["details_truncated"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Animation work limit reached")
        self.objects._transform(obj, action.transform)
        for path in ("location", "rotation_euler", "scale"):
            if not obj.keyframe_insert(data_path=path, frame=action.frame):
                raise AgentError(
                    ErrorCode.EXECUTION_ERROR, "Keyframe insertion failed; inspect action"
                )
            self._owned_actions[action.target.object_id] = obj.animation_data.action
        readback = {}
        for curve in action_curves(obj):
            points = [
                point for point in curve.keyframe_points if abs(point.co[0] - action.frame) < 1e-5
            ]
            if len(points) == 1:
                points[0].interpolation = action.interpolation
                curve.update()
                readback[f"{curve.data_path}:{curve.array_index}"] = {
                    "frame": float(points[0].co[0]),
                    "value": float(points[0].co[1]),
                    "interpolation": points[0].interpolation,
                }
        after = self.inspector.snapshot(obj)
        after["inserted_keys"] = readback
        expected = {
            "inserted_keys": {
                f"{path}:{index}": {
                    "frame": action.frame,
                    "value": value,
                    "interpolation": action.interpolation,
                }
                for path, values in action.transform.to_dict().items()
                for index, value in enumerate(values)
            }
        }
        return self.objects._result(request, before, after, expected)

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "animation.inspect",
                SafetyClass.READ_ONLY,
                AnimationInspect.parse,
                self.inspect,
            ),
            Tool("animation.set_range", SafetyClass.MUTATION, FrameRange.parse, self.set_range),
            Tool("animation.set_frame", SafetyClass.MUTATION, SetFrame.parse, self.set_frame),
            Tool(
                "animation.insert_keyframe", SafetyClass.MUTATION, InsertKeyframe.parse, self.insert
            ),
        ]
