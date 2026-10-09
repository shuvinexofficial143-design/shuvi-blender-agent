"""Level 10 M5: direct Blender CLOTH modifier settings, safety and rollback."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_cloth import ClothPreview, ClothSimulationOperations


def setup():
    fabric = FakeObject("Drape", "MESH")
    bpy = fake_bpy([fabric])
    inspector = BpyInspector(bpy)
    reg = ToolRegistry(
        ClothSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    snap = inspector.snapshot(fabric)
    args = {
        "target": {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        },
        "name": "ShuviFabric",
        "settings": {
            "quality": 8,
            "mass": 0.4,
            "air_damping": 1.3,
            "tension_stiffness": 18,
            "bending_stiffness": 0.75,
            "self_collision": True,
            "collision_distance": 0.025,
        },
    }
    return bpy, fabric, inspector, reg, args


def preview(reg, args):
    out = reg.dispatch(Request("vfx.cloth_preview", args))
    assert out.status == Status.SUCCEEDED, out.error
    return out.data


def apply(reg, args, plan):
    return reg.dispatch(
        Request("vfx.cloth_apply", args | {"expected_cloth_revision": plan["cloth_revision"]})
    )


def release(reg, token):
    return reg.dispatch(Request("vfx.cloth_release", {"expected_cloth_token": token}))


def test_m5_cloth_writes_nested_blender_rna_and_safe_release():
    _, obj, inspector, reg, args = setup()
    foreign = obj.modifiers.new("Existing", "SUBSURF")
    args["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    assert not plan["mutation_performed"] and plan["evaluated_frames"] == 0
    assert obj.modifiers == [foreign]
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.verification["matched"]
    mod = obj.modifiers.get("ShuviFabric")
    assert mod.type == "CLOTH"
    assert mod.settings.quality == 8
    assert mod.settings.mass == 0.4
    assert mod.settings.bending_stiffness == 0.75
    assert mod.settings.tension_stiffness == 18
    assert mod.collision_settings.use_self_collision is True
    assert mod.collision_settings.distance_min == 0.025
    assert obj.modifiers[0] is foreign
    removed = release(reg, done.data["cloth_token"])
    assert removed.status == Status.VERIFIED, removed.error
    assert obj.modifiers == [foreign]
    assert inspector.summary()["revision"] == before
    assert release(reg, done.data["cloth_token"]).error.code == ErrorCode.STALE_STATE


def test_m5_external_cloth_physics_change_blocks_release():
    _, obj, _, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    obj.modifiers.get("ShuviFabric").settings.mass = 8.0
    refused = release(reg, done.data["cloth_token"])
    assert refused.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("ShuviFabric").settings.mass == 8.0


def test_m5_corrupt_cloth_property_readback_removes_only_owned_modifier():
    bpy, obj, inspector, reg, args = setup()
    foreign = obj.modifiers.new("Foreign", "BEVEL")
    args["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    prior = inspector.summary()["revision"]
    plan = preview(reg, args)
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            obj.modifiers.get("ShuviFabric").collision_settings.distance_min = 0.09

    bpy.context.view_layer.update = corrupt_once
    failed = apply(reg, args, plan)
    assert failed.status == Status.FAILED
    assert failed.error.code == ErrorCode.VERIFICATION_FAILED
    assert obj.modifiers == [foreign]
    assert inspector.summary()["revision"] == prior


def test_m5_stale_target_or_name_collision_refused_before_modification():
    _, obj, _, reg, args = setup()
    old = preview(reg, args)
    obj.modifiers.new("Other", "BEVEL")
    stale = apply(reg, args, old)
    assert stale.error.code in (ErrorCode.STALE_STATE, ErrorCode.INVALID_REQUEST)
    assert obj.modifiers.get("ShuviFabric") is None


def test_m5_same_object_second_cloth_modifier_refused():
    _, obj, inspector, reg, args = setup()
    first = apply(reg, args, preview(reg, args))
    assert first.status == Status.VERIFIED
    snap = inspector.snapshot(obj)
    args["target"]["expected_revision"] = snap["revision"]
    args["name"] = "SecondCloth"
    refused = reg.dispatch(Request("vfx.cloth_preview", args))
    assert refused.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.modifiers) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("quality", 1),
        ("quality", 1.5),
        ("quality", True),
        ("mass", -1),
        ("mass", float("nan")),
        ("air_damping", 15),
        ("bending_stiffness", 99999),
        ("collision_distance", 0),
        ("self_collision", 1),
        ("self_collision", "true"),
    ],
)
def test_m5_invalid_cloth_settings_rejected(field, value):
    _, _, _, _, args = setup()
    args["settings"][field] = value
    with pytest.raises(AgentError):
        ClothPreview.parse(args)


def test_m5_permission_gate_and_factory_registration():
    bpy, obj, inspector, _, args = setup()
    full = create_registry(bpy, SafetyPolicy(allow_mutations=False))
    assert len(full.catalog()) == 289
    names = {entry["name"] for entry in full.catalog()}
    assert {"vfx.cloth_preview", "vfx.cloth_apply", "vfx.cloth_release"} <= names
    locked = ToolRegistry(
        ClothSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    proposal = preview(locked, args)
    assert apply(locked, args, proposal).status == Status.FAILED
    assert not obj.modifiers


def test_m5_foreign_release_and_extra_payload_denied():
    _, obj, _, reg, args = setup()
    assert release(reg, "not-owned").error.code == ErrorCode.STALE_STATE
    with pytest.raises(AgentError):
        ClothPreview.parse(args | {"script": "import bpy"})
    assert not obj.modifiers
