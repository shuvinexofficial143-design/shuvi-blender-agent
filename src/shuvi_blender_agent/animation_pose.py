"""Level 7 milestone 5: bounded pose-bone animation channels."""

from dataclasses import dataclass

from .animation import (
    MAX_ANIMATION_CURVES,
    MAX_ANIMATION_POINTS,
    AnimationInspect,
    AnimationOperations,
)
from .animation_state import action_curves
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .models import ObjectTarget, object_name
from .rigging import PoseBoneTransform, RiggingOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string
from .verification import compare

POSE_INTERPOLATIONS = {"LINEAR", "BEZIER", "CONSTANT"}


@dataclass(frozen=True)
class PoseBoneAnimationInspect:
    object_id: str
    bone_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "bone_name"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            object_name(data["bone_name"]),
        )


@dataclass(frozen=True)
class PoseBoneKeyframeInsert:
    target: ObjectTarget
    expected_rig_revision: str
    expected_animation_revision: str
    bone_name: str
    frame: int
    location: tuple[float, float, float]
    rotation_mode: str
    rotation: tuple[float, ...]
    scale: tuple[float, float, float]
    interpolation: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_rig_revision",
                "expected_animation_revision",
                "bone_name",
                "frame",
                "location",
                "rotation_mode",
                "rotation",
                "scale",
                "interpolation",
            },
        )
        pose = PoseBoneTransform.parse(
            {
                "target": data["target"],
                "expected_rig_revision": data["expected_rig_revision"],
                "bone_name": data["bone_name"],
                "location": data["location"],
                "rotation_mode": data["rotation_mode"],
                "rotation": data["rotation"],
                "scale": data["scale"],
            }
        )
        interpolation = data["interpolation"]
        if interpolation not in POSE_INTERPOLATIONS:
            raise invalid("Unsupported pose-bone interpolation")
        return cls(
            pose.target,
            pose.expected_rig_revision,
            string(
                data["expected_animation_revision"],
                "expected_animation_revision",
                limit=64,
            ),
            pose.bone_name,
            integer(data["frame"], "frame", 1, 100_000),
            pose.location,
            pose.rotation_mode,
            pose.rotation,
            pose.scale,
            interpolation,
        )


