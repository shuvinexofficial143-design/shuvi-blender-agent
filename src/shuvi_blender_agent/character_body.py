"""Level 3 milestone 8: bounded body, limb, hand/foot and symmetry helpers."""

from dataclasses import dataclass

from .character_blockout import PRESETS, _guide, _preset
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .models import vector3
from .operations import ObjectOperations
from .safety import SafetyClass
from .sculpting_controls import _symmetry_lookup
from .tools import Tool
from .validation import fields, invalid, number, string

SIDES = ("LEFT", "RIGHT")
LIMB_KINDS = ("ARM", "LEG")
EXTREMITY_KINDS = ("HAND", "FOOT")
MAX_BODY_AUDIT_VERTICES = 4096


def _side(value):
    if not isinstance(value, str) or value not in SIDES:
        raise invalid("side must be LEFT or RIGHT")
    return value


def _limb_kind(value):
    if not isinstance(value, str) or value not in LIMB_KINDS:
        raise invalid("limb_kind must be ARM or LEG")
    return value


def _extremity_kind(value):
    if not isinstance(value, str) or value not in EXTREMITY_KINDS:
        raise invalid("kind must be HAND or FOOT")
    return value


def _bounds(vertices):
    if not vertices:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Body helper requires mesh vertices")
    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return minimum, maximum


def _body_frame(vertices):
    minimum, maximum = _bounds(vertices)
    height = maximum[2] - minimum[2]
    if height <= 0:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Body helper requires nonzero local Z height")
    origin = (
        (minimum[0] + maximum[0]) / 2,
        (minimum[1] + maximum[1]) / 2,
        minimum[2],
    )
    return minimum, maximum, height, origin


@dataclass(frozen=True)
class BodyRegionPlan:
    object_id: str
    preset: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "preset"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _preset(data["preset"]),
        )


@dataclass(frozen=True)
class LimbGuide:
    preset: str
    height: float
    origin: tuple[float, float, float]
    side: str
    limb_kind: str

    @classmethod
    def parse(cls, data):
        fields(data, {"preset", "height", "origin", "side", "limb_kind"})
        return cls(
            _preset(data["preset"]),
            number(data["height"], "height", 0.01, 1_000_000),
            vector3(data["origin"], "origin", 1_000_000),
            _side(data["side"]),
            _limb_kind(data["limb_kind"]),
        )


@dataclass(frozen=True)
class ExtremityGuide:
    kind: str
    side: str
    anchor: tuple[float, float, float]
    length: float

    @classmethod
    def parse(cls, data):
        fields(data, {"kind", "side", "anchor", "length"})
        return cls(
            _extremity_kind(data["kind"]),
            _side(data["side"]),
            vector3(data["anchor"], "anchor", 1_000_000),
            number(data["length"], "length", 0.001, 1_000_000),
        )


@dataclass(frozen=True)
class BodySymmetryAudit:
    object_id: str
    tolerance: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "tolerance"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            number(data["tolerance"], "tolerance", 1e-6, 100),
        )


class CharacterBodyOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.meshes = MeshOperations(objects)

    def _geometry(self, object_id):
        obj = self.inspector.resolve(object_id)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        geometry = self.meshes.snapshot(obj)
        if len(geometry["vertices"]) > MAX_BODY_AUDIT_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Body helper exceeds vertex limit")
        return obj, geometry

    def body_regions(self, request: Request, action: BodyRegionPlan):
        obj, geometry = self._geometry(action.object_id)
        minimum, maximum, height, origin = _body_frame(geometry["vertices"])
        guide = _guide(action.preset, height, origin)
        head = guide["head_height"]
        shoulder_half = guide["shoulder_width"] / 2
        hip_half = guide["hip_width"] / 2
        ox, oy, oz = origin

        regions = [
            {
                "name": "CHEST",
                "center": [ox, oy, oz + height * 0.735],
                "radius": head * 0.82,
            },
            {
                "name": "ABDOMEN",
                "center": [ox, oy, oz + height * 0.625],
                "radius": head * 0.68,
            },
            {
                "name": "PELVIS",
                "center": [ox, oy, oz + height * 0.535],
                "radius": head * 0.72,
            },
        ]
        for side, sign in (("L", -1), ("R", 1)):
            shoulder_x = ox + sign * shoulder_half * 0.88
            hip_x = ox + sign * hip_half * 0.58
            regions.extend(
                [
                    {
                        "name": f"SHOULDER_{side}",
                        "center": [shoulder_x, oy, oz + height * 0.815],
                        "radius": head * 0.42,
                    },
                    {
                        "name": f"UPPER_ARM_{side}",
                        "center": [ox + sign * shoulder_half * 1.18, oy, oz + height * 0.70],
                        "radius": head * 0.34,
                    },
                    {
                        "name": f"FOREARM_{side}",
                        "center": [ox + sign * shoulder_half * 1.30, oy, oz + height * 0.57],
                        "radius": head * 0.29,
                    },
                    {
                        "name": f"HAND_{side}",
                        "center": [ox + sign * shoulder_half * 1.35, oy, oz + height * 0.47],
                        "radius": head * 0.31,
                    },
                    {
                        "name": f"THIGH_{side}",
                        "center": [hip_x, oy, oz + height * 0.405],
                        "radius": head * 0.46,
                    },
                    {
                        "name": f"CALF_{side}",
                        "center": [hip_x, oy, oz + height * 0.185],
                        "radius": head * 0.36,
                    },
                    {
                        "name": f"FOOT_{side}",
                        "center": [hip_x, oy - head * 0.18, oz + height * 0.035],
                        "radius": head * 0.40,
                    },
                ]
            )

        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "preset": action.preset,
            "mesh_bounds_min": minimum,
            "mesh_bounds_max": maximum,
            "mesh_height": height,
            "regions": regions,
            "region_count": len(regions),
            "symmetry_axis": "LOCAL_X",
            "purpose": "CHARACTER_SCULPT_REGION_PLANNING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def limb(self, request: Request, action: LimbGuide):
        guide = _guide(action.preset, action.height, action.origin)
        sign = -1 if action.side == "LEFT" else 1
        ox, oy, oz = action.origin
        shoulder_half = guide["shoulder_width"] / 2
        hip_half = guide["hip_width"] / 2
        head = guide["head_height"]

        if action.limb_kind == "ARM":
            x = ox + sign * shoulder_half
            landmarks = [
                {"name": "SHOULDER", "position": [x, oy, oz + action.height * 0.815]},
                {
                    "name": "ELBOW",
                    "position": [ox + sign * shoulder_half * 1.22, oy, oz + action.height * 0.655],
                },
                {
                    "name": "WRIST",
                    "position": [ox + sign * shoulder_half * 1.32, oy, oz + action.height * 0.505],
                },
                {
                    "name": "HAND_CENTER",
                    "position": [
                        ox + sign * shoulder_half * 1.35,
                        oy,
                        oz + action.height * 0.455,
                    ],
                },
            ]
            thickness = head * 0.34
        else:
            x = ox + sign * hip_half * 0.45
            landmarks = [
                {"name": "HIP", "position": [x, oy, oz + action.height * 0.535]},
                {"name": "KNEE", "position": [x, oy, oz + action.height * 0.285]},
                {"name": "ANKLE", "position": [x, oy, oz + action.height * 0.045]},
                {
                    "name": "FOOT_CENTER",
                    "position": [x, oy - head * 0.18, oz + action.height * 0.025],
                },
            ]
            thickness = head * 0.46

        data = {
            "preset": action.preset,
            "height": action.height,
            "origin": list(action.origin),
            "side": action.side,
            "limb_kind": action.limb_kind,
            "landmarks": landmarks,
            "landmark_count": len(landmarks),
            "reference_thickness": thickness,
            "guide_status": "REFERENCE_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def extremity(self, request: Request, action: ExtremityGuide):
        sign = -1 if action.side == "LEFT" else 1
        x, y, z = action.anchor
        length = action.length

        if action.kind == "HAND":
            landmarks = [
                {"name": "WRIST", "position": [x, y, z]},
                {
                    "name": "PALM_CENTER",
                    "position": [x + sign * length * 0.32, y, z],
                },
                {
                    "name": "THUMB_TIP",
                    "position": [x + sign * length * 0.48, y - length * 0.24, z - length * 0.04],
                },
                {
                    "name": "INDEX_TIP",
                    "position": [x + sign * length * 0.92, y - length * 0.12, z],
                },
                {
                    "name": "MIDDLE_TIP",
                    "position": [x + sign * length, y, z],
                },
                {
                    "name": "RING_TIP",
                    "position": [x + sign * length * 0.94, y + length * 0.10, z],
                },
                {
                    "name": "PINKY_TIP",
                    "position": [x + sign * length * 0.80, y + length * 0.20, z],
                },
            ]
        else:
            landmarks = [
                {"name": "ANKLE", "position": [x, y, z]},
                {"name": "HEEL", "position": [x, y + length * 0.28, z - length * 0.10]},
                {"name": "BALL", "position": [x, y - length * 0.55, z - length * 0.16]},
                {"name": "BIG_TOE", "position": [x + sign * length * 0.16, y - length, z - length * 0.12]},
                {
                    "name": "LITTLE_TOE",
                    "position": [x - sign * length * 0.16, y - length * 0.88, z - length * 0.12],
                },
            ]

        data = {
            "kind": action.kind,
            "side": action.side,
            "anchor": list(action.anchor),
            "length": action.length,
            "landmarks": landmarks,
            "landmark_count": len(landmarks),
            "guide_status": "REFERENCE_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def symmetry(self, request: Request, action: BodySymmetryAudit):
        obj, geometry = self._geometry(action.object_id)
        vertices = geometry["vertices"]
        find_partner, get_checks = _symmetry_lookup(vertices, 0, action.tolerance)

        positive = [
            index for index, vertex in enumerate(vertices) if vertex[0] > action.tolerance
        ]
        negative = [
            index for index, vertex in enumerate(vertices) if vertex[0] < -action.tolerance
        ]
        plane = [
            index for index, vertex in enumerate(vertices) if abs(vertex[0]) <= action.tolerance
        ]

        pairs = []
        used_negative = set()
        unmatched_positive = []
        collisions = []
        for index in positive:
            partner = find_partner(index)
            if partner is None or partner not in negative:
                unmatched_positive.append(index)
                continue
            if partner in used_negative:
                collisions.append([index, partner])
                continue
            used_negative.add(partner)
            pairs.append([index, partner])

        unmatched_negative = sorted(set(negative) - used_negative)
        status = (
            "PASS"
            if not unmatched_positive and not unmatched_negative and not collisions
            else "REVIEW"
        )
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "axis": "LOCAL_X",
            "tolerance": action.tolerance,
            "positive_vertex_count": len(positive),
            "negative_vertex_count": len(negative),
            "plane_vertex_count": len(plane),
            "paired_vertex_count": len(pairs) * 2,
            "pairs": pairs,
            "unmatched_positive_indices": unmatched_positive,
            "unmatched_negative_indices": unmatched_negative,
            "collision_pairs": collisions,
            "symmetry_candidate_checks": get_checks(),
            "symmetry_status": status,
            "audit_status": "BASE_MESH_COORDINATE_AUDIT_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "character.body_region_plan",
                SafetyClass.READ_ONLY,
                BodyRegionPlan.parse,
                self.body_regions,
            ),
            Tool(
                "character.limb_guide",
                SafetyClass.READ_ONLY,
                LimbGuide.parse,
                self.limb,
            ),
            Tool(
                "character.extremity_guide",
                SafetyClass.READ_ONLY,
                ExtremityGuide.parse,
                self.extremity,
            ),
            Tool(
                "character.body_symmetry_audit",
                SafetyClass.READ_ONLY,
                BodySymmetryAudit.parse,
                self.symmetry,
            ),
        ]
