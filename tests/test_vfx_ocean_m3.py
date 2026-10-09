"""M3 actual Ocean foam and spray mask properties with guarded release."""

import pytest
from test_vfx_ocean_m2 import apply, preview, release, setup

from shuvi_blender_agent import AgentError, ErrorCode, Status
from shuvi_blender_agent.vfx_ocean import OceanPreview


def foam_data():
    bpy, obj, inspector, registry, data = setup()
    data["settings"]["foam"] = {
        "foam_layer_name": "ShuviWhiteFoam",
        "foam_coverage": 1.7,
        "use_spray": True,
        "spray_layer_name": "ShuviSprayMask",
        "invert_spray": False,
    }
    return bpy, obj, inspector, registry, data


def test_m3_real_ocean_foam_spray_layers_are_written_and_read_back():
    bpy, obj, inspector, registry, data = foam_data()
    before = inspector.summary()["revision"]
    planned = preview(registry, data)
    assert planned["settings"]["foam"]["foam_layer_name"] == "ShuviWhiteFoam"
    assert not obj.modifiers
    result = apply(registry, data, planned)
    assert result.status == Status.VERIFIED, result.error
    mod = obj.modifiers.get("ShuviOcean")
    assert mod.type == "OCEAN"
    assert mod.use_foam is True
    assert mod.foam_layer_name == "ShuviWhiteFoam"
    assert mod.foam_coverage == 1.7
    assert mod.use_spray is True
    assert mod.spray_layer_name == "ShuviSprayMask"
    assert mod.invert_spray is False
    assert result.verification["matched"]
    removed = release(registry, result.data["ocean_token"])
    assert removed.status == Status.VERIFIED, removed.error
    assert not obj.modifiers
    assert inspector.summary()["revision"] == before


def test_m3_only_foam_and_optional_spray_disabled_supported():
    _, obj, _, registry, data = foam_data()
    data["settings"]["foam"] = {
        "foam_layer_name": "Whitecaps",
        "foam_coverage": 0.5,
    }
    result = apply(registry, data, preview(registry, data))
    assert result.status == Status.VERIFIED, result.error
    mod = obj.modifiers.get("ShuviOcean")
    assert mod.use_foam is True
    assert mod.use_spray is False
    assert mod.spray_layer_name == "ShuviSpray"
    assert mod.invert_spray is False


def test_m3_legacy_ocean_payload_without_foam_is_unchanged():
    _, obj, _, registry, data = setup()
    result = apply(registry, data, preview(registry, data))
    assert result.status == Status.VERIFIED, result.error
    assert obj.modifiers.get("ShuviOcean").type == "OCEAN"
    assert release(registry, result.data["ocean_token"]).status == Status.VERIFIED


def test_m3_foreign_foam_changes_block_owned_release():
    _, obj, _, registry, data = foam_data()
    done = apply(registry, data, preview(registry, data))
    assert done.status == Status.VERIFIED
    obj.modifiers.get("ShuviOcean").foam_coverage = 9.5
    rejected = release(registry, done.data["ocean_token"])
    assert rejected.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("ShuviOcean").foam_coverage == 9.5


def test_m3_injected_foam_readback_corruption_rolls_back():
    bpy, obj, inspector, registry, data = foam_data()
    old = inspector.summary()["revision"]
    plan = preview(registry, data)
    count = {"n": 0}

    def corrupt_once():
        count["n"] += 1
        if count["n"] == 1:
            obj.modifiers.get("ShuviOcean").foam_layer_name = "Hijacked"

    bpy.context.view_layer.update = corrupt_once
    result = apply(registry, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert not obj.modifiers
    assert inspector.summary()["revision"] == old


@pytest.mark.parametrize(
    "bad",
    [
        {"foam_layer_name": "A", "foam_coverage": -0.1},
        {"foam_layer_name": "A", "foam_coverage": 99},
        {"foam_layer_name": "A", "foam_coverage": float("nan")},
        {"foam_layer_name": "A/B", "foam_coverage": 1.0},
        {"foam_layer_name": "A", "foam_coverage": 1, "use_spray": 1},
        {"foam_layer_name": "A", "foam_coverage": 1, "invert_spray": True},
        {
            "foam_layer_name": "Same",
            "foam_coverage": 1,
            "use_spray": True,
            "spray_layer_name": "Same",
        },
        {"foam_layer_name": "Foam", "foam_coverage": 1, "filepath": "/tmp/unsafe"},
    ],
)
def test_m3_invalid_foam_specs_are_rejected_before_mutation(bad):
    _, _, _, _, data = foam_data()
    data["settings"]["foam"] = bad
    with pytest.raises(AgentError):
        OceanPreview.parse(data)


def test_m3_changed_foam_plan_is_stale():
    _, obj, _, registry, data = foam_data()
    plan = preview(registry, data)
    data["settings"]["foam"]["foam_coverage"] = 2.9
    denied = apply(registry, data, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert not obj.modifiers
