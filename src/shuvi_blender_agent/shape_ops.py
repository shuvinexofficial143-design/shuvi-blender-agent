"""Bounded curve and text creation using direct Blender data APIs."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import Transform, object_name, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, number, string

MAX_CURVE_POINTS = 256
MAX_TEXT_LENGTH = 1000
TEXT_ALIGN = ("LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH")


def boolean(value, name):
    if type(value) is not bool:
        raise invalid(f"{name} must be boolean")
    return value


@dataclass(frozen=True)
class CreateCurve:
    name: str
    points: tuple[tuple[float, float, float], ...]
    cyclic: bool
    bevel_depth: float
    transform: Transform
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "name",
                "points",
                "cyclic",
                "bevel_depth",
                "transform",
                "expected_scene_revision",
            },
        )
        points = data["points"]
        if not isinstance(points, list) or not 2 <= len(points) <= MAX_CURVE_POINTS:
            raise invalid("Curve requires 2..256 points")
        return cls(
            object_name(data["name"]),
            tuple(vector3(point, "curve point", 1_000_000) for point in points),
            boolean(data["cyclic"], "cyclic"),
            number(data["bevel_depth"], "bevel_depth", 0, 100),
            Transform.parse(data["transform"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class CreateText:
    name: str
    body: str
    align_x: str
    size: float
    extrude: float
    transform: Transform
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "name",
                "body",
                "align_x",
                "size",
                "extrude",
                "transform",
                "expected_scene_revision",
            },
        )
        align = data["align_x"]
        if not isinstance(align, str) or align not in TEXT_ALIGN:
            raise invalid("Unsupported text horizontal alignment")
        return cls(
            object_name(data["name"]),
            string(data["body"], "body", limit=MAX_TEXT_LENGTH),
            align,
            number(data["size"], "size", 0.0001, 1000),
            number(data["extrude"], "extrude", 0, 100),
            Transform.parse(data["transform"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


class ShapeOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def _shape_snapshot(self, obj):
        if obj.type == "CURVE":
            data = obj.data
            if len(data.splines) != 1:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Expected one bounded curve spline")
            spline = data.splines[0]
            if spline.type != "POLY" or len(spline.points) > MAX_CURVE_POINTS:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported curve spline state")
            return {
                "object_id": self.inspector.identity(obj),
                "name": obj.name,
                "data_name": data.name,
                "type": "CURVE",
                "dimensions": data.dimensions,
                "spline_type": spline.type,
                "point_count": len(spline.points),
                "points": [
                    [float(point.co[0]), float(point.co[1]), float(point.co[2])]
                    for point in spline.points
                ],
                "cyclic": bool(spline.use_cyclic_u),
                "bevel_depth": float(data.bevel_depth),
            }
        if obj.type == "FONT":
            data = obj.data
            body = data.body
            if len(body) > MAX_TEXT_LENGTH:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Text exceeds readback limit")
            return {
                "object_id": self.inspector.identity(obj),
                "name": obj.name,
                "data_name": data.name,
                "type": "FONT",
                "body": body,
                "align_x": data.align_x,
                "size": float(data.size),
                "extrude": float(data.extrude),
            }
        raise AgentError(ErrorCode.SAFETY_DENIED, "Curve or text object required")

    def inspect(self, request: Request, object_id: str) -> Result:
        obj = self.inspector.resolve(object_id)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._shape_snapshot(obj),
        )

    def create_curve(self, request: Request, action: CreateCurve) -> Result:
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        self.objects._free_name(action.name)
        data = obj = None
        try:
            data = self.bpy.data.curves.new(action.name + "Curve", type="CURVE")
            data.dimensions = "3D"
            data.bevel_depth = action.bevel_depth
            spline = data.splines.new("POLY")
            spline.points.add(len(action.points) - 1)
            for point, value in zip(spline.points, action.points, strict=True):
                point.co = (*value, 1.0)
            spline.use_cyclic_u = action.cyclic
            obj = self.bpy.data.objects.new(action.name, data)
            self.bpy.context.scene.collection.objects.link(obj)
            self.objects._transform(obj, action.transform)
            self.bpy.context.view_layer.update()
            after = {
                "object": self.objects._readback(obj),
                "shape": self._shape_snapshot(obj),
            }
            expected = {
                "object": {
                    "name": action.name,
                    "type": "CURVE",
                    "scene_member": True,
                    "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
                },
                "shape": {
                    "name": action.name,
                    "type": "CURVE",
                    "dimensions": "3D",
                    "spline_type": "POLY",
                    "point_count": len(action.points),
                    "points": [list(point) for point in action.points],
                    "cyclic": action.cyclic,
                    "bevel_depth": action.bevel_depth,
                },
            }
            result = self.objects._result(request, None, after, expected)
            if result.status == Status.FAILED:
                self.objects._remove_created(obj, None)
                if data.users == 0:
                    self.bpy.data.curves.remove(data)
                result.data["rolled_back"] = True
            return result
        except Exception:
            if obj is not None:
                self.objects._remove_created(obj, None)
            if data is not None and data.users == 0:
                self.bpy.data.curves.remove(data)
            raise

    def create_text(self, request: Request, action: CreateText) -> Result:
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        self.objects._free_name(action.name)
        data = obj = None
        try:
            data = self.bpy.data.curves.new(action.name + "Text", type="FONT")
            data.body = action.body
            data.align_x = action.align_x
            data.size = action.size
            data.extrude = action.extrude
            obj = self.bpy.data.objects.new(action.name, data)
            self.bpy.context.scene.collection.objects.link(obj)
            self.objects._transform(obj, action.transform)
            self.bpy.context.view_layer.update()
            after = {
                "object": self.objects._readback(obj),
                "shape": self._shape_snapshot(obj),
            }
            expected = {
                "object": {
                    "name": action.name,
                    "type": "FONT",
                    "scene_member": True,
                    "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
                },
                "shape": {
                    "name": action.name,
                    "type": "FONT",
                    "body": action.body,
                    "align_x": action.align_x,
                    "size": action.size,
                    "extrude": action.extrude,
                },
            }
            result = self.objects._result(request, None, after, expected)
            if result.status == Status.FAILED:
                self.objects._remove_created(obj, None)
                if data.users == 0:
                    self.bpy.data.curves.remove(data)
                result.data["rolled_back"] = True
            return result
        except Exception:
            if obj is not None:
                self.objects._remove_created(obj, None)
            if data is not None and data.users == 0:
                self.bpy.data.curves.remove(data)
            raise

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool("shape.inspect", SafetyClass.READ_ONLY, parse_id, self.inspect),
            Tool("curve.create", SafetyClass.MUTATION, CreateCurve.parse, self.create_curve),
            Tool("text.create", SafetyClass.MUTATION, CreateText.parse, self.create_text),
        ]
