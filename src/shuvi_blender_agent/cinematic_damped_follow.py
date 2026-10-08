"""Level 8 M8: bounded time-damped camera follow baked from LINEAR subject keys."""

from dataclasses import dataclass
from math import atan2, cos, hypot, pi, sin, sqrt

from .animation_state import action_curves
from .cinematic_motion import CameraMotionOperations
from .cinematic_shots import ShotPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number, string

MAX_SAMPLES = 24
PATH = "location"
EPSILON = 1e-4


@dataclass(frozen=True)
class DampedFollowPreview:
    camera: ObjectTarget
    subject: ObjectTarget
    azimuth_degrees: float
    elevation_degrees: float
    margin: float
    damping_alpha: float
    make_active: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera",
                "subject",
                "azimuth_degrees",
                "elevation_degrees",
                "margin",
                "damping_alpha",
                "make_active",
            },
        )
        if type(data["make_active"]) is not bool:
            raise invalid("make_active must be boolean")
        return cls(
            ObjectTarget.parse(data["camera"]),
            ObjectTarget.parse(data["subject"]),
            number(data["azimuth_degrees"], "azimuth_degrees", -180, 180),
            number(data["elevation_degrees"], "elevation_degrees", -75, 75),
            number(data["margin"], "margin", 1.05, 2.5),
            number(data["damping_alpha"], "damping_alpha", 0.1, 0.9),
            data["make_active"],
        )


@dataclass(frozen=True)
class DampedFollowApply:
    preview: DampedFollowPreview
    expected_damped_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera",
                "subject",
                "azimuth_degrees",
                "elevation_degrees",
                "margin",
                "damping_alpha",
                "make_active",
                "expected_damped_revision",
            },
        )
        return cls(
            DampedFollowPreview.parse(
                {key: val for key, val in data.items() if key != "expected_damped_revision"}
            ),
            string(data["expected_damped_revision"], "expected_damped_revision", limit=64),
        )


