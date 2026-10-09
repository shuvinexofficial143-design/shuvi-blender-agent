"""Level 10 M6: actual COLLISION surface settings and Cloth integration."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_cloth import ClothSimulationOperations
from shuvi_blender_agent.vfx_collision import CollisionPreview, CollisionSimulationOperations


def setup():
    ground = FakeObject("CollisionGround", "MESH")
    bpy = fake_bpy([ground])
    inspector = BpyInspector(bpy)
    ops = CollisionSimulationOperations(ObjectOperations(inspector))
    registry = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    snap = inspector.snapshot(ground)
    args = {
        "target": {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        },
        "name": "ShuviCollider",
        "settings": {
            "thickness_outer": 0.04,
            "cloth_friction": 12.0,
            "damping": 0.3,
            "use_culling": True,
            "use_normal": False,
        },
    }
    return bpy, ground, inspector, registry, args


def preview(registry, args):
    outcome = registry.dispatch(Request("vfx.collision_preview", args))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    return outcome.data


def apply(registry, args, plan):
    return registry.dispatch(
        Request(
            "vfx.collision_apply",
            args | {"expected_collision_revision": plan["collision_revision"]},
        )
    )


def release(registry, token):
    return registry.dispatch(Request("vfx.collision_release", {"expected_collision_token": token}))


def test_m6_real_collision_modifier_and_exact_owned_release():
    _, ground, inspector, reg, args = setup()
    unrelated = ground.modifiers.new("Existing", "BEVEL")
    args["target"]["expected_revision"] = inspector.snapshot(ground)["revision"]
    prior = inspector.summary()["revision"]
    plan = preview(reg, args)
    assert not plan["mutation_performed"]
    result = apply(reg, args, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"]
    mod = ground.modifiers.get("ShuviCollider")
    assert mod.type == "COLLISION"
    assert mod.settings.use is True
    assert mod.settings.thickness_outer == 0.04
    assert mod.settings.cloth_friction == 12
    assert mod.settings.damping == 0.3
    assert mod.settings.use_culling is True
    assert mod.settings.use_normal is False
    assert ground.modifiers[0] is unrelated
    undone = release(reg, result.data["collision_token"])
    assert undone.status == Status.VERIFIED, undone.error
    assert ground.modifiers == [unrelated]
    assert inspector.summary()["revision"] == prior
    assert release(reg, result.data["collision_token"]).error.code == ErrorCode.STALE_STATE


def test_m6_collision_and_cloth_can_coexist_on_separate_meshes():
    cloth_obj = FakeObject("Flag", "MESH")
    collision_obj = FakeObject("Ground", "MESH")
    bpy = fake_bpy([cloth_obj, collision_obj])
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    reg = ToolRegistry(
        ClothSimulationOperations(objects).tools() + CollisionSimulationOperations(objects).tools(),
        SafetyPolicy(allow_mutations=True),
    )

    def target(obj):
        snap = inspector.snapshot(obj)
        return {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        }

    cloth_args = {
        "target": target(cloth_obj),
        "name": "FlagCloth",
        "settings": {
            "quality": 5,
            "mass": 0.3,
            "air_damping": 1,
            "tension_stiffness": 10,
            "bending_stiffness": 0.5,
            "self_collision": False,
            "collision_distance": 0.015,
        },
    }
    cplan = reg.dispatch(Request("vfx.cloth_preview", cloth_args)).data
    cloth = reg.dispatch(
        Request(
            "vfx.cloth_apply",
            cloth_args | {"expected_cloth_revision": cplan["cloth_revision"]},
        )
    )
    assert cloth.status == Status.VERIFIED, cloth.error
    collision_args = {
        "target": target(collision_obj),
        "name": "GroundCollider",
        "settings": {
            "thickness_outer": 0.05,
            "cloth_friction": 9,
            "damping": 0.5,
            "use_culling": False,
            "use_normal": True,
        },
    }
    plan = reg.dispatch(Request("vfx.collision_preview", collision_args)).data
    collider = reg.dispatch(
        Request(
            "vfx.collision_apply",
            collision_args | {"expected_collision_revision": plan["collision_revision"]},
        )
    )
    assert collider.status == Status.VERIFIED, collider.error
    assert cloth_obj.modifiers[0].type == "CLOTH"
    assert collision_obj.modifiers[0].type == "COLLISION"
    assert release(reg, collider.data["collision_token"]).status == Status.VERIFIED
    assert (
        reg.dispatch(
            Request("vfx.cloth_release", {"expected_cloth_token": cloth.data["cloth_token"]})
        ).status
        == Status.VERIFIED
    )
    assert not cloth_obj.modifiers and not collision_obj.modifiers


def test_m6_foreign_change_refuses_collider_deletion():
    _, obj, _, reg, args = setup()
    made = apply(reg, args, preview(reg, args))
    assert made.status == Status.VERIFIED, made.error
    obj.modifiers.get("ShuviCollider").settings.thickness_outer = 0.9
    denied = release(reg, made.data["collision_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("ShuviCollider") is not None


def test_m6_partial_property_corruption_restores_only_own_modifier():
    bpy, obj, inspector, reg, args = setup()
    other = obj.modifiers.new("Other", "SUBSURF")
    args["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    called = {"n": 0}

    def corrupt_once():
        called["n"] += 1
        if called["n"] == 1:
            obj.modifiers.get("ShuviCollider").settings.damping = 0.99

    bpy.context.view_layer.update = corrupt_once
    failed = apply(reg, args, plan)
    assert failed.status == Status.FAILED
    assert failed.error.code == ErrorCode.VERIFICATION_FAILED
    assert obj.modifiers == [other]
    assert inspector.summary()["revision"] == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("thickness_outer", 0),
        ("thickness_outer", 3),
        ("cloth_friction", -1),
        ("cloth_friction", float("inf")),
        ("damping", 2),
        ("use_culling", 1),
        ("use_normal", "yes"),
    ],
)
def test_m6_bad_collision_settings_rejected(key, value):
    _, _, _, _, args = setup()
    args["settings"][key] = value
    with pytest.raises(AgentError):
        CollisionPreview.parse(args)


def test_m6_fails_closed_on_stale_preview_or_duplicate_collider():
    _, obj, inspector, reg, args = setup()
    initial = preview(reg, args)
    obj.modifiers.new("Foreign", "BEVEL")
    assert apply(reg, args, initial).error.code in (
        ErrorCode.STALE_STATE,
        ErrorCode.INVALID_REQUEST,
    )
    assert obj.modifiers.get("ShuviCollider") is None
    args["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    made = apply(reg, args, preview(reg, args))
    assert made.status == Status.VERIFIED
    args["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    args["name"] = "DuplicateCollider"
    blocked = reg.dispatch(Request("vfx.collision_preview", args))
    assert blocked.error.code == ErrorCode.SAFETY_DENIED


def test_m6_factory_registration_and_permission_boundary():
    bpy, ground, inspector, _, args = setup()
    catalog = create_registry(bpy, SafetyPolicy(allow_mutations=False)).catalog()
    assert len(catalog) == 296
    names = {row["name"] for row in catalog}
    assert {"vfx.collision_preview", "vfx.collision_apply", "vfx.collision_release"} <= names
    read_only = ToolRegistry(
        CollisionSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(read_only, args)
    assert apply(read_only, args, plan).status == Status.FAILED
    assert not ground.modifiers


def test_m6_unknown_token_and_unsafe_extra_fields_denied():
    _, obj, _, reg, args = setup()
    assert release(reg, "foreign").error.code == ErrorCode.STALE_STATE
    with pytest.raises(AgentError):
        CollisionPreview.parse(args | {"execute": "import os"})
    assert not obj.modifiers