class PoseBoneAnimationOperations:
    def __init__(self, animation: AnimationOperations, rigging: RiggingOperations):
        self.animation = animation
        self.rigging = rigging
        self.objects = animation.objects
        self.inspector = animation.inspector
        self.bpy = animation.bpy

    def _animation_state(self, object_id):
        request = Request("animation.inspect", {"object_id": object_id})
        result = self.animation.inspect(request, AnimationInspect(object_id))
        return result.data

    @staticmethod
    def _path(pose_bone, property_name):
        path_from_id = getattr(pose_bone, "path_from_id", None)
        if not callable(path_from_id):
            raise AgentError(
                ErrorCode.UNSUPPORTED_OPERATION,
                "Pose bone does not expose RNA path_from_id",
            )
        return bounded_text(path_from_id(property_name), limit=256)

    def _paths(self, pose_bone, rotation_mode):
        rotation_property = "rotation_euler" if rotation_mode == "XYZ" else "rotation_quaternion"
        return {
            "location": self._path(pose_bone, "location"),
            "rotation": self._path(pose_bone, rotation_property),
            "scale": self._path(pose_bone, "scale"),
        }

    @staticmethod
    def _channel_prefix(channel):
        return channel["data_path"].startswith('pose.bones["')

    def inspect(self, request: Request, action: PoseBoneAnimationInspect):
        obj = self.inspector.resolve(action.object_id)
        rig = self.rigging._snapshot(obj)
        pose_state = next(
            (item for item in rig["pose_bones"] if item["name"] == action.bone_name),
            None,
        )
        if pose_state is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone not found")
        pose_bone = self.rigging._pose_bone_object(obj, action.bone_name)
        if pose_bone is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone unavailable")

        animation = self._animation_state(action.object_id)
        paths = self._paths(pose_bone, pose_state["rotation_mode"])
        bone_paths = set(paths.values())
        all_bone_paths = {
            self._path(pose_bone, "location"),
            self._path(pose_bone, "rotation_euler"),
            self._path(pose_bone, "rotation_quaternion"),
            self._path(pose_bone, "scale"),
        }
        channels = [
            channel for channel in animation["channels"] if channel["data_path"] in bone_paths
        ]
        channels.sort(key=lambda item: (item["data_path"], item["index"]))
        frames = sorted({point["frame"] for channel in channels for point in channel["points"]})

        non_pose_channels = [
            channel["data_path"]
            for channel in animation["channels"]
            if not self._channel_prefix(channel)
        ]
        blockers = list(animation["blockers"])
        if non_pose_channels:
            blockers.append("NON_POSE_CHANNELS_PRESENT")
        alternate_channels = [
            channel["data_path"]
            for channel in animation["channels"]
            if channel["data_path"] in all_bone_paths and channel["data_path"] not in bone_paths
        ]
        if alternate_channels:
            blockers.append("ALTERNATE_ROTATION_CHANNELS_PRESENT")

        expected_curve_count = 9 if pose_state["rotation_mode"] == "XYZ" else 10
        if channels and len(channels) != expected_curve_count:
            blockers.append("PARTIAL_POSE_BONE_CHANNEL_SET")

        point_count = sum(channel["point_count"] for channel in channels)
        data = {
            "object_id": action.object_id,
            "bone_name": action.bone_name,
            "rig_revision": rig["rig_revision"],
            "animation_revision": animation["animation_revision"],
            "action_name": animation["action_name"],
            "action_users": animation["action_users"],
            "managed_session_action": animation["managed_session_action"],
            "rotation_mode": pose_state["rotation_mode"],
            "channel_count": len(channels),
            "expected_channel_count": expected_curve_count,
            "point_count": point_count,
            "unique_frames": frames,
            "channels": channels,
            "blockers": blockers,
            "managed_mutation_ready": not blockers,
            "raw_pose_channels_only": True,
            "constraint_count": pose_state["constraint_count"],
            "source_only": True,
            "real_runtime_verified": False,
        }
        data["pose_animation_revision"] = revision(
            {
                "bone_name": action.bone_name,
                "rig_revision": rig["rig_revision"],
                "animation_revision": animation["animation_revision"],
                "rotation_mode": pose_state["rotation_mode"],
                "channels": channels,
            }
        )
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    @staticmethod
    def _point_values(action):
        return {
            "location": list(action.location),
            "rotation": list(action.rotation),
            "scale": list(action.scale),
        }

    def _delete_inserted(self, pose_bone, rotation_mode, frame):
        rotation_property = "rotation_euler" if rotation_mode == "XYZ" else "rotation_quaternion"
        for property_name in ("location", rotation_property, "scale"):
            delete = getattr(pose_bone, "keyframe_delete", None)
            if not callable(delete):
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Pose bone rollback cannot delete inserted keyframes",
                )
            try:
                delete(data_path=property_name, frame=frame)
            except TypeError:
                delete(property_name, frame=frame)

    def _restore(
        self,
        obj,
        pose_bone,
        pose_before,
        rotation_mode,
        frame,
        action_was_absent,
        object_id,
    ):
        self._delete_inserted(pose_bone, rotation_mode, frame)
        if action_was_absent:
            clear = getattr(obj, "animation_data_clear", None)
            if not callable(clear):
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Animation rollback cannot clear newly created action",
                )
            clear()
            self.animation._owned_actions.pop(object_id, None)
        self.rigging._restore_pose_state(pose_bone, pose_before)
        self.bpy.context.view_layer.update()

    def insert(self, request: Request, action: PoseBoneKeyframeInsert):
        obj, object_before = self.inspector.target(action.target)
        if obj.type != "ARMATURE" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature object required")
        if (
            obj.library is not None
            or obj.override_library is not None
            or not obj.is_editable
            or self.bpy.context.mode != "OBJECT"
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe pose animation target")

        rig_before = self.rigging._snapshot(obj)
        require_revision(action.expected_rig_revision, rig_before["rig_revision"])
        pose_before = next(
            (item for item in rig_before["pose_bones"] if item["name"] == action.bone_name),
            None,
        )
        if pose_before is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone not found")
        pose_bone = self.rigging._pose_bone_object(obj, action.bone_name)
        if pose_bone is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone unavailable")

        animation_before = self._animation_state(action.target.object_id)
        require_revision(
            action.expected_animation_revision,
            animation_before["animation_revision"],
        )
        if animation_before["action_name"] is not None:
            if (
                not animation_before["managed_session_action"]
                or not animation_before["managed_mutation_ready"]
            ):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Only a session-created unshared pose Action may be extended",
                )
            if any(not self._channel_prefix(channel) for channel in animation_before["channels"]):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "Pose animation cannot share an Action with non-pose channels",
                )

        paths = self._paths(pose_bone, action.rotation_mode)
        current_paths = self._paths(pose_bone, pose_before["rotation_mode"])
        existing_bone_paths = {
            channel["data_path"]
            for channel in animation_before["channels"]
            if channel["data_path"]
            in {
                self._path(pose_bone, "location"),
                self._path(pose_bone, "rotation_euler"),
                self._path(pose_bone, "rotation_quaternion"),
                self._path(pose_bone, "scale"),
            }
        }
        if (
            existing_bone_paths
            and action.rotation_mode != pose_before["rotation_mode"]
            and current_paths["rotation"] in existing_bone_paths
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Existing pose animation rotation mode cannot be changed",
            )
        all_bone_paths = {
            self._path(pose_bone, "location"),
            self._path(pose_bone, "rotation_euler"),
            self._path(pose_bone, "rotation_quaternion"),
            self._path(pose_bone, "scale"),
        }
        if any(
            point["frame"] == float(action.frame)
            for channel in animation_before["channels"]
            if channel["data_path"] in all_bone_paths
            for point in channel["points"]
        ):
            raise AgentError(
                ErrorCode.AMBIGUOUS_TARGET,
                "Pose bone frame already has keys; overwrite is disabled",
            )

        values = self._point_values(action)
        expected_channels = {
            paths["location"]: values["location"],
            paths["rotation"]: values["rotation"],
            paths["scale"]: values["scale"],
        }
        existing_curve_keys = {
            (channel["data_path"], channel["index"]) for channel in animation_before["channels"]
        }
        required_curve_keys = {
            (data_path, index)
            for data_path, channel_values in expected_channels.items()
            for index in range(len(channel_values))
        }
        if len(existing_curve_keys | required_curve_keys) > MAX_ANIMATION_CURVES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pose animation curve limit exceeded")
        if animation_before["point_count"] + len(required_curve_keys) > MAX_ANIMATION_POINTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pose animation point limit exceeded")

        action_was_absent = animation_before["action_name"] is None
        changed = False
        try:
            pose_bone.location = list(action.location)
            pose_bone.scale = list(action.scale)
            pose_bone.rotation_mode = action.rotation_mode
            rotation_property = (
                "rotation_euler" if action.rotation_mode == "XYZ" else "rotation_quaternion"
            )
            setattr(pose_bone, rotation_property, list(action.rotation))
            changed = True

            for property_name in ("location", rotation_property, "scale"):
                if not pose_bone.keyframe_insert(data_path=property_name, frame=action.frame):
                    raise AgentError(
                        ErrorCode.EXECUTION_ERROR,
                        "Pose-bone keyframe insertion failed",
                    )
                self.animation._owned_actions[action.target.object_id] = obj.animation_data.action

            for curve in action_curves(obj):
                if curve.data_path not in expected_channels:
                    continue
                points = [
                    point
                    for point in curve.keyframe_points
                    if abs(float(point.co[0]) - float(action.frame)) < 1e-5
                ]
                if len(points) != 1:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "Inserted pose keyframe is not uniquely addressable",
                    )
                points[0].interpolation = action.interpolation
                curve.update()

            self.bpy.context.view_layer.update()
            animation_after = self._animation_state(action.target.object_id)
            rig_after = self.rigging._snapshot(obj)
            inserted = {}
            for channel in animation_after["channels"]:
                if channel["data_path"] not in expected_channels:
                    continue
                points = [
                    point for point in channel["points"] if point["frame"] == float(action.frame)
                ]
                if len(points) == 1:
                    inserted[f"{channel['data_path']}:{channel['index']}"] = points[0]

            expected_inserted = {
                f"{data_path}:{index}": {
                    "frame": float(action.frame),
                    "value": float(value),
                    "interpolation": action.interpolation,
                }
                for data_path, channel_values in expected_channels.items()
                for index, value in enumerate(channel_values)
            }
            actual_inserted = {
                key: {
                    "frame": value["frame"],
                    "value": value["value"],
                    "interpolation": value["interpolation"],
                }
                for key, value in inserted.items()
            }
            expected = {
                "inserted": expected_inserted,
                "action_owned": True,
                "animation_revision_changed": True,
                "pose": {
                    "rotation_mode": action.rotation_mode,
                    "location": list(action.location),
                    "scale": list(action.scale),
                    rotation_property: list(action.rotation),
                },
            }
            pose_after = next(
                item for item in rig_after["pose_bones"] if item["name"] == action.bone_name
            )
            actual = {
                "inserted": actual_inserted,
                "action_owned": (
                    self.animation._owned_actions.get(action.target.object_id)
                    is obj.animation_data.action
                ),
                "animation_revision_changed": (
                    animation_after["animation_revision"] != animation_before["animation_revision"]
                ),
                "pose": {
                    "rotation_mode": pose_after["rotation_mode"],
                    "location": pose_after["location"],
                    "scale": pose_after["scale"],
                    rotation_property: pose_after[rotation_property],
                },
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "object_before": object_before,
                        "rig_before": rig_before,
                        "rig_after": rig_after,
                        "animation_before": animation_before,
                        "animation_after": animation_after,
                        "bone_name": action.bone_name,
                        "frame": action.frame,
                    },
                    verification=verification.to_dict(),
                )

            self._restore(
                obj,
                pose_bone,
                pose_before,
                action.rotation_mode,
                action.frame,
                action_was_absent,
                action.target.object_id,
            )
            recovered_animation = self._animation_state(action.target.object_id)
            recovered_rig = self.rigging._snapshot(obj)
            recovery = compare(
                {
                    "animation_revision": animation_before["animation_revision"],
                    "rig_revision": rig_before["rig_revision"],
                },
                {
                    "animation_revision": recovered_animation["animation_revision"],
                    "rig_revision": recovered_rig["rig_revision"],
                },
            )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "object_before": object_before,
                    "rig_before": rig_before,
                    "animation_before": animation_before,
                    "animation_after": animation_after,
                    "rolled_back": True,
                    "recovery_verified": recovery.matched,
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Pose-bone animation readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if changed:
                try:
                    self._restore(
                        obj,
                        pose_bone,
                        pose_before,
                        action.rotation_mode,
                        action.frame,
                        action_was_absent,
                        action.target.object_id,
                    )
                except Exception:
                    pass
            raise

    def tools(self):
        return [
            Tool(
                "animation.pose_bone_inspect",
                SafetyClass.READ_ONLY,
                PoseBoneAnimationInspect.parse,
                self.inspect,
            ),
            Tool(
                "animation.pose_bone_keyframe_insert",
                SafetyClass.MUTATION,
                PoseBoneKeyframeInsert.parse,
                self.insert,
            ),
        ]
