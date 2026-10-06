"""Level 3 milestone 3: bounded mask, region, symmetry and side-aware sculpt controls."""

from dataclasses import dataclass
from itertools import product
from math import floor

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass
from .sculpting import (
    FALLOFFS,
    MAX_SCULPT_VERTICES,
    NORMAL_EPSILON,
    SculptingOperations,
    _add,
    _falloff,
    _length,
    _mul,
    _sub,
    _vertex_normals,
)
from .tools import Tool
from .validation import fields, integer, invalid, number, string

AXES = ("NONE", "X", "Y", "Z")
SIDES = ("BOTH", "POSITIVE", "NEGATIVE")
MAX_MASK_ENTRIES = 512
MAX_SYMMETRY_CANDIDATE_CHECKS = 1_000_000
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def _bool(value, name):
    if type(value) is not bool:
        raise invalid(f"{name} must be boolean")
    return value


def _axis_side(axis, side, symmetry):
    if not isinstance(axis, str) or axis not in AXES:
        raise invalid("axis must be NONE, X, Y or Z")
    if not isinstance(side, str) or side not in SIDES:
        raise invalid("side must be BOTH, POSITIVE or NEGATIVE")
    if axis == "NONE" and side != "BOTH":
        raise invalid("side filtering requires X, Y or Z axis")
    if symmetry and (axis == "NONE" or side == "BOTH"):
        raise invalid("symmetry requires an axis and POSITIVE or NEGATIVE source side")
    return axis, side


def _parse_mask(value):
    if not isinstance(value, list) or len(value) > MAX_MASK_ENTRIES:
        raise invalid(f"mask must contain at most {MAX_MASK_ENTRIES} entries")
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise invalid("mask entry must be an object")
        fields(item, {"vertex_index", "weight"})
        index = integer(item["vertex_index"], "vertex_index", 0, 1_000_000)
        if index in result:
            raise invalid("mask vertex indices must be unique")
        result[index] = number(item["weight"], "mask weight", 0, 1)
    return result


@dataclass(frozen=True)
class RegionControl:
    center: tuple[float, float, float]
    radius: float
    falloff: str
    axis: str
    side: str
    symmetry: bool
    plane_epsilon: float
    require_symmetry_pairs: bool
    mask: dict[int, float]

    @classmethod
    def parse_fields(cls, data):
        falloff = data["falloff"]
        if not isinstance(falloff, str) or falloff not in FALLOFFS:
            raise invalid("falloff must be LINEAR or SMOOTH")
        symmetry = _bool(data["symmetry"], "symmetry")
        axis, side = _axis_side(data["axis"], data["side"], symmetry)
        require_pairs = _bool(
            data["require_symmetry_pairs"],
            "require_symmetry_pairs",
        )
        if require_pairs and not symmetry:
            raise invalid("require_symmetry_pairs requires symmetry=true")
        return cls(
            vector3(data["center"], "center", 1_000_000),
            number(data["radius"], "radius", 1e-6, 1_000_000),
            falloff,
            axis,
            side,
            symmetry,
            number(data["plane_epsilon"], "plane_epsilon", 1e-9, 100),
            require_pairs,
            _parse_mask(data["mask"]),
        )


@dataclass(frozen=True)
class RegionPreview:
    object_id: str
    control: RegionControl

    @classmethod
    def parse(cls, data):
        allowed = {
            "object_id",
            "center",
            "radius",
            "falloff",
            "axis",
            "side",
            "symmetry",
            "plane_epsilon",
            "require_symmetry_pairs",
            "mask",
        }
        fields(data, allowed)
        return cls(
            string(data["object_id"], "object_id", limit=128),
            RegionControl.parse_fields(data),
        )


@dataclass(frozen=True)
class ControlledDisplace:
    target: ObjectTarget
    expected_geometry_revision: str
    control: RegionControl
    strength: float

    @classmethod
    def parse(cls, data):
        allowed = {
            "target",
            "expected_geometry_revision",
            "center",
            "radius",
            "falloff",
            "axis",
            "side",
            "symmetry",
            "plane_epsilon",
            "require_symmetry_pairs",
            "mask",
            "strength",
        }
        fields(data, allowed)
        strength = number(data["strength"], "strength", -100, 100)
        if strength == 0:
            raise invalid("strength cannot be zero")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            RegionControl.parse_fields(data),
            strength,
        )


@dataclass(frozen=True)
class ControlledGrab:
    target: ObjectTarget
    expected_geometry_revision: str
    control: RegionControl
    delta: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        allowed = {
            "target",
            "expected_geometry_revision",
            "center",
            "radius",
            "falloff",
            "axis",
            "side",
            "symmetry",
            "plane_epsilon",
            "require_symmetry_pairs",
            "mask",
            "delta",
        }
        fields(data, allowed)
        delta = vector3(data["delta"], "delta", 1000)
        if delta == (0.0, 0.0, 0.0):
            raise invalid("delta cannot be zero")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            RegionControl.parse_fields(data),
            delta,
        )


