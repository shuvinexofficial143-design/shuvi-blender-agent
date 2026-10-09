"""Level 9 M7 — live, verified updates to already-owned AREA lights."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.studio_lighting import StudioLightingOperations, TunePreview
from shuvi_blender_agent.tools import ToolRegistry


def setup(preset="PRODUCT_FIVE_POINT"):
    subject = FakeObject("Product", "MESH")
    subject.dimensions = [2.0, 3.0, 4.0]
    bpy = fake_bpy([subject])
    inspect = BpyInspector(bpy)
    snap = inspect.snapshot(subject)
    target = {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }
    registry = ToolRegistry(
        StudioLightingOperations(ObjectOperations(inspect)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    original = inspect.summary()["revision"]
    args = {
        "subject": target,
        "name_prefix": "MyRig",
        "preset": preset,
        "distance_scale": 3.5,
        "intensity_scale": 1.0,
    }
    plan = registry.dispatch(Request("lighting.studio_preview", args)).data
    result = registry.dispatch(
        Request(
            "lighting.studio_apply",
            args | {"expected_lighting_revision": plan["lighting_revision"]},
        )
    )
    assert result.status == Status.VERIFIED, result.error
    return bpy, inspect, registry, result.data["lighting_token"], original


def tune_plan(registry, token, role, settings):
    args = {"expected_lighting_token": token, "role": role, "settings": settings}
    result = registry.dispatch(Request("lighting.tune_preview", args))
    assert result.status == Status.SUCCEEDED, result.error
    return args, result.data


def apply(registry, args, plan):
    return registry.dispatch(
        Request("lighting.tune_apply", args | {"expected_tuning_revision": plan["tuning_revision"]})
    )


@pytest.mark.parametrize(
    "preset,role",
    [
        ("SOFT_STUDIO", "Key"),
        ("BEAUTY_CLAMSHELL", "Catchlight"),
        ("PRODUCT_FIVE_POINT", "Edge"),
    ],
)
def test_m7_real_light_tuning_preserves_and_releases_entire_rig(preset, role):
    bpy, inspect, registry, token, before = setup(preset)
    light = bpy.data.objects.get(f"MyRig_{role}")
    original = light.data.energy
    settings = {
        "energy_watts": original * 0.5,
        "rgb": [0.12, 0.52, 0.84],
        "emitter_size": 2.5,
        "cast_shadows": False,
    }
    args, plan = tune_plan(registry, token, role, settings)
    assert not plan["mutation_performed"]
    assert light.data.energy == original
    result = apply(registry, args, plan)
    assert result.status == Status.VERIFIED, result.error
    assert light.data.energy == original * 0.5
    assert list(light.data.color) == settings["rgb"]
    assert float(light.data.size) == 2.5
    assert light.data.use_shadow is False
    released = registry.dispatch(
        Request("lighting.studio_release", {"expected_lighting_token": token})
    )
    assert released.status == Status.VERIFIED, released.error
    assert not bpy.data.lights
    assert inspect.summary()["revision"] == before


def test_m7_replay_of_old_preview_fails_stale():
    bpy, _, registry, token, _ = setup()
    args, plan = tune_plan(registry, token, "Key", {"energy_watts": 680})
    assert apply(registry, args, plan).status == Status.VERIFIED
    again = apply(registry, args, plan)
    assert again.error.code == ErrorCode.STALE_STATE
    assert bpy.data.objects.get("MyRig_Key").data.energy == 680


def test_m7_external_light_edit_blocks_preview_without_adoption():
    bpy, _, registry, token, _ = setup()
    bpy.data.objects.get("MyRig_Fill").data.energy = 8
    result = registry.dispatch(
        Request(
            "lighting.tune_preview",
            {"expected_lighting_token": token, "role": "Key", "settings": {"rgb": [1, 0, 0]}},
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_m7_injected_bad_readback_restores_previous_settings():
    bpy, _, registry, token, _ = setup()
    old = bpy.data.objects.get("MyRig_Key").data.energy
    args, plan = tune_plan(registry, token, "Key", {"energy_watts": 990})
    count = {"n": 0}

    def corrupt_once():
        count["n"] += 1
        if count["n"] == 1:
            bpy.data.objects.get("MyRig_Key").data.energy = 9999

    bpy.context.view_layer.update = corrupt_once
    out = apply(registry, args, plan)
    assert out.status == Status.FAILED
    assert out.error.code == ErrorCode.VERIFICATION_FAILED
    assert bpy.data.objects.get("MyRig_Key").data.energy == old
    assert (
        registry.dispatch(
            Request("lighting.studio_release", {"expected_lighting_token": token})
        ).status
        == Status.VERIFIED
    )


def test_m7_existing_foreign_light_is_never_modified():
    bpy, _, registry, token, _ = setup()
    foreign_data = bpy.data.lights.new("Existing", "AREA")
    foreign_data.energy = 543
    foreign_obj = bpy.data.objects.new("Existing", foreign_data)
    bpy.context.scene.collection.objects.link(foreign_obj)
    result = registry.dispatch(
        Request(
            "lighting.tune_preview",
            {
                "expected_lighting_token": token,
                "role": "Rim",
                "settings": {"energy_watts": 100},
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert foreign_data.energy == 543


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"energy_watts": -1},
        {"energy_watts": True},
        {"energy_watts": float("nan")},
        {"rgb": [1, 2]},
        {"rgb": [1, True, 0]},
        {"cast_shadows": "no"},
        {"emitter_size": 0.01},
        {"script": "import bpy"},
    ],
)
def test_m7_invalid_tuning_payloads_fail_closed(settings):
    with pytest.raises(AgentError):
        TunePreview.parse(
            {"expected_lighting_token": "sample", "role": "Key", "settings": settings}
        )


def test_m7_unknown_role_and_foreign_token_denied():
    _, _, registry, token, _ = setup()
    bad = registry.dispatch(
        Request(
            "lighting.tune_preview",
            {
                "expected_lighting_token": token,
                "role": "NotARole",
                "settings": {"energy_watts": 100},
            },
        )
    )
    assert bad.error.code == ErrorCode.INVALID_REQUEST
    foreign = registry.dispatch(
        Request(
            "lighting.tune_preview",
            {
                "expected_lighting_token": "not-owned",
                "role": "Key",
                "settings": {"energy_watts": 100},
            },
        )
    )
    assert foreign.error.code == ErrorCode.STALE_STATE
