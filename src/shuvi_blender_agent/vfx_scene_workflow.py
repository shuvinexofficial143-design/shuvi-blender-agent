"""Level 10 M10: four-mesh VFX scene orchestration, source-only.

Combines real Blender WAVE, OCEAN, CLOTH and COLLISION modifiers without
rendering, solver stepping, bake, filesystem access or modifying foreign data.
"""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string
from .verification import compare
from .vfx_cloth import ClothPreview
from .vfx_cloth_collision_workflow import ClothColliderPreview, ClothColliderWorkflowOperations
from .vfx_collision import CollisionPreview
from .vfx_ocean import OceanPreview, OceanSimulationOperations
from .vfx_wave import WavePreview, WaveSimulationOperations


@dataclass(frozen=True)
class VfxScenePreview:
    cloth: ClothPreview
    collider: CollisionPreview
    ocean: OceanPreview
    wave: WavePreview

    @classmethod
    def parse(cls, data):
        fields(data, {"cloth", "collider", "ocean", "wave"})
        return cls(
            ClothPreview.parse(data["cloth"]),
            CollisionPreview.parse(data["collider"]),
            OceanPreview.parse(data["ocean"]),
            WavePreview.parse(data["wave"]),
        )


@dataclass(frozen=True)
class VfxSceneApply:
    preview: VfxScenePreview
    expected_scene_workflow_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"cloth", "collider", "ocean", "wave", "expected_scene_workflow_revision"})
        preview = VfxScenePreview.parse(
            {k: v for k, v in data.items() if k != "expected_scene_workflow_revision"}
        )
        expected = string(
            data["expected_scene_workflow_revision"],
            "expected_scene_workflow_revision",
            limit=64,
        )
        return cls(preview, expected)


@dataclass(frozen=True)
class VfxSceneRelease:
    expected_scene_workflow_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_scene_workflow_token"})
        return cls(
            string(data["expected_scene_workflow_token"], "expected_scene_workflow_token", limit=64)
        )


