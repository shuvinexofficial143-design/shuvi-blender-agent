"""Level 9 M10: transactional studio + World + optional cinematic recipe workflow.

Source/fake-bpy acceptance only; no Blender process or render is launched.
"""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .lighting_recipes import LightingRecipeOperations, RecipeApply, RecipePreview, RecipeRestore
from .safety import SafetyClass
from .studio_lighting import RigApply, RigPreview, RigRelease, StudioLightingOperations
from .tools import Tool
from .validation import fields, string
from .verification import compare
from .world_lighting import WorldApply, WorldLightingOperations, WorldPreview, WorldRelease


@dataclass(frozen=True)
class WorkflowPreview:
    studio: RigPreview
    world: WorldPreview
    recipe: str | None

    @classmethod
    def parse(cls, data):
        fields(data, {"studio", "world"}, {"recipe"})
        if not isinstance(data["studio"], dict) or not isinstance(data["world"], dict):
            raise AgentError(ErrorCode.INVALID_REQUEST, "studio and world must be typed objects")
        name = data.get("recipe")
        if name is not None:
            name = RecipePreview.parse(
                {"expected_lighting_token": "placeholder", "recipe": name}
            ).recipe
        return cls(RigPreview.parse(data["studio"]), WorldPreview.parse(data["world"]), name)


@dataclass(frozen=True)
class WorkflowApply:
    preview: WorkflowPreview
    expected_workflow_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"studio", "world", "expected_workflow_revision"}, {"recipe"})
        return cls(
            WorkflowPreview.parse(
                {key: value for key, value in data.items() if key != "expected_workflow_revision"}
            ),
            string(data["expected_workflow_revision"], "expected_workflow_revision", limit=64),
        )


@dataclass(frozen=True)
class WorkflowRelease:
    expected_workflow_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_workflow_token"})
        return cls(string(data["expected_workflow_token"], "expected_workflow_token", limit=64))


