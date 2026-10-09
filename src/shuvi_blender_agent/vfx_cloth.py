"""Level 10 M5: owned Blender Cloth physics modifier with direct RNA readback.

Blender 4.2 ClothModifier.settings and collision_settings (readonly nested structs).
No animation baking, time stepping, visual verification or solver execution is claimed.
"""

from dataclasses import dataclass
from math import isfinite

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, object_name
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, number, string
from .verification import compare
from .vfx_wave import WaveSimulationOperations

CLOTH_FIELDS = {
    "quality": ("settings", "quality"),
    "mass": ("settings", "mass"),
    "air_damping": ("settings", "air_damping"),
    "tension_stiffness": ("settings", "tension_stiffness"),
    "bending_stiffness": ("settings", "bending_stiffness"),
    "self_collision": ("collision_settings", "use_self_collision"),
    "collision_distance": ("collision_settings", "distance_min"),
    "pin_group": ("settings", "vertex_group_mass"),
    "pin_stiffness": ("settings", "pin_stiffness"),
}
CLOTH_INT = {"quality"}
CLOTH_BOOL = {"self_collision"}


def _cloth_settings(data):
    fields(data, set(CLOTH_FIELDS) - {"pin_group", "pin_stiffness"}, {"pin_group", "pin_stiffness"})
    if ("pin_group" in data) != ("pin_stiffness" in data):
        raise AgentError(ErrorCode.INVALID_REQUEST, "Pin group and stiffness must be paired")
    if type(data["self_collision"]) is not bool:
        raise AgentError(ErrorCode.INVALID_REQUEST, "self_collision must be Boolean")
    return {
        "quality": integer(data["quality"], "quality", 2, 20),
        "mass": number(data["mass"], "mass", 0.01, 10),
        "air_damping": number(data["air_damping"], "air_damping", 0, 10),
        "tension_stiffness": number(data["tension_stiffness"], "tension_stiffness", 0, 500),
        "bending_stiffness": number(data["bending_stiffness"], "bending_stiffness", 0, 500),
        "self_collision": data["self_collision"],
        "collision_distance": number(data["collision_distance"], "collision_distance", 0.001, 0.1),
        "pin_group": string(data["pin_group"], "pin_group", limit=64)
        if "pin_group" in data
        else "",
        "pin_stiffness": number(data["pin_stiffness"], "pin_stiffness", 0, 50)
        if "pin_stiffness" in data
        else 1.0,
    }


@dataclass(frozen=True)
class ClothPreview:
    target: ObjectTarget
    name: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name", "settings"})
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["name"]),
            _cloth_settings(data["settings"]),
        )


@dataclass(frozen=True)
class ClothApply:
    preview: ClothPreview
    expected_cloth_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name", "settings", "expected_cloth_revision"})
        return cls(
            ClothPreview.parse(
                {key: value for key, value in data.items() if key != "expected_cloth_revision"}
            ),
            string(data["expected_cloth_revision"], "expected_cloth_revision", limit=64),
        )


@dataclass(frozen=True)
class ClothRelease:
    expected_cloth_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_cloth_token"})
        return cls(string(data["expected_cloth_token"], "expected_cloth_token", limit=64))


