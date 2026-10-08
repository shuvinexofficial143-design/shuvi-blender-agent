"""Level 7 milestone 6: bounded camera lens and depth-of-field focus animation."""

from dataclasses import dataclass

from .animation import MAX_ANIMATION_AUX_ITEMS, MAX_ANIMATION_CURVES, MAX_ANIMATION_POINTS
from .animation_state import action_curves
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .models import ObjectTarget
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

OPTICS_PATHS = ("lens", "dof.focus_distance")
OPTICS_INTERPOLATIONS = ("LINEAR", "BEZIER", "CONSTANT")


@dataclass(frozen=True)
class CameraAnimationInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class CameraOpticsKeyframeInsert:
    target: ObjectTarget
    expected_camera_animation_revision: str
    frame: int
    lens: float
    focus_distance: float
    interpolation: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_camera_animation_revision",
                "frame",
                "lens",
                "focus_distance",
                "interpolation",
            },
        )
        interpolation = data["interpolation"]
        if type(interpolation) is not str or interpolation not in OPTICS_INTERPOLATIONS:
            raise invalid("Unsupported camera optics interpolation")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_camera_animation_revision"],
                "expected_camera_animation_revision",
                limit=64,
            ),
            integer(data["frame"], "frame", 1, 100_000),
            number(data["lens"], "lens", 1.0, 500.0),
            number(data["focus_distance"], "focus_distance", 0.01, 10_000.0),
            interpolation,
        )