class LightingWorkflowOperations:
    """Composes existing adapter-owned bpy operations with exact reverse-order cleanup."""

    def __init__(
        self,
        studio: StudioLightingOperations,
        world: WorldLightingOperations,
        recipes: LightingRecipeOperations,
    ):
        if studio.inspector is not world.inspector or studio is not recipes.studio:
            raise ValueError("Lighting workflow adapters require one shared bpy/inspector session")
        self.studio = studio
        self.world = world
        self.recipes = recipes
        self.inspector = studio.inspector
        self.bpy = studio.bpy
        self._owned = {}

    def _plan(self, action: WorkflowPreview):
        _, _, studio_plan = self.studio._plan(action.studio)
        _, _, world_plan = self.world._plan(action.world)
        blockers = sorted(set(studio_plan["blockers"] + world_plan["blockers"]))
        if self._owned:
            blockers.append("WORKFLOW_ALREADY_MANAGED")
        plan = {
            "studio": studio_plan,
            "world": world_plan,
            "recipe": action.recipe,
            "ready": not blockers,
            "blockers": blockers,
            "scene_revision": self.inspector.summary()["revision"],
            "source_only": True,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["workflow_revision"] = revision(plan)
        return plan

    def preview(self, request: Request, action: WorkflowPreview):
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action))

    @staticmethod
    def _ensure_verified(result, step):
        if result.status != Status.VERIFIED:
            raise AgentError(ErrorCode.EXECUTION_ERROR, f"Integrated lighting {step} failed")

    def _verify_current(self, studio_token, world_token):
        studio = self.studio._live_owned(studio_token)
        world = self.world._owned.get(world_token)
        if world is None or self.bpy.context.scene.world is not world["new"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed World was swapped or removed")
        if not self.world._is_world(world["new"]):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed World datablock no longer exists")
        real_world = self.world._read(world["new"])
        real_lights = [self.studio._read(obj, data) for obj, data in studio["created"]]
        expected = {"lights": studio["expected"], "world": world["expected"]}
        actual = {"lights": real_lights, "world": real_world}
        verified = compare(expected, actual)
        if not verified.matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Combined lighting readback differs")
        if world["image"] is not None:
            source = world["image"]
            if (
                self.bpy.data.images.get(source.name) is not source
                or not self.world._image_read(source)["has_data"]
            ):
                raise AgentError(ErrorCode.SAFETY_DENIED, "HDRI image changed after application")
        return verified

    def apply(self, request: Request, action: WorkflowApply):
        plan = self._plan(action.preview)
        if plan["workflow_revision"] != action.expected_workflow_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Combined lighting plan changed")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Combined lighting setup blocked")

        studio_token = None
        world_token = None
        recipe_token = None
        try:
            studio_result = self.studio.apply(
                request, RigApply(action.preview.studio, plan["studio"]["lighting_revision"])
            )
            self._ensure_verified(studio_result, "studio")
            studio_token = studio_result.data["lighting_token"]

            # Refresh World revision after owned lights have been created.
            world_plan = self.world._plan(action.preview.world)[2]
            world_result = self.world.apply(
                request, WorldApply(action.preview.world, world_plan["world_revision"])
            )
            self._ensure_verified(world_result, "World")
            world_token = world_result.data["world_token"]

            if action.preview.recipe is not None:
                recipe_action = RecipePreview(studio_token, action.preview.recipe)
                recipe_plan = self.recipes._plan(recipe_action)[2]
                recipe_result = self.recipes.apply(
                    request, RecipeApply(recipe_action, recipe_plan["recipe_revision"])
                )
                self._ensure_verified(recipe_result, "recipe")
                recipe_token = recipe_result.data["recipe_token"]

            checked = self._verify_current(studio_token, world_token)
            workflow_token = revision(
                {
                    "lighting": studio_token,
                    "world": world_token,
                    "recipe": recipe_token,
                    "scene": self.inspector.summary()["revision"],
                }
            )
            self._owned[workflow_token] = {
                "studio": studio_token,
                "world": world_token,
                "recipe": recipe_token,
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "workflow_token": workflow_token,
                    "lighting_token": studio_token,
                    "world_token": world_token,
                    "recipe_token": recipe_token,
                    "lights_created": studio_result.data["lights_created"],
                    "world_mode": action.preview.world.mode,
                    "source_only": True,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            # Each preceding step owns only its newly created objects.
            # Never attempt to remove foreign scene objects or existing worlds.
            try:
                if recipe_token is not None:
                    recipe = self.recipes.restore(request, RecipeRestore(recipe_token))
                    self._ensure_verified(recipe, "recipe rollback")
                if world_token is not None:
                    restored_world = self.world.release(request, WorldRelease(world_token))
                    self._ensure_verified(restored_world, "World rollback")
                if studio_token is not None:
                    restored_studio = self.studio.release(request, RigRelease(studio_token))
                    self._ensure_verified(restored_studio, "studio rollback")
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Combined lighting recovery uncertain; inspect before retry",
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR,
                "Combined lighting failed; verified owned-state rollback",
            ) from exc

    def release(self, request: Request, action: WorkflowRelease):
        state = self._owned.get(action.expected_workflow_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown/foreign workflow token")
        studio_token = state["studio"]
        world_token = state["world"]
        recipe_token = state["recipe"]

        # Strict read-only preflight of every owned fixture and World node graph.
        self._verify_current(studio_token, world_token)
        if recipe_token is not None:
            snapshot = self.studio._owned[studio_token].get("recipe_undo")
            if snapshot is None or snapshot["token"] != recipe_token:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Recipe was edited or token expired")
        else:
            owned = self.studio._owned[studio_token]
            if owned.get("recipe_undo") or owned.get("look_undo"):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Unexpected look/recipe changes")
        try:
            if recipe_token is not None:
                reverted = self.recipes.restore(request, RecipeRestore(recipe_token))
                self._ensure_verified(reverted, "recipe release")
            reverted_world = self.world.release(request, WorldRelease(world_token))
            self._ensure_verified(reverted_world, "World release")
            reverted_lights = self.studio.release(request, RigRelease(studio_token))
            self._ensure_verified(reverted_lights, "studio release")
        except Exception as exc:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Integrated release interrupted; inspect partial state before retry",
            ) from exc

        self._owned.pop(action.expected_workflow_token)
        # The release evidence compares original scene + World state only
        # after all owned datablocks have actually been removed.
        clean = compare(
            {"lights_restored": True, "world_restored": True},
            {
                "lights_restored": studio_token not in self.studio._owned,
                "world_restored": world_token not in self.world._owned,
            },
        )
        if not clean.matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Combined release recovery mismatch")
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"restored_original_scene": True, "source_only": True, "render_verified": False},
            verification=clean.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "lighting.workflow_preview",
                SafetyClass.READ_ONLY,
                WorkflowPreview.parse,
                self.preview,
            ),
            Tool("lighting.workflow_apply", SafetyClass.MUTATION, WorkflowApply.parse, self.apply),
            Tool(
                "lighting.workflow_release",
                SafetyClass.MUTATION,
                WorkflowRelease.parse,
                self.release,
            ),
        ]
