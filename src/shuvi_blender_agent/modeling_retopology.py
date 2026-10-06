"""Level 2 milestone 8: bounded retopology, projection and shrinkwrap-oriented helpers."""

from dataclasses import dataclass
from math import cos, sin, sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .mesh_transform import rotate_xyz
from .modeling import MAX_EDGES, MAX_VERTICES, topology_from_faces
from .modeling_hardsurface import HardSurfaceOperations, MAX_MODIFIERS
from .models import ObjectTarget, object_name, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_RETOPO_SELECTION = 128
MAX_RELAX_ITERATIONS = 8
MAX_PROJECTION_CHECKS = 1_000_000
SHRINKWRAP_METHODS = ("NEAREST_SURFACEPOINT", "NEAREST_VERTEX")
SHRINKWRAP_MODES = ("ON_SURFACE", "ABOVE_SURFACE")


def _indices(value, *, limit=MAX_RETOPO_SELECTION):
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise invalid(f"vertex_indices requires 1..{limit} indices")
    parsed = tuple(integer(item, "vertex_index", 0, MAX_VERTICES - 1) for item in value)
    if len(set(parsed)) != len(parsed):
        raise invalid("vertex_indices must be unique")
    return parsed


def _bool(value, name):
    if type(value) is not bool:
        raise invalid(f"{name} must be boolean")
    return value


def _sub(a, b):
    return tuple(a[index] - b[index] for index in range(3))


def _add(a, b):
    return tuple(a[index] + b[index] for index in range(3))


def _mul(vector, scalar):
    return tuple(value * scalar for value in vector)


def _dot(a, b):
    return sum(a[index] * b[index] for index in range(3))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(vector):
    return sqrt(_dot(vector, vector))


def _normalize(vector):
    length = _length(vector)
    if length <= 1e-12:
        return None
    return tuple(value / length for value in vector)


def _inverse_rotate_xyz(vector, euler):
    """Inverse of rotate_xyz: undo Z, then Y, then X rotations."""
    x, y, z = vector
    rx, ry, rz = euler
    sx, cx = sin(rx), cos(rx)
    sy, cy = sin(ry), cos(ry)
    sz, cz = sin(rz), cos(rz)

    x1 = cz * x + sz * y
    y1 = -sz * x + cz * y
    z1 = z

    x2 = cy * x1 - sy * z1
    y2 = y1
    z2 = sy * x1 + cy * z1

    return (
        x2,
        cx * y2 + sx * z2,
        -sx * y2 + cx * z2,
    )


def _world_from_local(value, transform):
    scaled = tuple(
        component * factor
        for component, factor in zip(value, transform["scale"], strict=True)
    )
    rotated = rotate_xyz(scaled, transform["rotation_euler"])
    return tuple(
        component + offset
        for component, offset in zip(rotated, transform["location"], strict=True)
    )


def _local_from_world(value, transform):
    translated = tuple(
        component - offset
        for component, offset in zip(value, transform["location"], strict=True)
    )
    rotated = _inverse_rotate_xyz(translated, transform["rotation_euler"])
    return vector3(
        [
            component / factor
            for component, factor in zip(rotated, transform["scale"], strict=True)
        ],
        "projected vertex",
        1_000_000,
    )


def _closest_point_triangle(point, a, b, c):
    """Return the nearest point on a nondegenerate triangle."""
    ab = _sub(b, a)
    ac = _sub(c, a)
    ap = _sub(point, a)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return a

    bp = _sub(point, b)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return b

    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        factor = d1 / (d1 - d3)
        return _add(a, _mul(ab, factor))

    cp = _sub(point, c)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return c

    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        factor = d2 / (d2 - d6)
        return _add(a, _mul(ac, factor))

    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        bc = _sub(c, b)
        factor = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return _add(b, _mul(bc, factor))

    denominator = va + vb + vc
    if abs(denominator) <= 1e-18:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Degenerate target triangle")
    inverse = 1.0 / denominator
    v = vb * inverse
    w = vc * inverse
    return _add(a, _add(_mul(ab, v), _mul(ac, w)))


