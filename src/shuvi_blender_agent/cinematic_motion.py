"""Level 8 M3: bounded, verified three-pose camera orbit and dolly keyframes."""

from dataclasses import dataclass
from math import pi

from .cinematic_shots import CinematicShotOperations, ShotPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

MODES = ("ORBIT", "DOLLY_IN", "DOLLY_OUT")
PATHS = ("location", "rotation_euler")


@dataclass(frozen=True)
class CameraMotionPreview:
    camera: ObjectTarget
    subject: ObjectTarget
    start_frame: int
    end_frame: int
    mode: str
    start_azimuth: float
    end_azimuth: float
    start_elevation: float
    end_elevation: float
    margin: float
    dolly_factor: float
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
                "mode",
                "start_azimuth",
                "end_azimuth",
                "start_elevation",
                "end_elevation",
                "margin",
                "dolly_factor",
                "make_active",
            },
        )
        mode = string(data["mode"], "mode", limit=16)
        if mode not in MODES:
            raise invalid("Only ORBIT, DOLLY_IN, DOLLY_OUT camera paths are supported")
        start = integer(data["start_frame"], "start_frame", 1, 99_996)
        end = integer(data["end_frame"], "end_frame", 1, 100_000)
        if not 4 <= end - start <= 720:
            raise invalid("Camera movement duration must be 4..720 frames")
        start_azimuth = number(data["start_azimuth"], "start_azimuth", -180, 180)
        end_azimuth = number(data["end_azimuth"], "end_azimuth", -180, 180)
        start_elevation = number(data["start_elevation"], "start_elevation", -75, 75)
        end_elevation = number(data["end_elevation"], "end_elevation", -75, 75)
        dolly_factor = number(data["dolly_factor"], "dolly_factor", 1, 2)
        if mode == "ORBIT":
            if (
                max(abs(end_azimuth - start_azimuth), abs(end_elevation - start_elevation)) < 0.5
                or abs(end_azimuth - start_azimuth) > 60
                or abs(end_elevation - start_elevation) > 35
                or dolly_factor != 1
            ):
                raise invalid("ORBIT needs 0.5..60 degree rotation and dolly_factor=1")
        elif start_azimuth != end_azimuth or start_elevation != end_elevation or dolly_factor < 1.1:
            raise invalid("DOLLY needs fixed angles and dolly_factor 1.1..2")
        if type(data["make_active"]) is not bool:
            raise invalid("make_active must be boolean")
        return cls(
            ObjectTarget.parse(data["camera"]),
            ObjectTarget.parse(data["subject"]),
            start,
            end,
            mode,
            start_azimuth,
            end_azimuth,
            start_elevation,
            end_elevation,
            number(data["margin"], "margin", 1.05, 2.5),
            dolly_factor,
            data["make_active"],
        )


@dataclass(frozen=True)
class CameraMotionApply:
    preview: CameraMotionPreview
    expected_motion_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera",
                "subject",
                "start_frame",
                "end_frame",
                "mode",
                "start_azimuth",
                "end_azimuth",
                "start_elevation",
                "end_elevation",
                "margin",
                "dolly_factor",
                "make_active",
                "expected_motion_revision",
            },
        )
        return cls(
            CameraMotionPreview.parse(
                {key: val for key, val in data.items() if key != "expected_motion_revision"}
            ),
            string(data["expected_motion_revision"], "expected_motion_revision", limit=64),
        )


