"""M4: actual Blender Ocean time F-Curve keying and one-use safe restoration."""

import pytest
from fake_bpy import fake_bpy
from test_vfx_ocean_m2 import apply as apply_ocean
from test_vfx_ocean_m2 import preview as preview_ocean
from test_vfx_ocean_m2 import release as release_ocean
from test_vfx_ocean_m2 import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_ocean import OceanSimulationOperations
from shuvi_blender_agent.vfx_ocean_timeline import OceanTimelineOperations, OceanTimelinePreview


def setup_animated():
    bpy, obj, inspector, ocean_registry, data = setup()
    ocean_plan = preview_ocean(ocean_registry, data)
    made = apply_ocean(ocean_registry, data, ocean_plan)
    assert made.status == Status.VERIFIED, made.error
    ocean = ocean_registry._tools["vfx.ocean_apply"].execute.__self__
    timeline = OceanTimelineOperations(ocean)
    registry = ToolRegistry(
        ocean.tools() + timeline.tools(),
        SafetyPolicy(allow_mutations=True),
    )
    payload = {
        "expected_ocean_token": made.data["ocean_token"],
        "keyframes": [[1, 0.5], [50, 2.5], [100, 7.5]],
    }
    return bpy, obj, inspector, registry, payload


def preview(registry, data):
    result = registry.dispatch(Request("vfx.ocean_timeline_preview", data))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request(
            "vfx.ocean_timeline_apply",
            data | {"expected_timeline_revision": plan["timeline_revision"]},
        )
    )


def restore(registry, token):
    return registry.dispatch(
        Request("vfx.ocean_timeline_restore", {"expected_timeline_token": token})
    )


def test_m4_real_ocean_modifier_creates_timeline_keys_then_restores():
    bpy, obj, inspector, registry, data = setup_animated()
    old_revision = inspector.summary()["revision"]
    plan = preview(registry, data)
    assert not plan["mutation_performed"]
    assert obj.animation_data is None
    done = apply(registry, data, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.verification["matched"]
    assert done.data["keyframe_count"] == 3
    mod = obj.modifiers.get("ShuviOcean")
    assert mod.time == 7.5
    assert obj.animation_data is not None
    fcurve = obj.animation_data.action.fcurves[0]
    assert fcurve.data_path == 'modifiers["ShuviOcean"].time'
    assert [list(k.co) for k in fcurve.keyframe_points] == [
        [1.0, 0.5],
        [50.0, 2.5],
        [100.0, 7.5],
    ]
    undone = restore(registry, done.data["timeline_token"])
    assert undone.status == Status.VERIFIED, undone.error
    assert mod.time == 7.0
    assert obj.animation_data is None
    assert inspector.summary()["revision"] == old_revision
    assert release_ocean(registry, data["expected_ocean_token"]).status == Status.VERIFIED
    assert not obj.modifiers
    assert restore(registry, done.data["timeline_token"]).error.code == ErrorCode.STALE_STATE


def test_m4_owned_ocean_cannot_be_released_before_animation_restore():
    bpy, obj, _, registry, data = setup_animated()
    plan = preview(registry, data)
    done = apply(registry, data, plan)
    assert done.status == Status.VERIFIED
    denied = release_ocean(registry, data["expected_ocean_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("ShuviOcean") is not None
    assert restore(registry, done.data["timeline_token"]).status == Status.VERIFIED


def test_m4_stale_time_plan_wont_write_keyframes():
    _, obj, _, registry, data = setup_animated()
    plan = preview(registry, data)
    data["keyframes"][1][1] = 3.0
    result = apply(registry, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.animation_data is None


def test_m4_external_key_edit_blocks_unsafe_restore():
    _, obj, _, registry, data = setup_animated()
    done = apply(registry, data, preview(registry, data))
    assert done.status == Status.VERIFIED, done.error
    obj.animation_data.action.fcurves[0].keyframe_points[0].co[1] = 999
    result = restore(registry, done.data["timeline_token"])
    assert result.error.code in (ErrorCode.SAFETY_DENIED, ErrorCode.VERIFICATION_FAILED)
    assert obj.animation_data is not None


def test_m4_ocean_existing_object_animation_is_never_adopted():
    _, obj, _, registry, data = setup_animated()
    obj.keyframe_insert("location", frame=10)
    blocked = registry.dispatch(Request("vfx.ocean_timeline_preview", data))
    assert blocked.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.animation_data.action.fcurves) == 3


def test_m4_injected_keyframe_insert_failure_restores_ocean_without_action():
    bpy, obj, inspector, registry, data = setup_animated()
    old_scene = inspector.summary()["revision"]
    mod = obj.modifiers.get("ShuviOcean")
    original = mod.keyframe_insert
    n = {"calls": 0}

    def fail_second(data_path, frame):
        n["calls"] += 1
        if n["calls"] == 2:
            return False
        return original(data_path, frame)

    mod.keyframe_insert = fail_second
    outcome = apply(registry, data, preview(registry, data))
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.EXECUTION_ERROR
    assert obj.animation_data is None
    assert mod.time == 7.0
    assert inspector.summary()["revision"] == old_scene


@pytest.mark.parametrize(
    "keyframes",
    [
        [],
        [[1, 1]],
        [[1, 1], [1, 2]],
        [[2, 3], [1, 4]],
        [[1, 10], [50, 5]],
        [[1, True], [2, 4]],
        [[1, 1.0], [10000, float("nan")]],
        [[0, 1.0], [10, 2.0]],
        [[1.2, 1.0], [10, 2.0]],
        [[1, 1], [10, 2], [20, 3], [30, 4], [40, 5], [50, 6], [60, 7], [70, 8], [80, 9]],
        [[1, 1], "unsafe"],
    ],
)
def test_m4_strict_timeline_input_validation(keyframes):
    with pytest.raises(AgentError):
        OceanTimelinePreview.parse({"expected_ocean_token": "abc", "keyframes": keyframes})


def test_m4_keyframe_outside_scene_range_denied():
    _, obj, _, reg, data = setup_animated()
    data["keyframes"] = [[1, 1], [300, 2]]
    result = reg.dispatch(Request("vfx.ocean_timeline_preview", data))
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert obj.animation_data is None


def test_m4_unknown_token_and_write_policy():
    bpy, obj, inspector, _, data = setup_animated()
    foreign = OceanTimelineOperations(OceanSimulationOperations(ObjectOperations(inspector)))
    foreign_registry = ToolRegistry(foreign.tools(), SafetyPolicy(allow_mutations=True))
    result = foreign_registry.dispatch(Request("vfx.ocean_timeline_preview", data))
    assert result.error.code == ErrorCode.STALE_STATE
    owner_ocean = OceanSimulationOperations(ObjectOperations(inspector))
    policy = ToolRegistry(
        OceanTimelineOperations(owner_ocean).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    assert policy.dispatch(Request("vfx.ocean_timeline_apply", data)).status == Status.FAILED
    assert obj.animation_data is None


def test_m4_factory_registration_uses_allowlisted_typed_contracts():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=False))
    names = {tool["name"] for tool in registry.catalog()}
    assert len(names) == 286
    assert {
        "vfx.ocean_timeline_preview",
        "vfx.ocean_timeline_apply",
        "vfx.ocean_timeline_restore",
    }.issubset(names)
