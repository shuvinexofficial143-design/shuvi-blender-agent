"""Level 2 milestone 5: normals, smoothing and shading/topology diagnostics."""

from dataclasses import dataclass
from math import sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .mesh import MeshOperations
from .modeling import MAX_FACES
from .modeling_region import ModelingRegionOperations
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string

MAX_SMOOTH_FACES = 256
NORMAL_EPSILON = 1e-12


def _vector_sub(a, b):
    return [a[index] - b[index] for index in range(3)]


def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _length(vector):
    return sqrt(sum(value * value for value in vector))


def _face_geometry(vertices, face):
    origin = vertices[face[0]]
    area_vector = [0.0, 0.0, 0.0]
    area = 0.0
    for offset in range(1, len(face) - 1):
        first = _vector_sub(vertices[face[offset]], origin)
        second = _vector_sub(vertices[face[offset + 1]], origin)
        cross = _cross(first, second)
        area += 0.5 * _length(cross)
        for axis in range(3):
            area_vector[axis] += cross[axis]

    normal_length = _length(area_vector)
    normal = (
        [value / normal_length for value in area_vector]
        if normal_length > NORMAL_EPSILON
        else [0.0, 0.0, 0.0]
    )
    return {
        "normal": normal,
        "area": area,
        "degenerate": area <= NORMAL_EPSILON,
        "normal_ambiguous": area > NORMAL_EPSILON and normal_length <= NORMAL_EPSILON,
    }


def _edge_orientation_diagnostics(faces):
    users = {}
    for face_index, face in enumerate(faces):
        for offset, a in enumerate(face):
            b = face[(offset + 1) % len(face)]
            edge = (a, b) if a < b else (b, a)
            direction = 1 if (a, b) == edge else -1
            users.setdefault(edge, []).append((face_index, direction))

    winding_conflicts = []
    nonmanifold = []
    boundary = []
    for edge in sorted(users):
        edge_users = users[edge]
        if len(edge_users) == 1:
            boundary.append(list(edge))
        if len(edge_users) != 2:
            nonmanifold.append(list(edge))
        elif edge_users[0][1] == edge_users[1][1]:
            winding_conflicts.append(list(edge))
    return users, boundary, nonmanifold, winding_conflicts


@dataclass(frozen=True)
class SetFaceSmoothing:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_shading_revision: str
    face_indices: tuple[int, ...]
    smooth: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_shading_revision",
                "face_indices",
                "smooth",
            },
        )
        values = data["face_indices"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_SMOOTH_FACES:
            raise invalid(f"face_indices requires 1..{MAX_SMOOTH_FACES} indices")
        indices = tuple(integer(value, "face_index", 0, MAX_FACES - 1) for value in values)
        if len(set(indices)) != len(indices):
            raise invalid("face_indices must be unique")
        if type(data["smooth"]) is not bool:
            raise invalid("smooth must be boolean")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_shading_revision"], "expected_shading_revision", limit=64),
            indices,
            data["smooth"],
        )


@dataclass(frozen=True)
class OrientFaces:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_shading_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"target", "expected_geometry_revision", "expected_shading_revision"},
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_shading_revision"], "expected_shading_revision", limit=64),
        )


