"""Level 10 M1: owned WAVE modifier driving actual non-destructive Blender ripples.

Source-only verification; no depsgraph evaluation, frame stepping, rendering or baking.
"""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .verification import compare

MAX_SIM_MODIFIERS = 12

WAVE_PROPERTIES = (
    "height",
    "width",
    "speed",
    "narrowness",
    "time_offset",
    "start_position_x",
    "start_position_y",
    "use_x",
    "use_y",
    "use_cyclic",
)


def _wave_settings(payload):
    fields(
        payload,
        {
            "height",
            "width",
            "speed",
            "narrowness",
            "time_offset",
            "start_position_x",
            "start_position_y",
        },
        {"use_cyclic"},
    )
    return {
        "height": number(payload["height"], "height", -10, 10),
        "width": number(payload["width"], "width", 0.05, 100),
        "speed": number(payload["speed"], "speed", 0.01, 10),
        "narrowness": number(payload["narrowness"], "narrowness", 0.05, 10),
        "time_offset": number(payload["time_offset"], "time_offset", -1000, 1000),
        "start_position_x": number(payload["start_position_x"], "start_position_x", -100, 100),
        "start_position_y": number(payload["start_position_y"], "start_position_y", -100, 100),
        "use_x": True,
        "use_y": True,
        "use_cyclic": _bool(payload.get("use_cyclic", True)),
    }


def _bool(value):
    if type(value) is not bool:
        raise AgentError(ErrorCode.INVALID_REQUEST, "use_cyclic must be a boolean")
    return value


@dataclass(frozen=True)
class WavePreview:
    target: ObjectTarget
    name: str
    settings: dict

    @classmethod
    def parse(cls, payload):
        fields(payload, {"target", "name", "settings"})
        return cls(
            ObjectTarget.parse(payload["target"]),
            object_name(payload["name"]),
            _wave_settings(payload["settings"]),
        )


@dataclass(frozen=True)
class WaveApply:
    preview: WavePreview
    expected_wave_revision: str

    @classmethod
    def parse(cls, payload):
        fields(payload, {"target", "name", "settings", "expected_wave_revision"})
        return cls(
            WavePreview.parse({k: v for k, v in payload.items() if k != "expected_wave_revision"}),
            string(payload["expected_wave_revision"], "expected_wave_revision", limit=64),
        )


@dataclass(frozen=True)
class WaveRelease:
    expected_wave_token: str

    @classmethod
    def parse(cls, payload):
        fields(payload, {"expected_wave_token"})
        return cls(string(payload["expected_wave_token"], "expected_wave_token", limit=64))


