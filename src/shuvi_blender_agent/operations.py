"""Allowlisted object mutations using direct data API, identity checks and readback."""

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import MAX_SCENE_OBJECTS, BpyInspector, revision
from .models import CreateObject, DuplicateObject, SetTransform, Transform
from .primitives import geometry
from .safety import SafetyClass, require_revision
from .tools import Tool
from .verification import compare


class ObjectOperations:
    def __init__(self, inspector: BpyInspector):
        self.inspector = inspector
        self.bpy = inspector.bpy

    def _editable(self, obj) -> None:
        if obj.library is not None or obj.override_library is not None or not obj.is_editable:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Linked/overridden/read-only objects cannot be edited"
            )
        if len(obj.constraints) or obj.animation_data is not None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Animated or constrained transforms need dedicated tooling"
            )
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")

    def _free_name(self, name: str) -> None:
        if self.bpy.data.objects.get(name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Object name already exists")
        if len(self.bpy.data.objects) >= MAX_SCENE_OBJECTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object work limit reached")
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")

    @staticmethod
    def _transform(obj, transform: Transform) -> None:
        obj.rotation_mode = "XYZ"
        obj.location = transform.location
        obj.rotation_euler = transform.rotation_euler
        obj.scale = transform.scale

    def _result(self, request: Request, before: dict | None, after: dict, expected: dict) -> Result:
        verification = compare(expected, after)
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"before": before, "after": after},
                verification=verification.to_dict(),
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"before": before, "after": after},
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Readback differs from requested state; inspect before recovery",
            ),
            verification.to_dict(),
        )

    def _readback(self, obj) -> dict:
        after = self.inspector.snapshot(obj)
        after["scene_member"] = self.bpy.context.scene.objects.get(obj.name) == obj
        return after

    @staticmethod
    def _geometry_summary(mesh):
        if (
            len(mesh.vertices) > 4096
            or len(mesh.polygons) > 4096
            or sum(len(face.vertices) for face in mesh.polygons) > 32768
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh copy/readback work limit exceeded")
        return {
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.polygons),
            "revision": revision(
                {
                    "vertices": [[float(value) for value in vertex.co] for vertex in mesh.vertices],
                    "faces": [list(face.vertices) for face in mesh.polygons],
                }
            ),
        }

    def set_transform(self, request: Request, action: SetTransform) -> Result:
        obj, before = self.inspector.target(action.target)
        self._editable(obj)
        self._transform(obj, action.transform)
        self.bpy.context.view_layer.update()
        after = self._readback(obj)
        expected = {
            "object_id": before["object_id"],
            "name": before["name"],
            "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
        }
        return self._result(request, before, after, expected)

    def create(self, request: Request, action: CreateObject) -> Result:
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        self._free_name(action.name)
        mesh = None
        obj = None
        try:
            if action.kind != "EMPTY":
                mesh = self.bpy.data.meshes.new(action.name + "Mesh")
                vertices, faces = geometry(action.kind)
                mesh.from_pydata(vertices, [], faces)
                mesh.update()
            obj = self.bpy.data.objects.new(action.name, mesh)
            self.bpy.context.scene.collection.objects.link(obj)
            self._transform(obj, action.transform)
            self.bpy.context.view_layer.update()
            after = self._readback(obj)
            expected = {
                "name": action.name,
                "type": "EMPTY" if mesh is None else "MESH",
                "scene_member": True,
                "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
            }
            if mesh is not None:
                actual_geometry = self._geometry_summary(mesh)
                after["geometry"] = actual_geometry
                expected["geometry"] = {
                    "vertex_count": len(vertices),
                    "face_count": len(faces),
                    "revision": revision(
                        {
                            "vertices": [[float(value) for value in vertex] for vertex in vertices],
                            "faces": [list(face) for face in faces],
                        }
                    ),
                }
            result = self._result(request, None, after, expected)
            if result.status == Status.FAILED:
                self._remove_created(obj, mesh)
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._remove_created(obj, mesh)
            raise

    def _remove_created(self, obj, mesh) -> None:
        name = obj.name if obj is not None else None
        if obj is not None:
            self.bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            self.bpy.data.meshes.remove(mesh)
        if name is not None and self.bpy.data.objects.get(name) is not None:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED, "Creation cleanup failed; inspect scene"
            )

    def duplicate(self, request: Request, action: DuplicateObject) -> Result:
        original, before = self.inspector.target(action.target)
        self._editable(original)
        self._free_name(action.name)
        if original.type not in ("MESH", "EMPTY") or original.parent is not None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Only unparented mesh/empty duplicates supported"
            )
        if original.data is not None and (
            len(original.data.vertices) > 4096
            or len(original.data.polygons) > 4096
            or sum(len(face.vertices) for face in original.data.polygons) > 32768
            or original.data.shape_keys is not None
            or len(original.modifiers)
            or len(original.material_slots) > 64
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Duplicate exceeds supported mesh work bounds"
            )
        obj = None
        mesh = None
        original_geometry = (
            self._geometry_summary(original.data) if original.data is not None else None
        )
        try:
            obj = original.copy()
            obj.name = action.name
            if original.data is not None:
                mesh = original.data.copy()
                obj.data = mesh
            self.bpy.context.scene.collection.objects.link(obj)
            self._transform(obj, action.transform)
            self.bpy.context.view_layer.update()
            after = self._readback(obj)
            expected = {
                "name": action.name,
                "type": before["type"],
                "scene_member": True,
                "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
                "materials": before["materials"],
            }
            if mesh is not None:
                after["geometry"] = self._geometry_summary(mesh)
                after["mesh_shared"] = mesh == original.data
                expected["geometry"] = original_geometry
                expected["mesh_shared"] = False
            result = self._result(request, before, after, expected)
            if after["object_id"] == before["object_id"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Duplicate identity did not change")
            if result.status == Status.FAILED:
                self._remove_created(obj, mesh)
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._remove_created(obj, mesh)
            raise

    def duplicate_linked(self, request: Request, action: DuplicateObject) -> Result:
        original, before = self.inspector.target(action.target)
        self._editable(original)
        self._free_name(action.name)
        if original.type != "MESH" or original.parent is not None or original.data is None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Linked duplicate requires an unparented mesh object"
            )
        if (
            len(original.data.vertices) > 4096
            or len(original.data.polygons) > 4096
            or sum(len(face.vertices) for face in original.data.polygons) > 32768
            or original.data.shape_keys is not None
            or len(original.modifiers)
            or len(original.material_slots) > 64
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Linked duplicate exceeds supported mesh work bounds"
            )

        original_geometry = self._geometry_summary(original.data)
        obj = None
        try:
            obj = original.copy()
            obj.name = action.name
            obj.data = original.data
            self.bpy.context.scene.collection.objects.link(obj)
            self._transform(obj, action.transform)
            self.bpy.context.view_layer.update()
            after = self._readback(obj)
            after["geometry"] = self._geometry_summary(obj.data)
            after["mesh_shared"] = obj.data == original.data
            expected = {
                "name": action.name,
                "type": "MESH",
                "scene_member": True,
                "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
                "materials": before["materials"],
                "geometry": original_geometry,
                "mesh_shared": True,
            }
            result = self._result(request, before, after, expected)
            if after["object_id"] == before["object_id"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Duplicate identity did not change")
            if result.status == Status.FAILED:
                self._remove_created(obj, None)
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._remove_created(obj, None)
            raise

    def tools(self) -> list[Tool]:
        return [
            Tool("object.create", SafetyClass.MUTATION, CreateObject.parse, self.create),
            Tool(
                "object.set_transform", SafetyClass.MUTATION, SetTransform.parse, self.set_transform
            ),
            Tool("object.duplicate", SafetyClass.MUTATION, DuplicateObject.parse, self.duplicate),
            Tool(
                "object.duplicate_linked",
                SafetyClass.MUTATION,
                DuplicateObject.parse,
                self.duplicate_linked,
            ),
        ]
