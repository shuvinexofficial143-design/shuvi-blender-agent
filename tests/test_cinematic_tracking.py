"""Level 8 M6: verified, owned TRACK_TO camera subject-follow source behavior."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_tracking import (
    CameraTrackingOperations,
    TrackingApply,
    TrackingPreview,
    TrackingRelease,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("FollowCam", "CAMERA")
    subject = FakeObject("MovingSubject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("FollowCameraData")
    camera.data.sensor_width = 36
    camera.data.sensor_fit = "HORIZONTAL"
    subject.location = [2, 1, 4]
    subject.dimensions = [2, 3, 4]
    inspector = BpyInspector(bpy)
    ops = CameraTrackingOperations(ObjectOperations(inspector))
    registry = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, camera, subject, inspector, ops, registry


def target(inspector, obj):
    state = inspector.snapshot(obj)
    return {
        "object_id": state["object_id"],
        "expected_name": state["name"],
        "expected_revision": state["revision"],
    }


def params(inspector, camera, subject, **changes):
    data = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "azimuth_degrees": 45,
        "elevation_degrees": 20,
        "margin": 1.3,
        "make_active": True,
    }
    data.update(changes)
    return data


def preview(registry, data):
    outcome = registry.dispatch(Request("cinema.track_preview", data))
    assert outcome.status == Status.SUCCEEDED, outcome.error
    return outcome.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request(
            "cinema.track_apply",
            data | {"expected_tracking_revision": plan["tracking_revision"]},
        )
    )


def release(registry, inspector, camera, token):
    return registry.dispatch(
        Request(
            "cinema.track_release",
            {"camera": target(inspector, camera), "expected_tracking_revision": token},
        )
    )


def test_m6_preview_reports_dynamic_orientation_tracking_without_mutation():
    bpy, camera, subject, inspector, _, registry = setup()
    before = inspector.snapshot(camera)
    data = params(inspector, camera, subject)
    first = preview(registry, data)
    assert first == preview(registry, data)
    assert first["ready"] is True
    assert first["blockers"] == []
    assert first["constraint_type"] == "TRACK_TO"
    assert first["track_axis"] == "TRACK_NEGATIVE_Z"
    assert first["up_axis"] == "UP_Y"
    assert first["follow_behavior"] == "EVALUATED_ORIENTATION_ONLY_CAMERA_POSITION_FIXED"
    assert first["target_id"] == inspector.identity(subject)
    assert first["mutation_performed"] is False
    assert first["evaluated_tracking_verified"] is False
    assert len(first["tracking_revision"]) == 64
    assert camera.constraints == []
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m6_apply_adds_real_constraint_and_moves_camera_to_safe_framing_pose():
    bpy, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    result = apply(registry, data, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert len(camera.constraints) == 1
    track = camera.constraints[0]
    assert track.target is subject
    assert track.type == "TRACK_TO"
    assert track.track_axis == "TRACK_NEGATIVE_Z"
    assert track.up_axis == "UP_Y"
    assert track.name == "Shuvi_M6_Subject_Track"
    assert track.influence == 1.0
    assert track.mute is False
    assert list(camera.location) == plan["camera_location"]
    assert list(camera.rotation_euler) == plan["camera_rotation_euler"]
    assert bpy.context.scene.camera is camera
    assert result.data["tracking_revision"]


def test_m6_animated_subject_supported_as_tracking_target_without_animation_edit():
    _, camera, subject, inspector, _, registry = setup()
    subject.animation_data = NS(action=None, action_slot=None, nla_tracks=[], drivers=[])
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    assert plan["subject_animation_present"] is True
    result = apply(registry, data, plan)
    assert result.status == Status.VERIFIED
    old_constraint = camera.constraints[0]
    subject.location = [12, -5, 6]
    # Target pointer persists; actual depsgraph evaluation belongs to runtime tests.
    assert old_constraint.target is subject
    assert len(camera.constraints) == 1
    assert subject.animation_data is not None


def test_m6_release_removes_only_own_constraint_and_preserves_camera_pose():
    bpy, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    created = apply(registry, data, plan)
    assert created.status == Status.VERIFIED
    initial_pose = list(camera.location), list(camera.rotation_euler)
    result = release(registry, inspector, camera, created.data["tracking_revision"])
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert camera.constraints == []
    assert (list(camera.location), list(camera.rotation_euler)) == initial_pose
    assert bpy.context.scene.camera is camera
    assert result.data["removed_own_constraint"] is True


def test_m6_release_allows_subject_movement_and_does_not_move_camera():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    result = apply(registry, data, preview(registry, data))
    subject.location = [15, 7, 9]
    assert release(registry, inspector, camera, result.data["tracking_revision"]).status == (
        Status.VERIFIED
    )
    assert subject.location == [15, 7, 9]


def test_m6_release_refuses_foreign_or_changed_tracking_constraint():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    result = apply(registry, data, preview(registry, data))
    camera.constraints[0].influence = 0.25
    denied = release(registry, inspector, camera, result.data["tracking_revision"])
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(camera.constraints) == 1


def test_m6_double_release_and_unknown_session_owner_fail_closed():
    _, camera, subject, inspector, ops, registry = setup()
    data = params(inspector, camera, subject)
    result = apply(registry, data, preview(registry, data))
    assert release(registry, inspector, camera, result.data["tracking_revision"]).status == (
        Status.VERIFIED
    )
    denied = release(registry, inspector, camera, result.data["tracking_revision"])
    assert denied.error.code == ErrorCode.STALE_STATE
    assert not ops._owned


@pytest.mark.parametrize(
    "blocker",
    [
        "parent",
        "constraint",
        "existing_animation",
        "shared",
        "linked",
        "locked",
        "sensor_fit",
        "lens_shift",
        "clip",
        "mode",
    ],
)
def test_m6_denies_unsafe_camera_before_creating_track(blocker):
    bpy, camera, subject, inspector, _, registry = setup()
    if blocker == "parent":
        camera.parent = subject
    elif blocker == "constraint":
        camera.constraints.append(
            NS(type="COPY_LOCATION", name="Other", target=subject, influence=1, mute=False)
        )
    elif blocker == "existing_animation":
        camera.animation_data = NS(action=None, action_slot=None, nla_tracks=[], drivers=[])
    elif blocker == "shared":
        camera.data.users = 2
    elif blocker == "linked":
        camera.library = "foreign"
    elif blocker == "locked":
        camera.lock_rotation = [True, False, False]
    elif blocker == "sensor_fit":
        camera.data.type = "ORTHO"
    elif blocker == "lens_shift":
        camera.data.shift_x = 0.2
    elif blocker == "clip":
        camera.data.clip_end = 3
    else:
        bpy.context.mode = "EDIT_MESH"
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    assert not plan["ready"]
    assert plan["blockers"]
    refused = apply(registry, data, plan)
    assert refused.error.code == ErrorCode.SAFETY_DENIED


def test_m6_subject_parent_chain_cycle_prevents_tracking():
    _, camera, subject, inspector, _, registry = setup()
    subject.parent = camera
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    assert "TARGET_CAMERA_PARENT_CYCLE" in plan["blockers"]
    assert apply(registry, data, plan).error.code == ErrorCode.SAFETY_DENIED


def test_m6_subject_constraint_dependency_prevents_tracking():
    _, camera, subject, inspector, _, registry = setup()
    subject.constraints.append(
        NS(name="FollowCam", type="COPY_LOCATION", target=camera, mute=False, influence=1.0)
    )
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    assert "TARGET_DEPENDS_ON_CAMERA_CONSTRAINT" in plan["blockers"]
    assert apply(registry, data, plan).error.code == ErrorCode.SAFETY_DENIED


def test_m6_stale_subject_and_camera_state_refused_before_mutation():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    subject.location = [5, 4, 3]
    assert apply(registry, data, plan).error.code == ErrorCode.STALE_STATE
    assert not camera.constraints


def test_m6_changed_plan_angles_refused_by_revision():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    changed = apply(registry, data | {"azimuth_degrees": 70}, plan)
    assert changed.error.code == ErrorCode.STALE_STATE
    assert not camera.constraints


def test_m6_old_revision_cannot_remove_tracking_after_new_camera_pose():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    result = apply(registry, data, preview(registry, data))
    camera.location = [100, 100, 100]
    denied = release(registry, inspector, camera, result.data["tracking_revision"])
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.STALE_STATE
    assert len(camera.constraints) == 1


def test_m6_mismatched_target_readback_recovers_original_camera():
    bpy, camera, subject, inspector, _, registry = setup()
    camera.location = [2.5, 4.5, 7.5]
    original = inspector.snapshot(camera)
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    count = {"n": 0}

    def corrupt_once():
        count["n"] += 1
        if count["n"] == 1:
            camera.constraints[0].track_axis = "TRACK_X"

    bpy.context.view_layer.update = corrupt_once
    result = apply(registry, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert camera.constraints == []
    assert inspector.snapshot(camera)["revision"] == original["revision"]


def test_m6_interrupted_constraint_write_rolls_back_original_pose():
    bpy, camera, subject, inspector, _, registry = setup()
    before = inspector.snapshot(camera)
    data = params(inspector, camera, subject)
    plan = preview(registry, data)
    calls = {"n": 0}

    def interrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Synthetic dependency graph failure")

    bpy.context.view_layer.update = interrupt_once
    result = apply(registry, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert camera.constraints == []


def test_m6_release_interruption_restores_owned_constraint_with_verified_revision():
    bpy, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    created = apply(registry, data, preview(registry, data))
    assert created.status == Status.VERIFIED
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def interrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Injected interruption after constraint removal")

    bpy.context.view_layer.update = interrupt_once
    recovered = release(registry, inspector, camera, created.data["tracking_revision"])
    assert recovered.status == Status.FAILED
    assert recovered.error.code == ErrorCode.EXECUTION_ERROR
    assert len(camera.constraints) == 1
    assert camera.constraints[0].target is subject
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    # The restored constraint remains session-owned and can be released safely.
    assert release(registry, inspector, camera, created.data["tracking_revision"]).status == (
        Status.VERIFIED
    )


def test_m6_release_corrupt_readback_recreates_same_managed_tracking():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    created = apply(registry, data, preview(registry, data))
    assert created.status == Status.VERIFIED
    original_snapshot = inspector.snapshot
    before = original_snapshot(camera)
    calls = {"n": 0}

    def altered_once(obj):
        state = original_snapshot(obj)
        if obj is camera and len(camera.constraints) == 0:
            calls["n"] += 1
            if calls["n"] == 1:
                state["constraint_count"] = 99
        return state

    inspector.snapshot = altered_once
    interrupted = release(registry, inspector, camera, created.data["tracking_revision"])
    assert interrupted.status == Status.FAILED
    assert interrupted.error.code == ErrorCode.EXECUTION_ERROR
    assert original_snapshot(camera)["revision"] == before["revision"]
    assert len(camera.constraints) == 1
    assert camera.constraints[0].target is subject
    inspector.snapshot = original_snapshot
    assert release(registry, inspector, camera, created.data["tracking_revision"]).status == (
        Status.VERIFIED
    )


def test_m6_release_wrong_token_refused_without_mutation():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    result = apply(registry, data, preview(registry, data))
    assert result.status == Status.VERIFIED
    refused = release(registry, inspector, camera, "0" * 64)
    assert refused.error.code == ErrorCode.STALE_STATE
    assert len(camera.constraints) == 1


def test_m6_track_apply_requires_exact_revision_and_approved_fields():
    _, camera, subject, inspector, _, registry = setup()
    data = params(inspector, camera, subject)
    with pytest.raises(AgentError):
        TrackingApply.parse(data)
    with pytest.raises(AgentError):
        TrackingPreview.parse(data | {"command": "import bpy"})
    with pytest.raises(AgentError):
        TrackingRelease.parse({"camera": target(inspector, camera)})
    with pytest.raises(AgentError):
        TrackingRelease.parse(
            {"camera": target(inspector, camera), "expected_tracking_revision": 5}
        )


def test_m6_factory_and_host_allowlist_register_three_tools():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS == 274
    assert {"cinema.track_preview", "cinema.track_apply", "cinema.track_release"} <= {
        tool["name"] for tool in registry.catalog()
    }
