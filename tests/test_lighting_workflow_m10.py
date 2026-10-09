"""Level 9 M10 — integrated studio/World/recipe workflow source acceptance."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.lighting_recipes import LightingRecipeOperations
from shuvi_blender_agent.lighting_workflow import LightingWorkflowOperations, WorkflowPreview
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.studio_lighting import StudioLightingOperations
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.world_lighting import WorldLightingOperations


def setup(preset="PRODUCT_FIVE_POINT", hdri=False):
    subject = FakeObject("Subject", "MESH")
    subject.dimensions = [2.0, 3.0, 4.0]
    bpy = fake_bpy([subject])
    foreign_world = bpy.data.worlds.new("OriginalWorld")
    bpy.context.scene.world = foreign_world
    if hdri:
        image = bpy.data.images.new("LoadedHDRI", 2048, 1024)
        image.source = "FILE"
        image.has_data = True
    inspector = BpyInspector(bpy)
    obj = ObjectOperations(inspector)
    studio = StudioLightingOperations(obj)
    world = WorldLightingOperations(obj)
    recipes = LightingRecipeOperations(studio)
    workflow = LightingWorkflowOperations(studio, world, recipes)
    registry = ToolRegistry(
        studio.tools() + world.tools() + recipes.tools() + workflow.tools(),
        SafetyPolicy(allow_mutations=True),
    )
    snap = inspector.snapshot(subject)
    target = {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }
    data = {
        "studio": {
            "subject": target,
            "name_prefix": "FinalRig",
            "preset": preset,
            "distance_scale": 3.5,
            "intensity_scale": 1,
            "mood": "GOLDEN_HOUR",
            "shadow_profile": "SOFT_CINEMATIC",
            "target_offsets": {"Key": [0.2, 0, 0.1]},
        },
        "world": (
            {"name": "OwnedWorld", "mode": "HDRI", "strength": 0.8, "image_name": "LoadedHDRI"}
            if hdri
            else {
                "name": "OwnedWorld",
                "mode": "COLOR",
                "strength": 0.6,
                "color": [0.2, 0.32, 0.55],
            }
        ),
    }
    return bpy, subject, foreign_world, inspector, registry, data


def preview(registry, data):
    outcome = registry.dispatch(Request("lighting.workflow_preview", data))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    return outcome.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request(
            "lighting.workflow_apply",
            data | {"expected_workflow_revision": plan["workflow_revision"]},
        )
    )


def release(registry, token):
    return registry.dispatch(
        Request("lighting.workflow_release", {"expected_workflow_token": token})
    )


@pytest.mark.parametrize(
    "preset,count",
    [
        ("SOFT_STUDIO", 3),
        ("BEAUTY_CLAMSHELL", 4),
        ("PRODUCT_FIVE_POINT", 5),
    ],
)
@pytest.mark.parametrize("recipe", [None, "PRODUCT_SHOWCASE"])
def test_m10_integrated_real_lights_world_optional_recipe_and_full_release(preset, count, recipe):
    bpy, subject, old_world, inspector, registry, args = setup(preset)
    if recipe:
        args["recipe"] = recipe
    original = inspector.summary()["revision"]
    plan = preview(registry, args)
    assert plan["ready"] and not plan["mutation_performed"]
    assert bpy.context.scene.world is old_world
    assert bpy.context.scene.objects == [subject]
    result = apply(registry, args, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"]
    assert result.data["lights_created"] == count
    assert len(bpy.data.lights) == count
    assert bpy.context.scene.world.name == "OwnedWorld"
    assert bpy.data.worlds.get("OriginalWorld") is old_world
    assert len(bpy.context.scene.objects) == count + 1
    if recipe is None:
        assert result.data["recipe_token"] is None
    else:
        assert isinstance(result.data["recipe_token"], str)
    done = release(registry, result.data["workflow_token"])
    assert done.status == Status.VERIFIED, done.error
    assert len(bpy.data.lights) == 0
    assert bpy.context.scene.objects == [subject]
    assert bpy.context.scene.world is old_world
    assert bpy.data.worlds == [old_world]
    assert inspector.summary()["revision"] == original
    again = release(registry, result.data["workflow_token"])
    assert again.error.code == ErrorCode.STALE_STATE


def test_m10_preloaded_hdri_is_referenced_not_loaded_or_removed():
    bpy, _, old_world, _, registry, args = setup(hdri=True)
    image = bpy.data.images.get("LoadedHDRI")
    initial = list(bpy.data.images)
    plan = preview(registry, args)
    result = apply(registry, args, plan)
    assert result.status == Status.VERIFIED, result.error
    node = bpy.context.scene.world.node_tree.nodes.get("SHUVI_WORLD_ENVIRONMENT")
    assert node.image is image
    assert release(registry, result.data["workflow_token"]).status == Status.VERIFIED
    assert bpy.context.scene.world is old_world
    assert list(bpy.data.images) == initial


def test_m10_stale_original_scene_or_world_blocks_all_mutations():
    bpy, _, _, _, reg, data = setup()
    first = preview(reg, data)
    bpy.context.scene.world = bpy.data.worlds.new("ForeignReplacement")
    denied = apply(reg, data, first)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights
    assert bpy.data.worlds.get("OwnedWorld") is None


def test_m10_world_creation_failure_rolls_back_new_studio_lights():
    bpy, subject, old_world, inspector, reg, data = setup()
    original = inspector.summary()["revision"]
    plan = preview(reg, data)
    old_new = bpy.data.worlds.new

    def bad_world(name):
        raise RuntimeError("Injected World failure")

    bpy.data.worlds.new = bad_world
    result = apply(reg, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert not bpy.data.lights
    assert bpy.context.scene.objects == [subject]
    assert bpy.context.scene.world is old_world
    assert inspector.summary()["revision"] == original
    bpy.data.worlds.new = old_new


def test_m10_recipe_stage_failure_rolls_back_world_and_studio():
    bpy, subject, old_world, _, reg, data = setup()
    data["recipe"] = "INTERVIEW_SOFTBOX"
    plan = preview(reg, data)
    recipe_op = reg._tools["lighting.recipe_apply"].execute.__self__
    original = recipe_op.apply

    def fail_recipe(request, action):
        raise AgentError(ErrorCode.SAFETY_DENIED, "Simulated blocked recipe")

    recipe_op.apply = fail_recipe
    result = apply(reg, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert bpy.context.scene.objects == [subject]
    assert bpy.context.scene.world is old_world
    assert not bpy.data.lights
    assert bpy.data.worlds == [old_world]
    recipe_op.apply = original


def test_m10_external_lamp_edit_refuses_release_and_preserves_foreign_content():
    bpy, _, old_world, _, reg, data = setup()
    result = apply(reg, data, preview(reg, data))
    assert result.status == Status.VERIFIED
    bpy.data.objects.get("FinalRig_Key").data.energy = 999
    denied = release(reg, result.data["workflow_token"])
    assert denied.error.code in (ErrorCode.SAFETY_DENIED, ErrorCode.VERIFICATION_FAILED)
    assert bpy.context.scene.world is not old_world
    assert len(bpy.data.lights) == 5


@pytest.mark.parametrize(
    "bad",
    [
        {"studio": {}, "world": {}},
        {"studio": "unsafe", "world": {}},
        {"studio": {}, "world": "unsafe"},
        {"studio": {}, "world": {}, "recipe": "ARBITRARY"},
    ],
)
def test_m10_malformed_nested_workflow_is_rejected(bad):
    with pytest.raises(AgentError):
        WorkflowPreview.parse(bad)


def test_m10_factory_has_real_registered_typed_tools():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=False))
    names = {row["name"] for row in registry.catalog()}
    assert len(registry.catalog()) == 329
    assert {
        "lighting.workflow_preview",
        "lighting.workflow_apply",
        "lighting.workflow_release",
    }.issubset(names)
    with pytest.raises(AgentError):
        WorkflowPreview.parse({"studio": {}, "world": {}, "execute_python": "eval()"})
