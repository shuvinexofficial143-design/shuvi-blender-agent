"""Level 2 topology foundation: bounded topology analysis and single-face extrusion."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string

MAX_VERTICES = 4096
MAX_FACES = 4096
MAX_LOOPS = 32768
MAX_EDGES = 8192
MAX_FACE_VERTICES = 32


def topology_from_faces(faces):
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, face in enumerate(faces):
        size = len(face)
        for offset in range(size):
            a = face[offset]
            b = face[(offset + 1) % size]
            edge = (a, b) if a < b else (b, a)
            edge_faces.setdefault(edge, []).append(face_index)
            if len(edge_faces) > MAX_EDGES:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Topology edge work limit exceeded")

    edges = sorted(edge_faces)
    boundary = [list(edge) for edge in edges if len(edge_faces[edge]) == 1]
    nonmanifold = [list(edge) for edge in edges if len(edge_faces[edge]) != 2]
    adjacent = [set() for _ in faces]
    for users in edge_faces.values():
        if len(users) == 2:
            a, b = users
            adjacent[a].add(b)
            adjacent[b].add(a)
    return {
        "edges": [list(edge) for edge in edges],
        "edge_count": len(edges),
        "boundary_edges": boundary,
        "boundary_edge_count": len(boundary),
        "nonmanifold_edges": nonmanifold,
        "nonmanifold_edge_count": len(nonmanifold),
        "face_adjacency": [sorted(items) for items in adjacent],
    }


@dataclass(frozen=True)
class ExtrudeFace:
    target: ObjectTarget
    expected_geometry_revision: str
    face_index: int
    offset: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "face_index", "offset"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            integer(data["face_index"], "face_index", 0, MAX_FACES - 1),
            vector3(data["offset"], "offset", 1000),
        )


class ModelingOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.meshes = MeshOperations(objects)

    def _editable_mesh(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Topology mutation requires Object mode")
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if (
            obj.data.users != 1
            or obj.data.library is not None
            or obj.data.shape_keys is not None
            or len(obj.modifiers)
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Unshared local mesh without shape keys/modifiers required",
            )
        geometry_before = self.meshes.snapshot(obj)
        require_revision(action.expected_geometry_revision, geometry_before["geometry_revision"])
        return obj, object_before, geometry_before

    @staticmethod
    def _replace_geometry(mesh, vertices, faces):
        if hasattr(mesh, "clear_geometry"):
            mesh.clear_geometry()
        mesh.from_pydata(vertices, [], faces)
        mesh.validate()
        mesh.update()

    def topology_inspect(self, request: Request, object_id: str) -> Result:
        obj = self.inspector.resolve(object_id)
        geometry = self.meshes.snapshot(obj)
        topology = topology_from_faces(geometry["faces"])
        data = geometry | topology
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def extrude_face(self, request: Request, action: ExtrudeFace) -> Result:
        obj, object_before, before = self._editable_mesh(action)
        if action.face_index >= len(before["faces"]):
            raise invalid("Face index does not exist")

        source_face = before["faces"][action.face_index]
        if not 3 <= len(source_face) <= MAX_FACE_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported source face size")

        new_vertex_count = len(before["vertices"]) + len(source_face)
        new_face_count = len(before["faces"]) + len(source_face)
        new_loop_count = (
            sum(len(face) for face in before["faces"])
            - len(source_face)
            + len(source_face)
            + 4 * len(source_face)
        )
        if (
            new_vertex_count > MAX_VERTICES
            or new_face_count > MAX_FACES
            or new_loop_count > MAX_LOOPS
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Extrusion exceeds geometry work limits")

        vertices = [list(vertex) for vertex in before["vertices"]]
        faces = [list(face) for face in before["faces"]]

        new_indices = []
        for index in source_face:
            source = before["vertices"][index]
            value = vector3(
                [component + delta for component, delta in zip(source, action.offset, strict=True)],
                "extruded vertex",
                1_000_000,
            )
            new_indices.append(len(vertices))
            vertices.append(list(value))

        faces[action.face_index] = list(new_indices)
        for offset, old_a in enumerate(source_face):
            old_b = source_face[(offset + 1) % len(source_face)]
            new_a = new_indices[offset]
            new_b = new_indices[(offset + 1) % len(new_indices)]
            faces.append([old_a, old_b, new_b, new_a])

        expected = {"vertices": vertices, "faces": faces}
        try:
            self._replace_geometry(obj.data, vertices, faces)
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(obj)
            after["object_revision"] = self.inspector.snapshot(obj)["revision"]
            after["extruded_face_index"] = action.face_index
            after["new_cap_indices"] = list(new_indices)
            result = self.objects._result(
                request,
                {"object": object_before, "geometry": before},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                self._replace_geometry(obj.data, before["vertices"], before["faces"])
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._replace_geometry(obj.data, before["vertices"], before["faces"])
            self.bpy.context.view_layer.update()
            raise

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool(
                "mesh.topology_inspect",
                SafetyClass.READ_ONLY,
                parse_id,
                self.topology_inspect,
            ),
            Tool(
                "mesh.extrude_face",
                SafetyClass.MUTATION,
                ExtrudeFace.parse,
                self.extrude_face,
            ),
        ]