class ModelingShadingOperations(ModelingRegionOperations):
    def __init__(self, objects: ObjectOperations):
        super().__init__(objects)
        self.meshes = MeshOperations(objects)

    def shading_snapshot(self, obj):
        geometry = self.meshes.snapshot(obj)
        vertices = geometry["vertices"]
        faces = geometry["faces"]
        face_data = [_face_geometry(vertices, face) for face in faces]
        smooth = [bool(getattr(face, "use_smooth", False)) for face in obj.data.polygons]
        users, boundary, nonmanifold, winding = _edge_orientation_diagnostics(faces)

        referenced = {index for face in faces for index in face}
        isolated = [index for index in range(len(vertices)) if index not in referenced]
        degenerate = [index for index, data in enumerate(face_data) if data["degenerate"]]
        ambiguous = [index for index, data in enumerate(face_data) if data["normal_ambiguous"]]
        state = {
            "geometry_revision": geometry["geometry_revision"],
            "object_id": geometry["object_id"],
            "name": geometry["name"],
            "face_normals": [data["normal"] for data in face_data],
            "face_areas": [data["area"] for data in face_data],
            "face_smooth": smooth,
            "smooth_face_indices": [index for index, value in enumerate(smooth) if value],
            "flat_face_indices": [index for index, value in enumerate(smooth) if not value],
            "degenerate_face_indices": degenerate,
            "ambiguous_normal_face_indices": ambiguous,
            "isolated_vertex_indices": isolated,
            "boundary_edges": boundary,
            "boundary_edge_count": len(boundary),
            "nonmanifold_edges": nonmanifold,
            "nonmanifold_edge_count": len(nonmanifold),
            "winding_conflict_edges": winding,
            "winding_conflict_edge_count": len(winding),
            "derived_edge_count": len(users),
        }
        state["shading_revision"] = revision(
            {
                "geometry_revision": state["geometry_revision"],
                "face_smooth": smooth,
            }
        )
        return state

    def inspect_shading(self, request: Request, object_id: str):
        obj = self.inspector.resolve(object_id)
        data = self.shading_snapshot(obj)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _editable_shading_mesh(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if obj.data.users != 1 or obj.data.library is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unshared local mesh data required")
        if obj.data.shape_keys is not None or len(obj.modifiers):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Smoothing mutation requires mesh without shape keys/modifiers",
            )
        before = self.shading_snapshot(obj)
        require_revision(action.expected_geometry_revision, before["geometry_revision"])
        require_revision(action.expected_shading_revision, before["shading_revision"])
        return obj, object_before, before

    @staticmethod
    def _restore_smoothing(obj, values):
        for face, value in zip(obj.data.polygons, values, strict=True):
            face.use_smooth = value
        obj.data.update()

    def set_face_smoothing(self, request: Request, action: SetFaceSmoothing):
        obj, object_before, before = self._editable_shading_mesh(action)
        if any(index >= len(obj.data.polygons) for index in action.face_indices):
            raise invalid("Smoothing face index does not exist")

        previous = list(before["face_smooth"])
        expected_flags = list(previous)
        for index in action.face_indices:
            expected_flags[index] = action.smooth

        try:
            for index in action.face_indices:
                obj.data.polygons[index].use_smooth = action.smooth
            obj.data.update()
            self.bpy.context.view_layer.update()
            after = self.shading_snapshot(obj)
            expected = {
                "geometry_revision": before["geometry_revision"],
                "face_smooth": expected_flags,
                "smooth_face_indices": [
                    index for index, value in enumerate(expected_flags) if value
                ],
                "flat_face_indices": [
                    index for index, value in enumerate(expected_flags) if not value
                ],
                "shading_revision": revision(
                    {
                        "geometry_revision": before["geometry_revision"],
                        "face_smooth": expected_flags,
                    }
                ),
            }
            result = self.objects._result(
                request,
                {"object": object_before, "shading": before},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                self._restore_smoothing(obj, previous)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._restore_smoothing(obj, previous)
            self.bpy.context.view_layer.update()
            raise

    @staticmethod
    def _orientation_plan(faces):
        users, _, nonmanifold, winding = _edge_orientation_diagnostics(faces)
        if any(len(users[tuple(edge)]) > 2 for edge in nonmanifold):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Consistent orientation rejects edges with more than two face users",
            )

        adjacency = {index: [] for index in range(len(faces))}
        for edge_users in users.values():
            if len(edge_users) != 2:
                continue
            (first, direction_a), (second, direction_b) = edge_users
            different_flip = direction_a == direction_b
            adjacency[first].append((second, different_flip))
            adjacency[second].append((first, different_flip))

        flips = {}
        components = 0
        for root in range(len(faces)):
            if root in flips:
                continue
            components += 1
            flips[root] = False
            stack = [root]
            while stack:
                current = stack.pop()
                for neighbor, different in adjacency[current]:
                    wanted = flips[current] ^ different
                    if neighbor in flips:
                        if flips[neighbor] != wanted:
                            raise AgentError(
                                ErrorCode.SAFETY_DENIED,
                                "Face graph has contradictory orientation constraints",
                            )
                        continue
                    flips[neighbor] = wanted
                    stack.append(neighbor)
        return sorted(index for index, value in flips.items() if value), components, winding

    def orient_faces_consistently(self, request: Request, action: OrientFaces):
        obj, object_before, geometry_before = self._editable_rebuild_mesh(action)
        shading_before = self.shading_snapshot(obj)
        require_revision(action.expected_shading_revision, shading_before["shading_revision"])
        if geometry_before["geometry_revision"] != shading_before["geometry_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Geometry changed during shading inspection")

        flips, components, conflicts_before = self._orientation_plan(geometry_before["faces"])
        vertices = [list(vertex) for vertex in geometry_before["vertices"]]
        faces = [list(face) for face in geometry_before["faces"]]
        for index in flips:
            faces[index] = list(reversed(faces[index]))
        smooth = list(shading_before["face_smooth"])

        try:
            self._replace_geometry(obj.data, vertices, faces)
            self._restore_smoothing(obj, smooth)
            self.bpy.context.view_layer.update()
            after = self.shading_snapshot(obj)
            expected = {
                "geometry_revision": revision({"vertices": vertices, "faces": faces}),
                "face_smooth": smooth,
                "winding_conflict_edge_count": 0,
                "winding_conflict_edges": [],
            }
            after["flipped_face_indices"] = flips
            after["orientation_component_count"] = components
            after["winding_conflict_edges_before"] = conflicts_before
            expected |= {
                "flipped_face_indices": flips,
                "orientation_component_count": components,
                "winding_conflict_edges_before": conflicts_before,
            }
            result = self.objects._result(
                request,
                {"object": object_before, "shading": shading_before},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                self._replace_geometry(
                    obj.data,
                    geometry_before["vertices"],
                    geometry_before["faces"],
                )
                self._restore_smoothing(obj, smooth)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._replace_geometry(
                obj.data,
                geometry_before["vertices"],
                geometry_before["faces"],
            )
            self._restore_smoothing(obj, smooth)
            self.bpy.context.view_layer.update()
            raise

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool(
                "mesh.shading_inspect",
                SafetyClass.READ_ONLY,
                parse_id,
                self.inspect_shading,
            ),
            Tool(
                "mesh.set_face_smoothing",
                SafetyClass.MUTATION,
                SetFaceSmoothing.parse,
                self.set_face_smoothing,
            ),
            Tool(
                "mesh.orient_faces_consistently",
                SafetyClass.MUTATION,
                OrientFaces.parse,
                self.orient_faces_consistently,
            ),
        ]
