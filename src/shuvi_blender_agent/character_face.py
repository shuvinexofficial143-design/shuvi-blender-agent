"""Level 3 milestone 7: bounded head/face character guides and landmark workflows."""

from dataclasses import dataclass
from math import sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .mesh import MeshOperations
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number, string

FRONT_DIRECTIONS = ("POSITIVE_Y", "NEGATIVE_Y")
MAX_FACE_FIT_VERTICES = 4096

_FACE_TEMPLATE = {
    "BROW_L": (-0.20, 0.82),
    "BROW_R": (0.20, 0.82),
    "EYE_L": (-0.20, 0.70),
    "EYE_R": (0.20, 0.70),
    "NOSE_BRIDGE": (0.00, 0.63),
    "NOSE_TIP": (0.00, 0.51),
    "MOUTH_L": (-0.16, 0.34),
    "MOUTH_R": (0.16, 0.34),
    "PHILTRUM": (0.00, 0.40),
    "CHIN": (0.00, 0.12),
    "JAW_L": (-0.34, 0.20),
    "JAW_R": (0.34, 0.20),
    "EAR_L": (-0.47, 0.56),
    "EAR_R": (0.47, 0.56),
}

_CENTERLINE = ("NOSE_BRIDGE", "NOSE_TIP", "PHILTRUM", "CHIN")
_PAIRS = (
    ("BROW_L", "BROW_R"),
    ("EYE_L", "EYE_R"),
    ("MOUTH_L", "MOUTH_R"),
    ("JAW_L", "JAW_R"),
    ("EAR_L", "EAR_R"),
)


def _front(value):
    if not isinstance(value, str) or value not in FRONT_DIRECTIONS:
        raise invalid("front_direction must be POSITIVE_Y or NEGATIVE_Y")
    return value


def _distance(a, b):
    return sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))


def _bounds(vertices):
    if not vertices:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Face workflow requires mesh vertices")
    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return minimum, maximum


def _face_guide(vertices, front_direction):
    minimum, maximum = _bounds(vertices)
    width = maximum[0] - minimum[0]
    depth = maximum[1] - minimum[1]
    height = maximum[2] - minimum[2]
    if min(width, depth, height) <= 0:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            "Face guide requires nonzero X/Y/Z head bounds",
        )
    center_x = (minimum[0] + maximum[0]) / 2
    front_y = maximum[1] if front_direction == "POSITIVE_Y" else minimum[1]
    direction_sign = 1 if front_direction == "POSITIVE_Y" else -1
    inset = depth * 0.04
    surface_y = front_y - direction_sign * inset

    landmarks = []
    for name, (x_ratio, z_ratio) in _FACE_TEMPLATE.items():
        landmarks.append(
            {
                "name": name,
                "position": [
                    center_x + width * x_ratio,
                    surface_y,
                    minimum[2] + height * z_ratio,
                ],
                "x_ratio": x_ratio,
                "z_ratio": z_ratio,
            }
        )
    return {
        "bounds_min": minimum,
        "bounds_max": maximum,
        "width": width,
        "depth": depth,
        "height": height,
        "front_direction": front_direction,
        "surface_y": surface_y,
        "landmarks": landmarks,
        "landmark_count": len(landmarks),
        "centerline_names": list(_CENTERLINE),
        "symmetry_pairs": [list(pair) for pair in _PAIRS],
        "coordinate_convention": "LOCAL_X_LEFT_RIGHT_Y_DEPTH_Z_UP",
        "guide_status": "REFERENCE_ONLY",
    }


def _fit(vertices, guide):
    fitted = {}
    for landmark in guide["landmarks"]:
        target = landmark["position"]
        index = min(
            range(len(vertices)),
            key=lambda item: (_distance(vertices[item], target), item),
        )
        fitted[landmark["name"]] = {
            "name": landmark["name"],
            "target_position": target,
            "vertex_index": index,
            "vertex_position": list(vertices[index]),
            "distance": _distance(vertices[index], target),
        }
    return fitted


@dataclass(frozen=True)
class FaceGuide:
    object_id: str
    front_direction: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "front_direction"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _front(data["front_direction"]),
        )


@dataclass(frozen=True)
class FaceFit:
    object_id: str
    front_direction: str
    max_normalized_distance: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "front_direction", "max_normalized_distance"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _front(data["front_direction"]),
            number(
                data["max_normalized_distance"],
                "max_normalized_distance",
                0.001,
                2.0,
            ),
        )


@dataclass(frozen=True)
class FaceRegions:
    object_id: str
    front_direction: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "front_direction"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _front(data["front_direction"]),
        )


@dataclass(frozen=True)
class FaceSymmetryAudit:
    object_id: str
    front_direction: str
    tolerance: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "front_direction", "tolerance"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _front(data["front_direction"]),
            number(data["tolerance"], "tolerance", 1e-6, 1.0),
        )


class CharacterFaceOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.meshes = MeshOperations(objects)

    def _geometry(self, object_id):
        obj = self.inspector.resolve(object_id)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        geometry = self.meshes.snapshot(obj)
        if len(geometry["vertices"]) > MAX_FACE_FIT_VERTICES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Face workflow exceeds vertex fit limit")
        return obj, geometry

    def guide(self, request: Request, action: FaceGuide):
        obj, geometry = self._geometry(action.object_id)
        guide = _face_guide(geometry["vertices"], action.front_direction)
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            **guide,
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def fit(self, request: Request, action: FaceFit):
        obj, geometry = self._geometry(action.object_id)
        guide = _face_guide(geometry["vertices"], action.front_direction)
        fitted = _fit(geometry["vertices"], guide)
        scale = max(guide["width"], guide["height"])
        items = []
        rejected = []
        for name in _FACE_TEMPLATE:
            item = dict(fitted[name])
            item["normalized_distance"] = item["distance"] / scale
            item["within_limit"] = item["normalized_distance"] <= action.max_normalized_distance
            items.append(item)
            if not item["within_limit"]:
                rejected.append(name)
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "front_direction": action.front_direction,
            "max_normalized_distance": action.max_normalized_distance,
            "fitted_landmarks": items,
            "landmark_count": len(items),
            "rejected_landmarks": rejected,
            "rejected_count": len(rejected),
            "fit_status": "REVIEW" if rejected else "CANDIDATE_MAPPING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def regions(self, request: Request, action: FaceRegions):
        obj, geometry = self._geometry(action.object_id)
        guide = _face_guide(geometry["vertices"], action.front_direction)
        by_name = {item["name"]: item["position"] for item in guide["landmarks"]}
        width = guide["width"]
        height = guide["height"]
        regions = [
            {
                "name": "LEFT_EYE_SOCKET",
                "center": by_name["EYE_L"],
                "radius": min(width * 0.16, height * 0.11),
            },
            {
                "name": "RIGHT_EYE_SOCKET",
                "center": by_name["EYE_R"],
                "radius": min(width * 0.16, height * 0.11),
            },
            {
                "name": "NOSE",
                "center": by_name["NOSE_TIP"],
                "radius": min(width * 0.14, height * 0.14),
            },
            {
                "name": "MOUTH",
                "center": [
                    (by_name["MOUTH_L"][axis] + by_name["MOUTH_R"][axis]) / 2
                    for axis in range(3)
                ],
                "radius": min(width * 0.22, height * 0.12),
            },
            {
                "name": "CHIN_JAW",
                "center": by_name["CHIN"],
                "radius": min(width * 0.30, height * 0.17),
            },
            {
                "name": "BROW",
                "center": [
                    (by_name["BROW_L"][axis] + by_name["BROW_R"][axis]) / 2
                    for axis in range(3)
                ],
                "radius": min(width * 0.28, height * 0.12),
            },
        ]
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "front_direction": action.front_direction,
            "regions": regions,
            "region_count": len(regions),
            "purpose": "SCULPT_BRUSH_PLANNING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def symmetry(self, request: Request, action: FaceSymmetryAudit):
        obj, geometry = self._geometry(action.object_id)
        guide = _face_guide(geometry["vertices"], action.front_direction)
        fitted = _fit(geometry["vertices"], guide)
        center_x = (guide["bounds_min"][0] + guide["bounds_max"][0]) / 2
        width = guide["width"]

        pair_results = []
        violations = []
        for left_name, right_name in _PAIRS:
            left = fitted[left_name]["vertex_position"]
            right = fitted[right_name]["vertex_position"]
            mirrored_x_error = abs((left[0] - center_x) + (right[0] - center_x)) / width
            yz_error = sqrt((left[1] - right[1]) ** 2 + (left[2] - right[2]) ** 2) / width
            score = max(mirrored_x_error, yz_error)
            item = {
                "left": left_name,
                "right": right_name,
                "mirrored_x_error": mirrored_x_error,
                "yz_error": yz_error,
                "score": score,
                "within_tolerance": score <= action.tolerance,
            }
            pair_results.append(item)
            if not item["within_tolerance"]:
                violations.append(f"{left_name}:{right_name}")

        centerline_results = []
        for name in _CENTERLINE:
            position = fitted[name]["vertex_position"]
            error = abs(position[0] - center_x) / width
            item = {
                "name": name,
                "centerline_x_error": error,
                "within_tolerance": error <= action.tolerance,
            }
            centerline_results.append(item)
            if not item["within_tolerance"]:
                violations.append(name)

        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "geometry_revision": geometry["geometry_revision"],
            "front_direction": action.front_direction,
            "tolerance": action.tolerance,
            "pair_results": pair_results,
            "centerline_results": centerline_results,
            "violations": violations,
            "violation_count": len(violations),
            "symmetry_status": "PASS" if not violations else "REVIEW",
            "audit_status": "CANDIDATE_VERTEX_AUDIT_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "character.face_guide",
                SafetyClass.READ_ONLY,
                FaceGuide.parse,
                self.guide,
            ),
            Tool(
                "character.face_landmark_fit",
                SafetyClass.READ_ONLY,
                FaceFit.parse,
                self.fit,
            ),
            Tool(
                "character.face_region_plan",
                SafetyClass.READ_ONLY,
                FaceRegions.parse,
                self.regions,
            ),
            Tool(
                "character.face_symmetry_audit",
                SafetyClass.READ_ONLY,
                FaceSymmetryAudit.parse,
                self.symmetry,
            ),
        ]
