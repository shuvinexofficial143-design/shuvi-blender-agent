"""Level 10 M1: actual managed WAVE modifier, readback, stale/undo safety."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_wave import WavePreview, WaveSimulationOperations


def setup():
    subject = FakeObject("RippleSurface", "MESH")
    bpy = fake_bpy([subject])
    insp = BpyInspector(bpy)
    reg = ToolRegistry(
        WaveSimulationOperations(ObjectOperations(insp)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    snap = insp.snapshot(subject)
    target = {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }
    args = {
        "target": target,
        "name": "ShuviWave",
        "settings": {
            "height": 0.8,
            "width": 1.2,
            "speed": 0.7,
            "narrowness": 1.3,
            "time_offset": 0,
            "start_position_x": 0.3,
            "start_position_y": -0.1,
            "use_cyclic": True,
        },
    }
    return bpy, subject, insp, reg, args


def preview(reg, args):
    result = reg.dispatch(Request("vfx.wave_preview", args))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(reg, args, plan):
    return reg.dispatch(
        Request("vfx.wave_apply", args | {"expected_wave_revision": plan["wave_revision"]})
    )


def release(reg, token):
    return reg.dispatch(Request("vfx.wave_release", {"expected_wave_token": token}))


def test_m1_real_wave_modifier_apply_exact_readback_and_release():
    bpy, obj, insp, reg, args = setup()
    foreign = obj.modifiers.new("ExistingSubsurf", "SUBSURF")
    # Foreign modifier was added after the initial inspection; refresh
    # ObjectTarget instead of bypassing the production stale-state guard.
    latest = insp.snapshot(obj)
    args["target"]["expected_revision"] = latest["revision"]
    before = insp.summary()["revision"]
    planned = preview(reg, args)
    assert not planned["mutation_performed"] and planned["simulated_frames"] == 0
    assert len(obj.modifiers) == 1
    created = apply(reg, args, planned)
    assert created.status == Status.VERIFIED, created.error
    assert created.verification["matched"]
    assert len(obj.modifiers) == 2
    mod = obj.modifiers.get("ShuviWave")
    assert mod.type == "WAVE"
    assert mod.height == 0.8
    assert mod.speed == 0.7
    assert mod.start_position_y == -0.1
    assert mod.use_x and mod.use_y and mod.use_cyclic
    assert obj.modifiers[0] is foreign
    result = release(reg, created.data["wave_token"])
    assert result.status == Status.VERIFIED, result.error
    assert obj.modifiers == [foreign]
    assert insp.summary()["revision"] == before
    assert release(reg, created.data["wave_token"]).error.code == ErrorCode.STALE_STATE


def test_m1_scene_or_target_change_refuses_stale_apply():
    bpy, obj, _, reg, args = setup()
    plan = preview(reg, args)
    obj.modifiers.new("Foreign", "BEVEL")
    result = apply(reg, args, plan)
    assert result.status == Status.FAILED
    assert result.error.code in (ErrorCode.STALE_STATE, ErrorCode.INVALID_REQUEST)
    assert obj.modifiers.get("ShuviWave") is None


def test_m1_external_property_change_refuses_to_delete_wave():
    _, obj, _, reg, args = setup()
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    obj.modifiers.get("ShuviWave").height = 9
    denied = release(reg, result.data["wave_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("ShuviWave").height == 9


def test_m1_partial_write_or_corrupt_readback_restores_old_state():
    bpy, obj, insp, reg, args = setup()
    original_scene = insp.summary()["revision"]
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            obj.modifiers.get("ShuviWave").width = 9

    bpy.context.view_layer.update = corrupt_once
    outcome = apply(reg, args, preview(reg, args))
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.VERIFICATION_FAILED
    assert not obj.modifiers
    assert insp.summary()["revision"] == original_scene


@pytest.mark.parametrize(
    "field,value",
    [
        ("height", float("nan")),
        ("height", 20),
        ("speed", -1),
        ("narrowness", 0),
        ("width", 0),
        ("use_cyclic", 0),
        ("start_position_x", True),
        ("start_position_y", 1e12),
    ],
)
def test_m1_bad_wave_input_denied_before_mutation(field, value):
    _, _, _, _, args = setup()
    args["settings"][field] = value
    with pytest.raises(AgentError):
        WavePreview.parse(args)


def test_m1_unknown_keys_and_mutation_permission_denied():
    bpy, obj, insp, _, args = setup()
    with pytest.raises(AgentError):
        WavePreview.parse(args | {"python": "import bpy"})
    reg = ToolRegistry(
        WaveSimulationOperations(ObjectOperations(insp)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    planned = preview(reg, args)
    denied = apply(reg, args, planned)
    assert denied.status == Status.FAILED
    assert not obj.modifiers


def test_m1_foreign_token_cannot_release_other_session_modifier():
    bpy, obj, insp, reg, args = setup()
    created = apply(reg, args, preview(reg, args))
    assert created.status == Status.VERIFIED
    unrelated = ToolRegistry(
        WaveSimulationOperations(ObjectOperations(BpyInspector(bpy))).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    assert release(unrelated, created.data["wave_token"]).error.code == ErrorCode.STALE_STATE
    assert len(obj.modifiers) == 1
