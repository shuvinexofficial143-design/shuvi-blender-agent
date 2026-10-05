"""Timeline controls and bounded keyframes on actions created by this session."""

from dataclasses import dataclass

from .animation_state import action_curves
from .contracts import Request, Result
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, Transform
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string


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
            Tool("animation.set_range", SafetyClass.MUTATION, FrameRange.parse, self.set_range),
            Tool("animation.set_frame", SafetyClass.MUTATION, SetFrame.parse, self.set_frame),
            Tool(
                "animation.insert_keyframe", SafetyClass.MUTATION, InsertKeyframe.parse, self.insert
            ),
        ]
