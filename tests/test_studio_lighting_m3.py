"""Level 9 M3 cinematic mood color/power changes: source-only verification."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.studio_lighting import RigPreview, StudioLightingOperations
from shuvi_blender_agent.tools import ToolRegistry


def rig():
    obj = FakeObject("MoodSubject", "MESH")
    obj.dimensions = [2.0, 2.0, 2.0]
    bpy = fake_bpy([obj])
    inspector = BpyInspector(bpy)
    s = inspector.snapshot(obj)
    target = {
        "object_id": s["object_id"],
        "expected_name": s["name"],
        "expected_revision": s["revision"],
    }
    registry = ToolRegistry(
        StudioLightingOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return (
        bpy,
        inspector,
        registry,
        {
            "subject": target,
            "name_prefix": "MoodRig",
            "preset": "SOFT_STUDIO",
            "distance_scale": 3.5,
            "intensity_scale": 1.0,
        },
    )


def test_m3_moods_change_real_planned_rgb_and_watts_without_mutating_preview():
    bpy, inspector, registry, data = rig()
    before = inspector.summary()["revision"]
    baseline = registry.dispatch(Request("lighting.studio_preview", data)).data
    for mood in ("GOLDEN_HOUR", "MOONLIT_BLUE", "TEAL_AMBER"):
        plan = registry.dispatch(Request("lighting.studio_preview", data | {"mood": mood}))
        assert plan.status == Status.SUCCEEDED, plan.error
        assert plan.data["mood"] == mood
        assert plan.data["lighting_revision"] != baseline["lighting_revision"]
        assert plan.data["lights"][0]["color"] != baseline["lights"][0]["color"]
        assert plan.data["lights"][0]["energy"] != baseline["lights"][0]["energy"]
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


@pytest.mark.parametrize("preset", ["SOFT_STUDIO", "BEAUTY_CLAMSHELL", "PRODUCT_FIVE_POINT"])
def test_m3_mood_creates_rgb_power_data_and_owned_release(preset):
    bpy, inspector, registry, data = rig()
    args = data | {"preset": preset, "mood": "TEAL_AMBER"}
    before = inspector.summary()["revision"]
    plan = registry.dispatch(Request("lighting.studio_preview", args)).data
    done = registry.dispatch(
        Request(
            "lighting.studio_apply",
            args | {"expected_lighting_revision": plan["lighting_revision"]},
        )
    )
    assert done.status == Status.VERIFIED, done.error
    for entry in plan["lights"]:
        light = bpy.data.objects.get(entry["name"]).data
        assert list(light.color) == entry["color"]
        assert float(light.energy) == entry["energy"]
    token = done.data["lighting_token"]
    released = registry.dispatch(
        Request("lighting.studio_release", {"expected_lighting_token": token})
    )
    assert released.status == Status.VERIFIED
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


def test_m3_changing_mood_after_preview_is_stale():
    bpy, _, registry, data = rig()
    initial = data | {"mood": "GOLDEN_HOUR"}
    plan = registry.dispatch(Request("lighting.studio_preview", initial)).data
    done = registry.dispatch(
        Request(
            "lighting.studio_apply",
            data
            | {
                "mood": "MOONLIT_BLUE",
                "expected_lighting_revision": plan["lighting_revision"],
            },
        )
    )
    assert done.status == Status.FAILED
    assert done.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights


@pytest.mark.parametrize("bad", ["rainbow", "", 5, None])
def test_m3_rejects_invalid_mood(bad):
    _, _, _, data = rig()
    with pytest.raises(AgentError):
        RigPreview.parse(data | {"mood": bad})
