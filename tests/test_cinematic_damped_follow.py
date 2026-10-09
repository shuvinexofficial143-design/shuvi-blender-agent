"""M8: source-side damped camera keyframe baking from moving subject's LINEAR Action."""

import math

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_damped_follow import (
    CameraDampedFollowOperations,
    DampedFollowApply,
    DampedFollowPreview,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup(frames=(1, 3, 5, 7, 9, 11, 13), travel=1.0):
    camera = FakeObject("LagCamera", "CAMERA")
    subject = FakeObject("WalkingSubject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("LagCameraLens")
    camera.data.sensor_width = 36
    camera.data.sensor_fit = "HORIZONTAL"
    subject.location = [0.0, 0.0, 0.0]
    subject.dimensions = [2.0, 2.0, 4.0]
    for index, frame in enumerate(frames):
        subject.location = [0, float(index) * travel, 0]
        assert subject.keyframe_insert(data_path="location", frame=frame)
    for curve in subject.animation_data.action.fcurves:
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"
    subject.location = [0.0, 0.0, 0.0]
    bpy.context.scene.frame_current = frames[0]
    inspector = BpyInspector(bpy)
    ops = CameraDampedFollowOperations(ObjectOperations(inspector))
    registry = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, camera, subject, inspector, registry


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def payload(inspector, camera, subject, **changes):
    data = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "azimuth_degrees": 0,
        "elevation_degrees": 15,
        "margin": 1.2,
        "damping_alpha": 0.25,
        "make_active": True,
    }
    data.update(changes)
    return data


def preview(registry, data):
    result = registry.dispatch(Request("cinema.damped_preview", data))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request(
            "cinema.damped_apply",
            data | {"expected_damped_revision": plan["damped_revision"]},
        )
    )


def test_m8_preview_uses_true_temporal_low_pass_without_mutation():
    bpy, camera, subject, inspector, registry = setup()
    data = payload(inspector, camera, subject)
    before = inspector.snapshot(camera)
    plan = preview(registry, data)
    assert plan == preview(registry, data)
    assert plan["ready"] is True, plan["blockers"]
    assert plan["sample_count"] == 7
    assert plan["keyframe_count"] == 42
    assert plan["scope"] == "M8_BOUNDED_BAKED_DAMPED_FOLLOW"
    assert plan["model"] == "EXPONENTIAL_MOVING_AVERAGE_DELTA_TIME_NORMALIZED"
    assert plan["mutation_performed"] is False
    assert plan["real_runtime_verified"] is False
    assert [x["frame"] for x in plan["key_poses"]] == [1, 3, 5, 7, 9, 11, 13]
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m8_alpha_applies_per_elapsed_frame_instead_of_per_key():
    _, camera, subject, inspector, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    first = plan["key_poses"][0]
    second = plan["key_poses"][1]
    assert first["effective_alpha"] == 1
    assert math.isclose(second["effective_alpha"], 1 - 0.75**2)
    assert math.isclose(second["lagged_target_location"][1], 1 - 0.75**2)
    assert second["lagged_target_location"][1] < second["target_location"][1]
    assert second["location"][1] < first["location"][1] + 1


def test_m8_more_damping_reduces_camera_progress():
    _, camera, subject, inspector, registry = setup()
    heavy = preview(registry, payload(inspector, camera, subject, damping_alpha=0.1))
    light = preview(registry, payload(inspector, camera, subject, damping_alpha=0.9))
    assert heavy["damped_revision"] != light["damped_revision"]
    assert heavy["key_poses"][-1]["location"][1] < light["key_poses"][-1]["location"][1]
    assert heavy["key_poses"][-1]["target_location"] == light["key_poses"][-1]["target_location"]


