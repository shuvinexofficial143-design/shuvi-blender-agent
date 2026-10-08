"""Level 7 milestone 2: revision-gated managed transform keyframe mutations."""

from dataclasses import dataclass

from .animation import AnimationInspect, AnimationOperations
from .animation_state import action_curves
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, Transform
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

TRANSFORM_CHANNELS = {
    ("location", 0),
    ("location", 1),
    ("location", 2),
    ("rotation_euler", 0),
    ("rotation_euler", 1),
    ("rotation_euler", 2),
    ("scale", 0),
    ("scale", 1),
    ("scale", 2),
}
PATH_BOUNDS = {
    "location": 1_000_000,
    "rotation_euler": 1000,
    "scale": 10_000,
}
INTERPOLATIONS = {"LINEAR", "BEZIER", "CONSTANT"}


def _interpolation(value):
    if value not in INTERPOLATIONS:
        raise invalid("Unsupported interpolation")
    return value


@dataclass(frozen=True)
class EditKeyframe:
    target: ObjectTarget
    expected_animation_revision: str
    data_path: str
    array_index: int
    frame: int
    value: float
    interpolation: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_animation_revision",
                "data_path",
                "array_index",
                "frame",
                "value",
                "interpolation",
            },
        )
        data_path = string(data["data_path"], "data_path", limit=32)
        if data_path not in PATH_BOUNDS:
            raise invalid("Unsupported animation data_path")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_animation_revision"],
                "expected_animation_revision",
                limit=64,
            ),
            data_path,
            integer(data["array_index"], "array_index", 0, 2),
            integer(data["frame"], "frame", 1, 100_000),
            number(data["value"], "value", -PATH_BOUNDS[data_path], PATH_BOUNDS[data_path]),
            _interpolation(data["interpolation"]),
        )


@dataclass(frozen=True)
class RemoveKeyframe:
    target: ObjectTarget
    expected_animation_revision: str
    frame: int

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_animation_revision", "frame"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_animation_revision"],
                "expected_animation_revision",
                limit=64,
            ),
            integer(data["frame"], "frame", 1, 100_000),
        )


@dataclass(frozen=True)
class ReplaceKeyframe:
    target: ObjectTarget
    expected_animation_revision: str
    frame: int
    transform: Transform
    interpolation: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_animation_revision",
                "frame",
                "transform",
                "interpolation",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_animation_revision"],
                "expected_animation_revision",
                limit=64,
            ),
            integer(data["frame"], "frame", 1, 100_000),
            Transform.parse(data["transform"]),
            _interpolation(data["interpolation"]),
        )


