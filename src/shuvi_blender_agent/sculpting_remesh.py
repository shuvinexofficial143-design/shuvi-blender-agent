"""Level 3 milestone 5: bounded remesh density planning and surface-preservation helpers."""

from dataclasses import dataclass
from math import ceil

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .modeling import topology_from_faces
from .operations import ObjectOperations
from .safety import SafetyClass
from .sculpting import _face_area_vector, _length, _sub, _vertex_normals
from .tools import Tool
from .validation import fields, integer, number, string

MAX_AXIS_VOXELS = 512
MAX_VOXEL_CELLS = 16_777_216
MAX_ANCHORS = 32


def _bounds(vertices):
    if not vertices:
        return ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return minimum, maximum


def _centroid(vertices):
    if not vertices:
        return [0.0, 0.0, 0.0]
    return [sum(vertex[axis] for vertex in vertices) / len(vertices) for axis in range(3)]


def _surface_area(vertices, faces):
    return 0.5 * sum(_length(_face_area_vector(vertices, face)) for face in faces)


def _average_edge_length(vertices, faces):
    topology = topology_from_faces(faces)
    if not topology["edges"]:
        return 0.0
    return sum(_length(_sub(vertices[a], vertices[b])) for a, b in topology["edges"]) / len(
        topology["edges"]
    )


def _voxel_plan(vertices, voxel_size):
    minimum, maximum = _bounds(vertices)
    extents = [maximum[axis] - minimum[axis] for axis in range(3)]
    dimensions = [max(1, int(ceil(extent / voxel_size)) + 2) for extent in extents]
    if any(value > MAX_AXIS_VOXELS for value in dimensions):
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            "Voxel plan exceeds per-axis resolution limit",
        )
    cells = dimensions[0] * dimensions[1] * dimensions[2]
    if cells > MAX_VOXEL_CELLS:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            "Voxel plan exceeds total cell work limit",
        )
    return minimum, maximum, extents, dimensions, cells


@dataclass(frozen=True)
class VoxelPlan:
    object_id: str
    voxel_size: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "voxel_size"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            number(data["voxel_size"], "voxel_size", 1e-6, 1_000_000),
        )


@dataclass(frozen=True)
class VoxelTarget:
    object_id: str
    longest_axis_voxels: int

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "longest_axis_voxels"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            integer(
                data["longest_axis_voxels"],
                "longest_axis_voxels",
                8,
                MAX_AXIS_VOXELS,
            ),
        )


@dataclass(frozen=True)
class SurfaceSnapshot:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class SurfaceAnchors:
    object_id: str
    max_anchors: int

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "max_anchors"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            integer(data["max_anchors"], "max_anchors", 4, MAX_ANCHORS),
        )


class SculptRemeshPlanningOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.meshes = MeshOperations(objects)

    def _mesh(self, object_id):
        obj = self.inspector.resolve(object_id)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        return obj, self.meshes.snapshot(obj)

    def voxel_plan(self, request: Request, action: VoxelPlan):
        obj, geometry = self._mesh(action.object_id)
        minimum, maximum, extents, dimensions, cells = _voxel_plan(
            geometry["vertices"],
            action.voxel_size,
        )
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "voxel_size": action.voxel_size,
            "bounds_min": minimum,
            "bounds_max": maximum,
            "extents": extents,
            "grid_dimensions": dimensions,
            "estimated_cell_count": cells,
            "per_axis_limit": MAX_AXIS_VOXELS,
            "total_cell_limit": MAX_VOXEL_CELLS,
            "runtime_remesh_required": True,
            "execution_status": "PLANNING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def target_density(self, request: Request, action: VoxelTarget):
        obj, geometry = self._mesh(action.object_id)
        minimum, maximum = _bounds(geometry["vertices"])
        extents = [maximum[axis] - minimum[axis] for axis in range(3)]
        longest = max(extents)
        if longest <= 0:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Cannot derive voxel density from zero-size mesh bounds",
            )
        voxel_size = longest / action.longest_axis_voxels
        _, _, _, dimensions, cells = _voxel_plan(geometry["vertices"], voxel_size)
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "longest_axis_extent": longest,
            "requested_longest_axis_voxels": action.longest_axis_voxels,
            "recommended_voxel_size": voxel_size,
            "grid_dimensions": dimensions,
            "estimated_cell_count": cells,
            "runtime_remesh_required": True,
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def surface_snapshot(self, request: Request, action: SurfaceSnapshot):
        obj, geometry = self._mesh(action.object_id)
        minimum, maximum = _bounds(geometry["vertices"])
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "bounds_min": minimum,
            "bounds_max": maximum,
            "centroid": _centroid(geometry["vertices"]),
            "surface_area": _surface_area(
                geometry["vertices"],
                geometry["faces"],
            ),
            "average_edge_length": _average_edge_length(
                geometry["vertices"],
                geometry["faces"],
            ),
            "vertex_count": len(geometry["vertices"]),
            "face_count": len(geometry["faces"]),
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def anchors(self, request: Request, action: SurfaceAnchors):
        obj, geometry = self._mesh(action.object_id)
        vertices = geometry["vertices"]
        if not vertices:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Surface anchor plan requires vertices")

        center = _centroid(vertices)
        selected = set()
        for axis in range(3):
            selected.add(min(range(len(vertices)), key=lambda i: (vertices[i][axis], i)))
            selected.add(max(range(len(vertices)), key=lambda i: (vertices[i][axis], -i)))

        by_center = sorted(
            range(len(vertices)),
            key=lambda index: (_length(_sub(vertices[index], center)), index),
        )
        for index in by_center:
            if len(selected) >= action.max_anchors:
                break
            selected.add(index)

        normals = _vertex_normals(vertices, geometry["faces"])
        anchors = [
            {
                "vertex_index": index,
                "position": list(vertices[index]),
                "normal": list(normals[index]),
                "distance_to_centroid": _length(_sub(vertices[index], center)),
            }
            for index in sorted(selected)[: action.max_anchors]
        ]
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "centroid": center,
            "anchor_count": len(anchors),
            "anchors": anchors,
            "purpose": "POST_REMESH_SURFACE_COMPARISON",
            "runtime_remesh_required": True,
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "sculpt.voxel_plan",
                SafetyClass.READ_ONLY,
                VoxelPlan.parse,
                self.voxel_plan,
            ),
            Tool(
                "sculpt.voxel_target_density",
                SafetyClass.READ_ONLY,
                VoxelTarget.parse,
                self.target_density,
            ),
            Tool(
                "sculpt.surface_snapshot",
                SafetyClass.READ_ONLY,
                SurfaceSnapshot.parse,
                self.surface_snapshot,
            ),
            Tool(
                "sculpt.surface_anchor_plan",
                SafetyClass.READ_ONLY,
                SurfaceAnchors.parse,
                self.anchors,
            ),
        ]
