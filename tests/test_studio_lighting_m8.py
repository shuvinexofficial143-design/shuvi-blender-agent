"""Level 9 M8: in-place atomic cinematic looks and one-step restoration."""

import pytest
from test_studio_lighting_m7 import setup as owned_rig

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.studio_lighting import LookPreview


def preview(registry, token, look):
    payload = {"expected_lighting_token": token, "look": look}
    result = registry.dispatch(Request("lighting.look_preview", payload))
    assert result.status == Status.SUCCEEDED, result.error
    return payload, result.data


def apply(registry, payload, plan):
    return registry.dispatch(
        Request(
            "lighting.look_apply",
            payload | {"expected_look_revision": plan["look_revision"]},
        )
    )


def restore(registry, look_token):
    return registry.dispatch(
        Request("lighting.look_restore", {"expected_look_token": look_token})
    )


@pytest.mark.parametrize(
    "preset,look",
    [
        ("SOFT_STUDIO", "FILM_NOIR"),
        ("BEAUTY_CLAMSHELL", "NEON_SPLIT"),
        ("PRODUCT_FIVE_POINT", "PRODUCT_GLOSS"),
    ],
)
def test_m8_real_multi_light_look_and_exact_undo_before_release(preset, look):
    bpy, inspector, registry, token, original_revision = owned_rig(preset)
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "LIGHT"]
    before = {obj.name: (obj.data.energy, list(obj.data.color)) for obj in objects}
    data, plan = preview(registry, token, look)
    assert not plan["mutation_performed"]
    assert len(plan["proposed_lights"]) == len(objects)
    done = apply(registry, data, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.data["lights_updated"] == len(objects)
    assert all(obj.data.energy != before[obj.name][0] for obj in objects)
    assert any(list(obj.data.color) != before[obj.name][1] for obj in objects)
    reverted = restore(registry, done.data["look_token"])
    assert reverted.status == Status.VERIFIED, reverted.error
    assert all(obj.data.energy == before[obj.name][0] for obj in objects)
    assert all(list(obj.data.color) == before[obj.name][1] for obj in objects)
    released = registry.dispatch(
        Request("lighting.studio_release", {"expected_lighting_token": token})
    )
    assert released.status == Status.VERIFIED
    assert inspector.summary()["revision"] == original_revision


def test_m8_stale_preview_and_concurrent_look_are_denied():
    _, _, registry, token, _ = owned_rig()
    first_data, first_plan = preview(registry, token, "FILM_NOIR")
    second_data, second_plan = preview(registry, token, "NEON_SPLIT")
    first = apply(registry, first_data, first_plan)
    assert first.status == Status.VERIFIED, first.error
    repeated = apply(registry, second_data, second_plan)
    assert repeated.status == Status.FAILED
    assert repeated.error.code in (ErrorCode.STALE_STATE, ErrorCode.SAFETY_DENIED)
    assert restore(registry, first.data["look_token"]).status == Status.VERIFIED


def test_m8_tuning_after_look_invalidates_old_undo():
    bpy, _, registry, token, _ = owned_rig()
    data, plan = preview(registry, token, "PRODUCT_GLOSS")
    applied = apply(registry, data, plan)
    assert applied.status == Status.VERIFIED
    tuning = {
        "expected_lighting_token": token,
        "role": "Key",
        "settings": {"energy_watts": 111},
    }
    proposed = registry.dispatch(Request("lighting.tune_preview", tuning)).data
    tuned = registry.dispatch(
        Request(
            "lighting.tune_apply",
            tuning | {"expected_tuning_revision": proposed["tuning_revision"]},
        )
    )
    assert tuned.status == Status.VERIFIED, tuned.error
    expired = restore(registry, applied.data["look_token"])
    assert expired.error.code == ErrorCode.STALE_STATE
    assert bpy.data.objects.get("MyRig_Key").data.energy == 111


def test_m8_tampered_look_blocks_unsafe_undo():
    bpy, _, registry, token, _ = owned_rig()
    data, plan = preview(registry, token, "NEON_SPLIT")
    done = apply(registry, data, plan)
    assert done.status == Status.VERIFIED
    owned = bpy.data.objects.get("MyRig_Rim")
    owned.data.energy = 2
    denied = restore(registry, done.data["look_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert owned.data.energy == 2


def test_m8_bad_readback_rolls_back_every_owned_lamp():
    bpy, inspector, registry, token, _ = owned_rig()
    data, plan = preview(registry, token, "FILM_NOIR")
    original = [
        (obj.name, obj.data.energy, list(obj.data.color))
        for obj in bpy.context.scene.objects
        if obj.type == "LIGHT"
    ]
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            bpy.data.objects.get("MyRig_Key").data.energy = 0

    bpy.context.view_layer.update = corrupt_once
    out = apply(registry, data, plan)
    assert out.status == Status.FAILED
    assert out.error.code == ErrorCode.VERIFICATION_FAILED
    for name, watts, rgb in original:
        lamp = bpy.data.objects.get(name).data
        assert lamp.energy == watts
        assert list(lamp.color) == rgb
    assert registry.dispatch(
        Request("lighting.studio_release", {"expected_lighting_token": token})
    ).status == Status.VERIFIED


@pytest.mark.parametrize("look", ["", "RAINBOW", 999, None, True])
def test_m8_rejects_invalid_look(look):
    with pytest.raises(AgentError):
        LookPreview.parse({"expected_lighting_token": "safe", "look": look})


def test_m8_cannot_apply_foreign_look_token():
    _, _, registry, token, _ = owned_rig()
    bad = restore(registry, "unowned")
    assert bad.error.code == ErrorCode.STALE_STATE
    preview_result = registry.dispatch(
        Request(
            "lighting.look_preview",
            {"expected_lighting_token": "foreign", "look": "NEON_SPLIT"},
        )
    )
    assert preview_result.error.code == ErrorCode.STALE_STATE
