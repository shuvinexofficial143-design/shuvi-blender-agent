"""Level 10 M6: real Cloth/Particle COLLISION mesh obstacle physics.

Uses Blender's CollisionModifier.settings RNA and M5 guarded owned-modifier
lifecycle. Source-side setup only; no solver frames or collision impacts tested.
"""

from dataclasses import dataclass

from .errors import AgentError, ErrorCode
from .models import ObjectTarget, object_name
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .vfx_cloth import ClothSimulationOperations

COLLISION_FIELDS = {
    "thickness_outer": ("settings", "thickness_outer"),
    "cloth_friction": ("settings", "cloth_friction"),
    "damping": ("settings", "damping"),
    "use_culling": ("settings", "use_culling"),
    "use_normal": ("settings", "use_normal"),
    "enabled": ("settings", "use"),
}


def _collision_settings(data):
    fields(
        data,
        {"thickness_outer", "cloth_friction", "damping", "use_culling", "use_normal"},
    )
    if type(data["use_culling"]) is not bool or type(data["use_normal"]) is not bool:
        raise AgentError(ErrorCode.INVALID_REQUEST, "Collision flags must be Boolean")
    return {
        "thickness_outer": number(data["thickness_outer"], "thickness_outer", 0.001, 1),
        "cloth_friction": number(data["cloth_friction"], "cloth_friction", 0, 80),
        "damping": number(data["damping"], "damping", 0, 1),
        "use_culling": data["use_culling"],
        "use_normal": data["use_normal"],
        "enabled": True,
    }


@dataclass(frozen=True)
class CollisionPreview:
    target: ObjectTarget
    name: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name", "settings"})
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["name"]),
            _collision_settings(data["settings"]),
        )


@dataclass(frozen=True)
class CollisionApply:
    preview: CollisionPreview
    expected_collision_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "name", "settings", "expected_collision_revision"})
        return cls(
            CollisionPreview.parse(
                {key: value for key, value in data.items() if key != "expected_collision_revision"}
            ),
            string(data["expected_collision_revision"], "expected_collision_revision", limit=64),
        )


@dataclass(frozen=True)
class CollisionRelease:
    expected_collision_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_collision_token"})
        return cls(string(data["expected_collision_token"], "expected_collision_token", limit=64))


class CollisionSimulationOperations(ClothSimulationOperations):
    kind = "COLLISION"
    config_fields = COLLISION_FIELDS
    int_fields = set()
    bool_fields = {"use_culling", "use_normal", "enabled"}
    marker = "collision"
    revision_key = "collision_revision"

    def preview(self, request, action: CollisionPreview):
        return self._preview_physics(request, action)

    def apply(self, request, action: CollisionApply):
        return self._apply_physics(request, action.preview, action.expected_collision_revision)

    def release(self, request, action: CollisionRelease):
        return self._release_physics(request, action.expected_collision_token)

    def tools(self):
        return [
            Tool(
                "vfx.collision_preview",
                SafetyClass.READ_ONLY,
                CollisionPreview.parse,
                self.preview,
            ),
            Tool(
                "vfx.collision_apply",
                SafetyClass.MUTATION,
                CollisionApply.parse,
                self.apply,
            ),
            Tool(
                "vfx.collision_release",
                SafetyClass.MUTATION,
                CollisionRelease.parse,
                self.release,
            ),
        ]
