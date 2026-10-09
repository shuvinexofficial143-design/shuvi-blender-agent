"""Level 10 M2: bounded, source-verified OCEAN surface simulation modifier."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, object_name
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, number, string
from .verification import compare
from .vfx_wave import WaveSimulationOperations

OCEAN_PROPERTIES = (
    "resolution",
    "spatial_size",
    "wave_scale",
    "wave_alignment",
    "wave_direction",
    "choppiness",
    "wind_velocity",
    "random_seed",
    "time",
)


def _ocean_settings(data):
    fields(data, set(OCEAN_PROPERTIES))
    return {
        "resolution": integer(data["resolution"], "resolution", 2, 16),
        "spatial_size": number(data["spatial_size"], "spatial_size", 1, 200),
        "wave_scale": number(data["wave_scale"], "wave_scale", 0.01, 3),
        "wave_alignment": number(data["wave_alignment"], "wave_alignment", 0, 1),
        "wave_direction": number(data["wave_direction"], "wave_direction", -3.14159, 3.14159),
        "choppiness": number(data["choppiness"], "choppiness", 0, 3),
        "wind_velocity": number(data["wind_velocity"], "wind_velocity", 0.1, 40),
        "random_seed": integer(data["random_seed"], "random_seed", 0, 1000),
        "time": number(data["time"], "time", 0, 1000),
    }


@dataclass(frozen=True)
class OceanPreview:
    target: ObjectTarget
    name: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name", "settings"})
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["name"]),
            _ocean_settings(data["settings"]),
        )


@dataclass(frozen=True)
class OceanApply:
    preview: OceanPreview
    expected_ocean_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name", "settings", "expected_ocean_revision"})
        return cls(
            OceanPreview.parse({k: v for k, v in data.items() if k != "expected_ocean_revision"}),
            string(data["expected_ocean_revision"], "expected_ocean_revision", limit=64),
        )


@dataclass(frozen=True)
class OceanRelease:
    expected_ocean_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_ocean_token"})
        return cls(string(data["expected_ocean_token"], "expected_ocean_token", limit=64))


class OceanSimulationOperations(WaveSimulationOperations):
    """Real Blender OCEAN modifier with standalone session-owned lifecycle."""

    def _read_ocean(self, obj, modifier):
        return {
            "name": modifier.name,
            "type": modifier.type,
            "geometry_mode": str(modifier.geometry_mode),
            "show_viewport": bool(modifier.show_viewport),
            "show_render": bool(modifier.show_render),
            "properties": {
                prop: (
                    int(getattr(modifier, prop))
                    if prop in ("resolution", "random_seed")
                    else float(getattr(modifier, prop))
                )
                for prop in OCEAN_PROPERTIES
            },
            "position": list(obj.modifiers).index(modifier),
            "owned_object_id": self.inspector.identity(obj),
        }

    def _plan_ocean(self, action: OceanPreview):
        obj, before = self._target(action.target)
        if obj.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Ocean modifier name collision")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Simulation ownership limit reached")
        plan = {
            "target_id": before["object_id"],
            "target_revision": before["revision"],
            "name": action.name,
            "kind": "OCEAN",
            "geometry_mode": "GENERATE",
            "settings": dict(action.settings),
            "modifier_index": len(obj.modifiers),
            "scene_revision": self.inspector.summary()["revision"],
            "source_only": True,
            "simulated_frames": 0,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["ocean_revision"] = revision(plan)
        return obj, plan

    def ocean_preview(self, request: Request, action: OceanPreview):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._plan_ocean(action)[1],
        )

    def ocean_apply(self, request: Request, action: OceanApply):
        obj, plan = self._plan_ocean(action.preview)
        if plan["ocean_revision"] != action.expected_ocean_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Ocean preview is stale")
        mod = None
        before = plan["scene_revision"]
        try:
            mod = obj.modifiers.new(action.preview.name, "OCEAN")
            mod.geometry_mode = "GENERATE"
            for name, value in action.preview.settings.items():
                setattr(mod, name, value)
            mod.show_viewport = True
            mod.show_render = True
            self.bpy.context.view_layer.update()
            actual = self._read_ocean(obj, mod)
            expected = {
                "name": plan["name"],
                "type": "OCEAN",
                "geometry_mode": "GENERATE",
                "show_viewport": True,
                "show_render": True,
                "properties": plan["settings"],
                "position": plan["modifier_index"],
                "owned_object_id": plan["target_id"],
            }
            checked = compare(expected, actual)
            if checked.matched:
                token = revision(
                    {
                        "target": plan["target_id"],
                        "modifier": self._pointer(mod),
                        "plan": plan["ocean_revision"],
                    }
                )
                self._owned[token] = {
                    "object": obj,
                    "modifier": mod,
                    "expected": expected,
                    "before_scene": before,
                    "after_scene": self.inspector.summary()["revision"],
                }
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "ocean_token": token,
                        "modifier_name": mod.name,
                        "simulation_type": "OCEAN",
                        "source_only": True,
                        "simulated_frames": 0,
                        "render_verified": False,
                    },
                    verification=checked.to_dict(),
                )
        except Exception as exc:
            try:
                self._remove_owned(obj, mod, before)
            except Exception as rollback:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Ocean rollback not verified"
                ) from rollback
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Ocean setup failed; original state restored"
            ) from exc
        self._remove_owned(obj, mod, before)
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Ocean property readback mismatch"),
            checked.to_dict(),
        )

    def ocean_release(self, request: Request, action: OceanRelease):
        state = self._owned.get(action.expected_ocean_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or foreign ocean token")
        obj, mod = state["object"], state["modifier"]
        if self.inspector.summary()["revision"] != state["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed since ocean creation")
        if (
            mod not in obj.modifiers
            or not compare(state["expected"], self._read_ocean(obj, mod)).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Ocean was changed or replaced")
        self._remove_owned(obj, mod, state["before_scene"])
        del self._owned[action.expected_ocean_token]
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"removed_owned_ocean": True, "restored_scene": True},
            verification=compare({"restored": True}, {"restored": True}).to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "vfx.ocean_preview",
                SafetyClass.READ_ONLY,
                OceanPreview.parse,
                self.ocean_preview,
            ),
            Tool("vfx.ocean_apply", SafetyClass.MUTATION, OceanApply.parse, self.ocean_apply),
            Tool("vfx.ocean_release", SafetyClass.MUTATION, OceanRelease.parse, self.ocean_release),
        ]
