"""Level 3 milestone 6: bounded character blockout and proportion/landmark guides."""

from dataclasses import dataclass
from math import sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .models import vector3
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number, string

PRESETS = ("ADULT_NEUTRAL", "HEROIC", "STYLIZED")
MAX_FIT_VERTICES = 4096

_PRESET_DATA = {
    "ADULT_NEUTRAL": {
        "head_units": 7.5,
        "shoulder_width_heads": 2.35,
        "hip_width_heads": 1.65,
        "landmarks": {
            "HEAD_TOP": 1.000,
            "BROW": 0.956,
            "CHIN": 0.867,
            "SHOULDER": 0.815,
            "CHEST": 0.735,
            "NAVEL": 0.625,
            "PELVIS": 0.535,
            "KNEE": 0.285,
            "ANKLE": 0.045,
            "FOOT": 0.000,
        },
    },
    "HEROIC": {
        "head_units": 8.0,
        "shoulder_width_heads": 2.70,
        "hip_width_heads": 1.60,
        "landmarks": {
            "HEAD_TOP": 1.000,
            "BROW": 0.958,
            "CHIN": 0.875,
            "SHOULDER": 0.825,
            "CHEST": 0.750,
            "NAVEL": 0.635,
            "PELVIS": 0.540,
            "KNEE": 0.290,
            "ANKLE": 0.045,
            "FOOT": 0.000,
        },
    },
    "STYLIZED": {
        "head_units": 6.5,
        "shoulder_width_heads": 2.10,
        "hip_width_heads": 1.75,
        "landmarks": {
            "HEAD_TOP": 1.000,
            "BROW": 0.948,
            "CHIN": 0.846,
            "SHOULDER": 0.790,
            "CHEST": 0.710,
            "NAVEL": 0.600,
            "PELVIS": 0.510,
            "KNEE": 0.275,
            "ANKLE": 0.050,
            "FOOT": 0.000,
        },
    },
}


def _preset(value):
    if not isinstance(value, str) or value not in PRESETS:
        raise invalid("preset must be ADULT_NEUTRAL, HEROIC or STYLIZED")
    return value


def _bounds(vertices):
    if not vertices:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Character guide fitting requires mesh vertices")
    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return minimum, maximum


def _distance(a, b):
    return sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))


def _guide(preset, height, origin):
    data = _PRESET_DATA[preset]
    head_height = height / data["head_units"]
    half_shoulder = data["shoulder_width_heads"] * head_height / 2
    half_hip = data["hip_width_heads"] * head_height / 2
    center_x, center_y, base_z = origin

    landmarks = []
    for name, ratio in data["landmarks"].items():
        landmarks.append(
            {
                "name": name,
                "position": [center_x, center_y, base_z + height * ratio],
                "height_ratio": ratio,
            }
        )

    paired = []
    for name, ratio, half_width in (
        ("SHOULDER", data["landmarks"]["SHOULDER"], half_shoulder),
        ("PELVIS", data["landmarks"]["PELVIS"], half_hip),
        ("KNEE", data["landmarks"]["KNEE"], half_hip * 0.68),
        ("ANKLE", data["landmarks"]["ANKLE"], half_hip * 0.48),
    ):
        z = base_z + height * ratio
        paired.extend(
            [
                {
                    "name": f"{name}_L",
                    "position": [center_x - half_width, center_y, z],
                    "height_ratio": ratio,
                },
                {
                    "name": f"{name}_R",
                    "position": [center_x + half_width, center_y, z],
                    "height_ratio": ratio,
                },
            ]
        )

    return {
        "preset": preset,
        "height": height,
        "origin": list(origin),
        "head_units": data["head_units"],
        "head_height": head_height,
        "shoulder_width": half_shoulder * 2,
        "hip_width": half_hip * 2,
        "centerline_landmarks": landmarks,
        "paired_landmarks": paired,
        "coordinate_convention": "LOCAL_X_LEFT_RIGHT_Y_DEPTH_Z_UP",
        "guide_status": "REFERENCE_ONLY",
    }


@dataclass(frozen=True)
class ProportionGuide:
    preset: str
    height: float
    origin: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(data, {"preset", "height", "origin"})
        return cls(
            _preset(data["preset"]),
            number(data["height"], "height", 0.01, 1_000_000),
            vector3(data["origin"], "origin", 1_000_000),
        )


@dataclass(frozen=True)
class BlockoutPlan:
    preset: str
    height: float
    origin: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(data, {"preset", "height", "origin"})
        return cls(
            _preset(data["preset"]),
            number(data["height"], "height", 0.01, 1_000_000),
            vector3(data["origin"], "origin", 1_000_000),
        )


@dataclass(frozen=True)
class LandmarkFit:
    object_id: str
    preset: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "preset"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _preset(data["preset"]),
        )


class CharacterBlockoutOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.meshes = MeshOperations(objects)

    def proportions(self, request: Request, action: ProportionGuide):
        data = _guide(action.preset, action.height, action.origin)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def blockout(self, request: Request, action: BlockoutPlan):
        guide = _guide(action.preset, action.height, action.origin)
        head = guide["head_height"]
        shoulder = guide["shoulder_width"]
        hip = guide["hip_width"]
        ox, oy, oz = action.origin

        parts = [
            {
                "name": "HEAD",
                "shape": "ELLIPSOID",
                "center": [ox, oy, oz + action.height * 0.93],
                "dimensions": [head * 0.72, head * 0.82, head],
            },
            {
                "name": "TORSO",
                "shape": "CAPSULE",
                "center": [ox, oy, oz + action.height * 0.70],
                "dimensions": [shoulder, head * 0.72, action.height * 0.25],
            },
            {
                "name": "PELVIS",
                "shape": "ELLIPSOID",
                "center": [ox, oy, oz + action.height * 0.53],
                "dimensions": [hip, head * 0.78, action.height * 0.12],
            },
        ]
        for side, sign in (("L", -1), ("R", 1)):
            arm_x = ox + sign * shoulder * 0.62
            leg_x = ox + sign * hip * 0.28
            parts.extend(
                [
                    {
                        "name": f"UPPER_ARM_{side}",
                        "shape": "CAPSULE",
                        "center": [arm_x, oy, oz + action.height * 0.70],
                        "dimensions": [head * 0.34, head * 0.34, action.height * 0.18],
                    },
                    {
                        "name": f"FOREARM_{side}",
                        "shape": "CAPSULE",
                        "center": [arm_x, oy, oz + action.height * 0.52],
                        "dimensions": [head * 0.28, head * 0.28, action.height * 0.17],
                    },
                    {
                        "name": f"THIGH_{side}",
                        "shape": "CAPSULE",
                        "center": [leg_x, oy, oz + action.height * 0.40],
                        "dimensions": [head * 0.48, head * 0.48, action.height * 0.25],
                    },
                    {
                        "name": f"LOWER_LEG_{side}",
                        "shape": "CAPSULE",
                        "center": [leg_x, oy, oz + action.height * 0.16],
                        "dimensions": [head * 0.36, head * 0.36, action.height * 0.22],
                    },
                ]
            )

        data = {
            "preset": action.preset,
            "height": action.height,
            "origin": list(action.origin),
            "parts": parts,
            "part_count": len(parts),
            "symmetry_axis": "LOCAL_X",
            "guide": guide,
            "execution_status": "PLANNING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def fit_landmarks(self, request: Request, action: LandmarkFit):
        obj = self.inspector.resolve(action.object_id)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        geometry = self.meshes.snapshot(obj)
        vertices = geometry["vertices"]
        if len(vertices) > MAX_FIT_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Character landmark fit exceeds vertex limit")
        minimum, maximum = _bounds(vertices)
        height = maximum[2] - minimum[2]
        if height <= 0:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Character landmark fit requires nonzero Z height",
            )
        origin = (
            (minimum[0] + maximum[0]) / 2,
            (minimum[1] + maximum[1]) / 2,
            minimum[2],
        )
        guide = _guide(action.preset, height, origin)
        targets = guide["centerline_landmarks"] + guide["paired_landmarks"]
        fitted = []
        for landmark in targets:
            target = landmark["position"]
            index = min(
                range(len(vertices)),
                key=lambda item: (_distance(vertices[item], target), item),
            )
            distance = _distance(vertices[index], target)
            fitted.append(
                {
                    "name": landmark["name"],
                    "target_position": target,
                    "vertex_index": index,
                    "vertex_position": list(vertices[index]),
                    "distance": distance,
                    "normalized_distance": distance / height,
                }
            )
        data = {
            "object_id": geometry["object_id"],
            "name": geometry["name"],
            "geometry_revision": geometry["geometry_revision"],
            "preset": action.preset,
            "mesh_bounds_min": minimum,
            "mesh_bounds_max": maximum,
            "mesh_height": height,
            "landmark_count": len(fitted),
            "fitted_landmarks": fitted,
            "fit_status": "CANDIDATE_MAPPING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "character.proportion_guide",
                SafetyClass.READ_ONLY,
                ProportionGuide.parse,
                self.proportions,
            ),
            Tool(
                "character.blockout_plan",
                SafetyClass.READ_ONLY,
                BlockoutPlan.parse,
                self.blockout,
            ),
            Tool(
                "character.landmark_fit",
                SafetyClass.READ_ONLY,
                LandmarkFit.parse,
                self.fit_landmarks,
            ),
        ]
