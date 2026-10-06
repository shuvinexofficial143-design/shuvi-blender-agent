"""Level 4 milestone 5: bounded UV packing and texel-density planning."""

from dataclasses import dataclass
from math import ceil, sqrt
from statistics import median

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .uv import MAX_UV_FACES, _face_area_3d, _uv_area
from .uv_workflows import UVWorkflowOperations, _islands
from .validation import fields, integer, invalid, number, string
from .verification import compare

MAX_TEXTURE_SIZE = 32768
MAX_TEXEL_DENSITY = 1_000_000.0
MAX_PACK_MARGIN = 0.1


def _layer_name(value):
    return string(value, "layer_name", limit=63)


@dataclass(frozen=True)
class UVPackPlan:
    object_id: str
    layer_name: str
    margin: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "layer_name", "margin"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _layer_name(data["layer_name"]),
            number(data["margin"], "margin", 0.0, MAX_PACK_MARGIN),
        )


@dataclass(frozen=True)
class UVPackApply:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_uv_revision: str
    layer_name: str
    margin: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_uv_revision",
                "layer_name",
                "margin",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_uv_revision"], "expected_uv_revision", limit=64),
            _layer_name(data["layer_name"]),
            number(data["margin"], "margin", 0.0, MAX_PACK_MARGIN),
        )


@dataclass(frozen=True)
class TexelDensityInspect:
    object_id: str
    layer_name: str
    texture_size: int

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "layer_name", "texture_size"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _layer_name(data["layer_name"]),
            integer(data["texture_size"], "texture_size", 16, MAX_TEXTURE_SIZE),
        )


@dataclass(frozen=True)
class TexelDensityPlan(TexelDensityInspect):
    target_density: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "layer_name", "texture_size", "target_density"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _layer_name(data["layer_name"]),
            integer(data["texture_size"], "texture_size", 16, MAX_TEXTURE_SIZE),
            number(data["target_density"], "target_density", 0.001, MAX_TEXEL_DENSITY),
        )


