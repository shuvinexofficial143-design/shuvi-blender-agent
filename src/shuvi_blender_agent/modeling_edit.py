"""Level 2 milestone 2: bounded element transforms, vertex merge and edge dissolve."""

from dataclasses import dataclass

from .contracts import Request, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .mesh_transform import rotate_xyz
from .modeling import MAX_EDGES, MAX_FACE_VERTICES, MAX_FACES, MAX_VERTICES, topology_from_faces
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string

MAX_ELEMENT_SELECTION = 256
MAX_MERGE_VERTICES = 64
DOMAINS = ("VERTEX", "EDGE", "FACE")
MERGE_MODES = ("CENTER", "FIRST", "LAST")


def _indices(value, name, limit, maximum):
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise invalid(f"{name} requires 1..{limit} indices")
    parsed = tuple(integer(item, name, 0, maximum) for item in value)
    if len(set(parsed)) != len(parsed):
        raise invalid(f"{name} indices must be unique")
    return parsed


@dataclass(frozen=True)
class TransformElements:
    target: ObjectTarget
    expected_geometry_revision: str
    domain: str
    indices: tuple[int, ...]
    translation: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]
    scale: tuple[float, float, float]
    pivot: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "domain",
                "indices",
                "translation",
                "rotation_euler",
                "scale",
                "pivot",
            },
        )
        domain = data["domain"]
        if not isinstance(domain, str) or domain not in DOMAINS:
            raise invalid("domain must be VERTEX, EDGE or FACE")
        maximum = MAX_EDGES - 1 if domain == "EDGE" else MAX_VERTICES - 1
        if domain == "FACE":
            maximum = MAX_FACES - 1
        indices = _indices(data["indices"], "element", MAX_ELEMENT_SELECTION, maximum)
        translation = vector3(data["translation"], "translation", 1000)
        rotation = vector3(data["rotation_euler"], "rotation_euler", 1000)
        scale = vector3(data["scale"], "scale", 10000)
        pivot = vector3(data["pivot"], "pivot", 1_000_000)
        if (
            translation == (0.0, 0.0, 0.0)
            and rotation == (0.0, 0.0, 0.0)
            and scale == (1.0, 1.0, 1.0)
        ):
            raise invalid("Element transform cannot be a no-op")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            domain,
            indices,
            translation,
            rotation,
            scale,
            pivot,
        )


@dataclass(frozen=True)
class MergeVertices:
    target: ObjectTarget
    expected_geometry_revision: str
    indices: tuple[int, ...]
    mode: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "indices", "mode"})
        indices = _indices(data["indices"], "merge vertex", MAX_MERGE_VERTICES, MAX_VERTICES - 1)
        if len(indices) < 2:
            raise invalid("Merge requires at least two vertices")
        mode = data["mode"]
        if not isinstance(mode, str) or mode not in MERGE_MODES:
            raise invalid("mode must be CENTER, FIRST or LAST")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            indices,
            mode,
        )


@dataclass(frozen=True)
class DissolveEdge:
    target: ObjectTarget
    expected_geometry_revision: str
    edge_index: int

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "edge_index"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            integer(data["edge_index"], "edge_index", 0, MAX_EDGES - 1),
        )


class ModelingEditOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.meshes = MeshOperations(objects)

    def _editable_mesh(self, action, *, rebuild=False):
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
        if rebuild:
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
    def _transform_point(value, action):
        relative = [
            (component - center) * factor
            for component, center, factor in zip(value, action.pivot, action.scale, strict=True)
        ]
        rotated = rotate_xyz(relative, action.rotation_euler)
        return vector3(
            [
                component + center + delta
                for component, center, delta in zip(
                    rotated, action.pivot, action.translation, strict=True
                )
            ],
            "transformed vertex",
            1_000_000,
        )

    @staticmethod
    def _edge_face_users(faces):
        users = {}
        for face_index, face in enumerate(faces):
            for offset, a in enumerate(face):
                b = face[(offset + 1) % len(face)]
                edge = (a, b) if a < b else (b, a)
                users.setdefault(edge, []).append(face_index)
        return users

    @staticmethod
    def _long_path(face, start, end):
        start_index = face.index(start)
        size = len(face)

        def walk(step):
            path = [start]
            index = start_index
            for _ in range(size):
                index = (index + step) % size
                path.append(face[index])
                if face[index] == end:
                    return path
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid polygon cycle")

        forward = walk(1)
        if len(forward) > 2:
            return forward
        backward = walk(-1)
        if len(backward) > 2:
            return backward
        raise AgentError(ErrorCode.SAFETY_DENIED, "Edge dissolve requires polygon remainder")

    def transform_elements(self, request: Request, action: TransformElements):
        obj, object_before, before = self._editable_mesh(action)
        topology = topology_from_faces(before["faces"])

        if action.domain == "VERTEX":
            if any(index >= len(before["vertices"]) for index in action.indices):
                raise invalid("Vertex index does not exist")
            affected = set(action.indices)
        elif action.domain == "EDGE":
            if any(index >= len(topology["edges"]) for index in action.indices):
                raise invalid("Edge index does not exist")
            affected = {
                vertex
                for edge_index in action.indices
                for vertex in topology["edges"][edge_index]
            }
        else:
            if any(index >= len(before["faces"]) for index in action.indices):
                raise invalid("Face index does not exist")
            affected = {
                vertex
                for face_index in action.indices
                for vertex in before["faces"][face_index]
            }

        expected = {
            "vertices": [list(vertex) for vertex in before["vertices"]],
            "faces": before["faces"],
        }
        previous = {index: list(obj.data.vertices[index].co) for index in affected}
        for index in affected:
            expected["vertices"][index] = list(
                self._transform_point(before["vertices"][index], action)
            )

        try:
            for index in affected:
                obj.data.vertices[index].co = expected["vertices"][index]
            obj.data.update()
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(obj)
            after["object_revision"] = self.inspector.snapshot(obj)["revision"]
            after["domain"] = action.domain
            after["element_indices"] = list(action.indices)
            after["affected_vertex_indices"] = sorted(affected)
            expected_result = expected | {
                "domain": action.domain,
                "element_indices": list(action.indices),
                "affected_vertex_indices": sorted(affected),
            }
            result = self.objects._result(
                request,
                {"object": object_before, "geometry": before},
                after,
                expected_result,
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

    def merge_vertices(self, request: Request, action: MergeVertices):
        obj, object_before, before = self._editable_mesh(action, rebuild=True)
        if any(index >= len(before["vertices"]) for index in action.indices):
            raise invalid("Merge vertex index does not exist")

        selected = set(action.indices)
        keep = action.indices[-1] if action.mode == "LAST" else action.indices[0]
        if action.mode == "CENTER":
            position = [
                sum(before["vertices"][index][axis] for index in action.indices)
                / len(action.indices)
                for axis in range(3)
            ]
        else:
            source = action.indices[-1] if action.mode == "LAST" else action.indices[0]
            position = list(before["vertices"][source])
        position = list(vector3(position, "merge position", 1_000_000))

        intermediate_vertices = [list(vertex) for vertex in before["vertices"]]
        intermediate_vertices[keep] = position
        intermediate_faces = []
        for face in before["faces"]:
            collapsed = []
            for index in face:
                mapped = keep if index in selected else index
                if not collapsed or collapsed[-1] != mapped:
                    collapsed.append(mapped)
            if len(collapsed) > 1 and collapsed[0] == collapsed[-1]:
                collapsed.pop()
            if len(set(collapsed)) < 3:
                continue
            if len(set(collapsed)) != len(collapsed):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Merge would create a self-repeating polygon",
                )
            intermediate_faces.append(collapsed)

        removed = selected - {keep}
        old_to_new = {}
        vertices = []
        for old_index, value in enumerate(intermediate_vertices):
            if old_index in removed:
                continue
            old_to_new[old_index] = len(vertices)
            vertices.append(value)
        faces = [[old_to_new[index] for index in face] for face in intermediate_faces]
        keep_after = old_to_new[keep]

        try:
            self._replace_geometry(obj.data, vertices, faces)
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(obj)
            after["object_revision"] = self.inspector.snapshot(obj)["revision"]
            after["merge_mode"] = action.mode
            after["merged_vertex_indices"] = list(action.indices)
            after["result_vertex_index"] = keep_after
            expected = {
                "vertices": vertices,
                "faces": faces,
                "merge_mode": action.mode,
                "merged_vertex_indices": list(action.indices),
                "result_vertex_index": keep_after,
            }
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

    def dissolve_edge(self, request: Request, action: DissolveEdge):
        obj, object_before, before = self._editable_mesh(action, rebuild=True)
        topology = topology_from_faces(before["faces"])
        if action.edge_index >= len(topology["edges"]):
            raise invalid("Edge index does not exist")

        edge = tuple(topology["edges"][action.edge_index])
        users = self._edge_face_users(before["faces"])[edge]
        if len(users) != 2:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Dissolve foundation requires an edge shared by exactly two faces",
            )

        first_index, second_index = sorted(users)
        first = before["faces"][first_index]
        second = before["faces"][second_index]
        path_a = self._long_path(first, edge[0], edge[1])
        path_b = self._long_path(second, edge[1], edge[0])
        merged = path_a + path_b[1:-1]
        if not 3 <= len(merged) <= MAX_FACE_VERTICES or len(set(merged)) != len(merged):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Dissolve would create an unsupported polygon",
            )

        faces = [list(face) for face in before["faces"]]
        faces[first_index] = merged
        del faces[second_index]
        vertices = [list(vertex) for vertex in before["vertices"]]

        try:
            self._replace_geometry(obj.data, vertices, faces)
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(obj)
            after["object_revision"] = self.inspector.snapshot(obj)["revision"]
            after["dissolved_edge"] = list(edge)
            after["dissolved_edge_index"] = action.edge_index
            after["merged_face_index"] = first_index
            expected = {
                "vertices": vertices,
                "faces": faces,
                "dissolved_edge": list(edge),
                "dissolved_edge_index": action.edge_index,
                "merged_face_index": first_index,
            }
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
        return [
            Tool(
                "mesh.transform_elements",
                SafetyClass.MUTATION,
                TransformElements.parse,
                self.transform_elements,
            ),
            Tool(
                "mesh.merge_vertices",
                SafetyClass.MUTATION,
                MergeVertices.parse,
                self.merge_vertices,
            ),
            Tool(
                "mesh.dissolve_edge",
                SafetyClass.MUTATION,
                DissolveEdge.parse,
                self.dissolve_edge,
            ),
        ]