class ClothSimulationOperations(WaveSimulationOperations):
    kind = "CLOTH"
    config_fields = CLOTH_FIELDS
    int_fields = CLOTH_INT
    bool_fields = CLOTH_BOOL
    string_fields = {"pin_group"}
    marker = "cloth"
    revision_key = "cloth_revision"

    def _read_physics(self, obj, mod):
        read = {}
        for alias, (group, property_name) in self.config_fields.items():
            value = getattr(getattr(mod, group), property_name)
            if alias in self.string_fields:
                read[alias] = str(value)
            elif alias in self.bool_fields:
                read[alias] = bool(value)
            elif alias in self.int_fields:
                read[alias] = int(value)
            else:
                read[alias] = float(value)
        return {
            "name": mod.name,
            "type": mod.type,
            "show_viewport": bool(mod.show_viewport),
            "show_render": bool(mod.show_render),
            "settings": read,
            "position": list(obj.modifiers).index(mod),
            "owned_object_id": self.inspector.identity(obj),
        }

    def _pin_signature(self, obj, group_name):
        """Fingerprint existing mesh weights without changing vertex groups."""
        group = obj.vertex_groups.get(group_name)
        if group is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pin vertex group not found")
        vertices = obj.data.vertices
        if not 0 < len(vertices) <= 12000:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pinned mesh vertex limit exceeded")
        weights = []
        for index, vertex in enumerate(vertices):
            for member in vertex.groups:
                if member.group == group.index:
                    weight = float(member.weight)
                    if not isfinite(weight) or not 0 <= weight <= 1:
                        raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe pin vertex weight")
                    if weight > 0:
                        weights.append((index, weight))
        if not weights:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pin group has no weighted vertices")
        return revision({"group": group.name, "index": group.index, "weights": weights})

    def _plan_physics(self, action):
        obj, before = self._target(action.target)
        if obj.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name is already present")
        if any(mod.type == self.kind for mod in obj.modifiers):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Duplicate physics modifiers are not supported"
            )
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Active physics modifier limit exceeded")
        planned = {
            "target_id": before["object_id"],
            "target_revision": before["revision"],
            "name": action.name,
            "kind": self.kind,
            "settings": dict(action.settings),
            "modifier_index": len(obj.modifiers),
            "scene_revision": self.inspector.summary()["revision"],
            "source_only": True,
            "evaluated_frames": 0,
            "render_verified": False,
            "mutation_performed": False,
        }
        if action.settings.get("pin_group"):
            planned["pin_group_signature"] = self._pin_signature(
                obj, action.settings["pin_group"]
            )
        planned[self.revision_key] = revision(planned)
        return obj, planned

    def _preview_physics(self, request, action):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._plan_physics(action)[1],
        )

    def _apply_physics(self, request, action, expected_revision):
        obj, plan = self._plan_physics(action)
        if plan[self.revision_key] != expected_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Physics preview revision has changed")
        mod = None
        before = plan["scene_revision"]
        try:
            mod = obj.modifiers.new(action.name, self.kind)
            for alias, value in action.settings.items():
                group, property_name = self.config_fields[alias]
                setattr(getattr(mod, group), property_name, value)
            mod.show_viewport = True
            mod.show_render = True
            self.bpy.context.view_layer.update()
            expected = {
                "name": plan["name"],
                "type": self.kind,
                "show_viewport": True,
                "show_render": True,
                "settings": plan["settings"],
                "position": plan["modifier_index"],
                "owned_object_id": plan["target_id"],
            }
            checked = compare(expected, self._read_physics(obj, mod))
            if checked.matched:
                token = revision(
                    {
                        "target": plan["target_id"],
                        "kind": self.kind,
                        "modifier": self._pointer(mod),
                        "plan": plan[self.revision_key],
                    }
                )
                self._owned[token] = {
                    "pin_group": action.settings.get("pin_group", ""),
                    "pin_signature": plan.get("pin_group_signature"),
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
                        f"{self.marker}_token": token,
                        "modifier_name": mod.name,
                        "simulation_type": self.kind,
                        "source_only": True,
                        "evaluated_frames": 0,
                        "render_verified": False,
                    },
                    verification=checked.to_dict(),
                )
        except Exception as exc:
            try:
                self._remove_owned(obj, mod, before)
            except Exception as restore_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Physics modifier recovery is uncertain"
                ) from restore_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Physics setup failed; earlier state restored"
            ) from exc
        self._remove_owned(obj, mod, before)
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Physics readback failed"),
            verification=checked.to_dict(),
        )

    def _release_physics(self, request, token):
        owned = self._owned.get(token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or foreign physics token")
        obj, mod = owned["object"], owned["modifier"]
        if owned.get("pin_group"):
            if self._pin_signature(obj, owned["pin_group"]) != owned["pin_signature"]:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Pinned vertex weights changed")
        if self.inspector.summary()["revision"] != owned["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed since physics setup")
        if mod not in obj.modifiers:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Owned modifier was removed externally")
        if not compare(owned["expected"], self._read_physics(obj, mod)).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Physics modifier was changed externally")
        self._remove_owned(obj, mod, owned["before_scene"])
        del self._owned[token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"removed_owned_modifier": True, "restored_scene": True, "source_only": True},
            verification=checked.to_dict(),
        )

    def preview(self, request: Request, action: ClothPreview):
        return self._preview_physics(request, action)

    def apply(self, request: Request, action: ClothApply):
        return self._apply_physics(request, action.preview, action.expected_cloth_revision)

    def release(self, request: Request, action: ClothRelease):
        return self._release_physics(request, action.expected_cloth_token)

    def tools(self):
        return [
            Tool("vfx.cloth_preview", SafetyClass.READ_ONLY, ClothPreview.parse, self.preview),
            Tool("vfx.cloth_apply", SafetyClass.MUTATION, ClothApply.parse, self.apply),
            Tool("vfx.cloth_release", SafetyClass.MUTATION, ClothRelease.parse, self.release),
        ]
