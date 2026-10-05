"""Typed scene, cursor, unit and mode-state controls for Level 1."""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .models import object_name, vector3
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, number, string

UNIT_SYSTEMS = ("NONE", "METRIC", "IMPERIAL")
LENGTH_UNITS = (
    "ADAPTIVE",
    "KILOMETERS",
    "METERS",
    "CENTIMETERS",
    "MILLIMETERS",
    "MICROMETERS",
    "MILES",
    "FEET",
    "INCHES",
    "THOU",
)


def cursor_snapshot(bpy):
    cursor = bpy.context.scene.cursor
    return {"location": [float(value) for value in cursor.location]}


def unit_snapshot(scene):
    units = scene.unit_settings
    return {
        "system": units.system,
        "scale_length": float(units.scale_length),
        "length_unit": units.length_unit,
    }


def mode_snapshot(inspector):
    layer = inspector.bpy.context.view_layer
    active = getattr(getattr(layer, "objects", None), "active", None)
    return {
        "mode": inspector.bpy.context.mode,
        "active_object_id": inspector.identity(active) if active is not None else None,
        "active_object_type": active.type if active is not None else None,
    }


@dataclass(frozen=True)
class CursorSet:
    location: tuple[float, float, float]
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"location", "expected_scene_revision"})
        return cls(
            vector3(data["location"], "location", 1_000_000),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class SceneRename:
    name: str
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"name", "expected_scene_revision"})
        return cls(
            object_name(data["name"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class SetUnits:
    values: dict
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"units", "expected_scene_revision"})
        values = fields(data["units"], set(), {"system", "scale_length", "length_unit"})
        if not values:
            raise invalid("Unit settings patch cannot be empty")
        parsed = {}
        if "system" in values:
            system = values["system"]
            if not isinstance(system, str) or system not in UNIT_SYSTEMS:
                raise invalid("Unsupported unit system")
            parsed["system"] = system
        if "scale_length" in values:
            parsed["scale_length"] = number(values["scale_length"], "scale_length", 1e-6, 1e6)
        if "length_unit" in values:
            length = values["length_unit"]
            if not isinstance(length, str) or length not in LENGTH_UNITS:
                raise invalid("Unsupported length unit")
            parsed["length_unit"] = length
        return cls(
            parsed,
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


class SceneStateOperations:
    def __init__(self, objects):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def inspect_cursor(self, req, _):
        return Result(
            req.request_id,
            req.command_id,
            Status.SUCCEEDED,
            cursor_snapshot(self.bpy),
        )

    def set_cursor(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        before = cursor_snapshot(self.bpy)
        self.bpy.context.scene.cursor.location = action.location
        self.bpy.context.view_layer.update()
        return self.objects._result(
            req,
            before,
            cursor_snapshot(self.bpy),
            {"location": list(action.location)},
        )

    def rename_scene(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        scene = self.bpy.context.scene
        before = {"name": scene.name}
        scenes = getattr(self.bpy.data, "scenes", None)
        if scenes is not None:
            existing = scenes.get(action.name)
            if existing is not None and existing != scene:
                raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Scene name already exists")
        scene.name = action.name
        return self.objects._result(req, before, {"name": scene.name}, {"name": action.name})

    def set_units(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        scene = self.bpy.context.scene
        before = unit_snapshot(scene)
        for key, value in action.values.items():
            setattr(scene.unit_settings, key, value)
        self.bpy.context.view_layer.update()
        expected = before | action.values
        return self.objects._result(req, before, unit_snapshot(scene), expected)

    def inspect_mode(self, req, _):
        return Result(
            req.request_id,
            req.command_id,
            Status.SUCCEEDED,
            mode_snapshot(self.inspector),
        )

    def tools(self):
        def empty(data):
            return fields(data, set())

        return [
            Tool("cursor.inspect", SafetyClass.READ_ONLY, empty, self.inspect_cursor),
            Tool("cursor.set", SafetyClass.MUTATION, CursorSet.parse, self.set_cursor),
            Tool("scene.rename", SafetyClass.MUTATION, SceneRename.parse, self.rename_scene),
            Tool("scene.set_units", SafetyClass.MUTATION, SetUnits.parse, self.set_units),
            Tool("mode.inspect", SafetyClass.READ_ONLY, empty, self.inspect_mode),
        ]
