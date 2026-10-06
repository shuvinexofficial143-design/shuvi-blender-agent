"""Level 2 milestone 4: subdivide, quad-strip loop cut, bridge and fill foundations."""

from dataclasses import dataclass

from .contracts import Request
from .errors import AgentError, ErrorCode
from .modeling import MAX_EDGES, MAX_FACE_VERTICES, MAX_VERTICES
from .modeling_region import ModelingRegionOperations
from .models import ObjectTarget, vector3
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_LOOP_VERTICES = 64
MAX_LOOP_CUT_EDGES = 256


def _vertex_loop(value, name, limit=MAX_LOOP_VERTICES):
    if not isinstance(value, list) or not 3 <= len(value) <= limit:
        raise invalid(f"{name} requires 3..{limit} vertex indices")
    parsed = tuple(integer(item, name, 0, MAX_VERTICES - 1) for item in value)
    if len(set(parsed)) != len(parsed):
        raise invalid(f"{name} vertices must be unique")
    return parsed


@dataclass(frozen=True)
class SubdivideEdge:
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
            number(data["factor"], "factor", 0.001, 0.999),
        )


@dataclass(frozen=True)
class LoopCutQuadStrip:
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
            number(data["factor"], "factor", 0.001, 0.999),
        )


@dataclass(frozen=True)
class BridgeBoundaryLoops:
    target: ObjectTarget
    expected_geometry_revision: str
    loop_a: tuple[int, ...]
    loop_b: tuple[int, ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "loop_a", "loop_b"})
        loop_a = _vertex_loop(data["loop_a"], "loop_a")
        loop_b = _vertex_loop(data["loop_b"], "loop_b")
        if len(loop_a) != len(loop_b):
            raise invalid("Boundary loops must have equal vertex counts")
        if set(loop_a) & set(loop_b):
            raise invalid("Boundary loops must be disjoint")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            loop_a,
            loop_b,
        )


@dataclass(frozen=True)
class FillBoundaryLoop:
    target: ObjectTarget
    expected_geometry_revision: str
    vertex_indices: tuple[int, ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "vertex_indices"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            _vertex_loop(data["vertex_indices"], "vertex_indices", MAX_FACE_VERTICES),
        )


