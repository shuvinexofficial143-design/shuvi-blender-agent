"""Level 2 milestone 3: region extrusion, face inset and boundary-edge bevel foundations."""

from dataclasses import dataclass

from .contracts import Request, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .modeling import MAX_EDGES, MAX_FACE_VERTICES, MAX_FACES, MAX_LOOPS, MAX_VERTICES
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_REGION_FACES = 64


def _face_indices(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_REGION_FACES:
        raise invalid(f"face_indices requires 1..{MAX_REGION_FACES} indices")
    parsed = tuple(integer(item, "face_index", 0, MAX_FACES - 1) for item in value)
    if len(set(parsed)) != len(parsed):
        raise invalid("face_indices must be unique")
    return parsed


@dataclass(frozen=True)
class ExtrudeRegion:
    target: ObjectTarget
    expected_geometry_revision: str
    face_indices: tuple[int, ...]
    offset: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "face_indices", "offset"})
        offset = vector3(data["offset"], "offset", 1000)
        if offset == (0.0, 0.0, 0.0):
            raise invalid("Region extrusion offset cannot be zero")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            _face_indices(data["face_indices"]),
            offset,
        )


@dataclass(frozen=True)
class InsetFace:
    target: ObjectTarget
    expected_geometry_revision: str
    face_index: int
    factor: float

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "face_index", "factor"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            integer(data["face_index"], "face_index", 0, MAX_FACES - 1),
            number(data["factor"], "factor", 0.001, 0.95),
        )


@dataclass(frozen=True)
class BevelBoundaryEdge:
    target: ObjectTarget
    expected_geometry_revision: str
    edge_index: int
    factor: float

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "edge_index", "factor"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            integer(data["edge_index"], "edge_index", 0, MAX_EDGES - 1),
            number(data["factor"], "factor", 0.001, 0.49),
        )


class ModelingRegionOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.meshes = MeshOperations(objects)

    def _editable_rebuild_mesh(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
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
        if (
            len(obj.material_slots)
            or len(getattr(obj, "vertex_groups", ()))
            or len(getattr(obj.data, "uv_layers", ()))
            or len(getattr(obj.data, "color_attributes", ()))
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Topology rebuild requires mesh without material/UV/color/vertex-group data",
            )
        geometry = self.meshes.snapshot(obj)
        require_revision(action.expected_geometry_revision, geometry["geometry_revision"])
        return obj, object_before, geometry

    @staticmethod
    def _replace_geometry(mesh, vertices, faces):
        if hasattr(mesh, "clear_geometry"):
            mesh.clear_geometry()
        mesh.from_pydata(vertices, [], faces)
        mesh.validate()
        mesh.update()

    @staticmethod
    def _edge_users(faces):
        users = {}
        for face_index, face in enumerate(faces):
            for offset, a in enumerate(face):
                b = face[(offset + 1) % len(face)]
                edge = (a, b) if a < b else (b, a)
                users.setdefault(edge, []).append(face_index)
        if len(users) > MAX_EDGES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Topology edge work limit exceeded")
        return users

    @staticmethod
    def _preflight(vertices, faces):
        if len(vertices) > MAX_VERTICES or len(faces) > MAX_FACES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modeling result exceeds geometry limits")
        loops = sum(len(face) for face in faces)
        if loops > MAX_LOOPS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modeling result exceeds loop work limit")
        if any(not 3 <= len(face) <= MAX_FACE_VERTICES for face in faces):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modeling result has unsupported face size")

    def _commit_rebuild(self, request, obj, object_before, before, vertices, faces, evidence):
        self._preflight(vertices, faces)
        expected = {"vertices": vertices, "faces": faces} | evidence
        try:
            self._replace_geometry(obj.data, vertices, faces)
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(obj)
            after["object_revision"] = self.inspector.snapshot(obj)["revision"]
            after.update(evidence)
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

    def extrude_region(self, request: Request, action: ExtrudeRegion):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        if any(index >= len(before["faces"]) for index in action.face_indices):
            raise invalid("Region face index does not exist")

        selected = set(action.face_indices)
        selected_edge_users = {}
        oriented_edges = {}
        adjacency = {index: set() for index in selected}
        selected_vertices = set()

        for face_index in action.face_indices:
            face = before["faces"][face_index]
            selected_vertices.update(face)
            for offset, a in enumerate(face):
                b = face[(offset + 1) % len(face)]
                edge = (a, b) if a < b else (b, a)
                selected_edge_users.setdefault(edge, []).append(face_index)
                oriented_edges.setdefault(edge, (a, b))

        for users in selected_edge_users.values():
            if len(users) == 2:
                a, b = users
                adjacency[a].add(b)
                adjacency[b].add(a)
            elif len(users) > 2:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Region contains a non-manifold selected edge",
                )

        visited = set()
        stack = [action.face_indices[0]]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(adjacency[current] - visited)
        if visited != selected:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Region faces must be edge-connected")

        boundary = [
            (edge, oriented_edges[edge])
            for edge, users in selected_edge_users.items()
            if len(users) == 1
        ]
        if not boundary:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Closed face region has no extrusion boundary",
            )

        vertices = [list(vertex) for vertex in before["vertices"]]
        mapping = {}
        source_vertices = sorted(selected_vertices)
        new_vertices = []
        for index in source_vertices:
            source = before["vertices"][index]
            value = vector3(
                [component + delta for component, delta in zip(source, action.offset, strict=True)],
                "region extrusion vertex",
                1_000_000,
            )
            mapping[index] = len(vertices)
            new_vertices.append(len(vertices))
            vertices.append(list(value))

        faces = [list(face) for face in before["faces"]]
        for face_index in action.face_indices:
            faces[face_index] = [mapping[index] for index in before["faces"][face_index]]
        for _, (old_a, old_b) in boundary:
            faces.append([old_a, old_b, mapping[old_b], mapping[old_a]])

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "region_face_indices": list(action.face_indices),
                "boundary_edge_count": len(boundary),
                "source_vertex_indices": source_vertices,
                "new_vertex_indices": new_vertices,
            },
        )

    def inset_face(self, request: Request, action: InsetFace):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        if action.face_index >= len(before["faces"]):
            raise invalid("Inset face index does not exist")
        face = before["faces"][action.face_index]
        if not 3 <= len(face) <= MAX_FACE_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported inset face size")

        center = [
            sum(before["vertices"][index][axis] for index in face) / len(face) for axis in range(3)
        ]
        vertices = [list(vertex) for vertex in before["vertices"]]
        inner = []
        for index in face:
            source = before["vertices"][index]
            value = vector3(
                [
                    center[axis] + (source[axis] - center[axis]) * (1.0 - action.factor)
                    for axis in range(3)
                ],
                "inset vertex",
                1_000_000,
            )
            inner.append(len(vertices))
            vertices.append(list(value))

        faces = [list(item) for item in before["faces"]]
        faces[action.face_index] = list(inner)
        for offset, old_a in enumerate(face):
            old_b = face[(offset + 1) % len(face)]
            new_a = inner[offset]
            new_b = inner[(offset + 1) % len(inner)]
            faces.append([old_a, old_b, new_b, new_a])

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "inset_face_index": action.face_index,
                "factor": action.factor,
                "inner_vertex_indices": inner,
            },
        )

    def bevel_boundary_edge(self, request: Request, action: BevelBoundaryEdge):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        users = self._edge_users(before["faces"])
        edges = sorted(users)
        if action.edge_index >= len(edges):
            raise invalid("Bevel edge index does not exist")
        edge = edges[action.edge_index]
        if len(users[edge]) != 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Boundary-edge bevel requires exactly one polygon user",
            )

        face_index = users[edge][0]
        face = before["faces"][face_index]
        if not 3 <= len(face) <= MAX_FACE_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported bevel face size")

        start = None
        for offset, a in enumerate(face):
            b = face[(offset + 1) % len(face)]
            if {a, b} == set(edge):
                start = offset
                break
        if start is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Edge is not present in polygon cycle")

        rotated = face[start:] + face[:start]
        old_a, old_b = rotated[0], rotated[1]
        prev_index = rotated[-1]
        next_index = rotated[2]
        point_a = before["vertices"][old_a]
        point_b = before["vertices"][old_b]
        prev_point = before["vertices"][prev_index]
        next_point = before["vertices"][next_index]

        new_a = vector3(
            [
                point_a[axis] + (prev_point[axis] - point_a[axis]) * action.factor
                for axis in range(3)
            ],
            "bevel vertex",
            1_000_000,
        )
        new_b = vector3(
            [
                point_b[axis] + (next_point[axis] - point_b[axis]) * action.factor
                for axis in range(3)
            ],
            "bevel vertex",
            1_000_000,
        )

        vertices = [list(vertex) for vertex in before["vertices"]]
        new_a_index = len(vertices)
        vertices.append(list(new_a))
        new_b_index = len(vertices)
        vertices.append(list(new_b))

        replacement = [new_a_index, new_b_index, *rotated[2:]]
        if len(set(replacement)) != len(replacement):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Bevel would create repeated polygon vertices",
            )
        faces = [list(item) for item in before["faces"]]
        faces[face_index] = replacement
        faces.append([old_a, old_b, new_b_index, new_a_index])

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "beveled_edge_index": action.edge_index,
                "beveled_edge": list(edge),
                "source_face_index": face_index,
                "factor": action.factor,
                "new_vertex_indices": [new_a_index, new_b_index],
            },
        )

    def tools(self):
        return [
            Tool(
                "mesh.extrude_region",
                SafetyClass.MUTATION,
                ExtrudeRegion.parse,
                self.extrude_region,
            ),
            Tool(
                "mesh.inset_face",
                SafetyClass.MUTATION,
                InsetFace.parse,
                self.inset_face,
            ),
            Tool(
                "mesh.bevel_boundary_edge",
                SafetyClass.MUTATION,
                BevelBoundaryEdge.parse,
                self.bevel_boundary_edge,
            ),
        ]
