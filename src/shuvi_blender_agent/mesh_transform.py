"""Bounded mesh transform baking and origin-to-centroid controls without bpy operators."""

from dataclasses import dataclass
from math import cos, sin

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, string


@dataclass(frozen=True)
class MeshTransformAction:
    target: ObjectTarget
    expected_geometry_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_geometry_revision"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
        )


def rotate_xyz(vector, euler):
    """Blender XYZ Euler: Rz @ Ry @ Rx applied to a column vector."""
    x, y, z = vector
    rx, ry, rz = euler
    sx, cx = sin(rx), cos(rx)
    sy, cy = sin(ry), cos(ry)
    sz, cz = sin(rz), cos(rz)
    return (
        (cz * cy) * x + (cz * sy * sx - sz * cx) * y + (cz * sy * cx + sz * sx) * z,
        (sz * cy) * x + (sz * sy * sx + cz * cx) * y + (sz * sy * cx - cz * sx) * z,
        (-sy) * x + (cy * sx) * y + (cy * cx) * z,
    )


class MeshTransformOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.meshes = MeshOperations(objects)

    def _target(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if obj.parent is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unparented mesh required")
        if obj.rotation_mode != "XYZ":
            raise AgentError(ErrorCode.SAFETY_DENIED, "XYZ Euler rotation mode required")
        if (
            obj.data.users != 1
            or obj.data.library is not None
            or obj.data.shape_keys is not None
            or len(obj.modifiers)
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Unshared local mesh without shapes/modifiers required"
            )
        geometry_before = self.meshes.snapshot(obj)
        require_revision(action.expected_geometry_revision, geometry_before["geometry_revision"])
        if not geometry_before["vertices"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh requires at least one vertex")
        return obj, object_before, geometry_before

    @staticmethod
    def _restore(obj, geometry_before, transform_before):
        for vertex, value in zip(obj.data.vertices, geometry_before["vertices"], strict=True):
            vertex.co = value
        obj.location = transform_before["location"]
        obj.rotation_mode = transform_before["rotation_mode"]
        obj.rotation_euler = transform_before["rotation_euler"]
        obj.scale = transform_before["scale"]
        obj.data.update()

    @staticmethod
    def _baked_vertex(value, scale, rotation, location):
        scaled = tuple(component * factor for component, factor in zip(value, scale, strict=True))
        rotated = rotate_xyz(scaled, rotation)
        return vector3(
            [component + offset for component, offset in zip(rotated, location, strict=True)],
            "baked vertex",
            1_000_000,
        )

    def apply_object_transform(self, request: Request, action: MeshTransformAction) -> Result:
        obj, object_before, geometry_before = self._target(action)
        transform_before = object_before["transform"]
        baked = [
            self._baked_vertex(
                vertex,
                transform_before["scale"],
                transform_before["rotation_euler"],
                transform_before["location"],
            )
            for vertex in geometry_before["vertices"]
        ]
        expected_geometry = {
            "vertices": [list(vertex) for vertex in baked],
            "faces": geometry_before["faces"],
        }
        try:
            for vertex, value in zip(obj.data.vertices, baked, strict=True):
                vertex.co = value
            obj.location = [0.0, 0.0, 0.0]
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = [0.0, 0.0, 0.0]
            obj.scale = [1.0, 1.0, 1.0]
            obj.data.update()
            self.bpy.context.view_layer.update()
            after = {
                "object": self.objects._readback(obj),
                "geometry": self.meshes.snapshot(obj),
            }
            expected = {
                "object": {
                    "object_id": object_before["object_id"],
                    "transform": {
                        "location": [0.0, 0.0, 0.0],
                        "rotation_mode": "XYZ",
                        "rotation_euler": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                },
                "geometry": expected_geometry,
            }
            result = self.objects._result(
                request,
                {"object": object_before, "geometry": geometry_before},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                self._restore(obj, geometry_before, transform_before)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._restore(obj, geometry_before, transform_before)
            self.bpy.context.view_layer.update()
            raise

    def origin_to_centroid(self, request: Request, action: MeshTransformAction) -> Result:
        obj, object_before, geometry_before = self._target(action)
        transform_before = object_before["transform"]
        count = len(geometry_before["vertices"])
        centroid = tuple(
            sum(vertex[axis] for vertex in geometry_before["vertices"]) / count for axis in range(3)
        )
        shifted = [
            vector3(
                [value - center for value, center in zip(vertex, centroid, strict=True)],
                "origin-shifted vertex",
                1_000_000,
            )
            for vertex in geometry_before["vertices"]
        ]
        scaled_centroid = tuple(
            value * factor
            for value, factor in zip(centroid, transform_before["scale"], strict=True)
        )
        world_offset = rotate_xyz(scaled_centroid, transform_before["rotation_euler"])
        new_location = vector3(
            [
                value + delta
                for value, delta in zip(transform_before["location"], world_offset, strict=True)
            ],
            "origin location",
            1_000_000,
        )
        expected_geometry = {
            "vertices": [list(vertex) for vertex in shifted],
            "faces": geometry_before["faces"],
        }
        try:
            for vertex, value in zip(obj.data.vertices, shifted, strict=True):
                vertex.co = value
            obj.location = new_location
            obj.data.update()
            self.bpy.context.view_layer.update()
            after = {
                "object": self.objects._readback(obj),
                "geometry": self.meshes.snapshot(obj),
                "centroid_local_before": list(centroid),
            }
            expected = {
                "object": {
                    "object_id": object_before["object_id"],
                    "transform": {
                        "location": list(new_location),
                        "rotation_mode": transform_before["rotation_mode"],
                        "rotation_euler": transform_before["rotation_euler"],
                        "scale": transform_before["scale"],
                    },
                },
                "geometry": expected_geometry,
                "centroid_local_before": list(centroid),
            }
            result = self.objects._result(
                request,
                {"object": object_before, "geometry": geometry_before},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                self._restore(obj, geometry_before, transform_before)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._restore(obj, geometry_before, transform_before)
            self.bpy.context.view_layer.update()
            raise

    def tools(self):
        return [
            Tool(
                "mesh.apply_object_transform",
                SafetyClass.MUTATION,
                MeshTransformAction.parse,
                self.apply_object_transform,
            ),
            Tool(
                "origin.to_centroid",
                SafetyClass.MUTATION,
                MeshTransformAction.parse,
                self.origin_to_centroid,
            ),
        ]
