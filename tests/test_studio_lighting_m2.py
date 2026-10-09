"""Level 9 M2 source acceptance for actual four/five AREA-light arrangements."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.studio_lighting import (
    RigPreview,
    StudioLightingOperations,
    StudioPresetCatalog,
)
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    subject = FakeObject("Product", "MESH")
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 3.0, 4.0]
    bpy = fake_bpy([subject])
    inspector = BpyInspector(bpy)
    ops = StudioLightingOperations(ObjectOperations(inspector))
    registry = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    snapshot = inspector.snapshot(subject)
    target = {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }
    return bpy, subject, inspector, registry, target


def payload(target, preset):
    return {
        "subject": target,
        "name_prefix": "NewRig",
        "preset": preset,
        "distance_scale": 3.5,
        "intensity_scale": 1.0,
    }


def preview(registry, args):
    outcome = registry.dispatch(Request("lighting.studio_preview", args))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    return outcome.data


def apply(registry, args, plan):
    return registry.dispatch(
        Request(
            "lighting.studio_apply",
            args | {"expected_lighting_revision": plan["lighting_revision"]},
        )
    )


def release(registry, token):
    return registry.dispatch(Request("lighting.studio_release", {"expected_lighting_token": token}))


def test_m2_catalog_is_read_only_and_reports_real_fixture_layouts():
    bpy, subject, inspector, registry, _ = setup()
    before = inspector.summary()["revision"]
    outcome = registry.dispatch(Request("lighting.preset_catalog", {}))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    assert outcome.data["source_only"] is True
    assert outcome.data["render_verified"] is False
    assert outcome.data["mutation_performed"] is False
    items = {item["preset"]: item for item in outcome.data["presets"]}
    assert len(items) == 5
    assert items["SOFT_STUDIO"]["light_count"] == 3
    assert [r["role"] for r in items["BEAUTY_CLAMSHELL"]["fixtures"]] == [
        "Key",
        "Fill",
        "Rim",
        "Catchlight",
    ]
    assert [r["role"] for r in items["PRODUCT_FIVE_POINT"]["fixtures"]] == [
        "Key",
        "Fill",
        "Rim",
        "Top",
        "Edge",
    ]
    assert bpy.context.scene.objects == [subject]
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


@pytest.mark.parametrize(
    "preset,roles",
    [
        ("BEAUTY_CLAMSHELL", ["Key", "Fill", "Rim", "Catchlight"]),
        ("PRODUCT_FIVE_POINT", ["Key", "Fill", "Rim", "Top", "Edge"]),
    ],
)
def test_m2_creates_real_extra_area_lights_and_releases_all(preset, roles):
    bpy, subject, inspector, registry, target = setup()
    args = payload(target, preset)
    before = inspector.summary()["revision"]
    plan = preview(registry, args)
    assert plan["ready"], plan["blockers"]
    assert [entry["role"] for entry in plan["lights"]] == roles
    assert len({tuple(entry["location"]) for entry in plan["lights"]}) == len(roles)
    result = apply(registry, args, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert result.data["lights_created"] == len(roles)
    assert result.data["roles"] == roles
    assert len(bpy.data.lights) == len(roles)
    for entry in plan["lights"]:
        lamp = bpy.data.objects.get(entry["name"])
        assert lamp is not None and lamp in bpy.context.scene.objects
        assert lamp.data.type == "AREA"
        assert lamp.data.shape == "DISK"
        assert float(lamp.data.energy) == entry["energy"]
        assert list(lamp.data.color) == entry["color"]
        assert float(lamp.data.size) == entry["size"]
        assert list(lamp.location) == entry["location"]
        assert list(lamp.rotation_euler) == entry["rotation_euler"]
        assert lamp.data.users == 1
    done = release(registry, result.data["lighting_token"])
    assert done.status == Status.VERIFIED, done.error
    assert done.data["removed_owned_lights"] == len(roles)
    assert bpy.context.scene.objects == [subject]
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


def test_m2_switching_layout_after_preview_is_stale():
    bpy, _, _, registry, target = setup()
    args = payload(target, "BEAUTY_CLAMSHELL")
    plan = preview(registry, args)
    result = apply(registry, args | {"preset": "PRODUCT_FIVE_POINT"}, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights


@pytest.mark.parametrize("role", ["Catchlight", "Top", "Edge"])
def test_m2_collision_with_extra_role_blocks_creation(role):
    bpy, _, _, registry, target = setup()
    bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"NewRig_{role}", None))
    preset = "BEAUTY_CLAMSHELL" if role == "Catchlight" else "PRODUCT_FIVE_POINT"
    args = payload(target, preset)
    plan = preview(registry, args)
    assert not plan["ready"]
    assert "LIGHT_NAME_COLLISION" in plan["blockers"]
    result = apply(registry, args, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert not bpy.data.lights


def test_m2_fifth_light_creation_error_rolls_back_entire_rig():
    bpy, subject, inspector, registry, target = setup()
    args = payload(target, "PRODUCT_FIVE_POINT")
    plan = preview(registry, args)
    before = inspector.summary()["revision"]
    original = bpy.data.lights.new
    calls = {"n": 0}

    def fail_on_fifth(name, kind):
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("Simulated failure at fifth light")
        return original(name, kind)

    bpy.data.lights.new = fail_on_fifth
    outcome = apply(registry, args, plan)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.EXECUTION_ERROR
    assert bpy.context.scene.objects == [subject]
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


def test_m2_extra_light_corrupt_readback_recovers_original_scene():
    bpy, subject, inspector, registry, target = setup()
    args = payload(target, "PRODUCT_FIVE_POINT")
    plan = preview(registry, args)
    before = inspector.summary()["revision"]
    counter = {"n": 0}

    def corrupt_once():
        counter["n"] += 1
        if counter["n"] == 1:
            bpy.data.objects.get("NewRig_Edge").data.energy = 1

    bpy.context.view_layer.update = corrupt_once
    result = apply(registry, args, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert bpy.context.scene.objects == [subject]
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


def test_m2_foreign_light_remains_untouched_after_setup_and_release():
    bpy, _, inspector, registry, target = setup()
    foreign_data = bpy.data.lights.new("External", "POINT")
    foreign_data.energy = 37
    foreign = bpy.data.objects.new("External", foreign_data)
    bpy.context.scene.collection.objects.link(foreign)
    before = inspector.snapshot(foreign)["revision"]
    args = payload(target, "BEAUTY_CLAMSHELL")
    result = apply(registry, args, preview(registry, args))
    assert result.status == Status.VERIFIED, result.error
    assert release(registry, result.data["lighting_token"]).status == Status.VERIFIED
    assert bpy.data.lights == [foreign_data]
    assert bpy.data.objects.get("External") is foreign
    assert inspector.snapshot(foreign)["revision"] == before


def test_m2_catalog_host_contract_caps_and_permissions():
    bpy, _, _, _, _ = setup()
    full = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    assert len(full.catalog()) == MAX_REGISTERED_TOOLS == 317
    assert "lighting.preset_catalog" in {tool["name"] for tool in full.catalog()}
    assert full.dispatch(Request("lighting.preset_catalog", {})).status == Status.SUCCEEDED
    deny = create_registry(bpy, SafetyPolicy(allow_mutations=False))
    inspector = deny._tools["lighting.studio_preview"].execute.__self__.inspector
    subject = bpy.data.objects.get("Product")
    snap = inspector.snapshot(subject)
    target = {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }
    args = payload(target, "PRODUCT_FIVE_POINT")
    planned = preview(deny, args)
    assert apply(deny, args, planned).status == Status.FAILED
    assert not bpy.data.lights


def test_m2_catalog_and_preset_parsers_reject_unsupported_payload():
    _, _, _, _, target = setup()
    with pytest.raises(AgentError):
        StudioPresetCatalog.parse({"execute_code": "import bpy"})
    with pytest.raises(AgentError):
        RigPreview.parse(payload(target, "UNKNOWN_STUDIO"))
    with pytest.raises(AgentError):
        RigPreview.parse(payload(target, "BEAUTY_CLAMSHELL") | {"script": "no"})