def _side_accept(value, side, epsilon):
    if side == "BOTH":
        return True
    if abs(value) <= epsilon:
        return True
    if side == "POSITIVE":
        return value > epsilon
    return value < -epsilon


def _mirror_point(value, axis_index):
    mirrored = list(value)
    mirrored[axis_index] = -mirrored[axis_index]
    return tuple(mirrored)


def _cell(value, epsilon):
    return tuple(floor(component / epsilon) for component in value)


def _symmetry_lookup(vertices, axis_index, epsilon):
    buckets = {}
    for index, vertex in enumerate(vertices):
        buckets.setdefault(_cell(vertex, epsilon), []).append(index)
    offsets = tuple(product((-1, 0, 1), repeat=3))
    checks = 0

    def find(index):
        nonlocal checks
        target = _mirror_point(vertices[index], axis_index)
        base = _cell(target, epsilon)
        best = None
        for offset in offsets:
            key = tuple(base[axis] + offset[axis] for axis in range(3))
            for candidate in buckets.get(key, ()):
                checks += 1
                if checks > MAX_SYMMETRY_CANDIDATE_CHECKS:
                    raise AgentError(
                        ErrorCode.SAFETY_DENIED,
                        "Symmetry candidate work limit exceeded",
                    )
                distance = _length(_sub(vertices[candidate], target))
                if distance <= epsilon:
                    choice = (distance, candidate)
                    if best is None or choice < best:
                        best = choice
        return None if best is None else best[1]

    return find, lambda: checks


def _region(vertices, control):
    axis_index = _AXIS_INDEX.get(control.axis)
    find_partner = None
    get_checks = lambda: 0
    if control.symmetry:
        find_partner, get_checks = _symmetry_lookup(
            vertices,
            axis_index,
            control.plane_epsilon,
        )

    entries = []
    changed = set()
    missing = []
    for index, vertex in enumerate(vertices):
        if axis_index is not None and not _side_accept(
            vertex[axis_index],
            control.side,
            control.plane_epsilon,
        ):
            continue
        distance = _length(_sub(vertex, control.center))
        if distance > control.radius:
            continue
        radial = _falloff(distance, control.radius, control.falloff)
        if radial <= 0:
            continue

        partner = None
        partner_mask = 0.0
        if control.symmetry:
            partner = find_partner(index)
            if partner is None:
                missing.append(index)
                if control.require_symmetry_pairs:
                    continue
            elif partner != index:
                partner_mask = control.mask.get(partner, 0.0)

        mask = control.mask.get(index, 0.0)
        effective_mask = max(mask, partner_mask) if partner is not None else mask
        final_weight = radial * (1.0 - effective_mask)
        if final_weight <= 0:
            continue

        entries.append(
            {
                "source_index": index,
                "partner_index": partner,
                "distance": distance,
                "radial_weight": radial,
                "mask_weight": mask,
                "partner_mask_weight": partner_mask,
                "effective_mask_weight": effective_mask,
                "final_weight": final_weight,
                "on_symmetry_plane": (
                    axis_index is not None
                    and abs(vertex[axis_index]) <= control.plane_epsilon
                ),
            }
        )
        changed.add(index)
        if partner is not None:
            changed.add(partner)

    if control.require_symmetry_pairs and missing:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            "One or more source-side vertices have no symmetry partner",
        )
    if len(changed) > MAX_SCULPT_VERTICES:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            f"Controlled sculpt affects more than {MAX_SCULPT_VERTICES} vertices",
        )
    return entries, sorted(changed), sorted(set(missing)), get_checks()


class SculptControlOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.base = SculptingOperations(objects)

    def _preview_data(self, geometry, control):
        entries, changed, missing, checks = _region(geometry["vertices"], control)
        return {
            "object_id": geometry["object_id"],
            "name": geometry["name"],
            "geometry_revision": geometry["geometry_revision"],
            "center": list(control.center),
            "radius": control.radius,
            "falloff": control.falloff,
            "axis": control.axis,
            "side": control.side,
            "symmetry": control.symmetry,
            "plane_epsilon": control.plane_epsilon,
            "require_symmetry_pairs": control.require_symmetry_pairs,
            "mask_entry_count": len(control.mask),
            "entries": entries,
            "source_vertex_indices": [entry["source_index"] for entry in entries],
            "changed_vertex_indices": changed,
            "source_vertex_count": len(entries),
            "changed_vertex_count": len(changed),
            "missing_symmetry_source_indices": missing,
            "symmetry_candidate_checks": checks,
        }

    def preview(self, request: Request, action: RegionPreview):
        obj = self.inspector.resolve(action.object_id)
        geometry = self.base.meshes.snapshot(obj)
        data = self._preview_data(geometry, action.control)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _editable(self, action):
        obj, object_before, before = self.base._editable_mesh(action)
        region = self._preview_data(before, action.control)
        if not region["entries"]:
            raise invalid("Controlled sculpt region has no vertices with positive influence")
        return obj, object_before, before, region

    @staticmethod
    def _mirrored_result(source_new, source_old, partner_old, axis_index, on_plane):
        if on_plane:
            result = list(source_new)
            result[axis_index] = 0.0
            return tuple(result)
        source_delta = _sub(source_new, source_old)
        mirrored_delta = list(source_delta)
        mirrored_delta[axis_index] = -mirrored_delta[axis_index]
        return _add(partner_old, mirrored_delta)

    def displace(self, request: Request, action: ControlledDisplace):
        obj, object_before, before, region = self._editable(action)
        normals = _vertex_normals(before["vertices"], before["faces"])
        axis_index = _AXIS_INDEX.get(action.control.axis)
        vertices = [list(vertex) for vertex in before["vertices"]]
        changed = set()
        applied = []

        for entry in region["entries"]:
            index = entry["source_index"]
            normal = normals[index]
            if _length(normal) <= NORMAL_EPSILON:
                continue
            source_new = _add(
                before["vertices"][index],
                _mul(normal, action.strength * entry["final_weight"]),
            )
            partner = entry["partner_index"]
            if action.control.symmetry and partner is not None:
                source_new = self._mirrored_result(
                    source_new,
                    before["vertices"][index],
                    before["vertices"][index],
                    axis_index,
                    entry["on_symmetry_plane"],
                ) if partner == index else source_new
            vertices[index] = list(
                vector3(source_new, "controlled sculpt displaced vertex", 1_000_000)
            )
            changed.add(index)

            if action.control.symmetry and partner is not None and partner != index:
                partner_new = self._mirrored_result(
                    source_new,
                    before["vertices"][index],
                    before["vertices"][partner],
                    axis_index,
                    False,
                )
                vertices[partner] = list(
                    vector3(partner_new, "controlled sculpt mirrored vertex", 1_000_000)
                )
                changed.add(partner)
            applied.append(entry)

        if not applied:
            raise invalid("Controlled displace has no vertices with valid normals")

        evidence = {
            "brush": "CONTROLLED_DISPLACE_NORMAL",
            "strength": action.strength,
            "axis": action.control.axis,
            "side": action.control.side,
            "symmetry": action.control.symmetry,
            "mask_entry_count": len(action.control.mask),
            "source_vertex_indices": [entry["source_index"] for entry in applied],
            "affected_vertex_indices": sorted(changed),
            "affected_vertex_count": len(changed),
            "missing_symmetry_source_indices": region["missing_symmetry_source_indices"],
            "weights": {
                str(entry["source_index"]): entry["final_weight"] for entry in applied
            },
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            sorted(changed),
        )

    def grab(self, request: Request, action: ControlledGrab):
        obj, object_before, before, region = self._editable(action)
        axis_index = _AXIS_INDEX.get(action.control.axis)
        vertices = [list(vertex) for vertex in before["vertices"]]
        changed = set()

        for entry in region["entries"]:
            index = entry["source_index"]
            source_new = _add(
                before["vertices"][index],
                _mul(action.delta, entry["final_weight"]),
            )
            partner = entry["partner_index"]
            if action.control.symmetry and partner == index:
                source_new = self._mirrored_result(
                    source_new,
                    before["vertices"][index],
                    before["vertices"][index],
                    axis_index,
                    True,
                )
            vertices[index] = list(
                vector3(source_new, "controlled sculpt grabbed vertex", 1_000_000)
            )
            changed.add(index)

            if action.control.symmetry and partner is not None and partner != index:
                partner_new = self._mirrored_result(
                    source_new,
                    before["vertices"][index],
                    before["vertices"][partner],
                    axis_index,
                    False,
                )
                vertices[partner] = list(
                    vector3(partner_new, "controlled sculpt mirrored grab vertex", 1_000_000)
                )
                changed.add(partner)

        evidence = {
            "brush": "CONTROLLED_GRAB",
            "delta": list(action.delta),
            "axis": action.control.axis,
            "side": action.control.side,
            "symmetry": action.control.symmetry,
            "mask_entry_count": len(action.control.mask),
            "source_vertex_indices": region["source_vertex_indices"],
            "affected_vertex_indices": sorted(changed),
            "affected_vertex_count": len(changed),
            "missing_symmetry_source_indices": region["missing_symmetry_source_indices"],
            "weights": {
                str(entry["source_index"]): entry["final_weight"]
                for entry in region["entries"]
            },
        }
        return self.base._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            sorted(changed),
        )

    def tools(self):
        return [
            Tool(
                "sculpt.region_preview",
                SafetyClass.READ_ONLY,
                RegionPreview.parse,
                self.preview,
            ),
            Tool(
                "sculpt.brush_displace_controlled",
                SafetyClass.MUTATION,
                ControlledDisplace.parse,
                self.displace,
            ),
            Tool(
                "sculpt.brush_grab_controlled",
                SafetyClass.MUTATION,
                ControlledGrab.parse,
                self.grab,
            ),
        ]
