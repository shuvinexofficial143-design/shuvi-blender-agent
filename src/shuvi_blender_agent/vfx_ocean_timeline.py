"""Level 10 M4: guarded Blender OceanModifier.time timeline keyframes.

Only brand-new animation on a previously unanimated owned Ocean object is accepted.
No simulation evaluation, bake or visual rendering is claimed.
"""

from dataclasses import dataclass

from .animation_state import action_curves
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, number, string
from .verification import compare
from .vfx_ocean import OceanSimulationOperations


@dataclass(frozen=True)
class OceanTimelinePreview:
    ocean_token: str
    points: tuple[tuple[int, float], ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_ocean_token", "keyframes"})
        points = data["keyframes"]
        if not isinstance(points, list) or not 2 <= len(points) <= 8:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Specify 2 to 8 Ocean timeline keys")
        checked = []
        for pair in points:
            if not isinstance(pair, list) or len(pair) != 2:
                raise AgentError(ErrorCode.INVALID_REQUEST, "Keyframes require [frame, time]")
            checked.append((integer(pair[0], "frame", 1, 10000), number(pair[1], "time", 0, 1000)))
        if any(
            right[0] <= left[0] or right[1] <= left[1]
            for left, right in zip(checked, checked[1:], strict=True)
        ):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Frame and Ocean time must increase")
        return cls(
            string(data["expected_ocean_token"], "expected_ocean_token", limit=64),
            tuple(checked),
        )


@dataclass(frozen=True)
class OceanTimelineApply:
    preview: OceanTimelinePreview
    expected_timeline_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_ocean_token", "keyframes", "expected_timeline_revision"})
        return cls(
            OceanTimelinePreview.parse(
                {k: value for k, value in data.items() if k != "expected_timeline_revision"}
            ),
            string(data["expected_timeline_revision"], "expected_timeline_revision", limit=64),
        )


@dataclass(frozen=True)
class OceanTimelineRestore:
    timeline_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_timeline_token"})
        return cls(string(data["expected_timeline_token"], "expected_timeline_token", limit=64))


class OceanTimelineOperations:
    def __init__(self, ocean: OceanSimulationOperations):
        self.ocean = ocean
        self.inspector = ocean.inspector
        self.bpy = ocean.bpy
        self._owned = {}

    def _plan(self, action: OceanTimelinePreview):
        owned = self.ocean._owned.get(action.ocean_token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Ocean token is unknown or foreign")
        obj, modifier = owned["object"], owned["modifier"]
        if owned.get("timeline_token") is not None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Existing owned Ocean animation must be restored"
            )
        if (
            obj.animation_data is not None
            or self.inspector.summary()["revision"] != owned["after_scene"]
            or modifier not in obj.modifiers
            or not compare(owned["expected"], self.ocean._read_ocean(obj, modifier)).matched
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Ocean modifier or animation was changed after setup",
            )
        scene = self.bpy.context.scene
        if action.points[0][0] < scene.frame_start or action.points[-1][0] > scene.frame_end:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Keys must lie inside scene frame range")
        planned = {
            "ocean_token": action.ocean_token,
            "object_id": self.inspector.identity(obj),
            "modifier_name": modifier.name,
            "keyframes": [[frame, time] for frame, time in action.points],
            "before_time": owned["expected"]["properties"]["time"],
            "before_scene": owned["after_scene"],
            "mutation_performed": False,
            "source_only": True,
            "evaluated_frames": 0,
            "render_verified": False,
        }
        planned["timeline_revision"] = revision(planned)
        return owned, planned

    @staticmethod
    def _get_curve(obj, modifier):
        animation = obj.animation_data
        if animation is None or animation.action is None:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Ocean keyframes not linked to object")
        path = modifier.path_from_id("time")
        curves = [curve for curve in action_curves(obj) if curve.data_path == path]
        if len(curves) != 1 or int(curves[0].array_index) != 0:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Ambiguous Ocean time F-Curve")
        return animation.action, curves[0]

    def _keys(self, obj, modifier):
        action, curve = self._get_curve(obj, modifier)
        return action, sorted(
            [[float(key.co[0]), float(key.co[1])] for key in curve.keyframe_points],
            key=lambda item: item[0],
        )

    def preview(self, request: Request, action: OceanTimelinePreview):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._plan(action)[1],
        )

    def _cleanup_action(self, obj, owned_action):
        # A preexisting action is never touched; preview refuses any such owner.
        animation = obj.animation_data
        if animation is not None and animation.action is not owned_action:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Foreign animation action appeared")
        if animation is not None:
            obj.animation_data_clear()
        if owned_action is not None and hasattr(self.bpy.data, "actions"):
            if owned_action in self.bpy.data.actions and owned_action.users == 0:
                self.bpy.data.actions.remove(owned_action)

    def apply(self, request: Request, action: OceanTimelineApply):
        owned, plan = self._plan(action.preview)
        if action.expected_timeline_revision != plan["timeline_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Ocean time-keyframe plan is stale")
        obj, mod = owned["object"], owned["modifier"]
        previous_time = owned["expected"]["properties"]["time"]
        previous_scene = owned["after_scene"]
        created_action = None
        try:
            for frame, ocean_time in action.preview.points:
                mod.time = ocean_time
                if mod.keyframe_insert(data_path="time", frame=frame) is not True:
                    raise AgentError(ErrorCode.EXECUTION_ERROR, "Ocean time key insertion failed")
            self.bpy.context.view_layer.update()
            created_action, actual = self._keys(obj, mod)
            expected = [[float(frame), time] for frame, time in action.preview.points]
            checked = compare({"keys": expected}, {"keys": actual})
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Ocean F-Curve readback mismatch")
            next_expected = {
                **owned["expected"],
                "properties": {
                    **owned["expected"]["properties"],
                    "time": action.preview.points[-1][1],
                },
            }
            if not compare(next_expected, self.ocean._read_ocean(obj, mod)).matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Ocean current time mismatch")
            token = revision(
                {
                    "ocean_token": action.preview.ocean_token,
                    "action": self.ocean._pointer(created_action),
                    "timeline_revision": plan["timeline_revision"],
                }
            )
            owned["expected"] = next_expected
            owned["after_scene"] = self.inspector.summary()["revision"]
            owned["timeline_token"] = token
            self._owned[token] = {
                "ocean_token": action.preview.ocean_token,
                "action": created_action,
                "expected_keys": expected,
                "previous_time": previous_time,
                "before_scene": previous_scene,
                "after_scene": owned["after_scene"],
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "timeline_token": token,
                    "keyframe_count": len(expected),
                    "animated_property": "OceanModifier.time",
                    "source_only": True,
                    "evaluated_frames": 0,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            if obj.animation_data is not None and created_action is None:
                created_action = obj.animation_data.action
            try:
                self._cleanup_action(obj, created_action)
                mod.time = previous_time
                self.bpy.context.view_layer.update()
                if (
                    obj.animation_data is not None
                    or self.inspector.summary()["revision"] != previous_scene
                    or not compare(owned["expected"], self.ocean._read_ocean(obj, mod)).matched
                ):
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Ocean animation rollback mismatch"
                    )
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Ocean animation recovery is uncertain"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Ocean timeline keying failed; prior state restored"
            ) from exc

    def restore(self, request: Request, action: OceanTimelineRestore):
        state = self._owned.get(action.timeline_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or expired timeline token")
        owned = self.ocean._owned.get(state["ocean_token"])
        if owned is None or owned.get("timeline_token") != action.timeline_token:
            raise AgentError(ErrorCode.STALE_STATE, "Ocean ownership changed")
        obj, mod = owned["object"], owned["modifier"]
        if self.inspector.summary()["revision"] != state["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene edited after animation creation")
        if not compare(owned["expected"], self.ocean._read_ocean(obj, mod)).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Ocean settings changed after animation")
        attached_action, current_keys = self._keys(obj, mod)
        if (
            attached_action is not state["action"]
            or not compare({"keys": state["expected_keys"]}, {"keys": current_keys}).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Ocean timeline keys changed externally")
        self._cleanup_action(obj, state["action"])
        mod.time = state["previous_time"]
        self.bpy.context.view_layer.update()
        previous_expected = {
            **owned["expected"],
            "properties": {**owned["expected"]["properties"], "time": state["previous_time"]},
        }
        if (
            obj.animation_data is not None
            or not compare(previous_expected, self.ocean._read_ocean(obj, mod)).matched
            or self.inspector.summary()["revision"] != state["before_scene"]
        ):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Ocean timeline recovery mismatch")
        owned["expected"] = previous_expected
        owned["after_scene"] = state["before_scene"]
        owned.pop("timeline_token")
        del self._owned[action.timeline_token]
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"timeline_restored": True, "source_only": True, "render_verified": False},
            verification=compare({"restored": True}, {"restored": True}).to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "vfx.ocean_timeline_preview",
                SafetyClass.READ_ONLY,
                OceanTimelinePreview.parse,
                self.preview,
            ),
            Tool(
                "vfx.ocean_timeline_apply",
                SafetyClass.MUTATION,
                OceanTimelineApply.parse,
                self.apply,
            ),
            Tool(
                "vfx.ocean_timeline_restore",
                SafetyClass.MUTATION,
                OceanTimelineRestore.parse,
                self.restore,
            ),
        ]
