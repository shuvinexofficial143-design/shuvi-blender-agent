"""Level 9 M4 source-only verification of area emitter/shadow controls."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.studio_lighting import RigPreview, StudioLightingOperations
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    subject = FakeObject("ShadowSubject", "MESH")
    subject.dimensions = [2.0, 3.0, 4.0]
    bpy = fake_bpy([subject])
    inspector = BpyInspector(bpy)
    snap = inspector.snapshot(subject)
    target = {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }
    reg = ToolRegistry(
        StudioLightingOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    args = {
        "subject": target,
        "name_prefix": "ShadowRig",
        "preset": "PRODUCT_FIVE_POINT",
        "distance_scale": 3.5,
        "intensity_scale": 1.0,
    }
    return bpy, inspector, reg, args


def preview(reg, args):
    result = reg.dispatch(Request("lighting.studio_preview", args))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(reg, args, plan):
    return reg.dispatch(
        Request("lighting.studio_apply", args | {
            "expected_lighting_revision": plan["lighting_revision"],
        })
    )


@pytest.mark.parametrize(
    "style,multiplier,casts",
    [
        ("STANDARD", 1.0, True),
        ("SOFT_CINEMATIC", 2.25, True),
        ("CRISP_DIRECTIONAL", 0.35, True),
        ("NO_SHADOWS", 1.0, False),
    ],
)
def test_m4_preview_and_actual_lights_apply_each_shadow_profile(style, multiplier, casts):
    bpy, inspector, reg, args = setup()
    before = inspector.summary()["revision"]
    baseline = preview(reg, args)
    current = args | {"shadow_profile": style, "mood": "TEAL_AMBER"}
    plan = preview(reg, current)
    assert plan["ready"]
    assert plan["shadow_profile"] == style
    for plain, light in zip(baseline["lights"], plan["lights"], strict=True):
        assert light["use_shadow"] is casts
        assert light["size"] == max(0.2, plain["size"] * multiplier)
    result = apply(reg, current, plan)
    assert result.status == Status.VERIFIED, result.error
    assert len(bpy.data.lights) == 5
    for entry in plan["lights"]:
        datum = bpy.data.objects.get(entry["name"]).data
        assert datum.use_shadow is casts
        assert datum.spread == entry["spread"]
        assert datum.size == entry["size"]
        assert list(datum.color) == entry["color"]
    done = reg.dispatch(Request("lighting.studio_release", {
        "expected_lighting_token": result.data["lighting_token"]
    }))
    assert done.status == Status.VERIFIED, done.error
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


def test_m4_changed_shadow_profile_between_preview_apply_is_stale():
    bpy, _, reg, args = setup()
    plan = preview(reg, args | {"shadow_profile": "SOFT_CINEMATIC"})
    out = apply(reg, args | {"shadow_profile": "NO_SHADOWS"}, plan)
    assert out.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights


def test_m4_modified_owned_shadow_flag_prevents_unsafe_release():
    bpy, _, reg, args = setup()
    current = args | {"shadow_profile": "NO_SHADOWS"}
    plan = preview(reg, current)
    result = apply(reg, current, plan)
    assert result.status == Status.VERIFIED
    bpy.data.objects.get("ShadowRig_Key").data.use_shadow = True
    done = reg.dispatch(Request("lighting.studio_release", {
        "expected_lighting_token": result.data["lighting_token"]
    }))
    assert done.error.code == ErrorCode.SAFETY_DENIED
    assert len(bpy.data.lights) == 5


def test_m4_bad_shadow_datablock_readback_rolls_back_all_new_lights():
    bpy, inspector, reg, args = setup()
    original = inspector.summary()["revision"]
    current = args | {"shadow_profile": "CRISP_DIRECTIONAL"}
    plan = preview(reg, current)
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            bpy.data.objects.get("ShadowRig_Edge").data.use_shadow = False

    bpy.context.view_layer.update = corrupt_once
    result = apply(reg, current, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == original


@pytest.mark.parametrize("bad", ["", "INSANE", None, 3, True])
def test_m4_unknown_or_untyped_shadow_profile_denied(bad):
    _, _, _, args = setup()
    with pytest.raises(AgentError):
        RigPreview.parse(args | {"shadow_profile": bad})