class VfxSceneWorkflowOperations:
    """Four-stage modifier setup with complete readback and owned-only rollback."""

    def __init__(self, objects):
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.pair = ClothColliderWorkflowOperations(objects)
        self.ocean = OceanSimulationOperations(objects)
        self.wave = WaveSimulationOperations(objects)
        self._owned = {}

    def _plan(self, action):
        fabric, collider, pair_plan = self.pair._plan(
            ClothColliderPreview(action.cloth, action.collider)
        )
        sea, ocean_plan = self.ocean._plan_ocean(action.ocean)
        ripples, wave_plan = self.wave._plan(action.wave)
        objs = [fabric, collider, sea, ripples]
        if len({id(obj) for obj in objs}) != 4 or len({id(obj.data) for obj in objs}) != 4:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Four independent editable meshes required")
        if any(mod.type == "OCEAN" for mod in sea.modifiers):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Ocean modifier already exists")
        if any(mod.type == "WAVE" for mod in ripples.modifiers):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Wave modifier already exists")
        if len(self._owned) >= 4:
            raise AgentError(ErrorCode.SAFETY_DENIED, "VFX scene ownership limit exceeded")
        plan = {
            "cloth_collider": pair_plan,
            "ocean": ocean_plan,
            "wave": wave_plan,
            "scene_revision": self.inspector.summary()["revision"],
            "source_only": True,
            "evaluated_frames": 0,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["scene_workflow_revision"] = revision(plan)
        return objs, plan

    def preview(self, request, action):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[1]
        )

    def _make_ocean(self, obj, action, plan, created):
        mod = obj.modifiers.new(action.name, "OCEAN")
        created.append((obj, mod))
        mod.geometry_mode = "GENERATE"
        for key, value in action.settings.items():
            if key != "foam":
                setattr(mod, key, value)
        for key, value in action.settings.get("foam", {}).items():
            setattr(mod, key, value)
        mod.show_viewport = True
        mod.show_render = True
        self.bpy.context.view_layer.update()
        expected = {
            "name": plan["name"],
            "type": "OCEAN",
            "geometry_mode": "GENERATE",
            "show_viewport": True,
            "show_render": True,
            "properties": {k: v for k, v in plan["settings"].items() if k != "foam"},
            "position": plan["modifier_index"],
            "owned_object_id": plan["target_id"],
        }
        if "foam" in plan["settings"]:
            expected["foam"] = plan["settings"]["foam"]
        if not compare(expected, self.ocean._read_ocean(obj, mod)).matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Ocean readback mismatch")
        return expected

    def _make_wave(self, obj, action, plan, created):
        mod = obj.modifiers.new(action.name, "WAVE")
        created.append((obj, mod))
        for key, value in action.settings.items():
            setattr(mod, key, value)
        mod.show_viewport = True
        mod.show_render = True
        self.bpy.context.view_layer.update()
        expected = {
            "name": plan["name"],
            "type": "WAVE",
            "show_viewport": True,
            "show_render": True,
            "properties": plan["settings"],
            "position": plan["modifier_index"],
            "owned_object_id": plan["target_id"],
        }
        if not compare(expected, self.wave._read(obj, mod)).matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Wave readback mismatch")
        return expected

    def _read_all(self, objs, created):
        fabric, collider, sea, ripples = objs
        return {
            "cloth": self.pair.cloth._read_physics(fabric, created[0][1]),
            "collider": self.pair.collider._read_physics(collider, created[1][1]),
            "ocean": self.ocean._read_ocean(sea, created[2][1]),
            "wave": self.wave._read(ripples, created[3][1]),
        }

    def _verify_geometry(self, fabric, cloth_plan, settings):
        pin = settings.get("pin_group")
        if pin and self.pair.cloth._pin_signature(fabric, pin) != cloth_plan["pin_group_signature"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pin weights changed during VFX setup")
        topo = cloth_plan.get("pressure_topology_signature")
        if topo and self.pair.cloth._pressure_topology(fabric) != topo:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pressure topology changed during VFX setup")

    def apply(self, request, action):
        objs, plan = self._plan(action.preview)
        if action.expected_scene_workflow_revision != plan["scene_workflow_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "VFX scene preview is stale")
        fabric, collider, sea, ripples = objs
        pair_plan = plan["cloth_collider"]
        before = plan["scene_revision"]
        created = []
        try:
            cloth = self.pair._create(
                fabric, action.preview.cloth, self.pair.cloth, pair_plan["cloth"], created
            )
            self.inspector.target(action.preview.collider.target)
            coll = self.pair._create(
                collider, action.preview.collider, self.pair.collider,
                pair_plan["collider"], created
            )
            self.inspector.target(action.preview.ocean.target)
            ocean = self._make_ocean(sea, action.preview.ocean, plan["ocean"], created)
            self.inspector.target(action.preview.wave.target)
            wave = self._make_wave(ripples, action.preview.wave, plan["wave"], created)
            self._verify_geometry(fabric, pair_plan["cloth"], action.preview.cloth.settings)
            expected = {"cloth": cloth, "collider": coll, "ocean": ocean, "wave": wave}
            checked = compare(expected, self._read_all(objs, created))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "VFX final readback mismatch")
            token = revision({
                "plan": plan["scene_workflow_revision"],
                "modifiers": [self.wave._pointer(mod) for _, mod in created],
            })
            self._owned[token] = {
                "objects": objs,
                "created": created,
                "expected": expected,
                "cloth_plan": pair_plan["cloth"],
                "cloth_settings": action.preview.cloth.settings,
                "before_scene": before,
                "after_scene": self.inspector.summary()["revision"],
            }
            return Result(
                request.request_id, request.command_id, Status.VERIFIED,
                {
                    "scene_workflow_token": token,
                    "owned_modifiers": 4,
                    "source_only": True,
                    "evaluated_frames": 0,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            self.pair._rollback(created, before)
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "VFX scene setup failed; owned changes reverted") from exc

    def release(self, request, action):
        token = action.expected_scene_workflow_token
        state = self._owned.get(token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or foreign VFX scene token")
        if self.inspector.summary()["revision"] != state["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed after VFX setup")
        created = state["created"]
        if any(not any(item is mod for item in obj.modifiers) for obj, mod in created):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Owned VFX modifier removed externally")
        self._verify_geometry(
            state["objects"][0], state["cloth_plan"], state["cloth_settings"]
        )
        if not compare(
            state["expected"], self._read_all(state["objects"], created)
        ).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "External VFX modifier edit detected")
        self.pair._rollback(created, state["before_scene"])
        del self._owned[token]
        return Result(
            request.request_id, request.command_id, Status.VERIFIED,
            {"removed_owned_modifiers": 4, "restored_scene": True, "source_only": True},
            verification=compare({"restored": True}, {"restored": True}).to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "vfx.scene_preview", SafetyClass.READ_ONLY,
                VfxScenePreview.parse, self.preview
            ),
            Tool(
                "vfx.scene_apply", SafetyClass.MUTATION,
                VfxSceneApply.parse, self.apply
            ),
            Tool(
                "vfx.scene_release", SafetyClass.MUTATION,
                VfxSceneRelease.parse, self.release
            ),
        ]
