"""Level 10 M8: verified two-object Cloth/Collision workflow and rollback."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_cloth_collision_workflow import (
    ClothColliderPreview,
    ClothColliderWorkflowOperations,
)


def setup(allow=True):
    fabric = FakeObject("Fabric")
    ground = FakeObject("Ground")
    bpy = fake_bpy([fabric, ground])
    inspector = BpyInspector(bpy)

    def target(obj):
        snap = inspector.snapshot(obj)
        return {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        }

    args = {
        "cloth": {
            "target": target(fabric),
            "name": "FabricCloth",
            "settings": {
                "quality": 5,
                "mass": 0.3,
                "air_damping": 1.0,
                "tension_stiffness": 12,
                "bending_stiffness": 0.6,
                "self_collision": False,
                "collision_distance": 0.02,
            },
        },
        "collider": {
            "target": target(ground),
            "name": "GroundCollision",
            "settings": {
                "thickness_outer": 0.03,
                "cloth_friction": 8.0,
                "damping": 0.4,
                "use_culling": False,
                "use_normal": True,
            },
        },
    }
    reg = ToolRegistry(
        ClothColliderWorkflowOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=allow),
    )
    return bpy, fabric, ground, inspector, reg, args


def preview(reg, args):
    return reg.dispatch(Request("vfx.cloth_collision_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "vfx.cloth_collision_apply",
            args | {"expected_workflow_revision": plan.data["workflow_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("vfx.cloth_collision_release", {"expected_workflow_token": token}))


def test_m8_compound_blender_rna_and_release_preserve_foreign_modifier():
    _, fabric, ground, inspector, reg, args = setup()
    other = ground.modifiers.new("Foreign", "BEVEL")
    snapshot = inspector.snapshot(ground)
    args["collider"]["target"]["expected_revision"] = snapshot["revision"]
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.verification["matched"]
    assert fabric.modifiers.get("FabricCloth").settings.quality == 5
    assert ground.modifiers.get("GroundCollision").settings.cloth_friction == 8
    assert ground.modifiers[0] is other
    assert release(reg, done.data["workflow_token"]).status == Status.VERIFIED
    assert not fabric.modifiers and ground.modifiers == [other]
    assert inspector.summary()["revision"] == before
    assert release(reg, done.data["workflow_token"]).error.code == ErrorCode.STALE_STATE


def test_m8_rejects_same_object_before_writes():
    _, fabric, ground, _, reg, args = setup()
    args["collider"]["target"] = args["cloth"]["target"]
    denied = preview(reg, args)
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert not fabric.modifiers and not ground.modifiers


def test_m8_stale_source_revision_fails_closed():
    _, fabric, ground, _, reg, args = setup()
    old = preview(reg, args)
    fabric.modifiers.new("External", "BEVEL")
    assert apply(reg, args, old).status == Status.FAILED
    assert fabric.modifiers.get("FabricCloth") is None
    assert not ground.modifiers


def test_m8_second_stage_readback_corruption_rolls_back_both():
    bpy, fabric, ground, inspector, reg, args = setup()
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    calls = {"count": 0}

    def corrupt_second():
        calls["count"] += 1
        if calls["count"] == 2:
            ground.modifiers.get("GroundCollision").settings.damping = 0.9

    bpy.context.view_layer.update = corrupt_second
    out = apply(reg, args, plan)
    assert out.status == Status.FAILED
    assert out.error.code == ErrorCode.VERIFICATION_FAILED
    assert not fabric.modifiers and not ground.modifiers
    assert inspector.summary()["revision"] == before


def test_m8_failure_in_second_update_removes_only_owned_modifiers():
    bpy, fabric, ground, inspector, reg, args = setup()
    other = fabric.modifiers.new("Unrelated", "SUBSURF")
    args["cloth"]["target"]["expected_revision"] = inspector.snapshot(fabric)["revision"]
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    calls = {"count": 0}

    def fail_second():
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("Injected update fault")

    bpy.context.view_layer.update = fail_second
    out = apply(reg, args, plan)
    assert out.status == Status.FAILED
    assert out.error.code == ErrorCode.EXECUTION_ERROR
    assert fabric.modifiers == [other]
    assert not ground.modifiers
    assert inspector.summary()["revision"] == before


def test_m8_foreign_collision_edit_blocks_cleanup():
    _, fabric, ground, _, reg, args = setup()
    made = apply(reg, args, preview(reg, args))
    assert made.status == Status.VERIFIED, made.error
    ground.modifiers.get("GroundCollision").settings.damping = 0.9
    assert release(reg, made.data["workflow_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert fabric.modifiers and ground.modifiers


def test_m8_compound_factory_registration_and_read_only_permission():
    bpy, fabric, ground, inspector, _, args = setup(allow=False)
    catalog = create_registry(bpy, SafetyPolicy(allow_mutations=False)).catalog()
    assert len(catalog) == 289
    expected = {
        "vfx.cloth_collision_preview",
        "vfx.cloth_collision_apply",
        "vfx.cloth_collision_release",
    }
    assert expected <= {tool["name"] for tool in catalog}
    locked = ToolRegistry(
        ClothColliderWorkflowOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert not fabric.modifiers and not ground.modifiers


def test_m8_untrusted_extra_code_and_foreign_release_rejected():
    _, fabric, ground, _, reg, args = setup()
    with pytest.raises(AgentError):
        ClothColliderPreview.parse(args | {"run_code": "import bpy"})
    assert release(reg, "foreign").error.code == ErrorCode.STALE_STATE
    assert not fabric.modifiers and not ground.modifiers
