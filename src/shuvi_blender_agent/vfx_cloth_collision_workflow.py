"""Level 10 M8: source-only atomic CLOTH and COLLISION modifiers on separate meshes."""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string
from .verification import compare
from .vfx_cloth import ClothPreview, ClothSimulationOperations
from .vfx_collision import CollisionPreview, CollisionSimulationOperations


@dataclass(frozen=True)
class ClothColliderPreview:
    cloth: ClothPreview
    collider: CollisionPreview

    @classmethod
    def parse(cls, data):
        fields(data, {"cloth", "collider"})
        return cls(ClothPreview.parse(data["cloth"]), CollisionPreview.parse(data["collider"]))


@dataclass(frozen=True)
class ClothColliderApply:
    preview: ClothColliderPreview
    expected_workflow_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"cloth", "collider", "expected_workflow_revision"})
        preview = ClothColliderPreview.parse(
            {key: value for key, value in data.items() if key != "expected_workflow_revision"}
        )
        expected = string(
            data["expected_workflow_revision"], "expected_workflow_revision", limit=64
        )
        return cls(preview, expected)


@dataclass(frozen=True)
class ClothColliderRelease:
    expected_workflow_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_workflow_token"})
        return cls(string(data["expected_workflow_token"], "expected_workflow_token", limit=64))


class ClothColliderWorkflowOperations:
    """Guarded preview, two-stage RNA readback, reverse rollback and release."""

    def __init__(self, objects):
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.cloth = ClothSimulationOperations(objects)
        self.collider = CollisionSimulationOperations(objects)
        self._owned = {}

    def _plan(self, action):
        fabric, cloth_plan = self.cloth._plan_physics(action.cloth)
        obstacle, collider_plan = self.collider._plan_physics(action.collider)
        if fabric is obstacle or fabric.data is obstacle.data:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Separate local meshes required")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Physics workflow limit reached")
        plan = {
            "cloth": cloth_plan,
            "collider": collider_plan,
            "scene_revision": self.inspector.summary()["revision"],
            "source_only": True,
            "evaluated_frames": 0,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["workflow_revision"] = revision(plan)
        return fabric, obstacle, plan

    def preview(self, request, action):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[2]
        )

    def _create(self, obj, action, adapter, plan, created):
        mod = obj.modifiers.new(action.name, adapter.kind)
        created.append((obj, mod))
        for alias, value in action.settings.items():
            group, prop = adapter.config_fields[alias]
            setattr(getattr(mod, group), prop, value)
        mod.show_viewport = True
        mod.show_render = True
        self.bpy.context.view_layer.update()
        expected = {
            "name": plan["name"],
            "type": adapter.kind,
            "show_viewport": True,
            "show_render": True,
            "settings": plan["settings"],
            "position": plan["modifier_index"],
            "owned_object_id": plan["target_id"],
        }
        if not compare(expected, adapter._read_physics(obj, mod)).matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Compound RNA readback failed")
        return expected

    def _rollback(self, created, before):
        try:
            for obj, mod in reversed(created):
                if any(item is mod for item in obj.modifiers):
                    obj.modifiers.remove(mod)
            self.bpy.context.view_layer.update()
            remaining = any(
                any(item is mod for item in obj.modifiers) for obj, mod in created
            )
            if remaining or self.inspector.summary()["revision"] != before:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Owned rollback failed")
        except Exception as exc:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED, "Owned rollback verification uncertain"
            ) from exc

    def apply(self, request, action):
        fabric, obstacle, plan = self._plan(action.preview)
        if action.expected_workflow_revision != plan["workflow_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Compound preview is stale")
        created = []
        before = plan["scene_revision"]
        try:
            cloth_expected = self._create(
                fabric, action.preview.cloth, self.cloth, plan["cloth"], created
            )
            self.inspector.target(action.preview.collider.target)
            collider_expected = self._create(
                obstacle, action.preview.collider, self.collider, plan["collider"], created
            )
            pin_group = action.preview.cloth.settings["pin_group"]
            if pin_group and (
                self.cloth._pin_signature(fabric, pin_group)
                != plan["cloth"]["pin_group_signature"]
            ):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Pin group changed during setup")
            expected = {"cloth": cloth_expected, "collider": collider_expected}
            actual = {
                "cloth": self.cloth._read_physics(fabric, created[0][1]),
                "collider": self.collider._read_physics(obstacle, created[1][1]),
            }
            checked = compare(expected, actual)
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Compound RNA changed")
            token = revision({
                "cloth": self.cloth._pointer(created[0][1]),
                "collider": self.collider._pointer(created[1][1]),
                "plan": plan["workflow_revision"],
            })
            self._owned[token] = {
                "fabric": fabric,
                "obstacle": obstacle,
                "cloth_modifier": created[0][1],
                "collider_modifier": created[1][1],
                "expected": expected,
                "before_scene": before,
                "after_scene": self.inspector.summary()["revision"],
                "pin_group": pin_group,
                "pin_signature": plan["cloth"].get("pin_group_signature"),
            }
            return Result(
                request.request_id, request.command_id, Status.VERIFIED,
                {
                    "workflow_token": token,
                    "source_only": True,
                    "evaluated_frames": 0,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            self._rollback(created, before)
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Compound setup failed; owned changes restored") from exc

    def release(self, request, action):
        token = action.expected_workflow_token
        owned = self._owned.get(token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or foreign workflow token")
        if self.inspector.summary()["revision"] != owned["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed after workflow")
        fabric, obstacle = owned["fabric"], owned["obstacle"]
        cloth_mod, coll_mod = owned["cloth_modifier"], owned["collider_modifier"]
        if not any(item is cloth_mod for item in fabric.modifiers) or not any(
            item is coll_mod for item in obstacle.modifiers
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Owned physics modifier missing")
        if owned["pin_group"] and (
            self.cloth._pin_signature(fabric, owned["pin_group"]) != owned["pin_signature"]
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pin group changed externally")
        actual = {
            "cloth": self.cloth._read_physics(fabric, cloth_mod),
            "collider": self.collider._read_physics(obstacle, coll_mod),
        }
        if not compare(owned["expected"], actual).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Foreign physics edit detected")
        self._rollback([(fabric, cloth_mod), (obstacle, coll_mod)], owned["before_scene"])
        del self._owned[token]
        return Result(
            request.request_id, request.command_id, Status.VERIFIED,
            {"removed_owned_modifiers": 2, "restored_scene": True, "source_only": True},
            verification=compare({"restored": True}, {"restored": True}).to_dict(),
        )

    def tools(self):
        return [
            Tool("vfx.cloth_collision_preview", SafetyClass.READ_ONLY,
                 ClothColliderPreview.parse, self.preview),
            Tool("vfx.cloth_collision_apply", SafetyClass.MUTATION,
                 ClothColliderApply.parse, self.apply),
            Tool("vfx.cloth_collision_release", SafetyClass.MUTATION,
                 ClothColliderRelease.parse, self.release),
        ]
