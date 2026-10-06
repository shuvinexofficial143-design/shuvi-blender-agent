"""Level 3 milestone 2: expanded bounded sculpt brush deformation foundations."""

from dataclasses import dataclass

from .contracts import Request
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass
from .sculpting import (
    FALLOFFS,
    NORMAL_EPSILON,
    SculptingOperations,
    _add,
    _brush_selection,
    _length,
    _mul,
    _sub,
    _vertex_normals,
)
from .tools import Tool
from .validation import fields, invalid, number, string


def _dot(a, b):
    return sum(a[index] * b[index] for index in range(3))


def _normalize(value):
    length = _length(value)
    if length <= NORMAL_EPSILON:
        return None
    return tuple(component / length for component in value)


def _valid_selection(vertices, center, radius, falloff):
    return [
        item
        for item in _brush_selection(vertices, center, radius, falloff)
        if item["weight"] > 0
    ]


def _weighted_brush_normal(normals, selected):
    total = (0.0, 0.0, 0.0)
    used = []
    for item in selected:
        normal = normals[item["index"]]
        if _length(normal) <= NORMAL_EPSILON:
            continue
        total = _add(total, _mul(normal, item["weight"]))
        used.append(item)
    normal = _normalize(total)
    if normal is None or not used:
        raise invalid("Sculpt brush cannot resolve a stable local surface normal")
    return normal, used


def _weighted_centroid(vertices, selected):
    weight_sum = sum(item["weight"] for item in selected)
    if weight_sum <= NORMAL_EPSILON:
        raise invalid("Sculpt brush has no positive falloff weight")
    return tuple(
        sum(vertices[item["index"]][axis] * item["weight"] for item in selected)
        / weight_sum
        for axis in range(3)
    )


def _weights(items):
    return {str(item["index"]): item["weight"] for item in items}


@dataclass(frozen=True)
class SculptNormalizedBrush:
    target: ObjectTarget
    expected_geometry_revision: str
    center: tuple[float, float, float]
    radius: float
    strength: float
    falloff: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "center",
                "radius",
                "strength",
                "falloff",
            },
        )
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        strength = number(data["strength"], "strength", -1.0, 1.0)
        if strength == 0:
            raise invalid("strength cannot be zero")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            strength,
            falloff,
        )


@dataclass(frozen=True)
class SculptFlatten:
    target: ObjectTarget
    expected_geometry_revision: str
    center: tuple[float, float, float]
    radius: float
    strength: float
    falloff: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "center",
                "radius",
                "strength",
                "falloff",
            },
        )
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            number(data["strength"], "strength", 0.001, 1.0),
            falloff,
        )


@dataclass(frozen=True)
class SculptGrab:
    target: ObjectTarget
    expected_geometry_revision: str
    center: tuple[float, float, float]
    radius: float
    delta: tuple[float, float, float]
    falloff: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "center",
                "radius",
                "delta",
                "falloff",
            },
        )
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        delta = vector3(data["delta"], "delta", 1000)
        if delta == (0.0, 0.0, 0.0):
            raise invalid("delta cannot be zero")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            delta,
            falloff,
        )


@dataclass(frozen=True)
class SculptCrease:
    target: ObjectTarget
    expected_geometry_revision: str
    center: tuple[float, float, float]
    radius: float
    pinch: float
    depth: float
    falloff: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "center",
                "radius",
                "pinch",
                "depth",
                "falloff",
            },
        )
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        pinch = number(data["pinch"], "pinch", 0, 1.0)
        depth = number(data["depth"], "depth", 0, 100)
        if pinch == 0 and depth == 0:
            raise invalid("crease requires nonzero pinch or depth")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            pinch,
            depth,
            falloff,
        )


class SculptBrushOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.base = SculptingOperations(objects)

    def _context(self, action, *, normals_required=True):
        obj, object_before, before = self.base._editable_mesh(action)
        selected = _valid_selection(
            before["vertices"],
            action.center,
            action.radius,
            action.falloff,
        )
        if not selected:
            raise invalid("Sculpt brush affects no vertices with positive falloff")
        if not normals_required:
            return obj, object_before, before, selected, None
        normals = _vertex_normals(before["vertices"], before["faces"])
        brush_normal, affected = _weighted_brush_normal(normals, selected)
        return obj, object_before, before, affected, (normals, brush_normal)

    def inflate(self, request: Request, action: SculptNormalizedBrush):
        obj, object_before, before, affected, normal_data = self._context(action)
        normals, _ = normal_data
        vertices = [list(vertex) for vertex in before["vertices"]]
        scale = action.radius * 0.25 * action.strength
        for item in affected:
            index = item["index"]
            vertices[index] = list(
                vector3(
                    _add(
                        before["vertices"][index],
                        _mul(normals[index], scale * item["weight"]),
                    ),
                    "sculpt inflated vertex",
                    1_000_000,
                )
            )
        evidence = {
            "brush": "INFLATE",
            "center": list(action.center),
            "radius": action.radius,
            "strength": action.strength,
            "normal_displacement_scale": scale,
            "falloff": action.falloff,
            "affected_vertex_indices": [item["index"] for item in affected],
            "affected_vertex_count": len(affected),
            "weights": _weights(affected),
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            [item["index"] for item in affected],
        )

    def flatten(self, request: Request, action: SculptFlatten):
        obj, object_before, before, affected, normal_data = self._context(action)
        _, brush_normal = normal_data
        plane_origin = _weighted_centroid(before["vertices"], affected)
        vertices = [list(vertex) for vertex in before["vertices"]]
        for item in affected:
            index = item["index"]
            signed_distance = _dot(
                _sub(before["vertices"][index], plane_origin),
                brush_normal,
            )
            vertices[index] = list(
                vector3(
                    _sub(
                        before["vertices"][index],
                        _mul(
                            brush_normal,
                            signed_distance * action.strength * item["weight"],
                        ),
                    ),
                    "sculpt flattened vertex",
                    1_000_000,
                )
            )
        evidence = {
            "brush": "FLATTEN",
            "center": list(action.center),
            "radius": action.radius,
            "strength": action.strength,
            "falloff": action.falloff,
            "plane_origin": list(plane_origin),
            "plane_normal": list(brush_normal),
            "affected_vertex_indices": [item["index"] for item in affected],
            "affected_vertex_count": len(affected),
            "weights": _weights(affected),
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            [item["index"] for item in affected],
        )

    def pinch(self, request: Request, action: SculptNormalizedBrush):
        obj, object_before, before, affected, normal_data = self._context(action)
        _, brush_normal = normal_data
        vertices = [list(vertex) for vertex in before["vertices"]]
        for item in affected:
            index = item["index"]
            radial = _sub(before["vertices"][index], action.center)
            tangent = _sub(radial, _mul(brush_normal, _dot(radial, brush_normal)))
            amount = action.strength * item["weight"]
            vertices[index] = list(
                vector3(
                    _sub(before["vertices"][index], _mul(tangent, amount)),
                    "sculpt pinched vertex",
                    1_000_000,
                )
            )
        evidence = {
            "brush": "PINCH",
            "center": list(action.center),
            "radius": action.radius,
            "strength": action.strength,
            "falloff": action.falloff,
            "plane_normal": list(brush_normal),
            "affected_vertex_indices": [item["index"] for item in affected],
            "affected_vertex_count": len(affected),
            "weights": _weights(affected),
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            [item["index"] for item in affected],
        )

    def grab(self, request: Request, action: SculptGrab):
        obj, object_before, before, affected, _ = self._context(
            action,
            normals_required=False,
        )
        vertices = [list(vertex) for vertex in before["vertices"]]
        for item in affected:
            index = item["index"]
            vertices[index] = list(
                vector3(
                    _add(
                        before["vertices"][index],
                        _mul(action.delta, item["weight"]),
                    ),
                    "sculpt grabbed vertex",
                    1_000_000,
                )
            )
        evidence = {
            "brush": "GRAB",
            "center": list(action.center),
            "radius": action.radius,
            "delta": list(action.delta),
            "falloff": action.falloff,
            "affected_vertex_indices": [item["index"] for item in affected],
            "affected_vertex_count": len(affected),
            "weights": _weights(affected),
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            [item["index"] for item in affected],
        )

    def crease(self, request: Request, action: SculptCrease):
        obj, object_before, before, affected, normal_data = self._context(action)
        _, brush_normal = normal_data
        vertices = [list(vertex) for vertex in before["vertices"]]
        for item in affected:
            index = item["index"]
            radial = _sub(before["vertices"][index], action.center)
            tangent = _sub(radial, _mul(brush_normal, _dot(radial, brush_normal)))
            weight = item["weight"]
            pinched = _sub(
                before["vertices"][index],
                _mul(tangent, action.pinch * weight),
            )
            vertices[index] = list(
                vector3(
                    _sub(pinched, _mul(brush_normal, action.depth * weight)),
                    "sculpt creased vertex",
                    1_000_000,
                )
            )
        evidence = {
            "brush": "CREASE",
            "center": list(action.center),
            "radius": action.radius,
            "pinch": action.pinch,
            "depth": action.depth,
            "falloff": action.falloff,
            "plane_normal": list(brush_normal),
            "affected_vertex_indices": [item["index"] for item in affected],
            "affected_vertex_count": len(affected),
            "weights": _weights(affected),
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            [item["index"] for item in affected],
        )

    def tools(self):
        return [
            Tool(
                "sculpt.brush_inflate",
                SafetyClass.MUTATION,
                SculptNormalizedBrush.parse,
                self.inflate,
            ),
            Tool(
                "sculpt.brush_flatten",
                SafetyClass.MUTATION,
                SculptFlatten.parse,
                self.flatten,
            ),
            Tool(
                "sculpt.brush_pinch",
                SafetyClass.MUTATION,
                SculptNormalizedBrush.parse,
                self.pinch,
            ),
            Tool(
                "sculpt.brush_grab",
                SafetyClass.MUTATION,
                SculptGrab.parse,
                self.grab,
            ),
            Tool(
                "sculpt.brush_crease",
                SafetyClass.MUTATION,
                SculptCrease.parse,
                self.crease,
            ),
        ]
