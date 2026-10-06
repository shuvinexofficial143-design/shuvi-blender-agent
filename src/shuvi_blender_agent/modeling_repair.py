"""Level 2 milestone 7: bounded topology repair diagnostics and cleanup helpers."""

from dataclasses import dataclass
from itertools import product
from math import floor

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .modeling import MAX_EDGES
from .modeling_region import ModelingRegionOperations
from .modeling_shading import _edge_orientation_diagnostics, _face_geometry
from .models import ObjectTarget
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number, string

MAX_REPAIR_PAIR_CHECKS = 1_000_000
MAX_DIAGNOSTIC_GROUPS = 512


def _canonical_face(face):
    values = tuple(face)
    rotations = [values[index:] + values[:index] for index in range(len(values))]
    reversed_values = tuple(reversed(values))
    rotations += [
        reversed_values[index:] + reversed_values[:index] for index in range(len(reversed_values))
    ]
    return min(rotations)


def _cluster_vertices(vertices, distance):
    buckets = {}
    parent = list(range(len(vertices)))
    pair_checks = 0
    distance_squared = distance * distance

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        root_a = find(a)
        root_b = find(b)
        if root_a == root_b:
            return
        if root_a < root_b:
            parent[root_b] = root_a
        else:
            parent[root_a] = root_b

    for index, vertex in enumerate(vertices):
        cell = tuple(floor(component / distance) for component in vertex)
        for delta in product((-1, 0, 1), repeat=3):
            neighbor = tuple(cell[axis] + delta[axis] for axis in range(3))
            for other in buckets.get(neighbor, ()):
                pair_checks += 1
                if pair_checks > MAX_REPAIR_PAIR_CHECKS:
                    raise AgentError(
                        ErrorCode.SAFETY_DENIED,
                        "Repair proximity work limit exceeded",
                    )
                squared = sum((vertex[axis] - vertices[other][axis]) ** 2 for axis in range(3))
                if squared <= distance_squared:
                    union(index, other)
        buckets.setdefault(cell, []).append(index)

    groups = {}
    for index in range(len(vertices)):
        groups.setdefault(find(index), []).append(index)
    merged = [group for _, group in sorted(groups.items()) if len(group) > 1]
    if len(merged) > MAX_DIAGNOSTIC_GROUPS:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Repair diagnostic group limit exceeded")
    return merged, pair_checks


def _duplicate_face_groups(faces):
    groups = {}
    for index, face in enumerate(faces):
        groups.setdefault(_canonical_face(face), []).append(index)
    duplicates = [group for _, group in sorted(groups.items()) if len(group) > 1]
    if len(duplicates) > MAX_DIAGNOSTIC_GROUPS:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Duplicate-face group limit exceeded")
    return duplicates


def _face_components(faces):
    edge_users = {}
    for face_index, face in enumerate(faces):
        for offset, a in enumerate(face):
            b = face[(offset + 1) % len(face)]
            edge = (a, b) if a < b else (b, a)
            edge_users.setdefault(edge, []).append(face_index)
            if len(edge_users) > MAX_EDGES:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Topology edge work limit exceeded")

    adjacency = [set() for _ in faces]
    for users in edge_users.values():
        for left in users:
            for right in users:
                if left != right:
                    adjacency[left].add(right)

    components = []
    visited = set()
    for root in range(len(faces)):
        if root in visited:
            continue
        stack = [root]
        component = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        components.append(sorted(component))
    return components


@dataclass(frozen=True)
class RepairInspect:
    object_id: str
    distance: float
    area_epsilon: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "distance", "area_epsilon"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            number(data["distance"], "distance", 1e-9, 100),
            number(data["area_epsilon"], "area_epsilon", 0, 1_000_000),
        )


@dataclass(frozen=True)
class MergeByDistance:
    target: ObjectTarget
    expected_geometry_revision: str
    distance: float

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision", "distance"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            number(data["distance"], "distance", 1e-9, 100),
        )


@dataclass(frozen=True)
class CleanupFaces:
    target: ObjectTarget
    expected_geometry_revision: str
    area_epsilon: float
    remove_duplicate_faces: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "area_epsilon",
                "remove_duplicate_faces",
            },
        )
        if type(data["remove_duplicate_faces"]) is not bool:
            raise invalid("remove_duplicate_faces must be boolean")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            number(data["area_epsilon"], "area_epsilon", 0, 1_000_000),
            data["remove_duplicate_faces"],
        )


@dataclass(frozen=True)
class RemoveLooseVertices:
    target: ObjectTarget
    expected_geometry_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
        )


