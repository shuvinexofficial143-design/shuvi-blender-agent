"""Bounded indexed mesh workflow. No edit-mode operators or arbitrary mesh scripts."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, Transform, object_name, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string


@dataclass(frozen=True)
class Geometry:
    vertices: tuple
    faces: tuple

    @classmethod
    def parse(cls, data):
        fields(data, {"vertices", "faces"})
        if not isinstance(data["vertices"], list) or not 3 <= len(data["vertices"]) <= 4096:
            raise invalid("Geometry needs 3..4096 vertices")
        vertices = tuple(vector3(item, "vertex", 1_000_000) for item in data["vertices"])
        if not isinstance(data["faces"], list) or not 1 <= len(data["faces"]) <= 4096:
            raise invalid("Geometry needs 1..4096 faces")
        faces = []
        loops = 0
        for face in data["faces"]:
            if not isinstance(face, list) or not 3 <= len(face) <= 32:
                raise invalid("A face requires 3..32 vertex indices")
            face = tuple(integer(index, "vertex index", 0, len(vertices) - 1) for index in face)
            if len(set(face)) != len(face):
                raise invalid("A face cannot repeat a vertex index")
            loops += len(face)
            faces.append(face)
        if loops > 32768:
            raise invalid("Face loop work limit exceeded")
        return cls(vertices, tuple(faces))

    def to_dict(self):
        return {
            "vertices": [list(v) for v in self.vertices],
            "faces": [list(f) for f in self.faces],
        }


@dataclass(frozen=True)
class CreateMesh:
    name: str
    geometry: Geometry
    transform: Transform
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"name", "geometry", "transform", "expected_scene_revision"})
        return cls(
            object_name(data["name"]),
            Geometry.parse(data["geometry"]),
            Transform.parse(data["transform"]),
            string(data["expected_scene_revision"], "revision", limit=64),
        )


@dataclass(frozen=True)
class TranslateVertices:
    target: ObjectTarget
    expected_geometry_revision: str
    indices: tuple[int, ...]
    delta: tuple

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "indices", "delta"})
        if not isinstance(data["indices"], list) or not 1 <= len(data["indices"]) <= 256:
            raise invalid("Translate 1..256 explicitly indexed vertices")
        indices = tuple(integer(index, "vertex index", 0, 4095) for index in data["indices"])
        if len(set(indices)) != len(indices):
            raise invalid("Vertex indices must be unique")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "geometry revision", limit=64),
            indices,
            vector3(data["delta"], "delta", 1000),
        )


class MeshOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector, self.bpy = objects.inspector, objects.bpy

    def snapshot(self, obj) -> dict:
        if obj.type != "MESH":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        mesh = obj.data
        if len(mesh.vertices) > 4096 or len(mesh.polygons) > 4096:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Geometry inspection work limit exceeded")
        if sum(len(face.vertices) for face in mesh.polygons) > 32768:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Geometry loop work limit exceeded")
        vertices = [list(vertex.co) for vertex in mesh.vertices]
        faces = [list(face.vertices) for face in mesh.polygons]
        geometry = {"vertices": vertices, "faces": faces}
        return geometry | {
            "geometry_revision": revision(geometry),
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
        }

    def inspect(self, request: Request, object_id: str) -> Result:
        obj = self.inspector.resolve(object_id)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, self.snapshot(obj))

    def create(self, request: Request, action: CreateMesh) -> Result:
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        self.objects._free_name(action.name)
        mesh = obj = None
        try:
            mesh = self.bpy.data.meshes.new(action.name + "Mesh")
            mesh.from_pydata(action.geometry.vertices, [], action.geometry.faces)
            mesh.validate()
            mesh.update()
            obj = self.bpy.data.objects.new(action.name, mesh)
            self.bpy.context.scene.collection.objects.link(obj)
            self.objects._transform(obj, action.transform)
            self.bpy.context.view_layer.update()
            after = {"object": self.objects._readback(obj), "geometry": self.snapshot(obj)}
            expected = {
                "object": {
                    "name": action.name,
                    "scene_member": True,
                    "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
                },
                "geometry": action.geometry.to_dict(),
            }
            result = self.objects._result(request, None, after, expected)
            if result.status == Status.FAILED:
                self.objects._remove_created(obj, mesh)
                result.data["rolled_back"] = True
            return result
        except Exception:
            self.objects._remove_created(obj, mesh)
            raise

    def translate(self, request: Request, action: TranslateVertices) -> Result:
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        before = self.snapshot(obj)
        require_revision(action.expected_geometry_revision, before["geometry_revision"])
        if (
            obj.data.users != 1
            or obj.data.library is not None
            or obj.data.shape_keys is not None
            or len(obj.modifiers)
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Unshared editable mesh without shapes/modifiers required"
            )
        updates = {}
        for index in action.indices:
            if index >= len(obj.data.vertices):
                raise invalid("Vertex index does not exist")
            updates[index] = vector3(
                [
                    value + delta
                    for value, delta in zip(obj.data.vertices[index].co, action.delta, strict=True)
                ],
                "translated vertex",
                1_000_000,
            )
        expected = {
            "vertices": [list(vertex) for vertex in before["vertices"]],
            "faces": before["faces"],
        }
        for index, value in updates.items():
            expected["vertices"][index] = list(value)
        for index, value in updates.items():
            obj.data.vertices[index].co = value
        obj.data.update()
        self.bpy.context.view_layer.update()
        after = self.snapshot(obj)
        after["object_revision"] = self.inspector.snapshot(obj)["revision"]
        return self.objects._result(
            request, {"object": object_before, "geometry": before}, after, expected
        )

    def tools(self) -> list[Tool]:
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool("mesh.inspect", SafetyClass.READ_ONLY, parse_id, self.inspect),
            Tool("mesh.create", SafetyClass.MUTATION, CreateMesh.parse, self.create),
            Tool(
                "mesh.translate_vertices",
                SafetyClass.MUTATION,
                TranslateVertices.parse,
                self.translate,
            ),
        ]