class WaveSimulationOperations:
    """Session-scoped modifier lifecycle with exact real-bpy property readback."""

    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned = {}

    @staticmethod
    def _pointer(value):
        return int(value.as_pointer()) if hasattr(value, "as_pointer") else id(value)

    def _target(self, target):
        obj, before = self.inspector.target(target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data is None or obj.data.library is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local editable mesh required")
        if obj.data.shape_keys is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shape-key mesh is unsupported")
        if not 0 < len(obj.modifiers) + 1 <= MAX_SIM_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier work limit exceeded")
        if any(abs(float(x)) > 10000 for x in obj.dimensions):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Oversized mesh work area")
        return obj, before

    def _read(self, obj, mod):
        return {
            "name": mod.name,
            "type": mod.type,
            "show_viewport": bool(mod.show_viewport),
            "show_render": bool(mod.show_render),
            "properties": {
                prop: (
                    bool(getattr(mod, prop))
                    if prop in ("use_x", "use_y", "use_cyclic")
                    else float(getattr(mod, prop))
                )
                for prop in WAVE_PROPERTIES
            },
            "position": list(obj.modifiers).index(mod),
            "owned_object_id": self.inspector.identity(obj),
        }

    def _plan(self, action: WavePreview):
        obj, before = self._target(action.target)
        if obj.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already used")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Session simulation limit reached")
        scene_revision = self.inspector.summary()["revision"]
        plan = {
            "target_id": before["object_id"],
            "target_revision": before["revision"],
            "name": action.name,
            "kind": "WAVE",
            "settings": dict(action.settings),
            "modifier_index": len(obj.modifiers),
            "scene_revision": scene_revision,
            "source_only": True,
            "simulated_frames": 0,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["wave_revision"] = revision(plan)
        return obj, plan

    def preview(self, request: Request, action: WavePreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[1]
        )

    def apply(self, request: Request, action: WaveApply):
        obj, plan = self._plan(action.preview)
        if action.expected_wave_revision != plan["wave_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Wave simulation preview is stale")
        before_scene = plan["scene_revision"]
        mod = None
        try:
            mod = obj.modifiers.new(action.preview.name, "WAVE")
            for name, value in action.preview.settings.items():
                setattr(mod, name, value)
            mod.show_viewport = True
            mod.show_render = True
            self.bpy.context.view_layer.update()
            actual = self._read(obj, mod)
            expected = {
                "name": plan["name"],
                "type": "WAVE",
                "show_viewport": True,
                "show_render": True,
                "properties": plan["settings"],
                "position": plan["modifier_index"],
                "owned_object_id": plan["target_id"],
            }
            verified = compare(expected, actual)
            if verified.matched:
                token = revision({
                    "object": plan["target_id"],
                    "modifier": self._pointer(mod),
                    "plan": plan["wave_revision"],
                })
                self._owned[token] = {
                    "object": obj, "modifier": mod, "expected": expected,
                    "before_scene": before_scene,
                    "after_scene": self.inspector.summary()["revision"],
                }
                return Result(
                    request.request_id, request.command_id, Status.VERIFIED,
                    {
                        "wave_token": token,
                        "modifier_name": mod.name,
                        "simulation_type": "WAVE",
                        "source_only": True,
                        "simulated_frames": 0,
                        "render_verified": False,
                    },
                    verification=verified.to_dict(),
                )
        except Exception as exc:
            try:
                self._remove_owned(obj, mod, before_scene)
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Wave modifier recovery is uncertain"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Wave creation failed; original state restored"
            ) from exc
        self._remove_owned(obj, mod, before_scene)
        return Result(
            request.request_id, request.command_id, Status.FAILED,
            {"rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Wave modifier property mismatch"),
            verification=verified.to_dict(),
        )

    def _remove_owned(self, obj, mod, before_scene):
        if mod is not None and any(current is mod for current in obj.modifiers):
            obj.modifiers.remove(mod)
        self.bpy.context.view_layer.update()
        if (
            (mod is not None and any(current is mod for current in obj.modifiers))
            or self.inspector.summary()["revision"] != before_scene
        ):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Wave cleanup not verified")

    def release(self, request: Request, action: WaveRelease):
        owned = self._owned.get(action.expected_wave_token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or foreign wave token")
        obj, mod = owned["object"], owned["modifier"]
        if self.inspector.summary()["revision"] != owned["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed after wave setup")
        if (
            mod not in obj.modifiers
            or not compare(owned["expected"], self._read(obj, mod)).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Wave modifier changed externally")
        self._remove_owned(obj, mod, owned["before_scene"])
        del self._owned[action.expected_wave_token]
        return Result(
            request.request_id, request.command_id, Status.VERIFIED,
            {"removed_owned_wave": True, "restored_scene": True},
            verification=compare({"restored": True}, {"restored": True}).to_dict(),
        )

    def tools(self):
        return [
            Tool("vfx.wave_preview", SafetyClass.READ_ONLY, WavePreview.parse, self.preview),
            Tool("vfx.wave_apply", SafetyClass.MUTATION, WaveApply.parse, self.apply),
            Tool("vfx.wave_release", SafetyClass.MUTATION, WaveRelease.parse, self.release),
        ]
