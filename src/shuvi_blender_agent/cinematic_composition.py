"""Level 8 M2: typed rule-of-thirds camera composition with real pose changes."""

from dataclasses import dataclass
from math import cos, sin

from .cinematic_shots import CinematicShotOperations, ShotPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string

# Coordinates are normalized within the image, with (0, 0) at bottom left.
ANCHORS = {
    "CENTER": (0.5, 0.5),
    "LEFT_THIRD": (1 / 3, 0.5),
    "RIGHT_THIRD": (2 / 3, 0.5),
    "TOP_THIRD": (0.5, 2 / 3),
    "BOTTOM_THIRD": (0.5, 1 / 3),
    "UPPER_LEFT_THIRD": (1 / 3, 2 / 3),
    "UPPER_RIGHT_THIRD": (2 / 3, 2 / 3),
    "LOWER_LEFT_THIRD": (1 / 3, 1 / 3),
    "LOWER_RIGHT_THIRD": (2 / 3, 1 / 3),
}


@dataclass(frozen=True)
class CompositionPreview:
    shot: ShotPreview
    anchor: str

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
                "make_active",
                "anchor",
            },
        )
        anchor = string(data["anchor"], "anchor", limit=32)
        if anchor not in ANCHORS:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unknown camera composition anchor")
        return cls(
            ShotPreview.parse({key: value for key, value in data.items() if key != "anchor"}),
            anchor,
        )


@dataclass(frozen=True)
class CompositionApply:
    preview: CompositionPreview
    expected_composition_revision: str

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
                "make_active",
                "anchor",
                "expected_composition_revision",
            },
        )
        return cls(
            CompositionPreview.parse(
                {
                    key: value
                    for key, value in data.items()
                    if key != "expected_composition_revision"
                }
            ),
            string(
                data["expected_composition_revision"], "expected_composition_revision", limit=64
            ),
        )


class CinematicCompositionOperations:
    """Offset a camera laterally in its image plane without changing look direction."""

    def __init__(self, objects: ObjectOperations):
        self.shots = CinematicShotOperations(objects)

    def _plan(self, action: CompositionPreview):
        camera, subject, camera_before, subject_before, original = self.shots._plan(action.shot)
        target_x, target_y = ANCHORS[action.anchor]
        position_x = 2 * target_x - 1
        position_y = 2 * target_y - 1
        radius = original["subject_enclosing_radius"]
        padded = radius * action.shot.margin
        half_horizontal_tan = original["sensor_width_mm"] / (2 * original["lens_mm"])
        half_vertical_tan = half_horizontal_tan / original["render_aspect"]
        distance = max(
            original["camera_distance"],
            (padded + radius * half_horizontal_tan) / (half_horizontal_tan * (1 - abs(position_x))),
            (padded + radius * half_vertical_tan) / (half_vertical_tan * (1 - abs(position_y))),
        )
        pitch, _, yaw = original["camera_rotation_euler"]
        right = [cos(yaw), sin(yaw), 0.0]
        up = [-sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch)]
        center = original["subject_center"]
        original_distance = original["camera_distance"]
        direction = [
            (original["camera_location"][i] - center[i]) / original_distance for i in range(3)
        ]
        offset_right = distance * position_x * half_horizontal_tan
        offset_up = distance * position_y * half_vertical_tan
        location = [
            center[i] + direction[i] * distance - right[i] * offset_right - up[i] * offset_up
            for i in range(3)
        ]
        blockers = list(original["blockers"])
        if (
            abs(float(getattr(camera.data, "shift_x", 0))) > 1e-8
            or abs(float(getattr(camera.data, "shift_y", 0))) > 1e-8
        ):
            blockers.append("LENS_SHIFT_NOT_SUPPORTED")
        if distance > 1_000_000 or any(abs(value) > 1_000_000 for value in location):
            blockers.append("CAMERA_POSE_EXCEEDS_COORDINATE_BOUNDS")
        if distance - padded <= original["clip_start"] or distance + padded >= original["clip_end"]:
            blockers.append("SUBJECT_OUTSIDE_CAMERA_CLIP")

        plan = dict(original)
        plan.pop("plan_revision")
        plan.update(
            {
                "base_shot_plan_revision": original["plan_revision"],
                "composition_anchor": action.anchor,
                "subject_screen_target": {"x": target_x, "y": target_y},
                "composition_coordinate_origin": "BOTTOM_LEFT",
                "camera_location": location,
                "camera_distance": distance,
                "camera_right_offset": offset_right,
                "camera_up_offset": offset_up,
                "horizontal_half_tangent": half_horizontal_tan,
                "vertical_half_tangent": half_vertical_tan,
                "blockers": sorted(set(blockers)),
                "ready": not blockers,
                "framing_assumption": "ORIGIN_CENTERED_WORLD_AXIS_ALIGNED_BOUNDING_SPHERE",
                "mutation_performed": False,
            }
        )
        plan["composition_revision"] = revision(plan)
        plan["plan_revision"] = plan["composition_revision"]
        return camera, subject, camera_before, subject_before, plan

    def preview(self, request: Request, action: CompositionPreview):
        _, _, _, _, plan = self._plan(action)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request: Request, action: CompositionApply):
        camera, subject, camera_before, subject_before, plan = self._plan(action.preview)
        if plan["composition_revision"] != action.expected_composition_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera composition changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera composition has safety blockers")
        return self.shots._apply_pose(
            request,
            camera,
            subject,
            camera_before,
            subject_before,
            plan,
            action.preview.shot.make_active,
        )

    def tools(self):
        return [
            Tool(
                "cinema.composition_preview",
                SafetyClass.READ_ONLY,
                CompositionPreview.parse,
                self.preview,
            ),
            Tool(
                "cinema.composition_apply",
                SafetyClass.MUTATION,
                CompositionApply.parse,
                self.apply,
            ),
        ]