class AdvancedAnimationOperations:
    def __init__(self, animation: AnimationOperations):
        self.animation = animation
        self.objects = animation.objects
        self.inspector = animation.inspector
        self.bpy = animation.bpy

    def _state(self, object_id):
        request = Request("animation.inspect", {"object_id": object_id})
        result = self.animation.inspect(request, AnimationInspect(object_id))
        return result.data

    @staticmethod
    def _curve_map(obj):
        curves = list(action_curves(obj))
        mapping = {(curve.data_path, curve.array_index): curve for curve in curves}
        if len(curves) != 9 or len(mapping) != 9 or set(mapping) != TRANSFORM_CHANNELS:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "M2 mutations require exactly nine managed transform curves",
            )
        return mapping

    @staticmethod
    def _point(curve, frame):
        points = [
            point
            for point in curve.keyframe_points
            if abs(float(point.co[0]) - float(frame)) < 1e-5
        ]
        if not points:
            raise AgentError(ErrorCode.NOT_FOUND, "Keyframe does not exist")
        if len(points) != 1:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Keyframe is not uniquely addressable")
        return points[0]

    @classmethod
    def _frame_points(cls, curves, frame):
        return {channel: cls._point(curve, frame) for channel, curve in curves.items()}

    def _managed(self, target, expected_animation_revision):
        obj, object_before = self.inspector.target(target)
        state = self._state(target.object_id)
        require_revision(expected_animation_revision, state["animation_revision"])
        if (
            state["action_name"] is None
            or not state["managed_session_action"]
            or not state["managed_mutation_ready"]
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Only a fresh session-created unshared transform Action may be mutated",
            )
        return obj, object_before, state, self._curve_map(obj)

    @staticmethod
    def _snapshot(curves):
        return {
            channel: [
                {
                    "frame": float(point.co[0]),
                    "value": float(point.co[1]),
                    "interpolation": point.interpolation,
                    "easing": getattr(point, "easing", "AUTO"),
                    "handle_left_type": getattr(point, "handle_left_type", "AUTO"),
                    "handle_right_type": getattr(point, "handle_right_type", "AUTO"),
                    "handle_left": list(getattr(point, "handle_left", point.co)),
                    "handle_right": list(getattr(point, "handle_right", point.co)),
                }
                for point in curve.keyframe_points
            ]
            for channel, curve in curves.items()
        }

    @staticmethod
    def _remove_point(points, point):
        try:
            points.remove(point, fast=True)
        except TypeError:
            points.remove(point)

    @staticmethod
    def _insert_point(curve, data):
        point = curve.keyframe_points.insert(data["frame"], data["value"])
        point.interpolation = data["interpolation"]
        point.easing = data.get("easing", "AUTO")
        point.handle_left_type = data.get("handle_left_type", "AUTO")
        point.handle_right_type = data.get("handle_right_type", "AUTO")
        if "handle_left" in data:
            point.handle_left = list(data["handle_left"])
        if "handle_right" in data:
            point.handle_right = list(data["handle_right"])
        curve.update()
        return point

    def _restore(self, obj, snapshot):
        curves = self._curve_map(obj)
        for channel, curve in curves.items():
            for point in list(curve.keyframe_points):
                self._remove_point(curve.keyframe_points, point)
            for data in snapshot[channel]:
                self._insert_point(curve, data)
            curve.update()
        self.bpy.context.view_layer.update()

    def _finish(
        self,
        request,
        obj,
        object_before,
        before,
        snapshot,
        after,
        expected,
        actual,
    ):
        verification = compare(expected, actual)
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"before": before, "after": after, "object_before": object_before},
                verification=verification.to_dict(),
            )

        self._restore(obj, snapshot)
        restored = self._state(before["object_id"])
        recovery = compare(
            {"animation_revision": before["animation_revision"]},
            {"animation_revision": restored["animation_revision"]},
        )
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Animation verification failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "object_before": object_before,
                "rolled_back": True,
                "recovery_verified": True,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Animation readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def edit(self, request: Request, action: EditKeyframe):
        obj, object_before, before, curves = self._managed(
            action.target,
            action.expected_animation_revision,
        )
        channel = (action.data_path, action.array_index)
        point = self._point(curves[channel], action.frame)
        if (
            abs(float(point.co[1]) - action.value) < 1e-9
            and point.interpolation == action.interpolation
        ):
            raise invalid("Keyframe edit must change value or interpolation")

        snapshot = self._snapshot(curves)
        point.co[1] = action.value
        point.interpolation = action.interpolation
        curves[channel].update()
        self.bpy.context.view_layer.update()
        after = self._state(action.target.object_id)
        edited = self._point(self._curve_map(obj)[channel], action.frame)
        expected = {
            "frame": float(action.frame),
            "value": action.value,
            "interpolation": action.interpolation,
            "revision_changed": True,
        }
        actual = {
            "frame": float(edited.co[0]),
            "value": float(edited.co[1]),
            "interpolation": edited.interpolation,
            "revision_changed": after["animation_revision"] != before["animation_revision"],
        }
        return self._finish(
            request,
            obj,
            object_before,
            before,
            snapshot,
            after,
            expected,
            actual,
        )

    def remove(self, request: Request, action: RemoveKeyframe):
        obj, object_before, before, curves = self._managed(
            action.target,
            action.expected_animation_revision,
        )
        points = self._frame_points(curves, action.frame)
        snapshot = self._snapshot(curves)
        for channel, point in points.items():
            self._remove_point(curves[channel].keyframe_points, point)
            curves[channel].update()
        self.bpy.context.view_layer.update()
        after = self._state(action.target.object_id)
        remaining = [
            point
            for curve in self._curve_map(obj).values()
            for point in curve.keyframe_points
            if abs(float(point.co[0]) - float(action.frame)) < 1e-5
        ]
        expected = {
            "frame_present": False,
            "point_count": before["point_count"] - 9,
            "revision_changed": True,
        }
        actual = {
            "frame_present": bool(remaining),
            "point_count": after["point_count"],
            "revision_changed": after["animation_revision"] != before["animation_revision"],
        }
        return self._finish(
            request,
            obj,
            object_before,
            before,
            snapshot,
            after,
            expected,
            actual,
        )

    def replace(self, request: Request, action: ReplaceKeyframe):
        obj, object_before, before, curves = self._managed(
            action.target,
            action.expected_animation_revision,
        )
        points = self._frame_points(curves, action.frame)
        wanted = {
            (path, index): value
            for path, values in action.transform.to_dict().items()
            for index, value in enumerate(values)
        }
        if all(
            abs(float(points[channel].co[1]) - wanted[channel]) < 1e-9
            and points[channel].interpolation == action.interpolation
            for channel in TRANSFORM_CHANNELS
        ):
            raise invalid("Keyframe replacement must change transform or interpolation")

        snapshot = self._snapshot(curves)
        for channel, point in points.items():
            point.co[1] = wanted[channel]
            point.interpolation = action.interpolation
            curves[channel].update()
        self.bpy.context.view_layer.update()
        after = self._state(action.target.object_id)
        readback = self._frame_points(self._curve_map(obj), action.frame)
        expected_points = {
            f"{path}:{index}": {
                "frame": float(action.frame),
                "value": wanted[(path, index)],
                "interpolation": action.interpolation,
            }
            for path, index in sorted(TRANSFORM_CHANNELS)
        }
        actual_points = {
            f"{path}:{index}": {
                "frame": float(readback[(path, index)].co[0]),
                "value": float(readback[(path, index)].co[1]),
                "interpolation": readback[(path, index)].interpolation,
            }
            for path, index in sorted(TRANSFORM_CHANNELS)
        }
        expected = {
            "points": expected_points,
            "point_count": before["point_count"],
            "revision_changed": True,
        }
        actual = {
            "points": actual_points,
            "point_count": after["point_count"],
            "revision_changed": after["animation_revision"] != before["animation_revision"],
        }
        return self._finish(
            request,
            obj,
            object_before,
            before,
            snapshot,
            after,
            expected,
            actual,
        )

    def tools(self):
        return [
            Tool(
                "animation.edit_keyframe",
                SafetyClass.MUTATION,
                EditKeyframe.parse,
                self.edit,
            ),
            Tool(
                "animation.remove_keyframe",
                SafetyClass.MUTATION,
                RemoveKeyframe.parse,
                self.remove,
            ),
            Tool(
                "animation.replace_keyframe",
                SafetyClass.MUTATION,
                ReplaceKeyframe.parse,
                self.replace,
            ),
        ]
