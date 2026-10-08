"""Level 7 milestone 3: bounded interpolation, easing and Bezier handle controls."""

from dataclasses import dataclass

from .animation_keyframes import AdvancedAnimationOperations, PATH_BOUNDS
from .errors import AgentError, ErrorCode
from .models import ObjectTarget
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, invalid, number, string

INTERPOLATIONS = {
    "CONSTANT",
    "LINEAR",
    "BEZIER",
    "SINE",
    "QUAD",
    "CUBIC",
    "QUART",
    "QUINT",
    "EXPO",
    "CIRC",
    "BACK",
    "BOUNCE",
    "ELASTIC",
}
EASINGS = {"AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"}
EASED_INTERPOLATIONS = INTERPOLATIONS - {"CONSTANT", "LINEAR", "BEZIER"}
HANDLE_TYPES = {"FREE", "VECTOR", "AUTO", "AUTO_CLAMPED"}


def _choice(value, name, allowed):
    value = string(value, name, limit=32)
    if value not in allowed:
        raise invalid(f"Unsupported {name}")
    return value


def _handle(value, name, frame, value_bound):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise invalid(f"{name} must have exactly two components")
    frame_value = number(value[0], f"{name}[0]", frame - 10_000, frame + 10_000)
    curve_value = number(value[1], f"{name}[1]", -value_bound, value_bound)
    return (frame_value, curve_value)


@dataclass(frozen=True)
class KeyframeStyleSet:
    target: ObjectTarget
    expected_animation_revision: str
    data_path: str
    array_index: int
    frame: int
    interpolation: str
    easing: str
    handle_left_type: str
    handle_right_type: str
    handle_left: tuple[float, float] | None
    handle_right: tuple[float, float] | None

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
                "interpolation",
                "easing",
                "handle_left_type",
                "handle_right_type",
            },
            {"handle_left", "handle_right"},
        )
        data_path = string(data["data_path"], "data_path", limit=32)
        if data_path not in PATH_BOUNDS:
            raise invalid("Unsupported animation data_path")
        frame = integer(data["frame"], "frame", 1, 100_000)
        interpolation = _choice(data["interpolation"], "interpolation", INTERPOLATIONS)
        easing = _choice(data["easing"], "easing", EASINGS)
        left_type = _choice(data["handle_left_type"], "handle_left_type", HANDLE_TYPES)
        right_type = _choice(data["handle_right_type"], "handle_right_type", HANDLE_TYPES)

        if interpolation not in EASED_INTERPOLATIONS and easing != "AUTO":
            raise invalid("Easing must be AUTO for CONSTANT, LINEAR and BEZIER")

        left = (
            _handle(data["handle_left"], "handle_left", frame, PATH_BOUNDS[data_path])
            if "handle_left" in data
            else None
        )
        right = (
            _handle(data["handle_right"], "handle_right", frame, PATH_BOUNDS[data_path])
            if "handle_right" in data
            else None
        )

        if interpolation != "BEZIER":
            if left_type != "AUTO" or right_type != "AUTO" or left is not None or right is not None:
                raise invalid("Non-BEZIER interpolation requires AUTO handles without coordinates")
        else:
            if (left_type == "FREE") != (left is not None):
                raise invalid("FREE left handle requires explicit handle_left coordinates")
            if (right_type == "FREE") != (right is not None):
                raise invalid("FREE right handle requires explicit handle_right coordinates")
            if left is not None and left[0] > frame:
                raise invalid("Left handle frame must not be after the keyframe")
            if right is not None and right[0] < frame:
                raise invalid("Right handle frame must not be before the keyframe")

        return cls(
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_animation_revision"],
                "expected_animation_revision",
                limit=64,
            ),
            data_path,
            integer(data["array_index"], "array_index", 0, 2),
            frame,
            interpolation,
            easing,
            left_type,
            right_type,
            left,
            right,
        )


class AnimationStyleOperations:
    def __init__(self, advanced: AdvancedAnimationOperations):
        self.advanced = advanced
        self.bpy = advanced.bpy

    @staticmethod
    def _style(point):
        return {
            "interpolation": point.interpolation,
            "easing": getattr(point, "easing", "AUTO"),
            "handle_left_type": getattr(point, "handle_left_type", "AUTO"),
            "handle_right_type": getattr(point, "handle_right_type", "AUTO"),
            "handle_left": [float(value) for value in getattr(point, "handle_left", point.co)],
            "handle_right": [float(value) for value in getattr(point, "handle_right", point.co)],
        }

    @staticmethod
    def _expected(action):
        expected = {
            "interpolation": action.interpolation,
            "easing": action.easing,
            "handle_left_type": action.handle_left_type,
            "handle_right_type": action.handle_right_type,
        }
        if action.handle_left is not None:
            expected["handle_left"] = list(action.handle_left)
        if action.handle_right is not None:
            expected["handle_right"] = list(action.handle_right)
        return expected

    def set_style(self, request, action: KeyframeStyleSet):
        obj, object_before, before, curves = self.advanced._managed(
            action.target,
            action.expected_animation_revision,
        )
        channel = (action.data_path, action.array_index)
        point = self.advanced._point(curves[channel], action.frame)
        expected_style = self._expected(action)
        current_style = self._style(point)
        if all(current_style[key] == value for key, value in expected_style.items()):
            raise invalid("Keyframe style request must change interpolation, easing or handles")

        snapshot = self.advanced._snapshot(curves)
        point.interpolation = action.interpolation
        point.easing = action.easing
        point.handle_left_type = action.handle_left_type
        point.handle_right_type = action.handle_right_type
        if action.handle_left is not None:
            point.handle_left = list(action.handle_left)
        if action.handle_right is not None:
            point.handle_right = list(action.handle_right)
        curves[channel].update()
        self.bpy.context.view_layer.update()

        after = self.advanced._state(action.target.object_id)
        readback = self.advanced._point(
            self.advanced._curve_map(obj)[channel],
            action.frame,
        )
        expected = expected_style | {"revision_changed": True}
        actual_style = self._style(readback)
        actual = {key: actual_style[key] for key in expected_style}
        actual["revision_changed"] = after["animation_revision"] != before["animation_revision"]

        result = self.advanced._finish(
            request,
            obj,
            object_before,
            before,
            snapshot,
            after,
            expected,
            actual,
        )
        if result.status.value not in {"verified", "failed"}:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Unexpected animation style result")
        return result

    def tools(self):
        return [
            Tool(
                "animation.keyframe_style_set",
                SafetyClass.MUTATION,
                KeyframeStyleSet.parse,
                self.set_style,
            )
        ]
