"""Level 8 M5: real bounded BEZIER camera keyframe handles with temporal easing."""

from dataclasses import dataclass
from math import cos, sin

from .cinematic_rail import CameraRailOperations, RailPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string

STYLES = ("EASE_IN", "EASE_OUT", "EASE_IN_OUT")
PATHS = ("location", "rotation_euler")


@dataclass(frozen=True)
class EasingPreview:
    rail: RailPreview
    style: str
    strength: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera",
                "subject",
                "start_frame",
                "end_frame",
                "azimuth_degrees",
                "elevation_degrees",
                "margin",
                "control_a",
                "control_b",
                "end_offset",
                "make_active",
                "style",
                "strength",
            },
        )
        style = string(data["style"], "style", limit=32)
        if style not in STYLES:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unsupported camera easing style")
        return cls(
            RailPreview.parse(
                {key: value for key, value in data.items() if key not in ("style", "strength")}
            ),
            style,
            number(data["strength"], "strength", 0.25, 1.0),
        )


@dataclass(frozen=True)
class EasingApply:
    preview: EasingPreview
    expected_easing_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera",
                "subject",
                "start_frame",
                "end_frame",
                "azimuth_degrees",
                "elevation_degrees",
                "margin",
                "control_a",
                "control_b",
                "end_offset",
                "make_active",
                "style",
                "strength",
                "expected_easing_revision",
            },
        )
        return cls(
            EasingPreview.parse(
                {key: value for key, value in data.items() if key != "expected_easing_revision"}
            ),
            string(data["expected_easing_revision"], "expected_easing_revision", limit=64),
        )


class CameraEasingOperations:
    """Sample eased cubic rail and author explicit FCurve BEZIER FREE handles."""

    def __init__(self, objects: ObjectOperations):
        self.rail = CameraRailOperations(objects)

    @staticmethod
    def _timing(t, style, strength):
        if style == "EASE_IN":
            eased, derivative = t * t, 2 * t
        elif style == "EASE_OUT":
            eased, derivative = 2 * t - t * t, 2 - 2 * t
        else:
            eased, derivative = 3 * t * t - 2 * t * t * t, 6 * t * (1 - t)
        return (1 - strength) * t + strength * eased, (1 - strength) + strength * derivative

    @staticmethod
    def _curve_tangent(a, b, end, t):
        return [
            3 * (1 - t) ** 2 * a[i]
            + 6 * (1 - t) * t * (b[i] - a[i])
            + 3 * t * t * (end[i] - b[i])
            for i in range(2)
        ]

    def _plan(self, action: EasingPreview):
        camera, subject, before, subject_before, base = self.rail._plan(action.rail)
        first = base["key_poses"][0]
        distance = first["distance"]
        pitch, _, yaw = first["rotation_euler"]
        right = [cos(yaw), sin(yaw), 0.0]
        up = [-sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch)]
        hx = camera.data.sensor_width / (2 * camera.data.lens)
        hy = hx / base["render_aspect"]
        frame_span = action.rail.end_frame - action.rail.start_frame
        positions = []
        for t, prior in zip(base["sample_parameters"], base["key_poses"], strict=True):
            u, speed = self._timing(t, action.style, action.strength)
            x, y = self.rail._bezier(
                action.rail.control_a, action.rail.control_b, action.rail.end_offset, u
            )
            dx, dy = self._curve_tangent(
                action.rail.control_a, action.rail.control_b, action.rail.end_offset, u
            )
            location = [
                first["location"][i] + distance * 2 * (
                    right[i] * hx * x + up[i] * hy * y
                )
                for i in range(3)
            ]
            slopes = [
                distance * 2 * (right[i] * hx * dx + up[i] * hy * dy)
                * speed / frame_span
                for i in range(3)
            ]
            positions.append(
                {
                    "frame": prior["frame"],
                    "location": location,
                    "rotation_euler": list(first["rotation_euler"]),
                    "distance": distance,
                    "subject_screen_prediction": {"x": 0.5 - x, "y": 0.5 - y},
                    "path_parameter": u,
                    "normalized_speed": speed,
                    "_slopes": slopes,
                }
            )

        frames = [pose["frame"] for pose in positions]
        for index, pose in enumerate(positions):
            left_span = (frames[index] - frames[index - 1]) / 3 if index else 0.0
            right_span = (frames[index + 1] - frames[index]) / 3 if index < 4 else 0.0
            handles = {}
            for path in PATHS:
                handles[path] = []
                for axis, value in enumerate(pose[path]):
                    slope = pose["_slopes"][axis] if path == "location" else 0.0
                    handles[path].append(
                        {
                            "left": [float(pose["frame"] - left_span), value - slope * left_span],
                            "right": [
                                float(pose["frame"] + right_span),
                                value + slope * right_span,
                            ],
                        }
                    )
            pose["key_handles"] = handles
            del pose["_slopes"]

        plan = dict(base)
        plan.pop("motion_revision")
        plan.pop("rail_revision")
        plan.update(
            {
                "base_rail_revision": base["rail_revision"],
                "style": action.style,
                "strength": action.strength,
                "key_poses": positions,
                "interpolation": "BEZIER",
                "handle_type": "FREE",
                "scope": "FIVE_POSE_EASED_CAMERA_RAIL_SOURCE_ONLY",
                "keyframe_count": 30,
                "evaluated_motion_verified": False,
                "mutation_performed": False,
            }
        )
        # Handles are bounded inside the current range for normal points; only
        # endpoint handles are pinned at the endpoints (no unbounded extrapolation).
        plan["easing_revision"] = revision(plan)
        plan["motion_revision"] = plan["easing_revision"]
        return camera, subject, before, subject_before, plan

    def preview(self, request: Request, action: EasingPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[4]
        )

    def apply(self, request: Request, action: EasingApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if plan["easing_revision"] != action.expected_easing_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera easing changed since preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera easing has unsafe rail blockers")
        return self.rail.motion._commit_poses(
            request, camera, subject, before, subject_before, plan, action.preview.rail.make_active
        )

    def tools(self):
        return [
            Tool("cinema.easing_preview", SafetyClass.READ_ONLY, EasingPreview.parse, self.preview),
            Tool("cinema.easing_apply", SafetyClass.MUTATION, EasingApply.parse, self.apply),
        ]
