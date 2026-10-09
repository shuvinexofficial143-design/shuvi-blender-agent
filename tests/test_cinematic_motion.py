"""M3 camera movement: real managed source keyframes, revisions and failure rollback."""

from math import isclose
from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_motion import (
    CameraMotionApply,
    CameraMotionOperations,
    CameraMotionPreview,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("MotionCamera", "CAMERA")
    subject = FakeObject("Subject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("MotionCameraData")
    camera.data.sensor_width = 36
    camera.data.sensor_fit = "HORIZONTAL"
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 2.0, 4.0]
    inspector = BpyInspector(bpy)
    motion = CameraMotionOperations(ObjectOperations(inspector))
    registry = ToolRegistry(motion.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, camera, subject, inspector, registry


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def args(inspector, camera, subject, **overrides):
    values = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "start_frame": 10,
        "end_frame": 50,
        "mode": "ORBIT",
        "start_azimuth": 0,
        "end_azimuth": 40,
        "start_elevation": 10,
        "end_elevation": 20,
        "margin": 1.2,
        "dolly_factor": 1,
        "make_active": True,
    }
    values.update(overrides)
    return values


def preview(registry, params):
    r = registry.dispatch(Request("cinema.motion_preview", params))
    assert r.status == Status.SUCCEEDED, r.error
    return r.data


def apply(registry, params, plan):
    return registry.dispatch(
        Request(
            "cinema.motion_apply",
            params
            | {
                "expected_motion_revision": plan["motion_revision"],
            },
        )
    )


def test_m3_orbit_preview_deterministic_and_nonmutating():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    before = inspector.snapshot(camera)
    first = preview(registry, params)
    assert first == preview(registry, params)
    assert first["ready"]
    assert first["key_poses"][0]["frame"] == 10
    assert first["key_poses"][1]["frame"] == 30
    assert first["key_poses"][2]["frame"] == 50
    assert first["mode"] == "ORBIT"
    assert first["interpolation"] == "LINEAR"
    assert len(first["motion_revision"]) == 64
    assert first["mutation_performed"] is False
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


@pytest.mark.parametrize("mode", ["ORBIT", "DOLLY_IN", "DOLLY_OUT"])
def test_m3_creates_three_real_camera_poses_with_eighteen_keyframes(mode):
    bpy, camera, subject, inspector, registry = setup()
    overrides = {}
    if mode != "ORBIT":
        overrides = {"mode": mode, "end_azimuth": 0, "end_elevation": 10, "dolly_factor": 1.6}
    params = args(inspector, camera, subject, **overrides)
    plan = preview(registry, params)
    result = apply(registry, params, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert result.data["keyframe_count"] == 18
    assert result.data["channel_count"] == 6
    assert result.data["keyframe_frames"] == [10, 30, 50]
    assert camera.animation_data.action.users == 1
    assert bpy.context.scene.camera is camera
    assert bpy.context.scene.frame_current == 1
    assert list(camera.location) == plan["key_poses"][-1]["location"]
    assert list(camera.rotation_euler) == plan["key_poses"][-1]["rotation_euler"]
    curves = camera.animation_data.action.fcurves
    assert len(curves) == 6
    assert {(curve.data_path, curve.array_index) for curve in curves} == {
        (path, index) for path in ("location", "rotation_euler") for index in range(3)
    }
    for curve in curves:
        assert len(curve.keyframe_points) == 3
        assert [p.co[0] for p in curve.keyframe_points] == [10, 30, 50]
        assert all(p.interpolation == "LINEAR" for p in curve.keyframe_points)
    if mode == "DOLLY_IN":
        assert plan["key_poses"][0]["distance"] > plan["key_poses"][-1]["distance"]
    if mode == "DOLLY_OUT":
        assert plan["key_poses"][0]["distance"] < plan["key_poses"][-1]["distance"]


def test_m3_preview_wraps_yaw_without_full_spin():
    _, camera, subject, inspector, registry = setup()
    plan = preview(
        registry,
        args(
            inspector,
            camera,
            subject,
            start_azimuth=89,
            end_azimuth=110,
            start_elevation=5,
            end_elevation=10,
        ),
    )
    angles = [pose["rotation_euler"][2] for pose in plan["key_poses"]]
    assert max(abs(b - a) for a, b in zip(angles, angles[1:], strict=False)) < 0.6


def test_m3_dolly_preview_nonzero_distance_across_midpoint():
    _, camera, subject, inspector, registry = setup()
    params = args(
        inspector,
        camera,
        subject,
        mode="DOLLY_IN",
        end_azimuth=0,
        end_elevation=10,
        dolly_factor=1.5,
    )
    plan = preview(registry, params)
    distances = [p["distance"] for p in plan["key_poses"]]
    assert distances[0] > distances[1] > distances[2]
    assert isclose(distances[0] / distances[2], 1.5)


def test_m3_stale_scene_lens_revision_blocks_without_keys():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    camera.data.lens = 65
    denied = apply(registry, params, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None

    camera.data.lens = 50
    bpy.context.scene.render.resolution_x = 1280
    denied = apply(registry, params, plan)
    assert denied.error.code == ErrorCode.STALE_STATE


def test_m3_stale_subject_target_refuses_mutation():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    subject.location = [3, 2, 1]
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


@pytest.mark.parametrize(
    "blocker",
    [
        "foreign",
        "shared",
        "parent",
        "constraint",
        "read_only",
        "camera_data_animated",
        "shift",
        "clip",
        "wrong_mode",
    ],
)
def test_m3_safe_camera_guards_before_action_creation(blocker):
    bpy, camera, subject, inspector, registry = setup()
    if blocker == "foreign":
        camera.animation_data = NS(action=None, action_slot=None, drivers=[], nla_tracks=[])
    elif blocker == "shared":
        camera.data.users = 2
    elif blocker == "parent":
        camera.parent = subject
    elif blocker == "constraint":
        camera.constraints.append(NS(name="Constraint", type="TRACK_TO"))
    elif blocker == "read_only":
        camera.is_editable = False
    elif blocker == "camera_data_animated":
        camera.data.animation_data = NS(action=None, action_slot=None, drivers=[], nla_tracks=[])
    elif blocker == "shift":
        camera.data.shift_x = 0.05
    elif blocker == "clip":
        camera.data.clip_end = 3
    else:
        bpy.context.mode = "EDIT_MESH"
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    assert not plan["ready"]
    assert plan["blockers"]
    denied = apply(registry, params, plan)
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m3_occupied_action_never_overwritten():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    assert apply(registry, params, plan).status == Status.VERIFIED
    fresh_params = args(inspector, camera, subject)
    next_plan = preview(registry, fresh_params)
    assert "EXISTING_CAMERA_ACTION_CANNOT_BE_ADOPTED" in next_plan["blockers"]
    assert apply(registry, fresh_params, next_plan).error.code == ErrorCode.SAFETY_DENIED
    assert len(camera.animation_data.action.fcurves) == 6


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "TRACKING"),
        ("start_frame", 0),
        ("end_frame", 800),
        ("end_azimuth", 140),
        ("end_elevation", -75),
        ("dolly_factor", 1.5),
        ("make_active", "yes"),
    ],
)
def test_m3_rejects_invalid_or_unsafe_motion_payload(field, value):
    _, camera, subject, inspector, _ = setup()
    params = args(inspector, camera, subject)
    with pytest.raises(AgentError):
        CameraMotionPreview.parse(params | {field: value})


