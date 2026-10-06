"""Level 4 milestones 3-4: bounded planar unwrap and UV-island editing."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .uv import MAX_UV_FACES, MAX_UV_LAYERS, UVOperations, _same_uv
from .validation import fields, integer, invalid, number, string
from .verification import compare

PROJECTIONS = frozenset({"XY", "XZ", "YZ"})
MAX_ISLAND_FACES = MAX_UV_FACES
MAX_UV_ABS_COORD = 16.0


def _projection(value):
    value = string(value, "projection", limit=8)
    if value not in PROJECTIONS:
        raise invalid("projection must be XY, XZ or YZ")
    return value


def _vec2(value, name, bound):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise invalid(f"{name} must have exactly two components")
    return tuple(number(item, name, -bound, bound) for item in value)


def _project(vertex, projection):
    if projection == "XY":
        return [float(vertex[0]), float(vertex[1])]
    if projection == "XZ":
        return [float(vertex[0]), float(vertex[2])]
    return [float(vertex[1]), float(vertex[2])]


def _normalized_projection(vertices, faces, projection):
    points = [_project(vertex, projection) for vertex in vertices]
    used = {index for face in faces for index in face}
    if not used:
        raise AgentError(ErrorCode.SAFETY_DENIED, "UV projection requires referenced vertices")
    minimum = [min(points[index][axis] for index in used) for axis in range(2)]
    maximum = [max(points[index][axis] for index in used) for axis in range(2)]
    extent = [maximum[axis] - minimum[axis] for axis in range(2)]
    if extent[0] <= 1e-12 or extent[1] <= 1e-12:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            "Selected planar projection has zero usable extent",
        )

    normalized = [
        [
            (point[0] - minimum[0]) / extent[0],
            (point[1] - minimum[1]) / extent[1],
        ]
        for point in points
    ]
    face_uvs = [[normalized[index] for index in face] for face in faces]
    return {
        "projection": projection,
        "source_min": minimum,
        "source_max": maximum,
        "source_extent": extent,
        "face_uvs": face_uvs,
        "coordinate_revision": revision({"projection": projection, "face_uvs": face_uvs}),
    }


def _islands(faces, face_uvs):
    if not faces:
        return []
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
        if _same_uv(face_maps[first][a], face_maps[second][a]) and _same_uv(
            face_maps[first][b], face_maps[second][b]
        ):
            adjacency[first].add(second)
            adjacency[second].add(first)

    groups = []
    seen = set()
    for start in range(len(faces)):
        if start in seen:
            continue
        group = []
        stack = [start]
        seen.add(start)
        while stack:
            current = stack.pop()
            group.append(current)
            for neighbor in sorted(adjacency[current], reverse=True):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        groups.append(sorted(group))
    return groups


@dataclass(frozen=True)
class UVUnwrapPlan:
    object_id: str
    projection: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "projection"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _projection(data["projection"]),
        )


@dataclass(frozen=True)
class UVUnwrapApply:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_uv_revision: str
    layer_name: str
    projection: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_uv_revision",
                "layer_name",
                "projection",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_uv_revision"], "expected_uv_revision", limit=64),
            string(data["layer_name"], "layer_name", limit=63),
            _projection(data["projection"]),
        )


@dataclass(frozen=True)
class UVIslandTransform:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_uv_revision: str
    layer_name: str
    face_indices: tuple[int, ...]
    translation: tuple[float, float]
    scale: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_uv_revision",
                "layer_name",
                "face_indices",
                "translation",
                "scale",
            },
        )
        values = data["face_indices"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_ISLAND_FACES:
            raise invalid(f"face_indices requires 1..{MAX_ISLAND_FACES} indices")
        indices = tuple(integer(value, "face_index", 0, MAX_UV_FACES - 1) for value in values)
        if len(set(indices)) != len(indices):
            raise invalid("face_indices must be unique")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_uv_revision"], "expected_uv_revision", limit=64),
            string(data["layer_name"], "layer_name", limit=63),
            indices,
            _vec2(data["translation"], "translation", MAX_UV_ABS_COORD),
            number(data["scale"], "scale", 0.01, 100.0),
        )


class UVWorkflowOperations(UVOperations):
    def __init__(self, objects: ObjectOperations):
        super().__init__(objects)

    @staticmethod
    def _layer_by_name(mesh, layer_name):
        layers = getattr(mesh, "uv_layers", None)
        if layers is None:
            return None
        getter = getattr(layers, "get", None)
        if callable(getter):
            return getter(layer_name)
        return next((layer for layer in layers if str(layer.name) == layer_name), None)

    @staticmethod
    def _capture_layer(layer):
        return [[float(value) for value in item.uv] for item in layer.data]

    @staticmethod
    def _write_layer(layer, flat_uvs):
        if len(layer.data) != len(flat_uvs):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "UV loop count changed during mutation")
        for item, uv in zip(layer.data, flat_uvs, strict=True):
            item.uv = [float(uv[0]), float(uv[1])]

    @staticmethod
    def _flatten(face_uvs):
        return [list(uv) for face in face_uvs for uv in face]

    def _editable_uv_mesh(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        mesh, _, _, layers = self._mesh(obj)
        if mesh.users != 1 or mesh.library is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unshared local mesh data required")
        before = self.snapshot(obj)
        require_revision(action.expected_geometry_revision, before["geometry_revision"])
        require_revision(action.expected_uv_revision, before["uv_revision"])
        return obj, object_before, before, mesh, layers

    def unwrap_plan(self, request: Request, action: UVUnwrapPlan):
        obj = self.inspector.resolve(action.object_id)
        geometry = self.meshes.snapshot(obj)
        self._mesh(obj)
        plan = _normalized_projection(
            geometry["vertices"],
            geometry["faces"],
            action.projection,
        )
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": geometry["object_id"],
                "geometry_revision": geometry["geometry_revision"],
                "projection": action.projection,
                "source_min": plan["source_min"],
                "source_max": plan["source_max"],
                "source_extent": plan["source_extent"],
                "face_count": len(geometry["faces"]),
                "loop_count": sum(len(face) for face in geometry["faces"]),
                "target_coordinate_revision": plan["coordinate_revision"],
                "execution_status": "SOURCE_PLANAR_PROJECTION_PREVIEW_ONLY",
                "runtime_unwrap_equivalent": False,
            },
        )

    @staticmethod
    def _layer_revision(snapshot, layer_name):
        for layer in snapshot["layers"]:
            if layer["name"] == layer_name:
                return layer["coordinate_revision"]
        return None

    def _unwrap_verification(self, snapshot, layer_name):
        return {
            "geometry_revision": snapshot["geometry_revision"],
            "seam_flags": snapshot["seam_flags"],
            "active_uv_layer": snapshot["active_uv_layer"],
            "uv_layer_count": snapshot["uv_layer_count"],
            "layer_names": [layer["name"] for layer in snapshot["layers"]],
            "target_coordinate_revision": self._layer_revision(snapshot, layer_name),
        }

    def unwrap_apply(self, request: Request, action: UVUnwrapApply):
        obj, object_before, before, mesh, layers = self._editable_uv_mesh(action)
        geometry = self.meshes.snapshot(obj)
        plan = _normalized_projection(
            geometry["vertices"],
            geometry["faces"],
            action.projection,
        )
        existing = self._layer_by_name(mesh, action.layer_name)
        created = existing is None
        if created and len(layers) >= MAX_UV_LAYERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV layer limit reached")

        active_before = getattr(getattr(mesh, "uv_layers", None), "active_index", 0)
        layer = existing
        prior_uvs = self._capture_layer(existing) if existing is not None else None
        try:
            if layer is None:
                layer = mesh.uv_layers.new(name=action.layer_name)
            flat_uvs = self._flatten(plan["face_uvs"])
            self._write_layer(layer, flat_uvs)
            layer_index = next(
                index for index, candidate in enumerate(mesh.uv_layers) if candidate is layer
            )
            mesh.uv_layers.active_index = layer_index
            mesh.update()
            self.bpy.context.view_layer.update()

            after = self.snapshot(obj)
            expected = {
                "geometry_revision": before["geometry_revision"],
                "seam_flags": before["seam_flags"],
                "active_uv_layer": action.layer_name,
                "uv_layer_count": before["uv_layer_count"] + (1 if created else 0),
                "layer_names": (
                    [layer["name"] for layer in before["layers"]] + [action.layer_name]
                    if created
                    else [layer["name"] for layer in before["layers"]]
                ),
                "target_coordinate_revision": plan["coordinate_revision"],
            }
            actual = self._unwrap_verification(after, action.layer_name)
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "projection": action.projection,
                        "layer_name": action.layer_name,
                        "created_layer": created,
                    },
                    verification=verification.to_dict(),
                )

            self._restore_unwrap(mesh, layer, created, prior_uvs, active_before)
            self.bpy.context.view_layer.update()
            restored = self.snapshot(obj)
            recovery = compare(
                self._unwrap_verification(before, action.layer_name),
                self._unwrap_verification(restored, action.layer_name),
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "UV unwrap verification failed and recovery could not be verified",
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
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "UV unwrap readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if created and layer is not None and self._layer_by_name(mesh, action.layer_name) is layer:
                self._restore_unwrap(mesh, layer, True, None, active_before)
            raise

    @staticmethod
    def _restore_unwrap(mesh, layer, created, prior_uvs, active_index):
        if created:
            mesh.uv_layers.remove(layer)
        else:
            for item, uv in zip(layer.data, prior_uvs, strict=True):
                item.uv = list(uv)
        if len(mesh.uv_layers):
            mesh.uv_layers.active_index = min(active_index, len(mesh.uv_layers) - 1)
        else:
            mesh.uv_layers.active_index = 0
        mesh.update()

    def _layer_face_uvs_named(self, mesh, layer_name):
        layer = self._layer_by_name(mesh, layer_name)
        if layer is None:
            raise AgentError(ErrorCode.NOT_FOUND, "UV layer not found")
        loop_count = sum(len(face.vertices) for face in mesh.polygons)
        return layer, self._layer_face_uvs(mesh, layer, loop_count)

    @staticmethod
    def _island_bounds(face_uvs, face_indices):
        points = [uv for index in face_indices for uv in face_uvs[index]]
        return {
            "min": [min(point[axis] for point in points) for axis in range(2)],
            "max": [max(point[axis] for point in points) for axis in range(2)],
        }

    def island_transform(self, request: Request, action: UVIslandTransform):
        obj, object_before, before, mesh, _ = self._editable_uv_mesh(action)
        layer, face_uvs = self._layer_face_uvs_named(mesh, action.layer_name)
        if any(index >= len(face_uvs) for index in action.face_indices):
            raise invalid("UV island face index does not exist")
        groups = _islands(self.meshes.snapshot(obj)["faces"], face_uvs)
        requested = sorted(action.face_indices)
        if requested not in groups:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "face_indices must exactly match one current UV island",
            )

        prior_uvs = self._capture_layer(layer)
        bounds = self._island_bounds(face_uvs, requested)
        pivot = [
            (bounds["min"][axis] + bounds["max"][axis]) * 0.5
            for axis in range(2)
        ]
        transformed = [list(uv) for uv in prior_uvs]
        selected_loops = []
        for face_index in requested:
            polygon = mesh.polygons[face_index]
            start = int(polygon.loop_start)
            count = int(polygon.loop_total)
            selected_loops.extend(range(start, start + count))
        for loop_index in selected_loops:
            original = prior_uvs[loop_index]
            value = [
                pivot[axis]
                + (original[axis] - pivot[axis]) * action.scale
                + action.translation[axis]
                for axis in range(2)
            ]
            if any(abs(component) > MAX_UV_ABS_COORD for component in value):
                raise AgentError(ErrorCode.SAFETY_DENIED, "UV transform exceeds coordinate bounds")
            transformed[loop_index] = value

        self._write_layer(layer, transformed)
        mesh.update()
        self.bpy.context.view_layer.update()
        after = self.snapshot(obj)

        unchanged_names = [item["name"] for item in before["layers"]]
        expected = {
            "geometry_revision": before["geometry_revision"],
            "seam_flags": before["seam_flags"],
            "uv_layer_count": before["uv_layer_count"],
            "layer_names": unchanged_names,
            "target_coordinate_revision": revision(
                {
                    "name": action.layer_name,
                    "face_uvs": self._layer_face_uvs(
                        mesh,
                        layer,
                        sum(len(face.vertices) for face in mesh.polygons),
                    ),
                }
            ),
        }
        actual = self._unwrap_verification(after, action.layer_name)
        verification = compare(expected, actual)
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "before": before,
                    "after": after,
                    "layer_name": action.layer_name,
                    "face_indices": requested,
                    "pivot": pivot,
                    "translation": list(action.translation),
                    "scale": action.scale,
                },
                verification=verification.to_dict(),
            )

        self._write_layer(layer, prior_uvs)
        mesh.update()
        self.bpy.context.view_layer.update()
        restored = self.snapshot(obj)
        recovery = compare(
            self._unwrap_verification(before, action.layer_name),
            self._unwrap_verification(restored, action.layer_name),
        )
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "UV island verification failed and recovery could not be verified",
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
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "UV island readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "uv.unwrap_plan",
                SafetyClass.READ_ONLY,
                UVUnwrapPlan.parse,
                self.unwrap_plan,
            ),
            Tool(
                "uv.unwrap_apply",
                SafetyClass.MUTATION,
                UVUnwrapApply.parse,
                self.unwrap_apply,
            ),
            Tool(
                "uv.island_transform",
                SafetyClass.MUTATION,
                UVIslandTransform.parse,
                self.island_transform,
            ),
        ]