def test_m8_bake_real_camera_location_and_look_at_rotations():
    bpy, camera, subject, inspector, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    result = apply(registry, data, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert result.data["keyframe_count"] == 42
    assert result.data["channel_count"] == 6
    assert result.data["keyframe_frames"] == [1, 3, 5, 7, 9, 11, 13]
    assert len(camera.animation_data.action.fcurves) == 6
    for curve in camera.animation_data.action.fcurves:
        assert len(curve.keyframe_points) == 7
        assert [p.co[0] for p in curve.keyframe_points] == [1, 3, 5, 7, 9, 11, 13]
        assert all(p.interpolation == "LINEAR" for p in curve.keyframe_points)
    assert list(camera.location) == plan["key_poses"][-1]["location"]
    assert list(camera.rotation_euler) == plan["key_poses"][-1]["rotation_euler"]
    assert bpy.context.scene.frame_current == 1
    assert bpy.context.scene.camera is camera
    assert subject.animation_data is not None


def test_m8_variable_key_spacing_is_respected():
    bpy, camera, subject, inspector, registry = setup(frames=(1, 2, 5, 6, 10, 13))
    plan = preview(registry, payload(inspector, camera, subject))
    assert plan["ready"]
    assert math.isclose(plan["key_poses"][1]["effective_alpha"], 0.25)
    assert math.isclose(plan["key_poses"][2]["effective_alpha"], 1 - 0.75**3)
    assert plan["key_poses"][-1]["frame"] == 13


def test_m8_bakes_at_least_six_poses_to_exercise_extended_writer():
    _, camera, subject, inspector, registry = setup(frames=(1, 2, 3, 4, 5, 6))
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    outcome = apply(registry, params, plan)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert outcome.data["keyframe_count"] == 36


@pytest.mark.parametrize(
    "bad",
    [
        {"damping_alpha": True},
        {"damping_alpha": 0},
        {"damping_alpha": 1},
        {"damping_alpha": -1},
        {"damping_alpha": "0.4"},
        {"make_active": "yes"},
    ],
)
def test_m8_strict_invalid_payloads(bad):
    _, camera, subject, inspector, _ = setup()
    with pytest.raises(AgentError):
        DampedFollowPreview.parse(payload(inspector, camera, subject, **bad))


def test_m8_apply_requires_preview_revision():
    _, camera, subject, inspector, _ = setup()
    params = payload(inspector, camera, subject)
    with pytest.raises(AgentError):
        DampedFollowApply.parse(params)
    with pytest.raises(AgentError):
        DampedFollowPreview.parse(params | {"python": "import bpy"})


def test_m8_changed_damping_or_camera_shot_invalidates_preview():
    _, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    for change in ({"damping_alpha": 0.3}, {"elevation_degrees": 25}):
        bad = apply(registry, params | change, plan)
        assert bad.error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


def test_m8_changed_subject_action_invalidates_preview_before_mutation():
    _, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    subject.animation_data.action.fcurves[1].keyframe_points[2].co[1] += 0.1
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


@pytest.mark.parametrize(
    "change",
    [
        "no_animation",
        "slot",
        "drivers",
        "nla",
        "shared_action",
        "parent",
        "constraint",
        "rotated",
        "scaled",
        "camera_animated",
        "nonlinear",
        "missing_axis",
        "wrong_path",
        "bad_first_pose",
        "wrong_scene_frame",
        "unequal_frames",
        "wrong_frame_gap",
        "too_few_frames",
        "subframe",
    ],
)
def test_m8_denies_unsafe_source_and_camera(change):
    bpy, camera, subject, inspector, registry = setup()
    if change == "no_animation":
        subject.animation_data = None
    elif change == "slot":
        subject.animation_data.action_slot = object()
    elif change == "drivers":
        subject.animation_data.drivers.append(object())
    elif change == "nla":
        subject.animation_data.nla_tracks.append(object())
    elif change == "shared_action":
        subject.animation_data.action.users = 2
    elif change == "parent":
        subject.parent = FakeObject("Parent")
    elif change == "constraint":
        subject.constraints.new(type="TRACK_TO")
    elif change == "rotated":
        subject.rotation_euler = [0, 0, 0.25]
    elif change == "scaled":
        subject.scale = [2, 1, 1]
    elif change == "camera_animated":
        camera.keyframe_insert(data_path="location", frame=1)
    elif change == "nonlinear":
        subject.animation_data.action.fcurves[0].keyframe_points[1].interpolation = "BEZIER"
    elif change == "missing_axis":
        subject.animation_data.action.fcurves.pop()
    elif change == "wrong_path":
        subject.animation_data.action.fcurves[0].data_path = "rotation_euler"
    elif change == "bad_first_pose":
        subject.location[1] = 99
    elif change == "wrong_scene_frame":
        bpy.context.scene.frame_current = 5
    elif change == "unequal_frames":
        subject.animation_data.action.fcurves[0].keyframe_points[1].co[0] = 4
    elif change == "wrong_frame_gap":
        for curve in subject.animation_data.action.fcurves:
            curve.keyframe_points[-1].co[0] = 201
    elif change == "too_few_frames":
        for curve in subject.animation_data.action.fcurves:
            del curve.keyframe_points[4:]
    else:
        for curve in subject.animation_data.action.fcurves:
            curve.keyframe_points[1].co[0] = 2.5
    params = payload(inspector, camera, subject)
    outcome = registry.dispatch(Request("cinema.damped_preview", params))
    assert outcome.status == Status.FAILED or not outcome.data["ready"]
    assert camera.animation_data is None if change != "camera_animated" else True


def test_m8_rejects_subject_motion_damaging_framing():
    _, camera, subject, inspector, registry = setup(travel=5000)
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    assert plan["blockers"]
    assert plan["ready"] is False
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_m8_partial_keyframe_failure_restores_camera_state():
    _, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    original_insert = camera.keyframe_insert
    calls = {"n": 0}

    def interrupted(**kwargs):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("injected camera keyframe interruption")
        return original_insert(**kwargs)

    camera.keyframe_insert = interrupted
    outcome = apply(registry, params, plan)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.EXECUTION_ERROR
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m8_corrupt_final_pose_rolls_back_new_action():
    bpy, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    count = {"n": 0}

    def corrupt():
        count["n"] += 1
        if count["n"] == 1:
            camera.location = [9999, 0, 0]

    bpy.context.view_layer.update = corrupt
    outcome = apply(registry, params, plan)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.VERIFICATION_FAILED
    assert outcome.data["rolled_back"] is True
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m8_hard_cap_24_sampled_subject_keys():
    bpy, camera, subject, inspector, registry = setup(frames=tuple(range(1, 26)))
    params = payload(inspector, camera, subject)
    outcome = registry.dispatch(Request("cinema.damped_preview", params))
    assert outcome.error.code == ErrorCode.SAFETY_DENIED
    assert camera.animation_data is None


def test_m8_factory_host_allowlist_has_two_new_tools():
    factory = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(factory.catalog()) == MAX_REGISTERED_TOOLS == 326
    assert {"cinema.damped_preview", "cinema.damped_apply"} <= {
        row["name"] for row in factory.catalog()
    }