def test_m3_dolly_requires_static_angles_and_factor():
    _, camera, subject, inspector, _ = setup()
    params = args(
        inspector,
        camera,
        subject,
        mode="DOLLY_IN",
        dolly_factor=1.6,
        end_azimuth=0,
        end_elevation=10,
    )
    assert CameraMotionPreview.parse(params).mode == "DOLLY_IN"
    with pytest.raises(AgentError):
        CameraMotionPreview.parse(params | {"end_elevation": 20})
    with pytest.raises(AgentError):
        CameraMotionPreview.parse(params | {"dolly_factor": 1.0})


def test_m3_strict_apply_revision_contract():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    with pytest.raises(AgentError):
        CameraMotionApply.parse(params)
    with pytest.raises(AgentError):
        CameraMotionPreview.parse(params | {"python": "bpy.ops.wm.open_mainfile()"})
    plan = preview(registry, params)
    wrong = apply(registry, params | {"end_azimuth": 30}, plan)
    assert wrong.error.code == ErrorCode.STALE_STATE


def test_m3_failed_readback_removes_generated_action_and_recovers_pose():
    bpy, camera, subject, inspector, registry = setup()
    camera.location = [1.5, 2.5, 3.5]
    camera.rotation_euler = [0.1, 0.2, 0.3]
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def corrupt():
        calls["n"] += 1
        if calls["n"] == 1:
            camera.location = [999, 0, 0]

    bpy.context.view_layer.update = corrupt
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m3_keyframe_insert_interrupted_after_partial_creation_cleans_up():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    original_insert = camera.keyframe_insert
    calls = {"n": 0}

    def fail_third(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("Synthetic failure after two channels keyed")
        return original_insert(*args, **kwargs)

    camera.keyframe_insert = fail_third
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert result.data["outcome"] == "unknown"
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m3_unsupported_created_slotted_action_fails_closed_and_restores():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def inject_slot():
        calls["n"] += 1
        if calls["n"] == 1:
            camera.animation_data.action_slot = object()

    bpy.context.view_layer.update = inject_slot
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m3_factory_and_host_contracts_are_consistent():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS == 261
    names = {entry["name"] for entry in registry.catalog()}
    assert {"cinema.motion_preview", "cinema.motion_apply"} <= names
