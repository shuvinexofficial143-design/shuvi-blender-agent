"""Level 10 M10: four-mesh Blender modifier workflow, safety and recovery."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_scene_workflow import VfxScenePreview, VfxSceneWorkflowOperations


def setup(allow=True):
    fabric = FakeObject("Fabric")
    obstacle = FakeObject("Obstacle")
    sea = FakeObject("Sea")
    ripples = FakeObject("Ripples")
    objs = [fabric, obstacle, sea, ripples]
    bpy = fake_bpy(objs)
    inspector = BpyInspector(bpy)

    def target(obj):
        snap = inspector.snapshot(obj)
        return {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        }

    payload = {
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
            "target": target(obstacle),
            "name": "GroundCollision",
            "settings": {
                "thickness_outer": 0.03,
                "cloth_friction": 8,
                "damping": 0.4,
                "use_culling": False,
                "use_normal": True,
            },
        },
        "ocean": {
            "target": target(sea),
            "name": "VfxSea",
            "settings": {
                "resolution": 5,
                "spatial_size": 25.0,
                "wave_scale": 1.0,
                "wave_alignment": 0.5,
                "wave_direction": 0.0,
                "choppiness": 1.2,
                "wind_velocity": 8.0,
                "random_seed": 2,
                "time": 3.5,
                "foam": {
                    "foam_layer_name": "ShuviFoam",
                    "foam_coverage": 1.5,
                    "use_spray": True,
                    "spray_layer_name": "ShuviSpray",
                    "invert_spray": False,
                },
            },
        },
        "wave": {
            "target": target(ripples),
            "name": "VfxRipple",
            "settings": {
                "height": 0.6,
                "width": 1.2,
                "speed": 0.8,
                "narrowness": 1.0,
                "time_offset": 0.0,
                "start_position_x": 0.0,
                "start_position_y": 0.0,
                "use_cyclic": True,
            },
        },
    }
    reg = ToolRegistry(
        VfxSceneWorkflowOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=allow),
    )
    return bpy, objs, inspector, reg, payload


def preview(reg, args):
    return reg.dispatch(Request("vfx.scene_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "vfx.scene_apply",
            args | {"expected_scene_workflow_revision": plan.data["scene_workflow_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("vfx.scene_release", {"expected_scene_workflow_token": token}))


def test_m10_integrates_four_real_modifier_types_with_foam_and_rollback():
    _, objs, inspector, reg, args = setup()
    foreign = objs[2].modifiers.new("KeepMe", "BEVEL")
    args["ocean"]["target"]["expected_revision"] = inspector.snapshot(objs[2])["revision"]
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    assert all(len(o.modifiers) == (1 if o is objs[2] else 0) for o in objs)
    out = apply(reg, args, plan)
    assert out.status == Status.VERIFIED, out.error
    assert out.data["owned_modifiers"] == 4
    assert objs[0].modifiers.get("FabricCloth").type == "CLOTH"
    assert objs[1].modifiers.get("GroundCollision").settings.cloth_friction == 8
    sea = objs[2].modifiers.get("VfxSea")
    assert sea.type == "OCEAN" and sea.geometry_mode == "GENERATE"
    assert sea.foam_layer_name == "ShuviFoam" and sea.use_spray is True
    assert objs[3].modifiers.get("VfxRipple").type == "WAVE"
    assert objs[3].modifiers[0].height == 0.6
    assert release(reg, out.data["scene_workflow_token"]).status == Status.VERIFIED
    assert [list(o.modifiers) for o in objs] == [[], [], [foreign], []]
    assert inspector.summary()["revision"] == before
    assert release(reg, out.data["scene_workflow_token"]).error.code == ErrorCode.STALE_STATE


def test_m10_refuses_same_mesh_for_any_two_stages():
    _, objs, _, reg, args = setup()
    args["wave"]["target"] = args["ocean"]["target"]
    denied = preview(reg, args)
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert all(not o.modifiers for o in objs)


def test_m10_stale_preview_refuses_all_mutation():
    _, objs, _, reg, args = setup()
    plan = preview(reg, args)
    objs[2].modifiers.new("Outside", "BEVEL")
    assert apply(reg, args, plan).status == Status.FAILED
    assert [len(o.modifiers) for o in objs] == [0, 0, 1, 0]


def test_m10_wave_stage_corruption_recovers_all_four_modifiers():
    bpy, objs, inspector, reg, args = setup()
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    calls = {"n": 0}

    def corrupt_fourth():
        calls["n"] += 1
        if calls["n"] == 4:
            objs[3].modifiers.get("VfxRipple").height = 8.0

    bpy.context.view_layer.update = corrupt_fourth
    out = apply(reg, args, plan)
    assert out.status == Status.FAILED
    assert out.error.code == ErrorCode.VERIFICATION_FAILED
    assert all(not o.modifiers for o in objs)
    assert inspector.summary()["revision"] == before


def test_m10_ocean_stage_exception_recovers_cloth_and_collider():
    bpy, objs, inspector, reg, args = setup()
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    calls = {"n": 0}

    def fail_third():
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("Ocean update failed")

    bpy.context.view_layer.update = fail_third
    failed = apply(reg, args, plan)
    assert failed.status == Status.FAILED
    assert failed.error.code == ErrorCode.EXECUTION_ERROR
    assert all(not o.modifiers for o in objs)
    assert inspector.summary()["revision"] == before


def test_m10_refuses_external_edit_before_any_release():
    _, objs, _, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    objs[2].modifiers.get("VfxSea").wind_velocity = 9.9
    denied = release(reg, done.data["scene_workflow_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert [len(o.modifiers) for o in objs] == [1, 1, 1, 1]


def test_m10_preflight_refuses_foreign_modifier_insert():
    _, objs, _, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    objs[3].modifiers.new("Unexpected", "BEVEL")
    denied = release(reg, done.data["scene_workflow_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert objs[0].modifiers.get("FabricCloth") is not None


def test_m10_readonly_policy_and_host_registration():
    bpy, objs, inspector, _, args = setup()
    factory = create_registry(bpy, SafetyPolicy(allow_mutations=False))
    names = {tool["name"] for tool in factory.catalog()}
    assert len(names) == 290
    assert {"vfx.scene_preview", "vfx.scene_apply", "vfx.scene_release"} <= names
    locked = ToolRegistry(
        VfxSceneWorkflowOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert all(not o.modifiers for o in objs)


def test_m10_rejects_arbitrary_code_and_forged_token():
    _, objs, _, reg, args = setup()
    with pytest.raises(AgentError):
        VfxScenePreview.parse(args | {"python": "import os"})
    assert release(reg, "other-session").error.code == ErrorCode.STALE_STATE
    assert all(not o.modifiers for o in objs)


@pytest.mark.parametrize("which", ["ocean", "wave", "cloth", "collider"])
def test_m10_invalid_stage_settings_denied(which):
    _, objs, _, reg, args = setup()
    args[which]["settings"]["foreign"] = {"exec": "python"}
    assert preview(reg, args).status == Status.FAILED
    assert all(not o.modifiers for o in objs)
