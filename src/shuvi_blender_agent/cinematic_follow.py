"""Level 8 M7: managed camera translation follow with constant world-space offset."""

from dataclasses import dataclass

from .cinematic_shots import ShotPreview
from .cinematic_tracking import CameraTrackingOperations, TrackingPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string
from .verification import compare

COPY_NAME = "Shuvi_M7_Position_Follow"
TRACK_NAME = "Shuvi_M7_Subject_Aim"
COPY_TYPE = "COPY_LOCATION"
TRACK_TYPE = "TRACK_TO"


@dataclass(frozen=True)
class FollowPreview:
    shot: ShotPreview

    @classmethod
    def parse(cls, data):
        return cls(ShotPreview.parse(data))


@dataclass(frozen=True)
class FollowApply:
    preview: FollowPreview
    expected_follow_revision: str

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
                "expected_follow_revision",
            },
        )
        return cls(
            FollowPreview.parse(
                {key: value for key, value in data.items() if key != "expected_follow_revision"}
            ),
            string(data["expected_follow_revision"], "expected_follow_revision", limit=64),
        )


@dataclass(frozen=True)
class FollowRelease:
    camera: ObjectTarget
    expected_follow_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"camera", "expected_follow_token"})
        return cls(
            ObjectTarget.parse(data["camera"]),
            string(data["expected_follow_token"], "expected_follow_token", limit=64),
        )