class UVPackingOperations(UVWorkflowOperations):
    def __init__(self, objects: ObjectOperations):
        super().__init__(objects)

    def _packing_data(self, obj, layer_name, margin):
        geometry = self.meshes.snapshot(obj)
        mesh, _, _, _ = self._mesh(obj)
        layer, face_uvs = self._layer_face_uvs_named(mesh, layer_name)
        groups = _islands(geometry["faces"], face_uvs)
        if not groups:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UV packing requires at least one island")

        columns = ceil(sqrt(len(groups)))
        rows = ceil(len(groups) / columns)
        cell_width = 1.0 / columns
        cell_height = 1.0 / rows
        inner_width = cell_width - 2.0 * margin
        inner_height = cell_height - 2.0 * margin
        if inner_width <= 0.0 or inner_height <= 0.0:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Pack margin leaves no usable UV cell area",
            )

        prior = self._capture_layer(layer)
        packed = [list(uv) for uv in prior]
        transforms = []
        for island_index, face_indices in enumerate(groups):
            loop_indices = []
            for face_index in face_indices:
                polygon = mesh.polygons[face_index]
                start = int(polygon.loop_start)
                count = int(polygon.loop_total)
                loop_indices.extend(range(start, start + count))
            points = [prior[index] for index in loop_indices]
            minimum = [min(point[axis] for point in points) for axis in range(2)]
            maximum = [max(point[axis] for point in points) for axis in range(2)]
            size = [maximum[axis] - minimum[axis] for axis in range(2)]
            if size[0] <= 1e-12 or size[1] <= 1e-12:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "UV packing does not accept degenerate island bounds",
                )
            scale = min(inner_width / size[0], inner_height / size[1])
            source_center = [(minimum[axis] + maximum[axis]) * 0.5 for axis in range(2)]
            row, column = divmod(island_index, columns)
            target_center = [
                column * cell_width + cell_width * 0.5,
                row * cell_height + cell_height * 0.5,
            ]
            for loop_index in loop_indices:
                original = prior[loop_index]
                packed[loop_index] = [
                    target_center[axis] + (original[axis] - source_center[axis]) * scale
                    for axis in range(2)
                ]
            transforms.append(
                {
                    "island_index": island_index,
                    "face_indices": list(face_indices),
                    "scale": scale,
                    "source_center": source_center,
                    "target_center": target_center,
                }
            )

        face_uvs_packed = self._flat_to_faces(mesh, packed)
        coordinate_revision = revision({"name": layer_name, "face_uvs": face_uvs_packed})
        return {
            "geometry": geometry,
            "mesh": mesh,
            "layer": layer,
            "groups": groups,
            "prior": prior,
            "packed": packed,
            "transforms": transforms,
            "columns": columns,
            "rows": rows,
            "coordinate_revision": coordinate_revision,
        }

    def pack_plan(self, request: Request, action: UVPackPlan):
        obj = self.inspector.resolve(action.object_id)
        snapshot = self.snapshot(obj)
        data = self._packing_data(obj, action.layer_name, action.margin)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": snapshot["object_id"],
                "geometry_revision": snapshot["geometry_revision"],
                "uv_revision": snapshot["uv_revision"],
                "layer_name": action.layer_name,
                "margin": action.margin,
                "island_count": len(data["groups"]),
                "grid": {"columns": data["columns"], "rows": data["rows"]},
                "transforms": data["transforms"],
                "target_coordinate_revision": data["coordinate_revision"],
                "execution_status": "SOURCE_GRID_PACK_PREVIEW_ONLY",
                "runtime_pack_equivalent": False,
            },
        )

    def pack_apply(self, request: Request, action: UVPackApply):
        obj, object_before, before, mesh, _ = self._editable_uv_mesh(action)
        data = self._packing_data(obj, action.layer_name, action.margin)
        layer = data["layer"]
        self._write_layer(layer, data["packed"])
        mesh.update()
        self.bpy.context.view_layer.update()
        after = self.snapshot(obj)

        expected = {
            "geometry_revision": before["geometry_revision"],
            "seam_flags": before["seam_flags"],
            "active_uv_layer": before["active_uv_layer"],
            "uv_layer_count": before["uv_layer_count"],
            "layer_names": [item["name"] for item in before["layers"]],
            "layer_revisions": self._expected_layer_revisions(
                before,
                action.layer_name,
                data["coordinate_revision"],
                False,
            ),
            "target_coordinate_revision": data["coordinate_revision"],
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
                    "margin": action.margin,
                    "island_count": len(data["groups"]),
                    "grid": {"columns": data["columns"], "rows": data["rows"]},
                },
                verification=verification.to_dict(),
            )

        self._write_layer(layer, data["prior"])
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
                "UV pack verification failed and recovery could not be verified",
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
                "UV pack readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def _density_data(self, obj, layer_name, texture_size):
        geometry = self.meshes.snapshot(obj)
        mesh, _, _, _ = self._mesh(obj)
        _, face_uvs = self._layer_face_uvs_named(mesh, layer_name)
        if len(face_uvs) > MAX_UV_FACES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Texel-density face limit exceeded")

        values = []
        valid = []
        for face_index, face in enumerate(geometry["faces"]):
            surface_area = _face_area_3d(geometry["vertices"], face)
            uv_area = _uv_area(face_uvs[face_index])
            density = None
            if surface_area > 1e-12 and uv_area > 1e-12:
                density = texture_size * sqrt(uv_area / surface_area)
                valid.append(density)
            values.append(
                {
                    "face_index": face_index,
                    "surface_area": surface_area,
                    "uv_area": uv_area,
                    "pixels_per_unit": density,
                }
            )
        return {
            "geometry": geometry,
            "face_values": values,
            "valid": valid,
            "median_density": median(valid) if valid else None,
            "minimum_density": min(valid) if valid else None,
            "maximum_density": max(valid) if valid else None,
        }

    def texel_density_inspect(self, request: Request, action: TexelDensityInspect):
        obj = self.inspector.resolve(action.object_id)
        snapshot = self.snapshot(obj)
        data = self._density_data(obj, action.layer_name, action.texture_size)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": snapshot["object_id"],
                "geometry_revision": snapshot["geometry_revision"],
                "uv_revision": snapshot["uv_revision"],
                "layer_name": action.layer_name,
                "texture_size": action.texture_size,
                "face_values": data["face_values"],
                "valid_face_count": len(data["valid"]),
                "median_pixels_per_unit": data["median_density"],
                "minimum_pixels_per_unit": data["minimum_density"],
                "maximum_pixels_per_unit": data["maximum_density"],
            },
        )

    def texel_density_plan(self, request: Request, action: TexelDensityPlan):
        obj = self.inspector.resolve(action.object_id)
        snapshot = self.snapshot(obj)
        data = self._density_data(obj, action.layer_name, action.texture_size)
        current = data["median_density"]
        if current is None or current <= 1e-12:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Texel-density target requires nondegenerate UV and surface area",
            )
        scale = action.target_density / current
        if scale <= 0.0 or scale > 10_000.0:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Texel-density scale is outside source bounds")
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": snapshot["object_id"],
                "geometry_revision": snapshot["geometry_revision"],
                "uv_revision": snapshot["uv_revision"],
                "layer_name": action.layer_name,
                "texture_size": action.texture_size,
                "current_median_pixels_per_unit": current,
                "target_pixels_per_unit": action.target_density,
                "uniform_uv_scale": scale,
                "predicted_median_pixels_per_unit": current * scale,
                "execution_status": "TARGET_SCALE_PLAN_ONLY",
                "runtime_density_equivalent": False,
            },
        )

    def tools(self):
        return [
            Tool("uv.pack_plan", SafetyClass.READ_ONLY, UVPackPlan.parse, self.pack_plan),
            Tool("uv.pack_apply", SafetyClass.MUTATION, UVPackApply.parse, self.pack_apply),
            Tool(
                "uv.texel_density_inspect",
                SafetyClass.READ_ONLY,
                TexelDensityInspect.parse,
                self.texel_density_inspect,
            ),
            Tool(
                "uv.texel_density_plan",
                SafetyClass.READ_ONLY,
                TexelDensityPlan.parse,
                self.texel_density_plan,
            ),
        ]