class CameraMotionOperations:
    """Never edits or adopts an existing Action; authors one fresh bounded clip."""

    def __init__(self, objects: ObjectOperations):
        self.shots = CinematicShotOperations(objects)
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def _plan(self, action: CameraMotionPreview):
        mid_frame = (action.start_frame + action.end_frame) // 2
        keyframes = [action.start_frame, mid_frame, action.end_frame]
        poses = []
        source_plans = []
        for position in (0, 0.5, 1):
            azimuth = action.start_azimuth + position * (action.end_azimuth - action.start_azimuth)
            elevation = action.start_elevation + position * (
                action.end_elevation - action.start_elevation
            )
            shot = ShotPreview(
                action.camera,
                action.subject,
                azimuth,
                elevation,
                action.margin,
                action.make_active,
            )
            camera, subject, camera_before, subject_before, plan = self.shots._plan(shot)
            source_plans.append(plan)
            distance = plan["camera_distance"]
            if action.mode == "DOLLY_IN":
                distance *= 1 + (1 - position) * (action.dolly_factor - 1)
            elif action.mode == "DOLLY_OUT":
                distance *= 1 + position * (action.dolly_factor - 1)
            center = plan["subject_center"]
            direction = [
                (plan["camera_location"][axis] - center[axis]) / plan["camera_distance"]
                for axis in range(3)
            ]
            location = [center[axis] + distance * direction[axis] for axis in range(3)]
            rotation = list(plan["camera_rotation_euler"])
            if poses:
                # Unwrap -pi/pi to avoid a spurious full spin between keyframes.
                while rotation[2] - poses[-1]["rotation_euler"][2] > pi:
                    rotation[2] -= 2 * pi
                while rotation[2] - poses[-1]["rotation_euler"][2] < -pi:
                    rotation[2] += 2 * pi
            poses.append(
                {
                    "frame": keyframes[len(poses)],
                    "location": location,
                    "rotation_euler": rotation,
                    "distance": distance,
                }
            )

        blockers = set(item for plan in source_plans for item in plan["blockers"])
        if getattr(camera.data, "shift_x", 0) != 0 or getattr(camera.data, "shift_y", 0) != 0:
            blockers.add("NONZERO_CAMERA_LENS_SHIFT")
        if camera.animation_data is not None:
            blockers.add("EXISTING_CAMERA_ACTION_CANNOT_BE_ADOPTED")
        if any(getattr(camera, path, None) is None for path in PATHS):
            blockers.add("CAMERA_TRANSFORM_UNAVAILABLE")
        for pose in poses:
            radius = source_plans[0]["subject_enclosing_radius"] * action.margin
            if (
                pose["distance"] - radius <= source_plans[0]["clip_start"]
                or pose["distance"] + radius >= source_plans[0]["clip_end"]
            ):
                blockers.add("CAMERA_PATH_EXCEEDS_CLIPPING")
            if any(abs(value) > 1_000_000 for value in pose["location"]):
                blockers.add("CAMERA_PATH_EXCEEDS_COORDINATE_BOUNDS")
        data = {
            "camera_id": camera_before["object_id"],
            "subject_id": subject_before["object_id"],
            "camera_object_revision": camera_before["revision"],
            "subject_object_revision": subject_before["revision"],
            "base_shot_revisions": [plan["plan_revision"] for plan in source_plans],
            "mode": action.mode,
            "start_frame": action.start_frame,
            "mid_frame": mid_frame,
            "end_frame": action.end_frame,
            "interpolation": "LINEAR",
            "key_poses": poses,
            "camera_lens": source_plans[0]["lens_mm"],
            "make_active": action.make_active,
            "dolly_factor": action.dolly_factor,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "scope": "THREE_MANAGED_CAMERA_POSES_SOURCE_ONLY",
            "evaluated_motion_verified": False,
            "real_runtime_verified": False,
            "mutation_performed": False,
        }
        data["motion_revision"] = revision(data)
        return camera, subject, camera_before, subject_before, data

    def preview(self, request: Request, action: CameraMotionPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[4]
        )

    def apply(self, request: Request, action: CameraMotionApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if plan["motion_revision"] != action.expected_motion_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera motion plan changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera movement safety blockers present")
        return self._commit_poses(
            request, camera, subject, before, subject_before, plan, action.preview.make_active
        )

    def _commit_poses(self, request, camera, subject, before, subject_before, plan, make_active):
        """M3/M4 shared fresh-Action creation, exact readback and rollback."""
        if len(plan["key_poses"]) not in (3, 5):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported camera path size")
        if camera.animation_data is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Cannot overwrite existing animation")
        interpolation = plan.get("interpolation", "LINEAR")
        if interpolation not in ("LINEAR", "BEZIER"):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported camera key interpolation")
        if interpolation == "BEZIER" and len(plan["key_poses"]) != 5:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Eased rail needs exactly five poses")
        if any(
            a["frame"] >= b["frame"]
            for a, b in zip(plan["key_poses"], plan["key_poses"][1:], strict=False)
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera frames must be increasing")

        old_location = list(camera.location)
        old_rotation = list(camera.rotation_euler)
        old_active = self.bpy.context.scene.camera
        old_frame = self.bpy.context.scene.frame_current
        created_action = None

        def rollback():
            camera.location = old_location
            camera.rotation_euler = old_rotation
            self.bpy.context.scene.camera = old_active
            if camera.animation_data is not None:
                current = getattr(camera.animation_data, "action", None)
                if created_action is not None and current is not created_action:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "Created camera Action identity changed during rollback",
                    )
                if not hasattr(camera, "animation_data_clear"):
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Animation cleanup unavailable")
                camera.animation_data_clear()
            actions = getattr(self.bpy.data, "actions", None)
            if (
                created_action is not None
                and actions is not None
                and getattr(created_action, "users", 1) == 0
            ):
                actions.remove(created_action)
            self.bpy.context.view_layer.update()
            recovered = self.inspector.snapshot(camera)
            if (
                recovered["revision"] != before["revision"]
                or self.bpy.context.scene.camera is not old_active
                or self.bpy.context.scene.frame_current != old_frame
            ):
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Camera motion rollback not verified"
                )

        try:
            for pose in plan["key_poses"]:
                camera.location = pose["location"]
                camera.rotation_euler = pose["rotation_euler"]
                for path in PATHS:
                    if not camera.keyframe_insert(data_path=path, frame=pose["frame"]):
                        raise AgentError(ErrorCode.EXECUTION_ERROR, "Camera keyframe insert failed")
                    if created_action is None:
                        created_action = camera.animation_data.action
                    if camera.animation_data.action is not created_action:
                        raise AgentError(ErrorCode.SAFETY_DENIED, "Camera Action changed mid-write")
            ad = camera.animation_data
            if (
                getattr(ad, "action_slot", None) is not None
                or getattr(created_action, "users", 0) != 1
                or not hasattr(created_action, "fcurves")
                or len(getattr(ad, "drivers", ())) != 0
                or len(getattr(ad, "nla_tracks", ())) != 0
            ):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported camera Action structure")
            for curve in created_action.fcurves:
                if curve.data_path not in PATHS or not 0 <= curve.array_index < 3:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Unexpected camera keyframe channel")
                for point in curve.keyframe_points:
                    point.interpolation = interpolation
                    if interpolation == "BEZIER":
                        pose = next(
                            (
                                item for item in plan["key_poses"]
                                if float(item["frame"]) == float(point.co[0])
                            ),
                            None,
                        )
                        if pose is None:
                            raise AgentError(
                                ErrorCode.VERIFICATION_FAILED, "Unexpected camera keyframe point"
                            )
                        handle = pose["key_handles"][curve.data_path][curve.array_index]
                        point.handle_left_type = "FREE"
                        point.handle_right_type = "FREE"
                        point.handle_left = handle["left"]
                        point.handle_right = handle["right"]
                curve.update()
            if make_active:
                self.bpy.context.scene.camera = camera
            self.bpy.context.view_layer.update()
            current_ad = camera.animation_data
            if (
                current_ad is None
                or current_ad.action is not created_action
                or getattr(current_ad, "action_slot", None) is not None
                or getattr(created_action, "users", 0) != 1
                or not hasattr(created_action, "fcurves")
                or len(getattr(current_ad, "drivers", ())) != 0
                or len(getattr(current_ad, "nla_tracks", ())) != 0
            ):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Camera Action became unsupported before final readback",
                )
            after = self.inspector.snapshot(camera)
            subject_after = self.inspector.snapshot(subject)
            frame_values = {
                (path, index, float(pose["frame"])): float(value)
                for pose in plan["key_poses"]
                for path in PATHS
                for index, value in enumerate(pose[path])
            }
            expected_keys = [
                {
                    "path": path,
                    "index": index,
                    "points": [
                        {
                            "frame": float(pose["frame"]),
                            "value": float(pose[path][index]),
                            "interpolation": interpolation,
                            **(
                                {
                                    "handle_left_type": "FREE",
                                    "handle_right_type": "FREE",
                                    "handle_left": pose["key_handles"][path][index]["left"],
                                    "handle_right": pose["key_handles"][path][index]["right"],
                                }
                                if interpolation == "BEZIER"
                                else {}
                            ),
                        }
                        for pose in plan["key_poses"]
                    ],
                }
                for path in PATHS
                for index in range(3)
            ]
            actual_keys = []
            for curve in after["animation"]["channels"]:
                actual_keys.append(
                    {
                        "path": curve["data_path"],
                        "index": curve["index"],
                        "points": [
                            {
                                "frame": float(point["co"][0]),
                                "value": float(point["co"][1]),
                                "interpolation": point["interpolation"],
                                **(
                                    {
                                        "handle_left_type": point["handle_left_type"],
                                        "handle_right_type": point["handle_right_type"],
                                        "handle_left": point["handle_left"],
                                        "handle_right": point["handle_right"],
                                    }
                                    if interpolation == "BEZIER"
                                    else {}
                                ),
                            }
                            for point in curve["points"]
                        ],
                    }
                )
            expected_keys.sort(key=lambda item: (item["path"], item["index"]))
            actual_keys.sort(key=lambda item: (item["path"], item["index"]))
            expected = {
                "keys": expected_keys,
                "location": plan["key_poses"][-1]["location"],
                "rotation": plan["key_poses"][-1]["rotation_euler"],
                "lens": plan["camera_lens"],
                "subject_revision": subject_before["revision"],
                "active_camera": (True if make_active else old_active is camera),
                "frame": old_frame,
                "created_action": created_action.name,
                "revision_changed": True,
            }
            actual = {
                "keys": actual_keys,
                "location": after["transform"]["location"],
                "rotation": after["transform"]["rotation_euler"],
                "lens": after["camera"]["lens"],
                "subject_revision": subject_after["revision"],
                "active_camera": self.bpy.context.scene.camera is camera,
                "frame": self.bpy.context.scene.frame_current,
                "created_action": after["animation"]["action"],
                "revision_changed": after["revision"] != before["revision"],
            }
            verification = compare(expected, actual)
            if verification.matched and len(frame_values) == 6 * len(plan["key_poses"]):
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "motion_revision": plan["motion_revision"],
                        "keyframe_count": len(frame_values),
                        "channel_count": 6,
                        "keyframe_frames": [pose["frame"] for pose in plan["key_poses"]],
                        "real_runtime_verified": False,
                    },
                    verification=verification.to_dict(),
                )
        except Exception as exc:
            try:
                rollback()
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Camera keyframe authoring failed and rollback was not verified",
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR,
                "Camera keyframe authoring interrupted; inspect before retry",
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
                "real_runtime_verified": False,
            },
            AgentError(ErrorCode.VERIFICATION_FAILED, "Camera keyframe readback mismatch"),
            verification.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "cinema.motion_preview",
                SafetyClass.READ_ONLY,
                CameraMotionPreview.parse,
                self.preview,
            ),
            Tool("cinema.motion_apply", SafetyClass.MUTATION, CameraMotionApply.parse, self.apply),
        ]