class ModelingRepairOperations(ModelingRegionOperations):
    def _repair_snapshot(self, obj, distance, area_epsilon):
        geometry = self.meshes.snapshot(obj)
        vertices = geometry["vertices"]
        faces = geometry["faces"]
        clusters, pair_checks = _cluster_vertices(vertices, distance)
        duplicate_faces = _duplicate_face_groups(faces)
        face_data = [_face_geometry(vertices, face) for face in faces]
        degenerate = [index for index, data in enumerate(face_data) if data["area"] <= area_epsilon]
        referenced = {index for face in faces for index in face}
        loose = [index for index in range(len(vertices)) if index not in referenced]
        users, boundary, nonmanifold, winding = _edge_orientation_diagnostics(faces)
        zero_length_edges = []
        threshold_squared = distance * distance
        for edge in sorted(users):
            a, b = edge
            squared = sum((vertices[a][axis] - vertices[b][axis]) ** 2 for axis in range(3))
            if squared <= threshold_squared:
                zero_length_edges.append(list(edge))
        components = _face_components(faces)

        data = geometry | {
            "distance": distance,
            "area_epsilon": area_epsilon,
            "near_duplicate_vertex_groups": clusters,
            "near_duplicate_vertex_group_count": len(clusters),
            "proximity_pair_checks": pair_checks,
            "duplicate_face_groups": duplicate_faces,
            "duplicate_face_group_count": len(duplicate_faces),
            "degenerate_face_indices": degenerate,
            "degenerate_face_count": len(degenerate),
            "loose_vertex_indices": loose,
            "loose_vertex_count": len(loose),
            "zero_length_edges": zero_length_edges,
            "zero_length_edge_count": len(zero_length_edges),
            "boundary_edges": boundary,
            "boundary_edge_count": len(boundary),
            "nonmanifold_edges": nonmanifold,
            "nonmanifold_edge_count": len(nonmanifold),
            "winding_conflict_edges": winding,
            "winding_conflict_edge_count": len(winding),
            "face_components": components,
            "face_component_count": len(components),
        }
        data["repair_revision"] = revision(
            {
                "geometry_revision": geometry["geometry_revision"],
                "distance": distance,
                "area_epsilon": area_epsilon,
                "near_duplicate_vertex_groups": clusters,
                "duplicate_face_groups": duplicate_faces,
                "degenerate_face_indices": degenerate,
                "loose_vertex_indices": loose,
            }
        )
        return data

    def inspect_repair(self, request: Request, action: RepairInspect):
        obj = self.inspector.resolve(action.object_id)
        if obj.type != "MESH":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._repair_snapshot(obj, action.distance, action.area_epsilon),
        )

    @staticmethod
    def _smooth_flags(obj):
        return [bool(getattr(face, "use_smooth", False)) for face in obj.data.polygons]

    @staticmethod
    def _restore_smooth_flags(obj, values):
        if len(values) != len(obj.data.polygons):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Face smoothing length changed")
        for face, value in zip(obj.data.polygons, values, strict=True):
            face.use_smooth = value
        obj.data.update()

    def _commit_repair(
        self,
        request,
        obj,
        object_before,
        before,
        vertices,
        faces,
        face_sources,
        evidence,
    ):
        self._preflight(vertices, faces)
        if not faces:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Repair cannot remove every polygon")
        source_smooth = self._smooth_flags(obj)
        expected_smooth = [source_smooth[index] for index in face_sources]
        expected = {"vertices": vertices, "faces": faces, "face_smooth": expected_smooth} | evidence

        try:
            self._replace_geometry(obj.data, vertices, faces)
            self._restore_smooth_flags(obj, expected_smooth)
            self.bpy.context.view_layer.update()
            after = self.meshes.snapshot(obj)
            after["object_revision"] = self.inspector.snapshot(obj)["revision"]
            after["face_smooth"] = self._smooth_flags(obj)
            after.update(evidence)
            result = self.objects._result(
                request,
                {"object": object_before, "geometry": before, "face_smooth": source_smooth},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                self._replace_geometry(obj.data, before["vertices"], before["faces"])
                self._restore_smooth_flags(obj, source_smooth)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._replace_geometry(obj.data, before["vertices"], before["faces"])
            self._restore_smooth_flags(obj, source_smooth)
            self.bpy.context.view_layer.update()
            raise

    def merge_by_distance(self, request: Request, action: MergeByDistance):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        clusters, pair_checks = _cluster_vertices(before["vertices"], action.distance)
        if not clusters:
            raise invalid("No vertices are within merge distance")

        representative = {index: index for index in range(len(before["vertices"]))}
        merged_indices = set()
        for group in clusters:
            keep = min(group)
            for index in group:
                representative[index] = keep
                if index != keep:
                    merged_indices.add(index)

        old_to_new = {}
        vertices = []
        for old_index, vertex in enumerate(before["vertices"]):
            if old_index in merged_indices:
                continue
            old_to_new[old_index] = len(vertices)
            vertices.append(list(vertex))

        faces = []
        face_sources = []
        removed_faces = []
        seen_faces = {}
        duplicate_removed = []
        for face_index, face in enumerate(before["faces"]):
            mapped = [representative[index] for index in face]
            collapsed = []
            for index in mapped:
                if not collapsed or collapsed[-1] != index:
                    collapsed.append(index)
            if len(collapsed) > 1 and collapsed[0] == collapsed[-1]:
                collapsed.pop()
            if len(set(collapsed)) < 3 or len(set(collapsed)) != len(collapsed):
                removed_faces.append(face_index)
                continue
            compacted = [old_to_new[index] for index in collapsed]
            key = _canonical_face(compacted)
            if key in seen_faces:
                duplicate_removed.append(face_index)
                continue
            seen_faces[key] = face_index
            faces.append(compacted)
            face_sources.append(face_index)

        return self._commit_repair(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            face_sources,
            {
                "distance": action.distance,
                "merged_vertex_groups": clusters,
                "merged_vertex_count": len(merged_indices),
                "removed_degenerate_face_indices": removed_faces,
                "removed_duplicate_face_indices": duplicate_removed,
                "proximity_pair_checks": pair_checks,
            },
        )

    def cleanup_faces(self, request: Request, action: CleanupFaces):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        duplicate_groups = _duplicate_face_groups(before["faces"])
        duplicate_indices = (
            {index for group in duplicate_groups for index in group[1:]}
            if action.remove_duplicate_faces
            else set()
        )

        faces = []
        face_sources = []
        removed_degenerate = []
        removed_duplicate = []
        for face_index, face in enumerate(before["faces"]):
            if face_index in duplicate_indices:
                removed_duplicate.append(face_index)
                continue
            data = _face_geometry(before["vertices"], face)
            if data["area"] <= action.area_epsilon:
                removed_degenerate.append(face_index)
                continue
            faces.append(list(face))
            face_sources.append(face_index)

        if not removed_degenerate and not removed_duplicate:
            raise invalid("No matching degenerate or duplicate faces found")

        return self._commit_repair(
            request,
            obj,
            object_before,
            before,
            [list(vertex) for vertex in before["vertices"]],
            faces,
            face_sources,
            {
                "area_epsilon": action.area_epsilon,
                "remove_duplicate_faces": action.remove_duplicate_faces,
                "removed_degenerate_face_indices": removed_degenerate,
                "removed_duplicate_face_indices": removed_duplicate,
            },
        )

    def remove_loose_vertices(self, request: Request, action: RemoveLooseVertices):
        obj, object_before, before = self._editable_rebuild_mesh(action)
        referenced = {index for face in before["faces"] for index in face}
        loose = [index for index in range(len(before["vertices"])) if index not in referenced]
        if not loose:
            raise invalid("No loose vertices found")

        old_to_new = {}
        vertices = []
        for old_index, vertex in enumerate(before["vertices"]):
            if old_index not in referenced:
                continue
            old_to_new[old_index] = len(vertices)
            vertices.append(list(vertex))
        faces = [[old_to_new[index] for index in face] for face in before["faces"]]
        face_sources = list(range(len(before["faces"])))

        return self._commit_repair(
            request,
            obj,
            object_before,
            before,
            vertices,
            faces,
            face_sources,
            {
                "removed_loose_vertex_indices": loose,
                "removed_loose_vertex_count": len(loose),
            },
        )

    def tools(self):
        return [
            Tool(
                "mesh.repair_inspect",
                SafetyClass.READ_ONLY,
                RepairInspect.parse,
                self.inspect_repair,
            ),
            Tool(
                "mesh.merge_by_distance",
                SafetyClass.MUTATION,
                MergeByDistance.parse,
                self.merge_by_distance,
            ),
            Tool(
                "mesh.cleanup_faces",
                SafetyClass.MUTATION,
                CleanupFaces.parse,
                self.cleanup_faces,
            ),
            Tool(
                "mesh.remove_loose_vertices",
                SafetyClass.MUTATION,
                RemoveLooseVertices.parse,
                self.remove_loose_vertices,
            ),
        ]
