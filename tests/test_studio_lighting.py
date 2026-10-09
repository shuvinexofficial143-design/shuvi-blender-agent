"""Level 9 M1: source-only studio Key/Fill/Rim AREA light rig regression tests."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.studio_lighting import (
    RigApply,
    RigPreview,
    RigRelease,
    StudioLightingOperations,
)
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    subject = FakeObject("StudioSubject", "MESH")
    bpy = fake_bpy([subject])
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 3.0, 4.0]
    inspector = BpyInspector(bpy)
    ops = StudioLightingOperations(ObjectOperations(inspector))
    registry = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, subject, inspector, ops, registry


def target(inspector, obj):
    s = inspector.snapshot(obj)
    return {
        "object_id": s["object_id"],
        "expected_name": s["name"],
        "expected_revision": s["revision"],
    }


def params(inspector, subject, **changes):
    data = {
        "subject": target(inspector, subject),
        "name_prefix": "StudioRig",
        "preset": "SOFT_STUDIO",
        "distance_scale": 3.5,
        "intensity_scale": 1.0,
    }
    data.update(changes)
    return data


def preview(registry, data):
    outcome = registry.dispatch(Request("lighting.studio_preview", data))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    return outcome.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request(
            "lighting.studio_apply",
            data | {"expected_lighting_revision": plan["lighting_revision"]},
        )
    )


def release(registry, token):
    return registry.dispatch(Request("lighting.studio_release", {"expected_lighting_token": token}))


def test_l9_m1_preview_is_deterministic_and_never_mutates():
    bpy, subject, inspector, _, registry = setup()
    before = inspector.summary()["revision"]
    data = params(inspector, subject)
    plan = preview(registry, data)
    assert plan == preview(registry, data)
    assert plan["ready"], plan["blockers"]
    assert [entry["role"] for entry in plan["lights"]] == ["Key", "Fill", "Rim"]
    assert [entry["name"] for entry in plan["lights"]] == [
        "StudioRig_Key",
        "StudioRig_Fill",
        "StudioRig_Rim",
    ]
    assert [entry["energy"] for entry in plan["lights"]] == [1200.0, 500.0, 850.0]
    assert plan["source_only"] is True
    assert plan["render_verified"] is False
    assert plan["mutation_performed"] is False
    assert len(plan["lighting_revision"]) == 64
    assert bpy.context.scene.objects == [subject]
    assert len(bpy.data.lights) == 0
    assert inspector.summary()["revision"] == before


@pytest.mark.parametrize(
    "preset",
    ["SOFT_STUDIO", "DRAMATIC", "WARM_PORTRAIT"],
)
def test_l9_m1_preset_creates_three_real_area_lights(preset):
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject, preset=preset)
    plan = preview(registry, data)
    outcome = apply(registry, data, plan)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert outcome.verification["matched"] is True
    assert outcome.data["lights_created"] == 3
    assert len(bpy.data.lights) == 3
    for entry in plan["lights"]:
        obj = bpy.data.objects.get(entry["name"])
        assert obj is not None
        assert obj.type == "LIGHT"
        assert obj.data.type == "AREA"
        assert obj.data.shape == "DISK"
        assert obj.data.size == entry["size"]
        assert obj.data.energy == entry["energy"]
        assert list(obj.data.color) == entry["color"]
        assert list(obj.location) == entry["location"]
        assert list(obj.rotation_euler) == entry["rotation_euler"]
        assert obj.data.users == 1
        assert obj in bpy.context.scene.objects
    assert subject.type == "MESH"


def test_l9_m1_roles_have_real_angular_separation_and_subject_aim():
    _, subject, inspector, _, registry = setup()
    plan = preview(registry, params(inspector, subject))
    assert len({tuple(round(v, 5) for v in row["location"]) for row in plan["lights"]}) == 3
    assert len({tuple(round(v, 5) for v in row["rotation_euler"]) for row in plan["lights"]}) == 3
    assert plan["lights"][0]["energy"] > plan["lights"][1]["energy"]
    assert plan["lights"][2]["energy"] > plan["lights"][1]["energy"]
    assert plan["lights"][1]["size"] > plan["lights"][2]["size"]


def test_l9_m1_energy_and_distance_scaling_changes_real_values():
    _, subject, inspector, _, registry = setup()
    base = preview(registry, params(inspector, subject))
    scaled = preview(registry, params(inspector, subject, intensity_scale=2, distance_scale=5))
    assert scaled["lighting_revision"] != base["lighting_revision"]
    for a, b in zip(base["lights"], scaled["lights"], strict=True):
        assert b["energy"] == 2 * a["energy"]
        assert b["location"] != a["location"]
        assert b["color"] == a["color"]


def test_l9_m1_release_cleans_up_all_three_owned_lights_and_restores_scene():
    bpy, subject, inspector, ops, registry = setup()
    before = inspector.summary()["revision"]
    data = params(inspector, subject)
    outcome = apply(registry, data, preview(registry, data))
    assert outcome.status == Status.VERIFIED, outcome.error
    released = release(registry, outcome.data["lighting_token"])
    assert released.status == Status.VERIFIED, released.error
    assert released.verification["matched"] is True
    assert released.data["removed_owned_lights"] == 3
    assert bpy.context.scene.objects == [subject]
    assert len(bpy.data.lights) == 0
    assert inspector.summary()["revision"] == before
    assert not ops._owned


def test_l9_m1_unrelated_existing_light_is_never_modified_or_removed():
    bpy, subject, inspector, _, registry = setup()
    data_foreign = bpy.data.lights.new("ForeignLight", "POINT")
    data_foreign.energy = 42
    foreign = bpy.data.objects.new("ForeignLight", data_foreign)
    bpy.context.scene.collection.objects.link(foreign)
    initial = inspector.snapshot(foreign)
    data = params(inspector, subject)
    outcome = apply(registry, data, preview(registry, data))
    assert outcome.status == Status.VERIFIED, outcome.error
    assert release(registry, outcome.data["lighting_token"]).status == Status.VERIFIED
    assert bpy.data.objects.get("ForeignLight") is foreign
    assert bpy.data.lights == [data_foreign]
    assert inspector.snapshot(foreign)["revision"] == initial["revision"]


def test_l9_m1_mutating_subject_after_preview_denies_apply():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    plan = preview(registry, data)
    subject.location = [4, 5, 6]
    denied = apply(registry, data, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert len(bpy.data.lights) == 0


def test_l9_m1_mutating_other_scene_object_after_preview_denies_apply():
    bpy, subject, inspector, _, registry = setup()
    other = FakeObject("OtherObject", "EMPTY")
    bpy.data.objects.link(other)
    data = params(inspector, subject)
    plan = preview(registry, data)
    other.location = [20, 0, 0]
    denied = apply(registry, data, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights


def test_l9_m1_changed_preset_after_preview_is_stale():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    plan = preview(registry, data)
    outcome = apply(registry, data | {"preset": "DRAMATIC"}, plan)
    assert outcome.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights


@pytest.mark.parametrize(
    "problem",
    [
        "parent",
        "constraint",
        "animated",
        "rotation",
        "scale",
        "linked",
        "mode",
        "name_collision",
    ],
)
def test_l9_m1_unsafe_subject_or_reserved_light_names_fail_closed(problem):
    bpy, subject, inspector, _, registry = setup()
    if problem == "parent":
        subject.parent = FakeObject("Parent", "EMPTY")
    elif problem == "constraint":
        subject.constraints.new(type="TRACK_TO")
    elif problem == "animated":
        subject.animation_data = NS(action=None, drivers=[], nla_tracks=[])
    elif problem == "rotation":
        subject.rotation_euler = [0, 0, 0.25]
    elif problem == "scale":
        subject.scale = [1, 2, 1]
    elif problem == "linked":
        subject.library = "OtherLibrary"
    elif problem == "mode":
        bpy.context.mode = "EDIT_MESH"
    else:
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("StudioRig_Key", None))
    data = params(inspector, subject)
    plan = preview(registry, data)
    assert not plan["ready"], problem
    assert apply(registry, data, plan).error.code == ErrorCode.SAFETY_DENIED
    assert not bpy.data.lights


def test_l9_m1_requires_mesh_subject_with_valid_size():
    bpy, subject, inspector, _, registry = setup()
    subject.dimensions = [0, 0, 0]
    data = params(inspector, subject)
    assert registry.dispatch(Request("lighting.studio_preview", data)).error.code == (
        ErrorCode.SAFETY_DENIED
    )
    subject.type = "EMPTY"
    data = params(inspector, subject)
    assert registry.dispatch(Request("lighting.studio_preview", data)).error.code == (
        ErrorCode.SAFETY_DENIED
    )


def test_l9_m1_partial_second_data_creation_rolls_back_every_owned_object():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    plan = preview(registry, data)
    before = inspector.summary()["revision"]
    original = bpy.data.lights.new
    calls = {"n": 0}

    def fail_second(name, kind):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("Injected second AREA light failure")
        return original(name, kind)

    bpy.data.lights.new = fail_second
    outcome = apply(registry, data, plan)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.EXECUTION_ERROR
    assert len(bpy.data.lights) == 0
    assert bpy.context.scene.objects == [subject]
    assert inspector.summary()["revision"] == before


def test_l9_m1_corrupt_light_size_readback_rolls_back_entire_rig():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    plan = preview(registry, data)
    before = inspector.summary()["revision"]
    counter = {"n": 0}

    def corrupt_once():
        counter["n"] += 1
        if counter["n"] == 1:
            bpy.data.objects.get("StudioRig_Fill").data.size = 0.1

    bpy.context.view_layer.update = corrupt_once
    outcome = apply(registry, data, plan)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.VERIFICATION_FAILED
    assert outcome.data["rolled_back"] is True
    assert len(bpy.data.lights) == 0
    assert inspector.summary()["revision"] == before


def test_l9_m1_interrupt_scene_update_rolls_back_without_orphan_data():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    plan = preview(registry, data)
    count = {"n": 0}

    def interrupt_once():
        count["n"] += 1
        if count["n"] == 1:
            raise RuntimeError("Injected dependency graph update failure")

    bpy.context.view_layer.update = interrupt_once
    outcome = apply(registry, data, plan)
    assert outcome.error.code == ErrorCode.EXECUTION_ERROR
    assert len(bpy.data.lights) == 0
    assert bpy.context.scene.objects == [subject]


def test_l9_m1_release_refuses_modified_light_and_scene_changes():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    outcome = apply(registry, data, preview(registry, data))
    assert outcome.status == Status.VERIFIED
    key = bpy.data.objects.get("StudioRig_Key")
    key.data.energy *= 0.5
    denied = release(registry, outcome.data["lighting_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(bpy.data.lights) == 3


def test_l9_m1_release_unknown_token_and_replay_fail_closed():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    outcome = apply(registry, data, preview(registry, data))
    assert release(registry, "f" * 64).error.code == ErrorCode.STALE_STATE
    assert release(registry, outcome.data["lighting_token"]).status == Status.VERIFIED
    assert release(registry, outcome.data["lighting_token"]).error.code == ErrorCode.STALE_STATE


def test_l9_m1_release_foreign_session_cannot_claim_original_rig():
    bpy, subject, inspector, _, registry = setup()
    data = params(inspector, subject)
    outcome = apply(registry, data, preview(registry, data))
    other_ops = StudioLightingOperations(ObjectOperations(BpyInspector(bpy)))
    other_registry = ToolRegistry(other_ops.tools(), SafetyPolicy(allow_mutations=True))
    assert release(other_registry, outcome.data["lighting_token"]).error.code == (
        ErrorCode.STALE_STATE
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("preset", "MOONLIGHT"),
        ("distance_scale", 0),
        ("intensity_scale", 10),
        ("name_prefix", "A" * 41),
        ("intensity_scale", True),
    ],
)
def test_l9_m1_parser_strict_invalid_requests(field, value):
    _, subject, inspector, _, _ = setup()
    with pytest.raises(AgentError):
        RigPreview.parse(params(inspector, subject, **{field: value}))


def test_l9_m1_strict_apply_and_release_payload_validation():
    _, subject, inspector, _, _ = setup()
    data = params(inspector, subject)
    with pytest.raises(AgentError):
        RigApply.parse(data)
    with pytest.raises(AgentError):
        RigPreview.parse(data | {"python": "import bpy"})
    with pytest.raises(AgentError):
        RigRelease.parse({"expected_lighting_token": 123})
    with pytest.raises(AgentError):
        RigRelease.parse({})


def test_l9_m1_host_registry_has_three_new_tools_and_permission_gate():
    bpy, subject, inspector, _, registry = setup()
    full = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    assert len(full.catalog()) == MAX_REGISTERED_TOOLS == 286
    names = {entry["name"] for entry in full.catalog()}
    assert {
        "lighting.studio_preview",
        "lighting.studio_apply",
        "lighting.studio_release",
    } <= names
    factory_inspector = full._tools["lighting.studio_preview"].execute.__self__.inspector
    data = params(factory_inspector, subject)
    planned = preview(full, data)
    outcome = apply(full, data, planned)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert release(full, outcome.data["lighting_token"]).status == Status.VERIFIED
    no_mutate = ToolRegistry(
        StudioLightingOperations(ObjectOperations(BpyInspector(bpy))).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    denied = no_mutate.dispatch(
        Request(
            "lighting.studio_apply",
            data | {"expected_lighting_revision": planned["lighting_revision"]},
        )
    )
    assert denied.status == Status.FAILED
