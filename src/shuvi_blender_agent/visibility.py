"""Distinct object and current-view-layer visibility controls."""

from dataclasses import dataclass

from .models import ObjectTarget
from .object_state import boolean
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid


@dataclass(frozen=True)
class SetVisibility:
    target: ObjectTarget
    visibility: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "visibility"})
        values = fields(
            data["visibility"], set(), {"hide_viewport", "hide_render", "hidden_in_view_layer"}
        )
        if not values:
            raise invalid("Visibility patch cannot be empty")
        return cls(ObjectTarget.parse(data["target"]), {k: boolean(v) for k, v in values.items()})


class VisibilityOperations:
    def __init__(self, objects):
        self.objects = objects

    def set_visibility(self, req, action):
        obj, before = self.objects.inspector.target(action.target)
        self.objects._editable(obj)
        expected = before["visibility"] | action.visibility
        for key, value in action.visibility.items():
            if key == "hidden_in_view_layer":
                obj.hide_set(value)
            else:
                setattr(obj, key, value)
        self.objects.bpy.context.view_layer.update()
        return self.objects._result(
            req,
            before,
            self.objects._readback(obj),
            {"object_id": before["object_id"], "visibility": expected},
        )

    def tools(self):
        return [
            Tool(
                "object.set_visibility",
                SafetyClass.MUTATION,
                SetVisibility.parse,
                self.set_visibility,
            )
        ]