@dataclass(frozen=True)
class ProjectionInspect:
    source_id: str
    target_id: str
    vertex_indices: tuple[int, ...]
    max_distance: float

    @classmethod
    def parse(cls, data):
        fields(data, {"source_id", "target_id", "vertex_indices", "max_distance"})
        return cls(
            string(data["source_id"], "source_id", limit=128),
            string(data["target_id"], "target_id", limit=128),
            _indices(data["vertex_indices"]),
            number(data["max_distance"], "max_distance", 0, 1_000_000),
        )


@dataclass(frozen=True)
class ProjectVertices:
    source: ObjectTarget
    target: ObjectTarget
    expected_source_geometry_revision: str
    expected_target_geometry_revision: str
    vertex_indices: tuple[int, ...]
    max_distance: float
    offset: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "source",
                "target",
                "expected_source_geometry_revision",
                "expected_target_geometry_revision",
                "vertex_indices",
                "max_distance",
                "offset",
            },
        )
        return cls(
            ObjectTarget.parse(data["source"]),
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_source_geometry_revision"],
                "expected_source_geometry_revision",
                limit=64,
            ),
            string(
                data["expected_target_geometry_revision"],
                "expected_target_geometry_revision",
                limit=64,
            ),
            _indices(data["vertex_indices"]),
            number(data["max_distance"], "max_distance", 0, 1_000_000),
            number(data["offset"], "offset", -100, 100),
        )


@dataclass(frozen=True)
class RelaxVertices:
    target: ObjectTarget
    expected_geometry_revision: str
    vertex_indices: tuple[int, ...]
    factor: float
    iterations: int
    preserve_boundary: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "vertex_indices",
                "factor",
                "iterations",
                "preserve_boundary",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            _indices(data["vertex_indices"]),
            number(data["factor"], "factor", 0.001, 1.0),
            integer(data["iterations"], "iterations", 1, MAX_RELAX_ITERATIONS),
            _bool(data["preserve_boundary"], "preserve_boundary"),
        )


@dataclass(frozen=True)
class ShrinkwrapAdd:
    source: ObjectTarget
    target: ObjectTarget
    expected_stack_revision: str
    name: str
    wrap_method: str
    wrap_mode: str
    offset: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "source",
                "target",
                "expected_stack_revision",
                "name",
                "wrap_method",
                "wrap_mode",
                "offset",
            },
        )
        method = data["wrap_method"]
        mode = data["wrap_mode"]
        if not isinstance(method, str) or method not in SHRINKWRAP_METHODS:
            raise invalid("wrap_method must be NEAREST_SURFACEPOINT or NEAREST_VERTEX")
        if not isinstance(mode, str) or mode not in SHRINKWRAP_MODES:
            raise invalid("wrap_mode must be ON_SURFACE or ABOVE_SURFACE")
        return cls(
            ObjectTarget.parse(data["source"]),
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            method,
            mode,
            number(data["offset"], "offset", -100, 100),
        )


class ModelingRetopologyOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.meshes = MeshOperations(objects)
        self.modifiers = HardSurfaceOperations(objects)

    def _mesh_snapshot(self, obj):
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        return self.meshes.snapshot(obj)

    @staticmethod
    def _transform_snapshot(obj):
        if obj.parent is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Retopology helper requires unparented objects")
        if obj.rotation_mode != "XYZ":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Retopology helper requires XYZ rotation")
        scale = tuple(float(value) for value in obj.scale)
        if any(abs(value) <= 1e-12 for value in scale):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Retopology helper rejects zero object scale")
        return {
            "location": tuple(float(value) for value in obj.location),
            "rotation_euler": tuple(float(value) for value in obj.rotation_euler),
            "scale": scale,
        }

    def _projection_target(self, obj):
        geometry = self._mesh_snapshot(obj)
        if obj.data.shape_keys is not None or len(obj.modifiers):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Projection target requires base mesh without shape keys/modifiers",
            )
        transform = self._transform_snapshot(obj)
        world_vertices = [
            _world_from_local(vertex, transform) for vertex in geometry["vertices"]
        ]
        triangles = []
        for face_index, face in enumerate(geometry["faces"]):
            if len(face) not in (3, 4):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Projection target currently requires triangle/quad faces",
                )
            for offset in range(1, len(face) - 1):
                tri = (face[0], face[offset], face[offset + 1])
                a, b, c = (world_vertices[index] for index in tri)
                normal = _normalize(_cross(_sub(b, a), _sub(c, a)))
                if normal is None:
                    continue
                triangles.append((face_index, tri, a, b, c, normal))
        if not triangles:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Projection target has no usable triangles")
        return geometry, transform, triangles

    def _projection_map(self, source_obj, target_obj, indices, max_distance):
        source_geometry = self._mesh_snapshot(source_obj)
        source_transform = self._transform_snapshot(source_obj)
        target_geometry, target_transform, triangles = self._projection_target(target_obj)
        if any(index >= len(source_geometry["vertices"]) for index in indices):
            raise invalid("Retopology source vertex index does not exist")
        checks = len(indices) * len(triangles)
        if checks > MAX_PROJECTION_CHECKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Projection work limit exceeded")

        matches = []
        for source_index in indices:
            point = _world_from_local(
                source_geometry["vertices"][source_index],
                source_transform,
            )
            best = None
            for face_index, tri, a, b, c, normal in triangles:
                nearest = _closest_point_triangle(point, a, b, c)
                distance = _length(_sub(point, nearest))
                candidate = (
                    distance,
                    face_index,
                    tri,
                    nearest,
                    normal,
                )
                if best is None or candidate[:3] < best[:3]:
                    best = candidate
            distance, face_index, tri, nearest, normal = best
            matches.append(
                {
                    "source_vertex_index": source_index,
                    "target_face_index": face_index,
                    "target_triangle_vertex_indices": list(tri),
                    "point_world": list(nearest),
                    "normal_world": list(normal),
                    "distance": distance,
                    "within_max_distance": distance <= max_distance,
                }
            )
        return {
            "source_geometry": source_geometry,
            "source_transform": source_transform,
            "target_geometry": target_geometry,
            "target_transform": target_transform,
            "matches": matches,
            "triangle_count": len(triangles),
            "projection_checks": checks,
        }

    def retopology_inspect(self, request: Request, object_id: str):
        obj = self.inspector.resolve(object_id)
        geometry = self._mesh_snapshot(obj)
        topology = topology_from_faces(geometry["faces"])
        valence = [0] * len(geometry["vertices"])
        for edge in topology["edges"]:
            valence[edge[0]] += 1
            valence[edge[1]] += 1
        boundary_vertices = sorted(
            {index for edge in topology["boundary_edges"] for index in edge}
        )
        boundary_set = set(boundary_vertices)
        triangles = [
            index for index, face in enumerate(geometry["faces"]) if len(face) == 3
        ]
        quads = [index for index, face in enumerate(geometry["faces"]) if len(face) == 4]
        ngons = [index for index, face in enumerate(geometry["faces"]) if len(face) > 4]
        isolated = [index for index, value in enumerate(valence) if value == 0]
        interior_poles = [
            index
            for index, value in enumerate(valence)
            if index not in boundary_set and value not in (0, 4)
        ]
        histogram = {}
        for value in valence:
            histogram[str(value)] = histogram.get(str(value), 0) + 1
        data = geometry | topology | {
            "vertex_valence": valence,
            "valence_histogram": dict(sorted(histogram.items(), key=lambda item: int(item[0]))),
            "boundary_vertex_indices": boundary_vertices,
            "isolated_vertex_indices": isolated,
            "interior_pole_vertex_indices": interior_poles,
            "triangle_face_indices": triangles,
            "quad_face_indices": quads,
            "ngon_face_indices": ngons,
            "quad_ratio": len(quads) / len(geometry["faces"]) if geometry["faces"] else 0.0,
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def projection_inspect(self, request: Request, action: ProjectionInspect):
        source = self.inspector.resolve(action.source_id)
        target = self.inspector.resolve(action.target_id)
        if source == target:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Projection source and target must differ")
        mapping = self._projection_map(
            source,
            target,
            action.vertex_indices,
            action.max_distance,
        )
        source_state = self.inspector.snapshot(source)
        target_state = self.inspector.snapshot(target)
        matches = mapping["matches"]
        data = {
            "source_object_id": source_state["object_id"],
            "source_object_revision": source_state["revision"],
            "source_geometry_revision": mapping["source_geometry"]["geometry_revision"],
            "target_object_id": target_state["object_id"],
            "target_object_revision": target_state["revision"],
            "target_geometry_revision": mapping["target_geometry"]["geometry_revision"],
            "max_distance": action.max_distance,
            "matches": matches,
            "matched_count": sum(item["within_max_distance"] for item in matches),
            "unmatched_vertex_indices": [
                item["source_vertex_index"]
                for item in matches
                if not item["within_max_distance"]
            ],
            "max_observed_distance": max(item["distance"] for item in matches),
            "triangle_count": mapping["triangle_count"],
            "projection_checks": mapping["projection_checks"],
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _editable_source(self, target):
        obj, object_before = self.inspector.target(target)
        self.objects._editable(obj)
        geometry = self._mesh_snapshot(obj)
        if (
            obj.data.users != 1
            or obj.data.library is not None
            or obj.data.shape_keys is not None
            or len(obj.modifiers)
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Retopology mutation requires unshared base mesh without shape keys/modifiers",
            )
        transform = self._transform_snapshot(obj)
        return obj, object_before, geometry, transform

    def project_vertices(self, request: Request, action: ProjectVertices):
        source, source_before, source_geometry, source_transform = self._editable_source(
            action.source
        )
        target, target_before = self.inspector.target(action.target)
        if source == target:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Projection source and target must differ")
        require_revision(
            action.expected_source_geometry_revision,
            source_geometry["geometry_revision"],
        )
        target_geometry = self._mesh_snapshot(target)
        require_revision(
            action.expected_target_geometry_revision,
            target_geometry["geometry_revision"],
        )

        mapping = self._projection_map(
            source,
            target,
            action.vertex_indices,
            action.max_distance,
        )
        if mapping["source_geometry"]["geometry_revision"] != source_geometry["geometry_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Source geometry changed during projection")
        if mapping["target_geometry"]["geometry_revision"] != target_geometry["geometry_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Target geometry changed during projection")
        unmatched = [
            item["source_vertex_index"]
            for item in mapping["matches"]
            if not item["within_max_distance"]
        ]
        if unmatched:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "One or more vertices exceed the projection distance limit",
            )

        expected = {
            "vertices": [list(vertex) for vertex in source_geometry["vertices"]],
            "faces": source_geometry["faces"],
        }
        previous = {}
        for item in mapping["matches"]:
            index = item["source_vertex_index"]
            previous[index] = list(source.data.vertices[index].co)
            world = _add(
                tuple(item["point_world"]),
                _mul(tuple(item["normal_world"]), action.offset),
            )
            expected["vertices"][index] = list(_local_from_world(world, source_transform))

        evidence = {
            "projected_vertex_indices": list(action.vertex_indices),
            "target_object_id": target_before["object_id"],
            "target_geometry_revision": target_geometry["geometry_revision"],
            "max_distance": action.max_distance,
            "offset": action.offset,
            "projection_checks": mapping["projection_checks"],
        }
        try:
            for index in action.vertex_indices:
                source.data.vertices[index].co = expected["vertices"][index]
            source.data.update()
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(source)
            after["object_revision"] = self.inspector.snapshot(source)["revision"]
            after.update(evidence)
            result = self.objects._result(
                request,
                {
                    "source": source_before,
                    "target": target_before,
                    "geometry": source_geometry,
                },
                after,
                expected | evidence,
            )
            if result.status == Status.FAILED:
                for index, value in previous.items():
                    source.data.vertices[index].co = value
                source.data.update()
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            for index, value in previous.items():
                source.data.vertices[index].co = value
            source.data.update()
            self.bpy.context.view_layer.update()
            raise

    def relax_vertices(self, request: Request, action: RelaxVertices):
        obj, object_before, before, _ = self._editable_source(action.target)
        require_revision(action.expected_geometry_revision, before["geometry_revision"])
        if any(index >= len(before["vertices"]) for index in action.vertex_indices):
            raise invalid("Retopology relax vertex index does not exist")

        topology = topology_from_faces(before["faces"])
        adjacency = [set() for _ in before["vertices"]]
        for a, b in topology["edges"]:
            adjacency[a].add(b)
            adjacency[b].add(a)
        boundary = {index for edge in topology["boundary_edges"] for index in edge}
        movable = [
            index
            for index in action.vertex_indices
            if adjacency[index] and not (action.preserve_boundary and index in boundary)
        ]
        if not movable:
            raise invalid("No selected vertices are movable with the requested boundary policy")

        vertices = [list(vertex) for vertex in before["vertices"]]
        for _ in range(action.iterations):
            previous_iteration = [list(vertex) for vertex in vertices]
            for index in movable:
                neighbors = adjacency[index]
                average = [
                    sum(previous_iteration[neighbor][axis] for neighbor in neighbors)
                    / len(neighbors)
                    for axis in range(3)
                ]
                vertices[index] = list(
                    vector3(
                        [
                            previous_iteration[index][axis]
                            + (average[axis] - previous_iteration[index][axis]) * action.factor
                            for axis in range(3)
                        ],
                        "relaxed vertex",
                        1_000_000,
                    )
                )

        previous = {index: list(obj.data.vertices[index].co) for index in movable}
        evidence = {
            "selected_vertex_indices": list(action.vertex_indices),
            "relaxed_vertex_indices": movable,
            "factor": action.factor,
            "iterations": action.iterations,
            "preserve_boundary": action.preserve_boundary,
        }
        expected = {"vertices": vertices, "faces": before["faces"]} | evidence
        try:
            for index in movable:
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

    def add_shrinkwrap(self, request: Request, action: ShrinkwrapAdd):
        source, source_before = self.modifiers._mesh_target(action.source)
        target, target_before = self.inspector.target(action.target)
        if source == target:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shrinkwrap target must be a different object")
        self._mesh_snapshot(target)
        if target.data.shape_keys is not None or len(target.modifiers):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shrinkwrap target requires base mesh without shape keys/modifiers",
            )
        self._transform_snapshot(source)
        self._transform_snapshot(target)
        before = self.modifiers.stack_snapshot(source)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        if len(source.modifiers) >= MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack is full")
        if source.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already exists")

        modifier = source.modifiers.new(action.name, "SHRINKWRAP")
        try:
            modifier.target = target
            modifier.wrap_method = action.wrap_method
            modifier.wrap_mode = action.wrap_mode
            modifier.offset = action.offset
            self.bpy.context.view_layer.update()
            after = self.modifiers.stack_snapshot(source)
            expected_entry = {
                "name": action.name,
                "type": "SHRINKWRAP",
                "show_viewport": True,
                "show_render": True,
                "settings": {
                    "wrap_method": action.wrap_method,
                    "wrap_mode": action.wrap_mode,
                    "offset": action.offset,
                    "target_object_id": target_before["object_id"],
                    "target_name": target_before["name"],
                },
            }
            result = self.objects._result(
                request,
                {
                    "source": source_before,
                    "target": target_before,
                    "stack": before,
                },
                after,
                {
                    "count": before["count"] + 1,
                    "items": before["items"] + [expected_entry],
                },
            )
            if result.status == Status.FAILED:
                self.modifiers._remove_if_present(source, modifier)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self.modifiers._remove_if_present(source, modifier)
            self.bpy.context.view_layer.update()
            raise

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool(
                "mesh.retopology_inspect",
                SafetyClass.READ_ONLY,
                parse_id,
                self.retopology_inspect,
            ),
            Tool(
                "mesh.retopology_projection_inspect",
                SafetyClass.READ_ONLY,
                ProjectionInspect.parse,
                self.projection_inspect,
            ),
            Tool(
                "mesh.retopology_project",
                SafetyClass.MUTATION,
                ProjectVertices.parse,
                self.project_vertices,
            ),
            Tool(
                "mesh.retopology_relax",
                SafetyClass.MUTATION,
                RelaxVertices.parse,
                self.relax_vertices,
            ),
            Tool(
                "modifier.shrinkwrap_add",
                SafetyClass.MUTATION,
                ShrinkwrapAdd.parse,
                self.add_shrinkwrap,
            ),
        ]