class ModelingTopologyOperations(ModelingRegionOperations):
    @staticmethod
    def _canonical_edge(a, b):
        return (a, b) if a < b else (b, a)

    @staticmethod
    def _split_point(vertices, edge, factor):
        a, b = edge
        point_a = vertices[a]
        point_b = vertices[b]
        return list(
            vector3(
                [point_a[axis] + (point_b[axis] - point_a[axis]) * factor for axis in range(3)],
                "subdivide point",
                1_000_000,
            )
        )

    @staticmethod
    def _insert_on_face(face, edge, new_index):
        rebuilt = []
        inserted = False
        for offset, a in enumerate(face):
            b = face[(offset + 1) % len(face)]
            rebuilt.append(a)
            if {a, b} == set(edge):
                rebuilt.append(new_index)
                inserted = True
        if not inserted:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Edge is missing from polygon cycle")
        if len(rebuilt) > MAX_FACE_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subdivision exceeds face vertex limit")
        return rebuilt

    def subdivide_edge(self, request: Request, action: SubdivideEdge):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        users = self._edge_users(before["faces"])
        edges = sorted(users)
        if action.edge_index >= len(edges):
            raise invalid("Subdivide edge index does not exist")
        edge = edges[action.edge_index]
        if not 1 <= len(users[edge]) <= 2:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Subdivision requires a boundary or manifold edge",
            )

        vertices = [list(vertex) for vertex in before["vertices"]]
        new_index = len(vertices)
        vertices.append(self._split_point(before["vertices"], edge, action.factor))
        faces = [list(face) for face in before["faces"]]
        for face_index in users[edge]:
            faces[face_index] = self._insert_on_face(faces[face_index], edge, new_index)

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "subdivided_edge_index": action.edge_index,
                "subdivided_edge": list(edge),
                "factor": action.factor,
                "new_vertex_index": new_index,
                "affected_face_indices": sorted(users[edge]),
            },
        )

    def loop_cut_quad_strip(self, request: Request, action: LoopCutQuadStrip):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        users = self._edge_users(before["faces"])
        edges = sorted(users)
        if action.edge_index >= len(edges):
            raise invalid("Loop-cut edge index does not exist")
        seed = edges[action.edge_index]
        if len(users[seed]) > 2:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Loop cut rejects non-manifold seed edge")

        ring_edges = set()
        affected_faces = set()
        queue = [seed]
        while queue:
            edge = queue.pop()
            if edge in ring_edges:
                continue
            ring_edges.add(edge)
            if len(ring_edges) > MAX_LOOP_CUT_EDGES:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Loop-cut edge work limit exceeded")
            for face_index in users.get(edge, ()):
                face = before["faces"][face_index]
                if len(face) != 4:
                    raise AgentError(
                        ErrorCode.SAFETY_DENIED,
                        "Loop-cut foundation requires an all-quad strip",
                    )
                affected_faces.add(face_index)
                positions = []
                for offset, a in enumerate(face):
                    b = face[(offset + 1) % 4]
                    if self._canonical_edge(a, b) == edge:
                        positions.append(offset)
                if len(positions) != 1:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid quad edge membership")
                opposite_pos = (positions[0] + 2) % 4
                opposite = self._canonical_edge(
                    face[opposite_pos],
                    face[(opposite_pos + 1) % 4],
                )
                if len(users.get(opposite, ())) > 2:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Loop cut crosses non-manifold edge")
                if opposite not in ring_edges:
                    queue.append(opposite)

        if not affected_faces:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Loop cut found no quad strip")

        vertices = [list(vertex) for vertex in before["vertices"]]
        split_index = {}
        for edge in sorted(ring_edges):
            split_index[edge] = len(vertices)
            vertices.append(self._split_point(before["vertices"], edge, action.factor))

        faces = [list(face) for face in before["faces"]]
        for face_index in sorted(affected_faces):
            face = before["faces"][face_index]
            ring_positions = []
            for offset, a in enumerate(face):
                b = face[(offset + 1) % 4]
                edge = self._canonical_edge(a, b)
                if edge in ring_edges:
                    ring_positions.append(offset)
            if len(ring_positions) != 2 or (ring_positions[0] - ring_positions[1]) % 2 != 0:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Quad strip does not contain opposite loop-cut edges",
                )
            start = ring_positions[0]
            rotated = face[start:] + face[:start]
            edge_a = self._canonical_edge(rotated[0], rotated[1])
            edge_b = self._canonical_edge(rotated[2], rotated[3])
            cut_a = split_index[edge_a]
            cut_b = split_index[edge_b]
            faces[face_index] = [rotated[0], cut_a, cut_b, rotated[3]]
            faces.append([cut_a, rotated[1], rotated[2], cut_b])

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "seed_edge_index": action.edge_index,
                "factor": action.factor,
                "ring_edges": [list(edge) for edge in sorted(ring_edges)],
                "affected_face_indices": sorted(affected_faces),
                "new_vertex_indices": [split_index[edge] for edge in sorted(ring_edges)],
            },
        )

    @staticmethod
    def _validate_boundary_loop(loop, users, vertex_count):
        if any(index >= vertex_count for index in loop):
            raise invalid("Boundary loop vertex index does not exist")
        edges = []
        for offset, a in enumerate(loop):
            b = loop[(offset + 1) % len(loop)]
            edge = (a, b) if a < b else (b, a)
            if len(users.get(edge, ())) != 1:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Loop must follow existing boundary edges with one polygon user",
                )
            edges.append(edge)
        return edges

    def bridge_boundary_loops(self, request: Request, action: BridgeBoundaryLoops):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        users = self._edge_users(before["faces"])
        self._validate_boundary_loop(action.loop_a, users, len(before["vertices"]))
        self._validate_boundary_loop(action.loop_b, users, len(before["vertices"]))

        faces = [list(face) for face in before["faces"]]
        new_faces = []
        size = len(action.loop_a)
        for offset in range(size):
            a0 = action.loop_a[offset]
            a1 = action.loop_a[(offset + 1) % size]
            b0 = action.loop_b[offset]
            b1 = action.loop_b[(offset + 1) % size]
            new_faces.append([a0, a1, b1, b0])
        faces.extend(new_faces)
        vertices = [list(vertex) for vertex in before["vertices"]]

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "loop_a": list(action.loop_a),
                "loop_b": list(action.loop_b),
                "bridge_face_indices": list(
                    range(len(before["faces"]), len(before["faces"]) + len(new_faces))
                ),
            },
        )

    def fill_boundary_loop(self, request: Request, action: FillBoundaryLoop):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        users = self._edge_users(before["faces"])
        loop_edges = self._validate_boundary_loop(
            action.vertex_indices,
            users,
            len(before["vertices"]),
        )
        candidate = list(action.vertex_indices)
        candidate_set = set(candidate)
        for face in before["faces"]:
            if len(face) == len(candidate) and set(face) == candidate_set:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Boundary loop is already filled")

        vertices = [list(vertex) for vertex in before["vertices"]]
        faces = [list(face) for face in before["faces"]]
        fill_index = len(faces)
        faces.append(candidate)

        return self._commit_rebuild(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            {
                "filled_vertex_indices": candidate,
                "filled_boundary_edges": [list(edge) for edge in loop_edges],
                "fill_face_index": fill_index,
            },
        )

    def tools(self):
        return [
            Tool(
                "mesh.subdivide_edge",
                SafetyClass.MUTATION,
                SubdivideEdge.parse,
                self.subdivide_edge,
            ),
            Tool(
                "mesh.loop_cut_quad_strip",
                SafetyClass.MUTATION,
                LoopCutQuadStrip.parse,
                self.loop_cut_quad_strip,
            ),
            Tool(
                "mesh.bridge_boundary_loops",
                SafetyClass.MUTATION,
                BridgeBoundaryLoops.parse,
                self.bridge_boundary_loops,
            ),
            Tool(
                "mesh.fill_boundary_loop",
                SafetyClass.MUTATION,
                FillBoundaryLoop.parse,
                self.fill_boundary_loop,
            ),
        ]
