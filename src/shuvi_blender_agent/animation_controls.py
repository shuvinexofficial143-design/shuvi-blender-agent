"""Level 7 milestone 7: bounded visibility and pose-constraint influence animation."""

from dataclasses import dataclass

from .animation import MAX_ANIMATION_POINTS, AnimationInspect, AnimationOperations
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text
from .models import ObjectTarget, object_name
from .rigging import RiggingOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

INTERPOLATIONS = {"CONSTANT", "LINEAR", "BEZIER"}
VISIBILITY_PATHS = ("hide_render", "hide_viewport")


@dataclass(frozen=True)
class ControlInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class ControlKeyframeInsert:
    target: ObjectTarget
    expected_animation_revision: str
    kind: str
    frame: int
    interpolation: str
    hide_render: bool | None
    hide_viewport: bool | None
    bone_name: str | None
    constraint_name: str | None
    expected_rig_revision: str | None
    influence: float | None

    @classmethod
    def parse(cls, data):
        common = {
            "target",
            "expected_animation_revision",
            "kind",
            "frame",
            "interpolation",
        }
        kind = data.get("kind") if isinstance(data, dict) else None
        if kind == "VISIBILITY":
            fields(data, common | {"hide_render", "hide_viewport"})
            hide_render = data["hide_render"]
            hide_viewport = data["hide_viewport"]
            if type(hide_render) is not bool or type(hide_viewport) is not bool:
                raise invalid("Visibility animation requires two explicit booleans")
            bone_name = constraint_name = expected_rig_revision = influence = None
        elif kind == "POSE_CONSTRAINT_INFLUENCE":
            fields(
                data,
                common
                | {
                    "bone_name",
                    "constraint_name",
                    "expected_rig_revision",
                    "influence",
                },
            )
            bone_name = object_name(data["bone_name"])
            constraint_name = object_name(data["constraint_name"])
            expected_rig_revision = string(
                data["expected_rig_revision"], "expected_rig_revision", limit=64
            )
            influence = number(data["influence"], "influence", 0, 1)
            hide_render = hide_viewport = None
        else:
            raise invalid("Unsupported animation control kind")
        interpolation = data["interpolation"]
        if type(interpolation) is not str or interpolation not in INTERPOLATIONS:
            raise invalid("Unsupported control interpolation")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_animation_revision"], "expected_animation_revision", limit=64),
            kind,
            integer(data["frame"], "frame", 1, 100_000),
            interpolation,
            hide_render,
            hide_viewport,
            bone_name,
            constraint_name,
            expected_rig_revision,
            influence,
        )


