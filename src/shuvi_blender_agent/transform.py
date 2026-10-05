"""Partial local transform patches; omitted channels are preserved and verified."""

from dataclasses import dataclass
from math import sqrt

from .models import ObjectTarget, vector3
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number


@dataclass(frozen=True)
class PatchTransform:
    target: ObjectTarget
    transform: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "transform"})
        values = fields(
            data["transform"], set(), {"location", "rotation_euler", "rotation_quaternion", "scale"}
        )
        if not values or {"rotation_euler", "rotation_quaternion"} <= values.keys():
            raise invalid("Provide a nonempty transform with at most one rotation representation")
        result = {}
        for key, value in values.items():
            if key == "rotation_quaternion":
                if not isinstance(value, (list, tuple)) or len(value) != 4:
                    raise invalid("Quaternion requires WXYZ components")
                q = [number(v, key, -1, 1) for v in value]
                if abs(sqrt(sum(v * v for v in q)) - 1) > 1e-6:
                    raise invalid("Quaternion must have unit length")
                result[key] = q
            else:
                result[key] = list(
                    vector3(
                        value, key, {"location": 1e6, "rotation_euler": 1000, "scale": 1e4}[key]
                    )
                )
        return cls(ObjectTarget.parse(data["target"]), result)


class TransformOperations:
    def __init__(self, objects):
        self.objects = objects

    def patch(self, req, action):
        obj, before = self.objects.inspector.target(action.target)
        self.objects._editable(obj)
        expected = {key: before["transform"][key] for key in ("location", "scale", "rotation_mode")}
        rotation_key = {
            "QUATERNION": "rotation_quaternion",
            "AXIS_ANGLE": "rotation_axis_angle",
        }.get(obj.rotation_mode, "rotation_euler")
        expected[rotation_key] = before["transform"][rotation_key]
        if "rotation_quaternion" in action.transform or "rotation_euler" in action.transform:
            expected.pop(rotation_key)
            obj.rotation_mode = "QUATERNION" if "rotation_quaternion" in action.transform else "XYZ"
            expected["rotation_mode"] = obj.rotation_mode
        expected.update(action.transform)
        for key, value in action.transform.items():
            setattr(obj, key, value)
        self.objects.bpy.context.view_layer.update()
        return self.objects._result(
            req,
            before,
            self.objects._readback(obj),
            {"object_id": before["object_id"], "transform": expected},
        )

    def tools(self):
        return [
            Tool("object.patch_transform", SafetyClass.MUTATION, PatchTransform.parse, self.patch)
        ]