class CameraAnimationOperations:
    def __init__(self, objects):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned_actions = {}

    @staticmethod
    def _camera(obj):
        if obj.type != "CAMERA" or getattr(obj, "data", None) is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera object required")
        camera = obj.data
        if camera.type != "PERSP" or getattr(camera, "dof", None) is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Perspective camera with DOF required")
        return camera

    def _state(self, obj):
        camera = self._camera(obj)
        dof = camera.dof
        ad = getattr(camera, "animation_data", None)
        action = getattr(ad, "action", None) if ad is not None else None
        curves = action_curves(camera)
        if len(curves) > MAX_ANIMATION_CURVES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera Action has too many FCurves")
        channels = []
        point_count = 0
        unexpected = False
        for curve in curves:
            path = bounded_text(curve.data_path, limit=256)
            index = curve.array_index
            if type(index) is not int or not 0 <= index <= 1024:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid camera FCurve channel index")
            if path not in OPTICS_PATHS or index != 0:
                unexpected = True
            if len(curve.keyframe_points) > 256:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Camera FCurve point limit exceeded")
            points = []
            for point in curve.keyframe_points:
                frame, value = (float(item) for item in point.co)
                if not (-float("inf") < frame < float("inf")):
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid camera keyframe")
                if not (-float("inf") < value < float("inf")):
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid camera keyframe")
                points.append(
                    {
                        "frame": frame,
                        "value": value,
                        "interpolation": bounded_text(point.interpolation, limit=32),
                        "easing": bounded_text(getattr(point, "easing", "AUTO"), limit=32),
                        "handle_left": list(getattr(point, "handle_left", point.co)),
                        "handle_right": list(getattr(point, "handle_right", point.co)),
                        "handle_left_type": bounded_text(
                            getattr(point, "handle_left_type", "AUTO"), limit=32
                        ),
                        "handle_right_type": bounded_text(
                            getattr(point, "handle_right_type", "AUTO"), limit=32
                        ),
                    }
                )
                point_count += 1
                if point_count > MAX_ANIMATION_POINTS:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Camera Action point limit exceeded")
            channels.append({"data_path": path, "index": index, "points": points})
        channels.sort(key=lambda item: (item["data_path"], item["index"]))

        drivers_count = len(getattr(ad, "drivers", ())) if ad is not None else 0
        nla_count = len(getattr(ad, "nla_tracks", ())) if ad is not None else 0
        if max(drivers_count, nla_count) > MAX_ANIMATION_AUX_ITEMS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera animation auxiliary limit exceeded")

        owned = action is not None and self._owned_actions.get(
            self.inspector.identity(obj)
        ) is action
        users = getattr(action, "users", 0) if action is not None else 0
        if type(users) is not int or users < 0:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid camera Action user count")
        blockers = []
        if (
            obj.library is not None
            or obj.override_library is not None
            or not obj.is_editable
            or getattr(camera, "library", None) is not None
        ):
            blockers.append("NONLOCAL_OR_READ_ONLY_CAMERA")
        if getattr(camera, "users", 0) != 1:
            blockers.append("SHARED_CAMERA_DATABLOCK")
        if self.bpy.context.mode != "OBJECT":
            blockers.append("OBJECT_MODE_REQUIRED")
        if len(obj.constraints):
            blockers.append("CAMERA_OBJECT_CONSTRAINTS_PRESENT")
        if not dof.use_dof:
            blockers.append("DEPTH_OF_FIELD_DISABLED")
        if getattr(dof, "focus_object", None) is not None:
            blockers.append("FOCUS_OBJECT_OVERRIDES_DISTANCE")
        if ad is not None and action is None:
            blockers.append("UNMANAGED_EMPTY_ANIMATION_DATA")
        if action is not None and not owned:
            blockers.append("FOREIGN_CAMERA_ACTION")
        if action is not None and users != 1:
            blockers.append("SHARED_CAMERA_ACTION")
        if getattr(ad, "action_slot", None) is not None:
            blockers.append("SLOTTED_CAMERA_ACTION_MUTATION_UNVERIFIED")
        if drivers_count or nla_count:
            blockers.append("DRIVERS_OR_NLA_PRESENT")
        if unexpected:
            blockers.append("UNMANAGED_CAMERA_CHANNELS")
        if len({(item["data_path"], item["index"]) for item in channels}) != len(channels):
            blockers.append("DUPLICATE_CAMERA_CHANNELS")
        if channels and {(item["data_path"], item["index"]) for item in channels} != {
            ("lens", 0),
            ("dof.focus_distance", 0),
        }:
            blockers.append("PARTIAL_CAMERA_CHANNELS")
        if len(channels) == 2:
            left, right = channels
            if len(left["points"]) != len(right["points"]) or {
                point["frame"] for point in left["points"]
            } != {point["frame"] for point in right["points"]}:
                blockers.append("INCOMPLETE_CAMERA_FRAME_PAIR")

        state = {
            "object_id": self.inspector.identity(obj),
            "camera_name": bounded_text(camera.name, limit=256),
            "lens": float(camera.lens),
            "focus_distance": float(dof.focus_distance),
            "dof_enabled": bool(dof.use_dof),
            "focus_object_present": getattr(dof, "focus_object", None) is not None,
            "camera_data_users": camera.users,
            "action_name": bounded_text(action.name, limit=256) if action is not None else None,
            "action_users": users,
            "managed_session_action": owned,
            "channels": channels,
            "curve_count": len(channels),
            "point_count": point_count,
            "drivers_count": drivers_count,
            "nla_track_count": nla_count,
            "blockers": blockers,
            "managed_mutation_ready": not blockers,
            "source_only": True,
            "real_runtime_verified": False,
        }
        state["camera_animation_revision"] = revision(
            {
                "camera_name": state["camera_name"],
                "lens": state["lens"],
                "focus_distance": state["focus_distance"],
                "dof_enabled": state["dof_enabled"],
                "focus_object_present": state["focus_object_present"],
                "camera_data_users": state["camera_data_users"],
                "action_name": state["action_name"],
                "action_users": users,
                "channels": channels,
                "drivers_count": drivers_count,
                "nla_count": nla_count,
            }
        )
        return state

    def inspect(self, request: Request, action: CameraAnimationInspect):
        obj = self.inspector.resolve(action.object_id)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, self._state(obj))

    def _restore(self, camera, old_lens, old_focus, frame, was_empty, object_id):
        if was_empty:
            camera.animation_data_clear()
            self._owned_actions.pop(object_id, None)
        else:
            for path in OPTICS_PATHS:
                camera.keyframe_delete(data_path=path, frame=frame)
        camera.lens = old_lens
        camera.dof.focus_distance = old_focus
        self.bpy.context.view_layer.update()

    def insert(self, request: Request, action: CameraOpticsKeyframeInsert):
        obj, object_before = self.inspector.target(action.target)
        before = self._state(obj)
        require_revision(
            action.expected_camera_animation_revision,
            before["camera_animation_revision"],
        )
        if not before["managed_mutation_ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera animation safety blockers present")
        if any(
            point["frame"] == float(action.frame)
            for channel in before["channels"]
            for point in channel["points"]
        ):
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Camera optics keyframe already exists")
        if before["point_count"] + 2 > MAX_ANIMATION_POINTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera animation point limit exceeded")

        camera = obj.data
        old_lens, old_focus = before["lens"], before["focus_distance"]
        was_empty = camera.animation_data is None
        changed = False
        try:
            changed = True
            camera.lens = action.lens
            camera.dof.focus_distance = action.focus_distance
            for path in OPTICS_PATHS:
                if not camera.keyframe_insert(data_path=path, frame=action.frame):
                    raise AgentError(
                        ErrorCode.EXECUTION_ERROR, "Camera optics key insertion failed"
                    )
                self._owned_actions[action.target.object_id] = camera.animation_data.action
            for curve in action_curves(camera):
                if curve.data_path not in OPTICS_PATHS or curve.array_index != 0:
                    continue
                matched = [
                    point for point in curve.keyframe_points
                    if float(point.co[0]) == float(action.frame)
                ]
                if len(matched) != 1:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Camera optics key not uniquely addressable"
                    )
                matched[0].interpolation = action.interpolation
                curve.update()
            self.bpy.context.view_layer.update()
            after = self._state(obj)
            inserted = {
                channel["data_path"]: [
                    {
                        "frame": point["frame"],
                        "value": point["value"],
                        "interpolation": point["interpolation"],
                    }
                    for point in channel["points"]
                    if point["frame"] == float(action.frame)
                ]
                for channel in after["channels"]
            }
            expected = {
                "inserted": {
                    "lens": [
                        {
                            "frame": float(action.frame),
                            "value": action.lens,
                            "interpolation": action.interpolation,
                        }
                    ],
                    "dof.focus_distance": [
                        {
                            "frame": float(action.frame),
                            "value": action.focus_distance,
                            "interpolation": action.interpolation,
                        }
                    ],
                },
                "point_count": before["point_count"] + 2,
                "lens": action.lens,
                "focus_distance": action.focus_distance,
                "action_owned": True,
                "revision_changed": True,
            }
            actual = {
                "inserted": inserted,
                "point_count": after["point_count"],
                "lens": after["lens"],
                "focus_distance": after["focus_distance"],
                "action_owned": after["managed_session_action"],
                "revision_changed": (
                    after["camera_animation_revision"] != before["camera_animation_revision"]
                ),
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "object_before": object_before,
                        "before": before,
                        "after": after,
                    },
                    verification=verification.to_dict(),
                )

            self._restore(
                camera,
                old_lens,
                old_focus,
                action.frame,
                was_empty,
                action.target.object_id,
            )
            recovered = self._state(obj)
            recovery = compare(
                {"revision": before["camera_animation_revision"]},
                {"revision": recovered["camera_animation_revision"]},
            )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "rolled_back": True,
                    "recovery_verified": recovery.matched,
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Camera optics readback differs from requested"
                ),
                verification.to_dict(),
            )
        except Exception:
            if changed:
                try:
                    self._restore(
                        camera,
                        old_lens,
                        old_focus,
                        action.frame,
                        was_empty,
                        action.target.object_id,
                    )
                except Exception:
                    pass
            raise

    def tools(self):
        return [
            Tool(
                "camera.optics_animation_inspect",
                SafetyClass.READ_ONLY,
                CameraAnimationInspect.parse,
                self.inspect,
            ),
            Tool(
                "camera.optics_keyframe_insert",
                SafetyClass.MUTATION,
                CameraOpticsKeyframeInsert.parse,
                self.insert,
            ),
        ]
