"""Level 8 M4: bounded 5-key perspective camera rail from cubic Bézier handles."""

from dataclasses import dataclass
from math import cos, sin

from .cinematic_motion import CameraMotionOperations
from .cinematic_shots import ShotPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_OFFSET = 0.25
SAMPLES = (0.0, 0.25, 0.5, 0.75, 1.0)


def _offset(value, label):
    if type(value) is not list or len(value) != 2:
        raise invalid(f"{label} must be a 2D numeric list")
    return (
        number(value[0], f"{label}.x", -MAX_OFFSET, MAX_OFFSET),
        number(value[1], f"{label}.y", -MAX_OFFSET, MAX_OFFSET),
    )


@dataclass(frozen=True)
class RailPreview:
    camera: ObjectTarget
    subject: ObjectTarget
    start_frame: int
    end_frame: int
    azimuth_degrees: float
    elevation_degrees: float
    margin: float
    control_a: tuple[float, float]
    control_b: tuple[float, float]
    end_offset: tuple[float, float]
    make_active: bool

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
            },
        )
        start = integer(data["start_frame"], "start_frame", 1, 99_992)
        end = integer(data["end_frame"], "end_frame", 1, 100_000)
        if not 8 <= end - start <= 720:
            raise invalid("Camera rail duration must be 8..720 frames")
        points = (
            _offset(data["control_a"], "control_a"),
            _offset(data["control_b"], "control_b"),
            _offset(data["end_offset"], "end_offset"),
        )
        if all(max(abs(v) for v in point) < 0.0001 for point in points):
            raise invalid("Camera rail needs nonzero control or end displacement")
        if type(data["make_active"]) is not bool:
            raise invalid("make_active must be boolean")
        return cls(
            ObjectTarget.parse(data["camera"]),
            ObjectTarget.parse(data["subject"]),
            start,
            end,
            number(data["azimuth_degrees"], "azimuth_degrees", -180, 180),
            number(data["elevation_degrees"], "elevation_degrees", -75, 75),
            number(data["margin"], "margin", 1.05, 2.5),
            *points,
            data["make_active"],
        )


@dataclass(frozen=True)
class RailApply:
    preview: RailPreview
    expected_rail_revision: str

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
                "expected_rail_revision",
            },
        )
        return cls(
            RailPreview.parse(
                {key: val for key, val in data.items() if key != "expected_rail_revision"}
            ),
            string(data["expected_rail_revision"], "expected_rail_revision", limit=64),
        )


class CameraRailOperations:
    """One origin-centered five-key camera rail; no generic rig/operator execution."""

    def __init__(self, objects: ObjectOperations):
        self.motion = CameraMotionOperations(objects)
        self.shots = self.motion.shots

    @staticmethod
    def _bezier(control_a, control_b, end_offset, t):
        other = 1 - t
        return [
            3 * other * other * t * control_a[i]
            + 3 * other * t * t * control_b[i]
            + t * t * t * end_offset[i]
            for i in range(2)
        ]

    def _plan(self, action: RailPreview):
        shot = ShotPreview(
            action.camera,
            action.subject,
            action.azimuth_degrees,
            action.elevation_degrees,
            action.margin,
            action.make_active,
        )
        camera, subject, camera_before, subject_before, base = self.shots._plan(shot)
        pitch, _, yaw = base["camera_rotation_euler"]
        right = [cos(yaw), sin(yaw), 0.0]
        up = [-sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch)]
        horizontal_tan = base["sensor_width_mm"] / (2 * base["lens_mm"])
        vertical_tan = horizontal_tan / base["render_aspect"]
        radius = base["subject_enclosing_radius"]
        padded = radius * action.margin
        outer_x = max(
            abs(point[0]) for point in (action.control_a, action.control_b, action.end_offset)
        )
        outer_y = max(
            abs(point[1]) for point in (action.control_a, action.control_b, action.end_offset)
        )
        distance = max(
            base["camera_distance"],
            (padded + radius * horizontal_tan) / (horizontal_tan * (1 - 2 * outer_x)),
            (padded + radius * vertical_tan) / (vertical_tan * (1 - 2 * outer_y)),
        )
        center = base["subject_center"]
        backwards = [
            (base["camera_location"][i] - center[i]) / base["camera_distance"] for i in range(3)
        ]
        frames = [
            action.start_frame + round((action.end_frame - action.start_frame) * t)
            for t in SAMPLES
        ]
        poses = []
        for frame, t in zip(frames, SAMPLES, strict=True):
            x, y = self._bezier(action.control_a, action.control_b, action.end_offset, t)
            location = [
                center[i]
                + backwards[i] * distance
                + right[i] * 2 * horizontal_tan * distance * x
                + up[i] * 2 * vertical_tan * distance * y
                for i in range(3)
            ]
            poses.append(
                {
                    "frame": frame,
                    "location": location,
                    "rotation_euler": list(base["camera_rotation_euler"]),
                    "distance": distance,
                    "subject_screen_prediction": {"x": 0.5 - x, "y": 0.5 - y},
                }
            )
        blockers = set(base["blockers"])
        if camera.animation_data is not None:
            blockers.add("EXISTING_CAMERA_ACTION_CANNOT_BE_ADOPTED")
        if getattr(camera.data, "shift_x", 0) != 0 or getattr(camera.data, "shift_y", 0) != 0:
            blockers.add("NONZERO_CAMERA_LENS_SHIFT")
        if distance - padded <= base["clip_start"] or distance + padded >= base["clip_end"]:
            blockers.add("CAMERA_RAIL_EXCEEDS_CLIPPING")
        if distance > 1_000_000 or any(
            abs(coord) > 1_000_000 for pose in poses for coord in pose["location"]
        ):
            blockers.add("CAMERA_RAIL_EXCEEDS_COORDINATE_BOUNDS")
        plan = {
            "camera_id": camera_before["object_id"],
            "subject_id": subject_before["object_id"],
            "camera_object_revision": camera_before["revision"],
            "subject_object_revision": subject_before["revision"],
            "base_shot_revision": base["plan_revision"],
            "start_frame": action.start_frame,
            "end_frame": action.end_frame,
            "control_a": list(action.control_a),
            "control_b": list(action.control_b),
            "end_offset": list(action.end_offset),
            "curve": "CUBIC_BEZIER_CAMERA_IMAGE_PLANE",
            "sample_parameters": list(SAMPLES),
            "interpolation": "LINEAR",
            "camera_lens": base["lens_mm"],
            "render_aspect": base["render_aspect"],
            "make_active": action.make_active,
            "key_poses": poses,
            "channel_count": 6,
            "keyframe_count": 30,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "scope": "FIVE_MANAGED_CAMERA_RAIL_POSES_SOURCE_ONLY",
            "evaluated_motion_verified": False,
            "real_runtime_verified": False,
            "mutation_performed": False,
        }
        plan["motion_revision"] = revision(plan)
        plan["rail_revision"] = plan["motion_revision"]
        return camera, subject, camera_before, subject_before, plan

    def preview(self, request: Request, action: RailPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[4]
        )

    def apply(self, request: Request, action: RailApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if plan["rail_revision"] != action.expected_rail_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera rail changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe camera rail or occupied Action")
        return self.motion._commit_poses(
            request, camera, subject, before, subject_before, plan, action.preview.make_active
        )

    def tools(self):
        return [
            Tool("cinema.rail_preview", SafetyClass.READ_ONLY, RailPreview.parse, self.preview),
            Tool("cinema.rail_apply", SafetyClass.MUTATION, RailApply.parse, self.apply),
        ]
