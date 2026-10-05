"""Bounded material/camera/light tools with property and membership verification."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, Transform, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, number, string


def color(value, size=3) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise invalid(f"Color requires {size} components")
    return tuple(number(item, "color", 0, 1) for item in value)


@dataclass(frozen=True)
class CreateDevice:
    name: str
    kind: str
    transform: Transform
    expected_scene_revision: str
    settings: dict

    @classmethod
    def parse(cls, data: dict) -> "CreateDevice":
        fields(data, {"name", "kind", "transform", "expected_scene_revision", "settings"})
        kind, settings = data["kind"], data["settings"]
        if kind == "CAMERA":
            fields(settings, {"lens", "clip_start", "clip_end", "make_active"})
            settings = {
                "lens": number(settings["lens"], "lens", 1, 500),
                "clip_start": number(settings["clip_start"], "clip_start", 0.0001, 1000),
                "clip_end": number(settings["clip_end"], "clip_end", 0.001, 1_000_000),
                "make_active": settings["make_active"],
            }
            if type(settings["make_active"]) is not bool:
                raise invalid("make_active must be boolean")
            if settings["clip_end"] <= settings["clip_start"]:
                raise invalid("clip_end must exceed clip_start")
        elif kind in ("POINT", "SUN", "SPOT", "AREA"):
            fields(settings, {"energy", "color"})
            settings = {
                "energy": number(settings["energy"], "energy", 0, 1_000_000),
                "color": list(color(settings["color"])),
            }
        else:
            raise invalid("Unsupported camera/light kind")
        return cls(
            object_name(data["name"]),
            kind,
            Transform.parse(data["transform"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
            settings,
        )


@dataclass(frozen=True)
class MaterialAssign:
    target: ObjectTarget
    name: str
    base_color: tuple
    metallic: float
    roughness: float

    @classmethod
    def parse(cls, data: dict) -> "MaterialAssign":
        fields(data, {"target", "name", "base_color", "metallic", "roughness"})
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["name"]),
            color(data["base_color"], 4),
            number(data["metallic"], "metallic", 0, 1),
            number(data["roughness"], "roughness", 0, 1),
        )


class AppearanceOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def create_device(self, request: Request, action: CreateDevice) -> Result:
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        self.objects._free_name(action.name)
        camera = action.kind == "CAMERA"
        table = self.bpy.data.cameras if camera else self.bpy.data.lights
        previous_camera = self.bpy.context.scene.camera
        data = obj = None
        try:
            data = table.new(action.name) if camera else table.new(action.name, action.kind)
            if camera:
                data.type = "PERSP"
                data.lens = action.settings["lens"]
                data.clip_start = action.settings["clip_start"]
                data.clip_end = action.settings["clip_end"]
            else:
                data.energy = action.settings["energy"]
                data.color = action.settings["color"]
            obj = self.bpy.data.objects.new(action.name, data)
            self.bpy.context.scene.collection.objects.link(obj)
            self.objects._transform(obj, action.transform)
            if camera and action.settings["make_active"]:
                self.bpy.context.scene.camera = obj
            self.bpy.context.view_layer.update()
            after = self.objects._readback(obj)
            expected = {
                "name": action.name,
                "type": "CAMERA" if camera else "LIGHT",
                "scene_member": True,
                "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
            }
            if camera:
                after["active_camera"] = self.bpy.context.scene.camera == obj
                expected["camera"] = {
                    key: value for key, value in action.settings.items() if key != "make_active"
                } | {"type": "PERSP"}
                expected["active_camera"] = action.settings["make_active"]
            else:
                expected["light"] = action.settings | {"type": action.kind}
            result = self.objects._result(request, None, after, expected)
            if result.status == Status.FAILED:
                self.bpy.context.scene.camera = previous_camera
                self.objects._remove_created(obj, None)
                table.remove(data)
                result.data["rolled_back"] = True
            return result
        except Exception:
            self.bpy.context.scene.camera = previous_camera
            if obj is not None:
                self.objects._remove_created(obj, None)
            if data is not None and data.users == 0:
                table.remove(data)
            raise

    def material_assign(self, request: Request, action: MaterialAssign) -> Result:
        obj, before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data.users != 1 or obj.data.library is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Editable mesh with unshared data required")
        if self.bpy.data.materials.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Material name already exists")
        if len(obj.material_slots) >= 64:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Material slot work limit reached")
        material = None
        slot_index = len(obj.data.materials)
        try:
            material = self.bpy.data.materials.new(action.name)
            material.use_nodes = True
            nodes = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
            if len(nodes) != 1:
                raise AgentError(ErrorCode.EXECUTION_ERROR, "Expected one new Principled shader")
            shader = nodes[0]
            material.diffuse_color = action.base_color
            shader.inputs["Base Color"].default_value = action.base_color
            shader.inputs["Metallic"].default_value = action.metallic
            shader.inputs["Roughness"].default_value = action.roughness
            obj.data.materials.append(material)
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(obj)
            after["assigned_material"] = {
                "name": material.name,
                "base_color": list(shader.inputs["Base Color"].default_value),
                "metallic": shader.inputs["Metallic"].default_value,
                "roughness": shader.inputs["Roughness"].default_value,
                "slot_index": slot_index,
                "slot_material": obj.material_slots[slot_index].material.name,
            }
            expected = {
                "assigned_material": {
                    "name": action.name,
                    "base_color": list(action.base_color),
                    "metallic": action.metallic,
                    "roughness": action.roughness,
                    "slot_index": slot_index,
                    "slot_material": action.name,
                }
            }
            result = self.objects._result(request, before, after, expected)
            if result.status == Status.FAILED:
                obj.data.materials.pop(index=slot_index)
                self.bpy.data.materials.remove(material)
                result.data["rolled_back"] = True
            return result
        except Exception:
            if len(obj.data.materials) > slot_index and obj.data.materials[slot_index] == material:
                obj.data.materials.pop(index=slot_index)
            if material is not None and material.users == 0:
                self.bpy.data.materials.remove(material)
            raise

    def tools(self) -> list[Tool]:
        return [
            Tool("device.create", SafetyClass.MUTATION, CreateDevice.parse, self.create_device),
            Tool(
                "material.create_assign",
                SafetyClass.MUTATION,
                MaterialAssign.parse,
                self.material_assign,
            ),
        ]
