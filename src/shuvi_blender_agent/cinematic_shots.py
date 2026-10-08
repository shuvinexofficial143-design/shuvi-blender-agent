"""Level 8 M1: bounded subject-centered perspective camera framing."""

from dataclasses import dataclass
from math import atan, atan2, cos, degrees, radians, sin, sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number, string
from .verification import compare


@dataclass(frozen=True)
class ShotPreview:
    camera: ObjectTarget
    subject: ObjectTarget
    azimuth_degrees: float
    elevation_degrees: float
    margin: float
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
            data["make_active"],
        )


@dataclass(frozen=True)
class ShotApply:
    preview: ShotPreview
    expected_plan_revision: str

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
                "expected_plan_revision",
            },
        )
        payload = {key: val for key, val in data.items() if key != "expected_plan_revision"}
        return cls(
            ShotPreview.parse(payload),
            string(data["expected_plan_revision"], "expected_plan_revision", limit=64),
        )


class CinematicShotOperations:
    """Frame an unanimated camera around a conservative subject bounding sphere."""

    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    @staticmethod
    def _finite_list(values, name, low, high):
        if len(values) != 3:
            raise AgentError(ErrorCode.SAFETY_DENIED, f"Invalid {name} dimensions")
        try:
            return [number(value, name, low, high) for value in values]
        except AgentError as exc:
            raise AgentError(ErrorCode.SAFETY_DENIED, f"Invalid {name} coordinates") from exc

    def _plan(self, action: ShotPreview):
        camera, camera_before = self.inspector.target(action.camera)
        subject, subject_before = self.inspector.target(action.subject)
        if camera is subject or camera.type != "CAMERA" or subject.type == "CAMERA":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Distinct subject and CAMERA are required")
        if not getattr(camera, "data", None):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Missing camera data")

        center = self._finite_list(subject.location, "subject center", -1_000_000, 1_000_000)
        dimensions = self._finite_list(subject.dimensions, "subject size", 0, 100_000)
        radius = 0.5 * sqrt(sum(item * item for item in dimensions))
        if radius < 0.0001:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subject has no usable size")

        data = camera.data
        lens = number(data.lens, "lens", 1, 500)
        sensor_width = number(getattr(data, "sensor_width", 36), "sensor_width", 1, 100)
        clip_start = number(data.clip_start, "clip_start", 0.0001, 1000)
        clip_end = number(data.clip_end, "clip_end", 0.001, 1_000_000)
        render = self.bpy.context.scene.render
        width = number(render.resolution_x, "resolution_x", 1, 100_000)
        height = number(render.resolution_y, "resolution_y", 1, 100_000)
        pixel_aspect_x = number(getattr(render, "pixel_aspect_x", 1), "pixel_aspect_x", 0.01, 100)
        pixel_aspect_y = number(getattr(render, "pixel_aspect_y", 1), "pixel_aspect_y", 0.01, 100)
        aspect = (width * pixel_aspect_x) / (height * pixel_aspect_y)
        if not 0.01 <= aspect <= 100:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported render aspect ratio")

        half_horizontal = atan(sensor_width / (2 * lens))
        half_vertical = atan((sensor_width / (2 * lens)) / aspect)
        half_limiting = min(half_horizontal, half_vertical)
        padded_radius = radius * action.margin
        distance = max(
            padded_radius / sin(half_limiting),
            padded_radius + clip_start * 1.1,
        )
        # Blender cameras look along local -Z, with local +Y up.
        azimuth = radians(action.azimuth_degrees)
        elevation = radians(action.elevation_degrees)
        direction = [
            cos(elevation) * cos(azimuth),
            cos(elevation) * sin(azimuth),
            sin(elevation),
        ]
        location = [center[i] + distance * direction[i] for i in range(3)]
        pitch = radians(90 - action.elevation_degrees)
        yaw_angle = azimuth + radians(90)
        yaw = atan2(sin(yaw_angle), cos(yaw_angle))
        rotation = [pitch, 0.0, yaw]

        blockers = []
        if (
            camera.library is not None
            or camera.override_library is not None
            or not camera.is_editable
        ):
            blockers.append("CAMERA_READ_ONLY_OR_LINKED")
        if camera.parent is not None or len(camera.constraints):
            blockers.append("CAMERA_PARENT_OR_CONSTRAINTS")
        if camera.animation_data is not None or getattr(data, "animation_data", None) is not None:
            blockers.append("CAMERA_ANIMATION_PRESENT")
        if getattr(data, "users", 0) != 1 or getattr(data, "library", None) is not None:
            blockers.append("SHARED_OR_LINKED_CAMERA_DATA")
        if data.type != "PERSP":
            blockers.append("PERSPECTIVE_CAMERA_REQUIRED")
        fit = getattr(data, "sensor_fit", "AUTO")
        if fit not in ("AUTO", "HORIZONTAL") or (fit == "AUTO" and aspect < 1):
            blockers.append("HORIZONTAL_SENSOR_FIT_REQUIRED")
        if camera.rotation_mode != "XYZ":
            blockers.append("CAMERA_XYZ_ROTATION_REQUIRED")
        if any(getattr(camera, "lock_location", (False,) * 3)):
            blockers.append("CAMERA_LOCATION_LOCKED")
        if any(getattr(camera, "lock_rotation", (False,) * 3)):
            blockers.append("CAMERA_ROTATION_LOCKED")
        if any(abs(value - 1) > 1e-5 for value in camera.scale):
            blockers.append("UNIT_CAMERA_SCALE_REQUIRED")
        if self.bpy.context.mode != "OBJECT":
            blockers.append("OBJECT_MODE_REQUIRED")
        if clip_end <= clip_start:
            blockers.append("INVALID_CLIP_RANGE")
        if distance - padded_radius <= clip_start or distance + padded_radius >= clip_end:
            blockers.append("SUBJECT_OUTSIDE_CAMERA_CLIP")

        active = self.bpy.context.scene.camera
        plan = {
            "camera_id": camera_before["object_id"],
            "subject_id": subject_before["object_id"],
            "camera_object_revision": camera_before["revision"],
            "subject_object_revision": subject_before["revision"],
            "active_camera_name": getattr(active, "name", None),
            "subject_center": center,
            "subject_dimensions": dimensions,
            "subject_enclosing_radius": radius,
            "margin": action.margin,
            "azimuth_degrees": action.azimuth_degrees,
            "elevation_degrees": action.elevation_degrees,
            "make_active": action.make_active,
            "camera_location": location,
            "camera_rotation_euler": rotation,
            "camera_distance": distance,
            "lens_mm": lens,
            "sensor_width_mm": sensor_width,
            "sensor_fit": fit,
            "render_aspect": aspect,
            "horizontal_fov_degrees": degrees(2 * half_horizontal),
            "vertical_fov_degrees": degrees(2 * half_vertical),
            "clip_start": clip_start,
            "clip_end": clip_end,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "center_assumption": "SUBJECT_ORIGIN_AND_WORLD_AXIS_ALIGNED_DIMENSIONS",
            "source_only": True,
            "real_runtime_verified": False,
            "mutation_performed": False,
        }
        plan["plan_revision"] = revision(plan)
        return camera, subject, camera_before, subject_before, plan

    def preview(self, request: Request, action: ShotPreview):
        _, _, _, _, plan = self._plan(action)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request: Request, action: ShotApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if action.expected_plan_revision != plan["plan_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Camera shot plan changed since preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera shot has unresolved safety blockers")

        old_location = list(camera.location)
        old_rotation = list(camera.rotation_euler)
        old_active = self.bpy.context.scene.camera

        def rollback():
            camera.location = old_location
            camera.rotation_euler = old_rotation
            self.bpy.context.scene.camera = old_active
            self.bpy.context.view_layer.update()
            restored = self.inspector.snapshot(camera)
            if restored["revision"] != before["revision"]:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Camera shot rollback could not be verified"
                )

        try:
            camera.location = plan["camera_location"]
            camera.rotation_euler = plan["camera_rotation_euler"]
            if action.preview.make_active:
                self.bpy.context.scene.camera = camera
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(camera)
            subject_after = self.inspector.snapshot(subject)
            expected = {
                "location": plan["camera_location"],
                "rotation_euler": plan["camera_rotation_euler"],
                "rotation_mode": "XYZ",
                "subject_revision": subject_before["revision"],
                "lens_mm": plan["lens_mm"],
                "active_camera": (True if action.preview.make_active else old_active is camera),
                "revision_changed": True,
            }
            actual = {
                "location": after["transform"]["location"],
                "rotation_euler": after["transform"]["rotation_euler"],
                "rotation_mode": after["transform"]["rotation_mode"],
                "subject_revision": subject_after["revision"],
                "lens_mm": after["camera"]["lens"],
                "active_camera": self.bpy.context.scene.camera is camera,
                "revision_changed": after["revision"] != before["revision"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "shot_plan_revision": plan["plan_revision"],
                        "source_only": True,
                        "real_runtime_verified": False,
                    },
                    verification=verification.to_dict(),
                )
        except Exception as exc:
            try:
                rollback()
            except Exception as recovery_error:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Camera shot failed and rollback was not verified",
                ) from recovery_error
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Camera shot interrupted; original pose restored"
            ) from exc

        rollback()
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "rolled_back": True,
                "recovery_verified": True,
            },
            AgentError(ErrorCode.VERIFICATION_FAILED, "Camera shot readback mismatch"),
            verification.to_dict(),
        )

    def tools(self):
        return [
            Tool("cinema.shot_preview", SafetyClass.READ_ONLY, ShotPreview.parse, self.preview),
            Tool("cinema.shot_frame", SafetyClass.MUTATION, ShotApply.parse, self.apply),
        ]