class CameraFollowOperations:
    """Only two exact session-created constraints; foreign constraints are never adopted."""

    def __init__(self, objects: ObjectOperations):
        self.tracking = CameraTrackingOperations(objects)
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned = {}

    @staticmethod
    def _copy_readback(item, subject):
        return {
            "name": item.name,
            "type": item.type,
            "target_matches": item.target is subject,
            "use_offset": bool(item.use_offset),
            "target_space": item.target_space,
            "owner_space": item.owner_space,
            "use_axis": [bool(item.use_x), bool(item.use_y), bool(item.use_z)],
            "invert_axis": [bool(item.invert_x), bool(item.invert_y), bool(item.invert_z)],
            "influence": float(item.influence),
            "mute": bool(item.mute),
        }

    @staticmethod
    def _copy_expected():
        return {
            "name": COPY_NAME,
            "type": COPY_TYPE,
            "target_matches": True,
            "use_offset": True,
            "target_space": "WORLD",
            "owner_space": "WORLD",
            "use_axis": [True, True, True],
            "invert_axis": [False, False, False],
            "influence": 1.0,
            "mute": False,
        }

    @staticmethod
    def _track_expected():
        return {
            "name": TRACK_NAME,
            "type": TRACK_TYPE,
            "target_matches": True,
            "track_axis": "TRACK_NEGATIVE_Z",
            "up_axis": "UP_Y",
            "influence": 1.0,
            "mute": False,
        }

    @staticmethod
    def _track_readback(item, subject):
        return {
            "name": item.name,
            "type": item.type,
            "target_matches": item.target is subject,
            "track_axis": item.track_axis,
            "up_axis": item.up_axis,
            "influence": float(item.influence),
            "mute": bool(item.mute),
        }

    def _configure(self, camera, subject):
        follow = camera.constraints.new(type=COPY_TYPE)
        follow.name = COPY_NAME
        follow.target = subject
        follow.target_space = "WORLD"
        follow.owner_space = "WORLD"
        follow.use_x = True
        follow.use_y = True
        follow.use_z = True
        follow.invert_x = False
        follow.invert_y = False
        follow.invert_z = False
        follow.use_offset = True
        follow.influence = 1.0
        follow.mute = False
        aim = camera.constraints.new(type=TRACK_TYPE)
        aim.name = TRACK_NAME
        aim.target = subject
        aim.track_axis = "TRACK_NEGATIVE_Z"
        aim.up_axis = "UP_Y"
        aim.influence = 1.0
        aim.mute = False
        return follow, aim

    def _plan(self, action: FollowPreview):
        camera, subject, before, subject_before, base = self.tracking._plan(
            TrackingPreview(action.shot)
        )
        blockers = set(base["blockers"])
        if len(camera.constraints):
            blockers.add("CAMERA_CONSTRAINTS_PRESENT")
        if subject.parent is not None:
            blockers.add("PARENTED_SUBJECT_WORLD_OFFSET_UNSUPPORTED")
        if before["object_id"] in self._owned:
            blockers.add("CAMERA_ALREADY_FOLLOWING")
        offset = [base["camera_location"][axis] - base["subject_center"][axis] for axis in range(3)]
        if any(abs(component) > 1_000_000 for component in offset):
            blockers.add("FOLLOW_OFFSET_OUT_OF_RANGE")
        result = dict(base)
        result.pop("tracking_revision")
        result.update(
            {
                "base_tracking_revision": base["tracking_revision"],
                "copy_constraint": COPY_NAME,
                "aim_constraint": TRACK_NAME,
                "copy_type": COPY_TYPE,
                "tracking_type": TRACK_TYPE,
                "owner_space": "WORLD",
                "target_space": "WORLD",
                "use_offset": True,
                "camera_local_offset": offset,
                "predicted_initial_world_location": base["camera_location"],
                "follow_equation": "CAMERA_WORLD_POSITION = TARGET_WORLD_POSITION + CAMERA_OFFSET",
                "constraint_order": [COPY_NAME, TRACK_NAME],
                "blockers": sorted(blockers),
                "ready": not blockers,
                "evaluated_follow_verified": False,
                "real_runtime_verified": False,
                "mutation_performed": False,
            }
        )
        result["follow_revision"] = revision(result)
        return camera, subject, before, subject_before, result

    def preview(self, request: Request, action: FollowPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[4]
        )

    def apply(self, request: Request, action: FollowApply):
        camera, subject, before, subject_before, plan = self._plan(action.preview)
        if plan["follow_revision"] != action.expected_follow_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Camera follow plan changed after preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe camera/subject follow plan")

        original_location = list(camera.location)
        original_rotation = list(camera.rotation_euler)
        original_active = self.bpy.context.scene.camera
        made = []

        def rollback():
            for item in reversed(made):
                if item not in camera.constraints:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Follow constraint identity lost"
                    )
                camera.constraints.remove(item)
            camera.location = original_location
            camera.rotation_euler = original_rotation
            self.bpy.context.scene.camera = original_active
            self.bpy.context.view_layer.update()
            if self.inspector.snapshot(camera)["revision"] != before["revision"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Follow setup rollback unverified")

        try:
            camera.location = list(plan["camera_local_offset"])
            camera.rotation_euler = list(plan["camera_rotation_euler"])
            # Track each new constraint even when the second .new call fails.
            copy = camera.constraints.new(type=COPY_TYPE)
            made.append(copy)
            copy.name = COPY_NAME
            copy.target = subject
            copy.target_space = "WORLD"
            copy.owner_space = "WORLD"
            copy.use_x = copy.use_y = copy.use_z = True
            copy.invert_x = copy.invert_y = copy.invert_z = False
            copy.use_offset = True
            copy.influence = 1.0
            copy.mute = False
            aim = camera.constraints.new(type=TRACK_TYPE)
            made.append(aim)
            aim.name = TRACK_NAME
            aim.target = subject
            aim.track_axis = "TRACK_NEGATIVE_Z"
            aim.up_axis = "UP_Y"
            aim.influence = 1.0
            aim.mute = False
            if action.preview.shot.make_active:
                self.bpy.context.scene.camera = camera
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(camera)
            subject_after = self.inspector.snapshot(subject)
            expected = {
                "copy": self._copy_expected(),
                "track": self._track_expected(),
                "count": 2,
                "target_id": subject_before["object_id"],
                "subject_revision": subject_before["revision"],
                "stored_offset": plan["camera_local_offset"],
                "rotation": plan["camera_rotation_euler"],
                "lens": plan["lens_mm"],
                "active": True if action.preview.shot.make_active else original_active is camera,
                "revision_changed": True,
            }
            actual = {
                "copy": self._copy_readback(copy, subject),
                "track": self._track_readback(aim, subject),
                "count": after["constraint_count"],
                "target_id": after["constraints"][0]["target_id"],
                "subject_revision": subject_after["revision"],
                "stored_offset": after["transform"]["location"],
                "rotation": after["transform"]["rotation_euler"],
                "lens": after["camera"]["lens"],
                "active": self.bpy.context.scene.camera is camera,
                "revision_changed": after["revision"] != before["revision"],
            }
            verification = compare(expected, actual)
            if (
                verification.matched
                and len(camera.constraints) == 2
                and camera.constraints[0] is copy
                and camera.constraints[1] is aim
            ):
                token = revision(
                    {
                        "camera_revision": after["revision"],
                        "subject_id": subject_before["object_id"],
                        "copy": actual["copy"],
                        "track": actual["track"],
                    }
                )
                self._owned[after["object_id"]] = (
                    copy,
                    aim,
                    subject,
                    token,
                    original_location,
                    original_rotation,
                )
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "follow_token": token,
                        "camera_local_offset": plan["camera_local_offset"],
                        "predicted_initial_world_location": (
                            plan["predicted_initial_world_location"]
                        ),
                        "evaluated_follow_verified": False,
                        "real_runtime_verified": False,
                    },
                    verification=verification.to_dict(),
                )
        except Exception as exc:
            try:
                rollback()
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Follow setup failed and rollback unverified"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Camera follow setup interrupted; inspect before retry"
            ) from exc

        rollback()
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"before": before, "after": after, "rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Camera follow setup readback mismatch"),
            verification.to_dict(),
        )

    def release(self, request: Request, action: FollowRelease):
        camera, before = self.inspector.target(action.camera)
        owned = self._owned.get(before["object_id"])
        if owned is None or owned[3] != action.expected_follow_token:
            raise AgentError(ErrorCode.STALE_STATE, "Follow token not owned by this session")
        copy, aim, subject, token, original_location, original_rotation = owned
        if (
            len(camera.constraints) != 2
            or camera.constraints[0] is not copy
            or camera.constraints[1] is not aim
            or not compare(self._copy_expected(), self._copy_readback(copy, subject)).matched
            or not compare(self._track_expected(), self._track_readback(aim, subject)).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed follow constraints were modified")
        expected_token = revision(
            {
                "camera_revision": before["revision"],
                "subject_id": self.inspector.identity(subject),
                "copy": self._copy_readback(copy, subject),
                "track": self._track_readback(aim, subject),
            }
        )
        if expected_token != token:
            raise AgentError(ErrorCode.STALE_STATE, "Follow state changed since creation")
        old_active = self.bpy.context.scene.camera
        old_stored_offset = list(camera.location)
        old_rotation = list(camera.rotation_euler)

        def rollback():
            if any(item not in (copy, aim) for item in camera.constraints):
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Foreign constraint on rollback")
            for item in list(camera.constraints):
                camera.constraints.remove(item)
            new_copy, new_aim = self._configure(camera, subject)
            camera.location = old_stored_offset
            camera.rotation_euler = old_rotation
            self.bpy.context.scene.camera = old_active
            self.bpy.context.view_layer.update()
            if self.inspector.snapshot(camera)["revision"] != before["revision"]:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Follow release recovery unverified"
                )
            self._owned[before["object_id"]] = (
                new_copy,
                new_aim,
                subject,
                token,
                original_location,
                original_rotation,
            )

        try:
            camera.constraints.remove(aim)
            camera.constraints.remove(copy)
            camera.location = list(original_location)
            camera.rotation_euler = list(original_rotation)
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(camera)
            verification = compare(
                {
                    "count": 0,
                    "location": original_location,
                    "rotation": original_rotation,
                    "active": True,
                    "revision_changed": True,
                },
                {
                    "count": after["constraint_count"],
                    "location": after["transform"]["location"],
                    "rotation": after["transform"]["rotation_euler"],
                    "active": self.bpy.context.scene.camera is old_active,
                    "revision_changed": after["revision"] != before["revision"],
                },
            )
            if verification.matched and len(camera.constraints) == 0:
                del self._owned[before["object_id"]]
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "restored_pre_follow_camera_pose": True,
                        "removed_own_constraints": 2,
                        "real_runtime_verified": False,
                    },
                    verification=verification.to_dict(),
                )
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Follow release readback mismatch")
        except Exception as exc:
            try:
                rollback()
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Follow release rollback not verified"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Follow release interrupted; original state recovered"
            ) from exc

    def tools(self):
        return [
            Tool("cinema.follow_preview", SafetyClass.READ_ONLY, FollowPreview.parse, self.preview),
            Tool("cinema.follow_apply", SafetyClass.MUTATION, FollowApply.parse, self.apply),
            Tool("cinema.follow_release", SafetyClass.MUTATION, FollowRelease.parse, self.release),
        ]
