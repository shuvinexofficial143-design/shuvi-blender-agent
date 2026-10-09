"""M9 source acceptance: real 3–5 fixture multi-property lighting recipes."""

import pytest
from fake_bpy import fake_bpy
from test_studio_lighting_m7 import setup as setup_owned

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.lighting_recipes import LightingRecipeOperations, RecipePreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def rig(preset="PRODUCT_FIVE_POINT"):
    bpy, inspector, studio_registry, token, revision = setup_owned(preset)
    studio = studio_registry._tools["lighting.studio_apply"].execute.__self__
    recipes = LightingRecipeOperations(studio)
    registry = ToolRegistry(studio.tools() + recipes.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, registry, token, revision


def preview(reg, token, recipe):
    payload = {"expected_lighting_token": token, "recipe": recipe}
    result = reg.dispatch(Request("lighting.recipe_preview", payload))
    assert result.status == Status.SUCCEEDED, result.error
    return payload, result.data


def apply(reg, payload, plan):
    return reg.dispatch(
        Request(
            "lighting.recipe_apply",
            payload | {"expected_recipe_revision": plan["recipe_revision"]},
        )
    )


def restore(reg, token):
    return reg.dispatch(Request("lighting.recipe_restore", {"expected_recipe_token": token}))


@pytest.mark.parametrize("preset", ["SOFT_STUDIO", "BEAUTY_CLAMSHELL", "PRODUCT_FIVE_POINT"])
@pytest.mark.parametrize("recipe", ["INTERVIEW_SOFTBOX", "NOIR_PORTRAIT", "PRODUCT_SHOWCASE"])
def test_m9_real_full_rig_recipe_and_exact_undo(preset, recipe):
    bpy, inspector, reg, token, original_scene = rig(preset)
    lamps = [obj for obj in bpy.context.scene.objects if obj.type == "LIGHT"]
    before = [
        (
            obj,
            obj.data.energy,
            list(obj.data.color),
            obj.data.size,
            obj.data.spread,
            obj.data.use_shadow,
        )
        for obj in lamps
    ]
    payload, plan = preview(reg, token, recipe)
    assert not plan["mutation_performed"]
    assert len(plan["after"]) == len(lamps)
    done = apply(reg, payload, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.data["lights_updated"] == len(lamps)
    for obj, _, _, _, _, _ in before:
        after = next(entry for entry in plan["after"] if entry["name"] == obj.name)
        assert obj.data.energy == after["energy"]
        assert list(obj.data.color) == after["color"]
        assert obj.data.size == after["size"]
        assert obj.data.spread == after["spread"]
        assert obj.data.use_shadow is after["use_shadow"]
    undone = restore(reg, done.data["recipe_token"])
    assert undone.status == Status.VERIFIED, undone.error
    for obj, watts, color, size, spread, cast in before:
        assert obj.data.energy == watts
        assert list(obj.data.color) == color
        assert obj.data.size == size
        assert obj.data.spread == spread
        assert obj.data.use_shadow is cast
    released = reg.dispatch(Request("lighting.studio_release", {"expected_lighting_token": token}))
    assert released.status == Status.VERIFIED, released.error
    assert inspector.summary()["revision"] == original_scene


def test_m9_stale_plan_and_duplicate_recipe_cannot_override_active_undo():
    _, _, reg, token, _ = rig()
    first_payload, first_plan = preview(reg, token, "NOIR_PORTRAIT")
    stale_payload, stale_plan = preview(reg, token, "INTERVIEW_SOFTBOX")
    done = apply(reg, first_payload, first_plan)
    assert done.status == Status.VERIFIED, done.error
    denied = apply(reg, stale_payload, stale_plan)
    assert denied.status == Status.FAILED
    assert denied.error.code in (ErrorCode.SAFETY_DENIED, ErrorCode.STALE_STATE)
    assert restore(reg, done.data["recipe_token"]).status == Status.VERIFIED
    assert restore(reg, done.data["recipe_token"]).error.code == ErrorCode.STALE_STATE


def test_m9_m7_tuning_expires_old_recipe_undo_and_m8_is_blocked_until_restore():
    bpy, _, reg, token, _ = rig()
    payload, plan = preview(reg, token, "PRODUCT_SHOWCASE")
    done = apply(reg, payload, plan)
    assert done.status == Status.VERIFIED
    look = reg.dispatch(
        Request(
            "lighting.look_preview",
            {"expected_lighting_token": token, "look": "FILM_NOIR"},
        )
    )
    assert look.error.code == ErrorCode.SAFETY_DENIED
    tune_payload = {
        "expected_lighting_token": token,
        "role": "Key",
        "settings": {"energy_watts": 333},
    }
    tune = reg.dispatch(Request("lighting.tune_preview", tune_payload))
    assert tune.status == Status.SUCCEEDED
    assert (
        reg.dispatch(
            Request(
                "lighting.tune_apply",
                tune_payload | {"expected_tuning_revision": tune.data["tuning_revision"]},
            )
        ).status
        == Status.VERIFIED
    )
    assert restore(reg, done.data["recipe_token"]).error.code == ErrorCode.STALE_STATE
    assert bpy.data.objects.get("MyRig_Key").data.energy == 333


def test_m9_changed_managed_light_blocks_recipe_restore():
    bpy, _, reg, token, _ = rig()
    payload, plan = preview(reg, token, "NOIR_PORTRAIT")
    done = apply(reg, payload, plan)
    bpy.data.objects.get("MyRig_Key").data.size = 999
    refused = restore(reg, done.data["recipe_token"])
    assert refused.error.code == ErrorCode.SAFETY_DENIED
    assert bpy.data.objects.get("MyRig_Key").data.size == 999


def test_m9_corrupt_readback_restores_all_original_owned_light_settings():
    bpy, _, reg, token, _ = rig()
    before = [
        (obj, obj.data.energy, list(obj.data.color), obj.data.size, obj.data.spread)
        for obj in bpy.context.scene.objects
        if obj.type == "LIGHT"
    ]
    payload, plan = preview(reg, token, "NOIR_PORTRAIT")
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            bpy.data.objects.get("MyRig_Rim").data.spread = 0.05

    bpy.context.view_layer.update = corrupt_once
    result = apply(reg, payload, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    for obj, energy, color, size, spread in before:
        assert obj.data.energy == energy
        assert list(obj.data.color) == color
        assert obj.data.size == size
        assert obj.data.spread == spread
    assert (
        reg.dispatch(Request("lighting.studio_release", {"expected_lighting_token": token})).status
        == Status.VERIFIED
    )


@pytest.mark.parametrize("bad", ["", "UNKNOWN", 3, None, True])
def test_m9_unapproved_recipe_denied(bad):
    with pytest.raises(AgentError):
        RecipePreview.parse({"expected_lighting_token": "sample", "recipe": bad})


def test_m9_catalog_host_registration_and_permission_gate():
    bpy = fake_bpy()
    full = create_registry(bpy, SafetyPolicy(allow_mutations=False))
    catalog = full.catalog()
    assert len(catalog) == 277
    assert {"lighting.recipe_apply", "lighting.recipe_restore"}.issubset(
        {row["name"] for row in catalog}
    )
    outcome = full.dispatch(Request("lighting.recipe_catalog", {}))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    assert len(outcome.data["recipes"]) == 3
    with pytest.raises(AgentError):
        RecipePreview.parse(
            {"expected_lighting_token": "ok", "recipe": "NOIR_PORTRAIT", "code": "unsafe"}
        )