class AnimationControlOperations:
    def __init__(self, animation: AnimationOperations, rigging: RiggingOperations):
        self.animation = animation
        self.rigging = rigging
        self.inspector = animation.inspector
        self.bpy = animation.bpy
        self._owned_actions = {}

    def _state(self, object_id):
        result = self.animation.inspect(
            Request("animation.inspect", {"object_id": object_id}),
            AnimationInspect(object_id),
        )
        state = dict(result.data)
        obj = self.inspector.resolve(object_id)
        action = getattr(getattr(obj, "animation_data", None), "action", None)
        owned = action is not None and self._owned_actions.get(object_id) is action
        blockers = [
            item
            for item in state["blockers"]
            if not (item == "FOREIGN_ACTION" and owned)
        ]
        if action is not None and not owned:
            blockers.append("FOREIGN_CONTROL_ACTION")
        if action is not None and getattr(obj.animation_data, "action_slot", None) is not None:
            blockers.append("SLOTTED_ACTION_MUTATION_UNVERIFIED")
        for channel in state["channels"]:
            path = channel["data_path"]
            if path not in VISIBILITY_PATHS and not (
                path.startswith('pose.bones["')
                and '.constraints["' in path
                and path.endswith('"].influence')
                and channel["index"] == 0
            ):
                blockers.append("UNMANAGED_CONTROL_CHANNEL")
                break
        if len({(x["data_path"], x["index"]) for x in state["channels"]}) != len(
            state["channels"]
        ):
            blockers.append("DUPLICATE_CONTROL_CHANNELS")
        state["managed_control_action"] = owned
        state["control_blockers"] = sorted(set(blockers))
        state["managed_control_ready"] = not blockers
        if obj.type == "ARMATURE":
            state["rig_revision"] = self.rigging._snapshot(obj)["rig_revision"]
        else:
            state["rig_revision"] = None
        return state

    def inspect(self, request: Request, action: ControlInspect):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._state(action.object_id),
        )

    def _constraint(self, obj, action):
        if obj.type != "ARMATURE":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature required for pose constraint")
        rig = self.rigging._snapshot(obj)
        require_revision(action.expected_rig_revision, rig["rig_revision"])
        pose_state = next(
            (item for item in rig["pose_bones"] if item["name"] == action.bone_name),
            None,
        )
        if pose_state is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone not found")
        constraint_state = self.rigging._constraint_from_snapshot(
            pose_state, action.constraint_name
        )
        if constraint_state is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose constraint not found")
        if constraint_state["type"] not in ("IK", "LIMIT_ROTATION"):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported pose constraint type")
        self.rigging._validate_removable_constraint(constraint_state, obj)
        bone = self.rigging._pose_bone_object(obj, action.bone_name)
        constraint = self.rigging._constraint_object(bone, action.constraint_name)
        if constraint is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose constraint unavailable")
        path_from_id = getattr(constraint, "path_from_id", None)
        if not callable(path_from_id):
            raise AgentError(ErrorCode.UNSUPPORTED_OPERATION, "Constraint RNA path unavailable")
        path = bounded_text(path_from_id("influence"), limit=256)
        if not (
            path.startswith('pose.bones["')
            and '.constraints["' in path
            and path.endswith('"].influence')
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported constraint RNA path")
        return rig, constraint, path

    def _restore(self, obj, before_values, paths, frame, new_action, object_id):
        if new_action:
            obj.animation_data_clear()
            self._owned_actions.pop(object_id, None)
        else:
            for path in paths:
                obj.keyframe_delete(data_path=path, frame=frame)
        for holder, field, value in before_values:
            setattr(holder, field, value)
        self.bpy.context.view_layer.update()

    def insert(self, request: Request, action: ControlKeyframeInsert):
        obj, object_before = self.inspector.target(action.target)
        state = self._state(action.target.object_id)
        require_revision(action.expected_animation_revision, state["animation_revision"])
        if not state["managed_control_ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe control animation target")

        rig_before = None
        if action.kind == "VISIBILITY":
            paths = list(VISIBILITY_PATHS)
            values = [action.hide_render, action.hide_viewport]
            before_values = [(obj, path, bool(getattr(obj, path))) for path in paths]
        else:
            rig_before, constraint, path = self._constraint(obj, action)
            paths = [path]
            values = [action.influence]
            before_values = [(constraint, "influence", float(constraint.influence))]

        for channel in state["channels"]:
            if channel["data_path"] not in paths:
                continue
            if any(point["frame"] == float(action.frame) for point in channel["points"]):
                raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Control frame already keyed")
        if state["point_count"] + len(paths) > MAX_ANIMATION_POINTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Control animation point limit exceeded")
        new_action = obj.animation_data is None
        mutated = False
        try:
            mutated = True
            for path, value in zip(paths, values, strict=True):
                if action.kind == "VISIBILITY":
                    setattr(obj, path, value)
                else:
                    constraint.influence = value
                if not obj.keyframe_insert(data_path=path, frame=action.frame):
                    raise AgentError(ErrorCode.EXECUTION_ERROR, "Control key insertion failed")
                self._owned_actions[action.target.object_id] = obj.animation_data.action

            from .animation_state import action_curves

            for curve in action_curves(obj):
                if curve.data_path not in paths:
                    continue
                points = [
                    point
                    for point in curve.keyframe_points
                    if float(point.co[0]) == float(action.frame)
                ]
                if len(points) != 1:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Control point not uniquely addressable"
                    )
                points[0].interpolation = action.interpolation
                curve.update()
            self.bpy.context.view_layer.update()

            after = self._state(action.target.object_id)
            rig_after = self.rigging._snapshot(obj) if rig_before is not None else None
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
                if channel["data_path"] in paths
            }
            expected = {
                "inserted": {
                    path: [
                        {
                            "frame": float(action.frame),
                            "value": float(value),
                            "interpolation": action.interpolation,
                        }
                    ]
                    for path, value in zip(paths, values, strict=True)
                },
                "point_count": state["point_count"] + len(paths),
                "owned": True,
                "revision_changed": True,
                "values": [float(value) for value in values],
            }
            actual = {
                "inserted": inserted,
                "point_count": after["point_count"],
                "owned": after["managed_control_action"],
                "revision_changed": after["animation_revision"] != state["animation_revision"],
                "values": [
                    float(getattr(obj, path))
                    if action.kind == "VISIBILITY"
                    else float(constraint.influence)
                    for path in paths
                ],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": state,
                        "after": after,
                        "rig_before": rig_before,
                        "rig_after": rig_after,
                        "object_before": object_before,
                    },
                    verification=verification.to_dict(),
                )

            self._restore(
                obj, before_values, paths, action.frame, new_action, action.target.object_id
            )
            recovered = self._state(action.target.object_id)
            recovery = compare(
                {
                    "animation_revision": state["animation_revision"],
                    "rig_revision": rig_before["rig_revision"] if rig_before else None,
                },
                {
                    "animation_revision": recovered["animation_revision"],
                    "rig_revision": recovered["rig_revision"] if rig_before else None,
                },
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Control animation recovery could not be verified",
                )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": state,
                    "after": after,
                    "rolled_back": True,
                    "recovery_verified": True,
                },
                AgentError(ErrorCode.VERIFICATION_FAILED, "Control animation readback mismatch"),
                verification.to_dict(),
            )
        except Exception:
            if mutated:
                try:
                    self._restore(
                        obj, before_values, paths, action.frame, new_action, action.target.object_id
                    )
                except Exception:
                    pass
            raise

    def tools(self):
        return [
            Tool(
                "animation.control_inspect",
                SafetyClass.READ_ONLY,
                ControlInspect.parse,
                self.inspect,
            ),
            Tool(
                "animation.control_keyframe_insert",
                SafetyClass.MUTATION,
                ControlKeyframeInsert.parse,
                self.insert,
            ),
        ]