class CameraDampedFollowOperations:
    """Bake camera location/rotation keys; does not claim live evaluated chasing."""

    def __init__(self, objects: ObjectOperations):
        self.motion = CameraMotionOperations(objects)
        self.shots = self.motion.shots
        self.bpy = objects.bpy

    def _subject_samples(self, subject):
        """Consume only exact legacy object location XYZ LINEAR keyframe triplets."""
        ad = subject.animation_data
        if (
            ad is None
            or ad.action is None
            or getattr(ad, "action_slot", None) is not None
            or len(getattr(ad, "nla_tracks", ())) != 0
            or len(getattr(ad, "drivers", ())) != 0
            or getattr(subject.data, "shape_keys", None) is not None
            and getattr(subject.data.shape_keys, "animation_data", None) is not None
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Damped follow requires one legacy subject Action without NLA/drivers",
            )
        if subject.parent is not None or len(subject.constraints):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Parented or constrained target unsupported")
        if subject.rotation_mode != "XYZ" or any(abs(v) > 1e-5 for v in subject.rotation_euler):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subject must have zero Euler rotation")
        if any(abs(v - 1) > 1e-5 for v in subject.scale):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subject must have unit scale")
        if getattr(ad.action, "users", 0) != 1:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shared subject Actions unsupported")
        curves = action_curves(subject)
        if len(curves) != 3 or {
            (curve.data_path, curve.array_index) for curve in curves
        } != {(PATH, index) for index in range(3)}:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Target Action must contain only location XYZ channels"
            )
        channels = sorted(curves, key=lambda curve: curve.array_index)
        count = len(channels[0].keyframe_points)
        if not 5 <= count <= MAX_SAMPLES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Target needs 5..24 LINEAR location keys")
        frames = None
        values = []
        for curve in channels:
            if len(curve.keyframe_points) != count:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Unequal location channel lengths")
            rows = []
            for point in curve.keyframe_points:
                if point.interpolation != "LINEAR":
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Only LINEAR target keys supported")
                frame = number(point.co[0], "target frame", 1, 100_000)
                value = number(point.co[1], "target position", -100_000, 100_000)
                if not frame.is_integer():
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Subframe targets not supported")
                rows.append((int(frame), value))
            channel_frames = [item[0] for item in rows]
            if any(a >= b or b - a > 60 for a, b in zip(
                channel_frames, channel_frames[1:], strict=False
            )):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED, "Target frames must increase with gap <=60"
                )
            if frames is not None and channel_frames != frames:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Location channel frames differ")
            frames = channel_frames
            values.append([item[1] for item in rows])
        if self.bpy.context.scene.frame_current != frames[0]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene must be at subject first keyframe")
        if any(abs(subject.location[i] - values[i][0]) > EPSILON for i in range(3)):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Current target pose differs from first Action key"
            )
        return [
            {"frame": frames[index], "location": [values[i][index] for i in range(3)]}
            for index in range(count)
        ]

    def _plan(self, action: DampedFollowPreview):
        shot = ShotPreview(
            action.camera,
            action.subject,
            action.azimuth_degrees,
            action.elevation_degrees,
            action.margin,
            action.make_active,
        )
        camera, subject, before, subject_before, base = self.shots._plan(shot)
        samples = self._subject_samples(subject)
        first_subject = samples[0]["location"]
        offset = [base["camera_location"][i] - first_subject[i] for i in range(3)]
        smoothed = list(first_subject)
        previous_frame = samples[0]["frame"]
        previous_yaw = None
        poses = []
        blockers = set(base["blockers"])
        for item in samples:
            dt = item["frame"] - previous_frame
            effective_alpha = 1 - (1 - action.damping_alpha) ** dt if dt else 1.0
            smoothed = [
                smoothed[i] + effective_alpha * (item["location"][i] - smoothed[i])
                for i in range(3)
            ]
            location = [smoothed[i] + offset[i] for i in range(3)]
            delta = [location[i] - item["location"][i] for i in range(3)]
            distance = sqrt(sum(component * component for component in delta))
            if distance < EPSILON:
                blockers.add("CAMERA_OVERLAPS_SUBJECT")
                distance = EPSILON
            yaw = atan2(delta[1], delta[0]) + pi / 2
            if previous_yaw is not None:
                while yaw - previous_yaw > pi:
                    yaw -= 2 * pi
                while yaw - previous_yaw < -pi:
                    yaw += 2 * pi
            previous_yaw = yaw
            pitch = pi / 2 - atan2(delta[2], hypot(delta[0], delta[1]))
            if distance - base["subject_enclosing_radius"] * action.margin <= base["clip_start"]:
                blockers.add("SUBJECT_NEAR_CLIP_OR_INTERSECTION")
            if distance + base["subject_enclosing_radius"] * action.margin >= base["clip_end"]:
                blockers.add("SUBJECT_FAR_CLIP")
            if distance < base["camera_distance"] - EPSILON:
                blockers.add("MOVEMENT_EXCEEDS_INITIAL_FRAMING")
            if any(abs(coord) > 1_000_000 for coord in location):
                blockers.add("CAMERA_COORDINATES_TOO_LARGE")
            poses.append(
                {
                    "frame": item["frame"],
                    "location": location,
                    "rotation_euler": [pitch, 0.0, yaw],
                    "target_location": item["location"],
                    "lagged_target_location": list(smoothed),
                    "effective_alpha": effective_alpha,
                    "camera_distance": distance,
                }
            )
            previous_frame = item["frame"]

        plan = {
            "camera_id": before["object_id"],
            "subject_id": subject_before["object_id"],
            "camera_object_revision": before["revision"],
            "subject_object_revision": subject_before["revision"],
            "base_shot_revision": base["plan_revision"],
            "damping_alpha": action.damping_alpha,
            "model": "EXPONENTIAL_MOVING_AVERAGE_DELTA_TIME_NORMALIZED",
            "target_samples": samples,
            "camera_offset": offset,
            "sample_count": len(samples),
            "interpolation": "LINEAR",
            "key_poses": poses,
            "keyframe_count": len(poses) * 6,
            "camera_lens": base["lens_mm"],
            "make_active": action.make_active,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "scope": "M8_BOUNDED_BAKED_DAMPED_FOLLOW",
            "source_only": True,
            "evaluated_playback_verified": False,
            "real_runtime_verified": False,
            "mutation_performed": False,
        }
        plan["motion_revision"] = revision(plan)
        plan["damped_revision"] = plan["motion_revision"]
        return camera, subject, before, subject_before, plan

    def preview(self, request: Request, action: DampedFollowPreview):
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[4])

    def apply(self, request: Request, action: DampedFollowApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if plan["damped_revision"] != action.expected_damped_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Damped camera plan changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe smoothed camera path")
        return self.motion._commit_poses(
            request, camera, subject, before, subject_before, plan, action.preview.make_active
        )

    def tools(self):
        return [
            Tool(
                "cinema.damped_preview",
                SafetyClass.READ_ONLY,
                DampedFollowPreview.parse,
                self.preview,
            ),
            Tool(
                "cinema.damped_apply",
                SafetyClass.MUTATION,
                DampedFollowApply.parse,
                self.apply,
            ),
        ]
