"""Typed object naming and display property mutations."""

from dataclasses import dataclass

from .errors import AgentError, ErrorCode
from .models import ObjectTarget, object_name
from .object_state import property_values
from .safety import SafetyClass
from .tools import Tool
from .validation import fields


@dataclass(frozen=True)
class RenameObject:
    target: ObjectTarget
    name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name"})
        return cls(ObjectTarget.parse(data["target"]), object_name(data["name"]))


@dataclass(frozen=True)
class SetProperties:
    target: ObjectTarget
    properties: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "properties"})
        return cls(ObjectTarget.parse(data["target"]), property_values(data["properties"]))


class ObjectCore:
    def __init__(self, objects):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def rename(self, req, action):
        obj, before = self.inspector.target(action.target)
        self.objects._editable(obj)
        existing = self.bpy.data.objects.get(action.name)
        if existing is not None and existing != obj:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Object name already exists")
        obj.name = action.name
        return self.objects._result(
            req,
            before,
            self.objects._readback(obj),
            {"object_id": before["object_id"], "name": action.name, "scene_member": True},
        )

    def set_properties(self, req, action):
        obj, before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.type != "EMPTY" and any(k.startswith("empty_") for k in action.properties):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Empty display properties require an empty")
        for key, value in action.properties.items():
            setattr(obj, key, value)
        self.bpy.context.view_layer.update()
        return self.objects._result(
            req,
            before,
            self.objects._readback(obj),
            {"object_id": before["object_id"], "properties": action.properties},
        )

    def tools(self):
        return [
            Tool("object.rename", SafetyClass.MUTATION, RenameObject.parse, self.rename),
            Tool(
                "object.set_properties",
                SafetyClass.MUTATION,
                SetProperties.parse,
                self.set_properties,
            ),
        ]
