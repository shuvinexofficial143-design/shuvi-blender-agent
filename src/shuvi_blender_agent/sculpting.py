"""Level 3 milestone 1: bounded sculpt-mesh diagnostics and radial brush foundations."""

from dataclasses import dataclass
from math import sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .modeling import topology_from_faces
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_SCULPT_VERTICES = 512
MAX_SMOOTH_ITERATIONS = 8
FALLOFFS = ("LINEAR", "SMOOTH")
NORMAL_EPSILON = 1e-12


def _sub(a, b):
    return tuple(a[index] - b[index] for index in range(3))


def _add(a, b):
    return tuple(a[index] + b[index] for index in range(3))


def _mul(value, scalar):
    return tuple(component * scalar for component in value)


def _length(value):
    return sqrt(sum(component * component for component in value))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _falloff(distance, radius, kind):
    normalized = min(max(distance / radius, 0.0), 1.0)
    weight = 1.0 - normalized
    if kind == "LINEAR":
        return weight
    return weight * weight * (3.0 - 2.0 * weight)


def _face_area_vector(vertices, face):
    origin = vertices[face[0]]
    total = (0.0, 0.0, 0.0)
    for offset in range(1, len(face) - 1):
        first = _sub(vertices[face[offset]], origin)
        second = _sub(vertices[face[offset + 1]], origin)
        total = _add(total, _cross(first, second))
    return total


def _vertex_normals(vertices, faces):
    accumulated = [(0.0, 0.0, 0.0) for _ in vertices]
    for face in faces:
        area_vector = _face_area_vector(vertices, face)
        for index in face:
            accumulated[index] = _add(accumulated[index], area_vector)

    normals = []
    for value in accumulated:
        length = _length(value)
        normals.append(
            (0.0, 0.0, 0.0)
            if length <= NORMAL_EPSILON
            else tuple(component / length for component in value)
        )
    return normals


def _brush_selection(vertices, center, radius, falloff):
    selected = []
    for index, vertex in enumerate(vertices):
        distance = _length(_sub(vertex, center))
        if distance <= radius:
            selected.append(
                {
                    "index": index,
                    "distance": distance,
                    "weight": _falloff(distance, radius, falloff),
                }
            )
    if len(selected) > MAX_SCULPT_VERTICES:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            f"Sculpt brush affects more than {MAX_SCULPT_VERTICES} vertices",
        )
    return selected


def _bool(value, name):
    if type(value) is not bool:
        raise invalid(f"{name} must be boolean")
    return value


@dataclass(frozen=True)
class SculptBrush:
    target: ObjectTarget
    expected_geometry_revision: str
    center: tuple[float, float, float]
    radius: float
    strength: float
    falloff: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "center",
                "radius",
                "strength",
                "falloff",
            },
        )
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        strength = number(data["strength"], "strength", -100, 100)
        if strength == 0:
            raise invalid("strength cannot be zero")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            strength,
            falloff,
        )


@dataclass(frozen=True)
class SculptSmooth:
    target: ObjectTarget
    expected_geometry_revision: str
    center: tuple[float, float, float]
    radius: float
    strength: float
    falloff: str
    iterations: int
    preserve_boundary: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "center",
                "radius",
                "strength",
                "falloff",
                "iterations",
                "preserve_boundary",
            },
        )
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        strength = number(data["strength"], "strength", 0.001, 1.0)
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            strength,
            falloff,
            integer(data["iterations"], "iterations", 1, MAX_SMOOTH_ITERATIONS),
            _bool(data["preserve_boundary"], "preserve_boundary"),
        )


class SculptingOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.meshes = MeshOperations(objects)

    def _mesh_state(self, obj):
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        geometry = self.meshes.snapshot(obj)
        topology = topology_from_faces(geometry["faces"])
        normals = _vertex_normals(geometry["vertices"], geometry["faces"])
        valence = [0] * len(geometry["vertices"])
        for a, b in topology["edges"]:
            valence[a] += 1
            valence[b] += 1
        degenerate_faces = [
            index
            for index, face in enumerate(geometry["faces"])
            if _length(_face_area_vector(geometry["vertices"], face)) <= NORMAL_EPSILON
        ]
        invalid_normal_vertices = [
            index for index, normal in enumerate(normals) if _length(normal) <= NORMAL_EPSILON
        ]
        return geometry, topology, normals, valence, degenerate_faces, invalid_normal_vertices

    def inspect(self, request: Request, object_id: str):
        obj = self.inspector.resolve(object_id)
        geometry, topology, normals, valence, degenerate, invalid_normals = self._mesh_state(obj)
        boundary_vertices = sorted(
            {index for edge in topology["boundary_edges"] for index in edge}
        )
        data = {
            "object_id": geometry["object_id"],
            "name": geometry["name"],
            "geometry_revision": geometry["geometry_revision"],
            "vertex_count": len(geometry["vertices"]),
            "face_count": len(geometry["faces"]),
            "edge_count": topology["edge_count"],
            "boundary_vertex_indices": boundary_vertices,
            "boundary_vertex_count": len(boundary_vertices),
            "nonmanifold_edge_count": topology["nonmanifold_edge_count"],
            "degenerate_face_indices": degenerate,
            "degenerate_face_count": len(degenerate),
            "invalid_normal_vertex_indices": invalid_normals,
            "invalid_normal_vertex_count": len(invalid_normals),
            "vertex_valence_min": min(valence) if valence else 0,
            "vertex_valence_max": max(valence) if valence else 0,
            "vertex_valence_average": (
                sum(valence) / len(valence) if valence else 0.0
            ),
            "sculpt_ready": (
                bool(geometry["faces"])
                and not degenerate
                and not invalid_normals
                and topology["nonmanifold_edge_count"] == len(topology["boundary_edges"])
            ),
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _editable_mesh(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        geometry = self.meshes.snapshot(obj)
        require_revision(action.expected_geometry_revision, geometry["geometry_revision"])
        if (
            obj.data.users != 1
            or obj.data.library is not None
            or obj.data.shape_keys is not None
            or len(obj.modifiers)
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Sculpt foundation requires unshared base mesh without shape keys/modifiers",
            )
        return obj, object_before, geometry

    def _verified_coordinate_mutation(
        self,
        request,
        obj,
        object_before,
        before,
        vertices,
        evidence,
        changed_indices,
    ):
        expected = {"vertices": vertices, "faces": before["faces"]} | evidence
        previous = {
            index: list(obj.data.vertices[index].co) for index in changed_indices
        }
        try:
            for index in changed_indices:
                obj.data.vertices[index].co = vertices[index]
            obj.data.update()
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
                for index, value in previous.items():
                    obj.data.vertices[index].co = value
                obj.data.update()
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            for index, value in previous.items():
                obj.data.vertices[index].co = value
            obj.data.update()
            self.bpy.context.view_layer.update()
            raise

    def displace(self, request: Request, action: SculptBrush):
        obj, object_before, before = self._editable_mesh(action)
        normals = _vertex_normals(before["vertices"], before["faces"])
        selected = _brush_selection(
            before["vertices"],
            action.center,
            action.radius,
            action.falloff,
        )
        affected = [
            item for item in selected if _length(normals[item["index"]]) > NORMAL_EPSILON
        ]
        if not affected:
            raise invalid("Sculpt brush affects no vertices with valid normals")

        vertices = [list(vertex) for vertex in before["vertices"]]
        weights = {}
        for item in affected:
            index = item["index"]
            weight = item["weight"]
            weights[str(index)] = weight
            vertices[index] = list(
                vector3(
                    _add(
                        before["vertices"][index],
                        _mul(normals[index], action.strength * weight),
                    ),
                    "sculpt displaced vertex",
                    1_000_000,
                )
            )
        evidence = {
            "brush": "DISPLACE_NORMAL",
            "center": list(action.center),
            "radius": action.radius,
            "strength": action.strength,
            "falloff": action.falloff,
            "affected_vertex_indices": [item["index"] for item in affected],
            "affected_vertex_count": len(affected),
            "weights": weights,
        }
        return self._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            [item["index"] for item in affected],
        )

    def smooth(self, request: Request, action: SculptSmooth):
        obj, object_before, before = self._editable_mesh(action)
        topology = topology_from_faces(before["faces"])
        adjacency = [set() for _ in before["vertices"]]
        for a, b in topology["edges"]:
            adjacency[a].add(b)
            adjacency[b].add(a)
        boundary = {index for edge in topology["boundary_edges"] for index in edge}
        selected = _brush_selection(
            before["vertices"],
            action.center,
            action.radius,
            action.falloff,
        )
        affected = [
            item
            for item in selected
            if adjacency[item["index"]]
            and not (action.preserve_boundary and item["index"] in boundary)
        ]
        if not affected:
            raise invalid("Sculpt smooth brush has no movable vertices")

        weights = {item["index"]: item["weight"] for item in affected}
        vertices = [list(vertex) for vertex in before["vertices"]]
        for _ in range(action.iterations):
            previous_iteration = [list(vertex) for vertex in vertices]
            for index, weight in weights.items():
                neighbors = adjacency[index]
                average = [
                    sum(previous_iteration[neighbor][axis] for neighbor in neighbors)
                    / len(neighbors)
                    for axis in range(3)
                ]
                factor = action.strength * weight
                vertices[index] = list(
                    vector3(
                        [
                            previous_iteration[index][axis]
                            + (average[axis] - previous_iteration[index][axis]) * factor
                            for axis in range(3)
                        ],
                        "sculpt smoothed vertex",
                        1_000_000,
                    )
                )
        evidence = {
            "brush": "SMOOTH",
            "center": list(action.center),
            "radius": action.radius,
            "strength": action.strength,
            "falloff": action.falloff,
            "iterations": action.iterations,
            "preserve_boundary": action.preserve_boundary,
            "affected_vertex_indices": sorted(weights),
            "affected_vertex_count": len(weights),
            "weights": {str(index): value for index, value in sorted(weights.items())},
        }
        return self._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            sorted(weights),
        )

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool("sculpt.inspect", SafetyClass.READ_ONLY, parse_id, self.inspect),
            Tool(
                "sculpt.brush_displace",
                SafetyClass.MUTATION,
                SculptBrush.parse,
                self.displace,
            ),
            Tool(
                "sculpt.brush_smooth",
                SafetyClass.MUTATION,
                SculptSmooth.parse,
                self.smooth,
            ),
        ]
