"""Level 4 milestones 1-2: bounded UV diagnostics and verified seam controls."""

from dataclasses import dataclass
from math import sqrt
from statistics import median

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .mesh import MeshOperations
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string
from .verification import compare

MAX_UV_FACES = 256
MAX_UV_LOOPS = 8192
MAX_UV_LAYERS = 8
MAX_MESH_EDGES = 8192
MAX_SEAM_SELECTION = 512
MAX_OVERLAP_RESULTS = 256
UV_EPSILON = 1e-9
STRETCH_OUTLIER_FACTOR = 4.0


def _distance2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _signed_area2(points):
    return sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _uv_area(points):
    return abs(_signed_area2(points)) * 0.5


def _face_area_3d(vertices, face):
    origin = vertices[face[0]]
    area = 0.0
    for offset in range(1, len(face) - 1):
        a = [vertices[face[offset]][axis] - origin[axis] for axis in range(3)]
        b = [vertices[face[offset + 1]][axis] - origin[axis] for axis in range(3)]
        cross = [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
        area += 0.5 * sqrt(sum(value * value for value in cross))
    return area


def _line_intersection(start, end, a, b):
    dx1, dy1 = end[0] - start[0], end[1] - start[1]
    dx2, dy2 = b[0] - a[0], b[1] - a[1]
    denominator = dx1 * dy2 - dy1 * dx2
    if abs(denominator) <= UV_EPSILON:
        return list(end)
    t = ((a[0] - start[0]) * dy2 - (a[1] - start[1]) * dx2) / denominator
    return [start[0] + t * dx1, start[1] + t * dy1]


def _clip_triangle(subject, clip):
    orientation = 1.0 if _signed_area2(clip) >= 0 else -1.0
    output = [list(point) for point in subject]
    for index, a in enumerate(clip):
        b = clip[(index + 1) % len(clip)]
        current = output
        output = []
        if not current:
            break

        def inside(point, a=a, b=b, orientation=orientation):
            cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (
                point[0] - a[0]
            )
            return orientation * cross >= -UV_EPSILON

        start = current[-1]
        for end in current:
            end_inside, start_inside = inside(end), inside(start)
            if end_inside:
                if not start_inside:
                    output.append(_line_intersection(start, end, a, b))
                output.append(list(end))
            elif start_inside:
                output.append(_line_intersection(start, end, a, b))
            start = end
    return output


def _triangles(points):
    return [
        [points[0], points[offset], points[offset + 1]]
        for offset in range(1, len(points) - 1)
    ]


def _faces_overlap(first, second):
    first_bounds = (
        min(point[0] for point in first),
        max(point[0] for point in first),
        min(point[1] for point in first),
        max(point[1] for point in first),
    )
    second_bounds = (
        min(point[0] for point in second),
        max(point[0] for point in second),
        min(point[1] for point in second),
        max(point[1] for point in second),
    )
    if (
        first_bounds[1] <= second_bounds[0] + UV_EPSILON
        or second_bounds[1] <= first_bounds[0] + UV_EPSILON
        or first_bounds[3] <= second_bounds[2] + UV_EPSILON
        or second_bounds[3] <= first_bounds[2] + UV_EPSILON
    ):
        return False
    for a in _triangles(first):
        if _uv_area(a) <= UV_EPSILON:
            continue
        for b in _triangles(second):
            if _uv_area(b) <= UV_EPSILON:
                continue
            clipped = _clip_triangle(a, b)
            if len(clipped) >= 3 and _uv_area(clipped) > UV_EPSILON:
                return True
    return False


def _same_uv(a, b):
    return _distance2(a, b) <= UV_EPSILON * UV_EPSILON


@dataclass(frozen=True)
class SeamPreview:
    object_id: str
    edge_indices: tuple[int, ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "edge_indices"})
        indices = data["edge_indices"]
        if not isinstance(indices, list) or not 1 <= len(indices) <= MAX_SEAM_SELECTION:
            raise invalid(f"edge_indices requires 1..{MAX_SEAM_SELECTION} indices")
        parsed = tuple(integer(value, "edge_index", 0, MAX_MESH_EDGES - 1) for value in indices)
        if len(set(parsed)) != len(parsed):
            raise invalid("edge_indices must be unique")
        return cls(string(data["object_id"], "object_id", limit=128), parsed)


@dataclass(frozen=True)
class SeamSet:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_uv_revision: str
    edge_indices: tuple[int, ...]
    seam: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_uv_revision",
                "edge_indices",
                "seam",
            },
        )
        indices = data["edge_indices"]
        if not isinstance(indices, list) or not 1 <= len(indices) <= MAX_SEAM_SELECTION:
            raise invalid(f"edge_indices requires 1..{MAX_SEAM_SELECTION} indices")
        parsed = tuple(integer(value, "edge_index", 0, MAX_MESH_EDGES - 1) for value in indices)
        if len(set(parsed)) != len(parsed):
            raise invalid("edge_indices must be unique")
        if type(data["seam"]) is not bool:
            raise invalid("seam must be boolean")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_uv_revision"], "expected_uv_revision", limit=64),
            parsed,
            data["seam"],
        )


class UVOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector, self.bpy = objects.inspector, objects.bpy
        self.meshes = MeshOperations(objects)

    def _mesh(self, obj):
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if len(obj.data.polygons) > MAX_UV_FACES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV face diagnostic work limit exceeded")
        loops = sum(len(face.vertices) for face in obj.data.polygons)
        if loops > MAX_UV_LOOPS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV loop diagnostic work limit exceeded")
        edges = list(getattr(obj.data, "edges", ()))
        if len(edges) > MAX_MESH_EDGES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV edge diagnostic work limit exceeded")
        layers = list(getattr(obj.data, "uv_layers", ()))
        if len(layers) > MAX_UV_LAYERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV layer diagnostic work limit exceeded")
        return obj.data, loops, edges, layers

    @staticmethod
    def _edge_state(edges):
        pairs, flags = [], []
        for edge in edges:
            vertices = list(edge.vertices)
            if len(vertices) != 2:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Mesh edge readback is invalid")
            pairs.append([int(vertices[0]), int(vertices[1])])
            flags.append(bool(getattr(edge, "use_seam", False)))
        return pairs, flags

    @staticmethod
    def _layer_face_uvs(mesh, layer, expected_loops):
        data = list(getattr(layer, "data", ()))
        if len(data) != expected_loops:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV layer loop count does not match mesh")
        result, offset = [], 0
        for polygon in mesh.polygons:
            loop_start = int(getattr(polygon, "loop_start", offset))
            loop_total = int(getattr(polygon, "loop_total", len(polygon.vertices)))
            if loop_total != len(polygon.vertices):
                raise AgentError(ErrorCode.SAFETY_DENIED, "UV polygon loop mapping is unsupported")
            if loop_start < 0 or loop_start + loop_total > len(data):
                raise AgentError(ErrorCode.SAFETY_DENIED, "UV loop mapping is out of bounds")
            points = []
            for loop_index in range(loop_start, loop_start + loop_total):
                uv = list(data[loop_index].uv)
                if len(uv) != 2:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "UV coordinate readback is invalid",
                    )
                points.append([float(uv[0]), float(uv[1])])
            result.append(points)
            offset += len(polygon.vertices)
        return result

    @staticmethod
    def _island_count(faces, face_uvs):
        if not faces:
            return 0
        edge_users = {}
        face_maps = []
        for face_index, face in enumerate(faces):
            mapping = {vertex: face_uvs[face_index][offset] for offset, vertex in enumerate(face)}
            face_maps.append(mapping)
            for offset, a in enumerate(face):
                b = face[(offset + 1) % len(face)]
                edge = (a, b) if a < b else (b, a)
                edge_users.setdefault(edge, []).append(face_index)

        adjacency = [set() for _ in faces]
        for edge, users in edge_users.items():
            if len(users) != 2:
                continue
            first, second = users
            a, b = edge
            if (
                _same_uv(face_maps[first][a], face_maps[second][a])
                and _same_uv(face_maps[first][b], face_maps[second][b])
            ):
                adjacency[first].add(second)
                adjacency[second].add(first)

        seen, islands = set(), 0
        for start in range(len(faces)):
            if start in seen:
                continue
            islands += 1
            stack = [start]
            seen.add(start)
            while stack:
                current = stack.pop()
                for neighbor in adjacency[current]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        return islands

    def _layer_summary(self, geometry, mesh, layer, active_name, expected_loops):
        face_uvs = self._layer_face_uvs(mesh, layer, expected_loops)
        faces, vertices = geometry["faces"], geometry["vertices"]
        uv_areas = [_uv_area(points) for points in face_uvs]
        surface_areas = [_face_area_3d(vertices, face) for face in faces]
        ratios = [
            uv_area / surface_area
            if uv_area > UV_EPSILON and surface_area > UV_EPSILON
            else None
            for uv_area, surface_area in zip(uv_areas, surface_areas, strict=True)
        ]
        positive = [value for value in ratios if value is not None]
        baseline = median(positive) if positive else None
        stretch = []
        for value in ratios:
            if value is None or baseline is None or baseline <= UV_EPSILON:
                stretch.append(None)
            else:
                stretch.append(max(value / baseline, baseline / value))

        overlaps, truncated = [], False
        for first in range(len(face_uvs)):
            for second in range(first + 1, len(face_uvs)):
                if _faces_overlap(face_uvs[first], face_uvs[second]):
                    if len(overlaps) < MAX_OVERLAP_RESULTS:
                        overlaps.append([first, second])
                    else:
                        truncated = True

        coordinate_revision = revision(
            {
                "name": str(layer.name),
                "face_uvs": face_uvs,
            }
        )
        return {
            "name": str(layer.name),
            "active": str(layer.name) == active_name,
            "loop_count": expected_loops,
            "coordinate_revision": coordinate_revision,
            "uv_area_total": sum(uv_areas),
            "degenerate_uv_face_indices": [
                index for index, area in enumerate(uv_areas) if area <= UV_EPSILON
            ],
            "overlap_face_pairs": overlaps,
            "overlap_pairs_truncated": truncated,
            "island_count": self._island_count(faces, face_uvs),
            "stretch_outlier_face_indices": [
                index
                for index, factor in enumerate(stretch)
                if factor is not None and factor > STRETCH_OUTLIER_FACTOR
            ],
            "max_stretch_factor": max(
                (factor for factor in stretch if factor is not None),
                default=None,
            ),
        }

    def snapshot(self, obj):
        geometry = self.meshes.snapshot(obj)
        mesh, loop_count, edges, layers = self._mesh(obj)
        edge_pairs, seam_flags = self._edge_state(edges)
        active = getattr(getattr(mesh, "uv_layers", None), "active", None)
        active_name = str(active.name) if active is not None else None
        layer_summaries = [
            self._layer_summary(geometry, mesh, layer, active_name, loop_count) for layer in layers
        ]
        uv_revision = revision(
            {
                "geometry_revision": geometry["geometry_revision"],
                "layers": [
                    {
                        "name": item["name"],
                        "coordinate_revision": item["coordinate_revision"],
                    }
                    for item in layer_summaries
                ],
                "seam_flags": seam_flags,
            }
        )
        return {
            "object_id": geometry["object_id"],
            "name": geometry["name"],
            "geometry_revision": geometry["geometry_revision"],
            "uv_revision": uv_revision,
            "missing_uv": not layer_summaries,
            "uv_layer_count": len(layer_summaries),
            "active_uv_layer": active_name,
            "layers": layer_summaries,
            "edge_count": len(edges),
            "edge_vertex_pairs": edge_pairs,
            "seam_flags": seam_flags,
            "seam_edge_indices": [index for index, value in enumerate(seam_flags) if value],
            "seam_vertex_pairs": [
                edge_pairs[index] for index, value in enumerate(seam_flags) if value
            ],
        }

    def inspect(self, request: Request, object_id: str):
        data = self.snapshot(self.inspector.resolve(object_id))
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def seam_preview(self, request: Request, action: SeamPreview):
        data = self.snapshot(self.inspector.resolve(action.object_id))
        if any(index >= data["edge_count"] for index in action.edge_indices):
            raise invalid("Seam edge index does not exist")
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": data["object_id"],
                "geometry_revision": data["geometry_revision"],
                "uv_revision": data["uv_revision"],
                "edges": [
                    {
                        "edge_index": index,
                        "vertices": data["edge_vertex_pairs"][index],
                        "seam": data["seam_flags"][index],
                    }
                    for index in action.edge_indices
                ],
                "execution_status": "PREVIEW_ONLY",
            },
        )

    def _editable_seam_mesh(self, action: SeamSet):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        mesh, _, _, _ = self._mesh(obj)
        if mesh.users != 1 or mesh.library is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unshared local mesh data required")
        before = self.snapshot(obj)
        require_revision(action.expected_geometry_revision, before["geometry_revision"])
        require_revision(action.expected_uv_revision, before["uv_revision"])
        if any(index >= before["edge_count"] for index in action.edge_indices):
            raise invalid("Seam edge index does not exist")
        return obj, object_before, before

    @staticmethod
    def _verification_view(snapshot):
        return {
            "geometry_revision": snapshot["geometry_revision"],
            "layer_revisions": [
                [item["name"], item["coordinate_revision"]] for item in snapshot["layers"]
            ],
            "seam_flags": snapshot["seam_flags"],
        }

    def seam_set(self, request: Request, action: SeamSet):
        obj, object_before, before = self._editable_seam_mesh(action)
        expected_flags = list(before["seam_flags"])
        for index in action.edge_indices:
            expected_flags[index] = action.seam
        expected = self._verification_view(before) | {"seam_flags": expected_flags}

        for index in action.edge_indices:
            obj.data.edges[index].use_seam = action.seam
        obj.data.update()
        self.bpy.context.view_layer.update()
        after = self.snapshot(obj)
        actual = self._verification_view(after)
        verification = compare(expected, actual)

        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "before": before,
                    "after": after,
                    "changed_edge_indices": list(action.edge_indices),
                    "seam": action.seam,
                },
                verification=verification.to_dict(),
            )

        for index, value in enumerate(before["seam_flags"]):
            obj.data.edges[index].use_seam = value
        obj.data.update()
        self.bpy.context.view_layer.update()
        restored = self.snapshot(obj)
        recovery = compare(self._verification_view(before), self._verification_view(restored))
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Seam verification failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
                "object_before": object_before,
            },
            AgentError(ErrorCode.VERIFICATION_FAILED, "Seam readback differs from requested state"),
            verification.to_dict(),
        )

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool("uv.inspect", SafetyClass.READ_ONLY, parse_id, self.inspect),
            Tool("uv.seam_preview", SafetyClass.READ_ONLY, SeamPreview.parse, self.seam_preview),
            Tool("uv.seam_set", SafetyClass.MUTATION, SeamSet.parse, self.seam_set),
        ]
