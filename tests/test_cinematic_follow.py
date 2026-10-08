"""Level 8 M7 source-only camera translation follow and owned recovery tests."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_follow import (
    CameraFollowOperations,
    FollowApply,
    FollowPreview,
    FollowRelease,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("FollowCamera", "CAMERA")
    subject = FakeObject("MobileSubject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("FollowLens")
    camera.data.sensor_width = 36.0
    camera.data.sensor_fit = "HORIZONTAL"
    camera.location = [6.0, 7.0, 8.0]
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 3.0, 4.0]
    inspector = BpyInspector(bpy)
    operations = CameraFollowOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, camera, subject, inspector, operations, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def payload(inspector, camera, subject, **changes):
    request = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "azimuth_degrees": 30,
        "elevation_degrees": 20,
        "margin": 1.25,
        "make_active": True,
    }
    request.update(changes)
    return request


def preview(registry, data):
    result = registry.dispatch(Request("cinema.follow_preview", data))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request("cinema.follow_apply", data | {"expected_follow_revision": plan["follow_revision"]})
    )


def release(registry, inspector, camera, token):
    return registry.dispatch(
        Request(
            "cinema.follow_release",
            {"camera": target(inspector, camera), "expected_follow_token": token},
        )
    )


def test_m7_preview_is_deterministic_and_nonmutating():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    before = inspector.snapshot(camera)
    plan = preview(registry, data)
    assert plan == preview(registry, data)
    assert plan["ready"] is True
    assert plan["constraint_order"] == [
        "Shuvi_M7_Position_Follow",
        "Shuvi_M7_Subject_Aim",
    ]
    assert plan["use_offset"] is True
    assert plan["owner_space"] == plan["target_space"] == "WORLD"
    assert len(plan["follow_revision"]) == 64
    assert plan["real_runtime_verified"] is False
    assert plan["mutation_performed"] is False
    assert camera.constraints == []
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m7_camera_initial_world_pose_is_target_plus_offset():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    outcome = apply(registry, data, plan)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert outcome.verification["matched"] is True
    assert len(camera.constraints) == 2
    assert camera.constraints[0].type == "COPY_LOCATION"
    assert camera.constraints[1].type == "TRACK_TO"
    assert camera.constraints[0].target is subject
    assert camera.constraints[1].target is subject
    assert camera.constraints[0].use_offset is True
    assert [subject.location[i] + camera.location[i] for i in range(3)] == (
        plan["predicted_initial_world_location"]
    )
    assert camera.constraints[0].target_space == "WORLD"
    assert camera.constraints[0].owner_space == "WORLD"
    assert camera.constraints[0].use_x is True
    assert camera.constraints[0].use_y is True
    assert camera.constraints[0].use_z is True
    assert all(
        not bool(getattr(camera.constraints[0], name))
        for name in ("invert_x", "invert_y", "invert_z")
    )
    assert camera.constraints[1].track_axis == "TRACK_NEGATIVE_Z"
    assert camera.constraints[1].up_axis == "UP_Y"
    assert bpy.context.scene.camera is camera
    assert outcome.data["follow_token"]


def test_m7_subject_translation_predicts_equal_camera_translation():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    assert apply(registry, data, plan).status == Status.VERIFIED
    camera_offset = list(camera.location)
    initial_world = [subject.location[i] + camera_offset[i] for i in range(3)]
    subject.location = [10, -4, 7]
    projected_world = [subject.location[i] + camera_offset[i] for i in range(3)]
    assert [projected_world[i] - initial_world[i] for i in range(3)] == [8, -7, 3]
    assert camera.constraints[0].target is subject
    assert camera.constraints[1].target is subject
    # Fake-bpy does not evaluate depsgraph: mathematical prediction only.


def test_m7_animated_subject_pointer_is_preserved():
    _, camera, subject, inspector, _, registry = setup()
    subject.animation_data = NS(action=None, action_slot=None, drivers=[], nla_tracks=[])
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    assert plan["subject_animation_present"] is True
    outcome = apply(registry, data, plan)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert camera.constraints[0].target is subject
    assert camera.constraints[1].target is subject
    assert subject.animation_data is not None


def test_m7_release_removes_both_owned_constraints_and_restores_original_pose():
    bpy, camera, subject, inspector, _, registry = setup()
    before = inspector.snapshot(camera)
    data = payload(inspector, camera, subject)
    outcome = apply(registry, data, preview(registry, data))
    assert outcome.status == Status.VERIFIED
    result = release(registry, inspector, camera, outcome.data["follow_token"])
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert camera.constraints == []
    assert inspector.snapshot(camera)["transform"]["location"] == before["transform"]["location"]
    assert (
        inspector.snapshot(camera)["transform"]["rotation_euler"]
        == (before["transform"]["rotation_euler"])
    )
    assert bpy.context.scene.camera is camera
    assert result.data["removed_own_constraints"] == 2


def test_m7_release_after_subject_moves_preserves_target_and_resets_saved_pose():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    outcome = apply(registry, data, preview(registry, data))
    subject.location = [10, 0, 6]
    release_result = release(registry, inspector, camera, outcome.data["follow_token"])
    assert release_result.status == Status.VERIFIED, release_result.error
    assert subject.location == [10, 0, 6]
    assert list(camera.location) == [6, 7, 8]


def test_m7_without_activation_keeps_prior_camera_selection():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject, make_active=False)
    outcome = apply(registry, data, preview(registry, data))
    assert outcome.status == Status.VERIFIED
    assert bpy.context.scene.camera is None


@pytest.mark.parametrize(
    "blocker",
    [
        "animated_camera",
        "parent",
        "existing_constraint",
        "shared_data",
        "linked",
        "lens_shift",
        "clip",
        "mode",
        "locked",
        "parented_subject",
        "target_cycle",
    ],
)
def test_m7_fails_closed_on_unsafe_camera_and_target(blocker):
    bpy, camera, subject, inspector, _, registry = setup()
    if blocker == "animated_camera":
        camera.animation_data = NS(action=None, action_slot=None, drivers=[], nla_tracks=[])
    elif blocker == "parent":
        camera.parent = subject
    elif blocker == "existing_constraint":
        camera.constraints.new(type="TRACK_TO")
    elif blocker == "shared_data":
        camera.data.users = 2
    elif blocker == "linked":
        camera.library = "external"
    elif blocker == "lens_shift":
        camera.data.shift_x = 0.2
    elif blocker == "clip":
        camera.data.clip_end = 2
    elif blocker == "mode":
        bpy.context.mode = "EDIT_MESH"
    elif blocker == "locked":
        camera.lock_location = [True, False, False]
    elif blocker == "parented_subject":
        subject.parent = FakeObject("Parent")
    else:
        subject.parent = camera
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    assert not plan["ready"]
    outcome = apply(registry, data, plan)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.SAFETY_DENIED


def test_m7_stale_render_or_subject_plan_denied_without_mutation():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    bpy.context.scene.render.resolution_x = 1440
    assert apply(registry, data, plan).error.code == ErrorCode.STALE_STATE
    bpy.context.scene.render.resolution_x = 1920
    subject.location = [1, 2, 3]
    assert apply(registry, data, plan).error.code == ErrorCode.STALE_STATE
    assert camera.constraints == []


def test_m7_changed_angles_rejected_by_exact_plan_revision():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    changed = apply(registry, data | {"azimuth_degrees": 25}, plan)
    assert changed.error.code == ErrorCode.STALE_STATE
    assert camera.constraints == []


def test_m7_foreign_constraint_cannot_be_removed():
    _, camera, subject, inspector, _, registry = setup()
    foreign = camera.constraints.new(type="TRACK_TO")
    attempt = release(registry, inspector, camera, "a" * 64)
    assert attempt.error.code == ErrorCode.STALE_STATE
    assert camera.constraints == [foreign]


@pytest.mark.parametrize(
    "field,value",
    [
        ("use_offset", False),
        ("use_x", False),
        ("invert_z", True),
        ("owner_space", "LOCAL"),
        ("target_space", "LOCAL"),
        ("influence", 0.25),
    ],
)
def test_m7_release_refuses_modified_translation_constraint(field, value):
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    applied = apply(registry, data, preview(registry, data))
    assert applied.status == Status.VERIFIED
    setattr(camera.constraints[0], field, value)
    denied = release(registry, inspector, camera, applied.data["follow_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(camera.constraints) == 2


def test_m7_stale_camera_pose_blocks_release_without_touching_constraint():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    applied = apply(registry, data, preview(registry, data))
    camera.location = [123, 34, 56]
    result = release(registry, inspector, camera, applied.data["follow_token"])
    assert result.error.code == ErrorCode.STALE_STATE
    assert len(camera.constraints) == 2


def test_m7_apply_second_constraint_insertion_failure_rolls_back():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    before = inspector.snapshot(camera)
    new = camera.constraints.new
    counter = {"n": 0}

    def fail_second(type):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("Injected second constraint creation error")
        return new(type=type)

    camera.constraints.new = fail_second
    result = apply(registry, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert camera.constraints == []
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m7_corrupted_copy_axis_readback_restores_pre_follow_state():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    plan = preview(registry, data)
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            camera.constraints[0].use_z = False

    bpy.context.view_layer.update = corrupt_once
    result = apply(registry, data, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert camera.constraints == []
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m7_release_mid_removal_interruption_restores_both_owned_constraints():
    bpy, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    applied = apply(registry, data, preview(registry, data))
    assert applied.status == Status.VERIFIED
    before = inspector.snapshot(camera)
    original_remove = camera.constraints.remove
    counter = {"n": 0}

    def fail_second(item):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("Injected second removal failure")
        return original_remove(item)

    camera.constraints.remove = fail_second
    failed = release(registry, inspector, camera, applied.data["follow_token"])
    assert failed.status == Status.FAILED
    assert failed.error.code == ErrorCode.EXECUTION_ERROR
    assert len(camera.constraints) == 2
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert release(registry, inspector, camera, applied.data["follow_token"]).status == (
        Status.VERIFIED
    )


def test_m7_release_corrupt_readback_rolls_back_to_tracking():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    applied = apply(registry, data, preview(registry, data))
    original = inspector.snapshot
    before = original(camera)
    counter = {"n": 0}

    def falsify_once(obj):
        state = original(obj)
        if obj is camera and len(camera.constraints) == 0:
            counter["n"] += 1
            if counter["n"] == 1:
                state["constraint_count"] = 99
        return state

    inspector.snapshot = falsify_once
    failed = release(registry, inspector, camera, applied.data["follow_token"])
    assert failed.status == Status.FAILED
    assert len(camera.constraints) == 2
    assert original(camera)["revision"] == before["revision"]
    inspector.snapshot = original


def test_m7_release_requires_exact_token_and_replay_is_stale():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    applied = apply(registry, data, preview(registry, data))
    assert release(registry, inspector, camera, "z" * 64).error.code == ErrorCode.STALE_STATE
    assert release(registry, inspector, camera, applied.data["follow_token"]).status == (
        Status.VERIFIED
    )
    assert release(registry, inspector, camera, applied.data["follow_token"]).error.code == (
        ErrorCode.STALE_STATE
    )


def test_m7_strict_contract_fields_reject_arbitrary_commands():
    _, camera, subject, inspector, _, registry = setup()
    data = payload(inspector, camera, subject)
    with pytest.raises(AgentError):
        FollowPreview.parse(data | {"python": "import bpy"})
    with pytest.raises(AgentError):
        FollowApply.parse(data)
    with pytest.raises(AgentError):
        FollowRelease.parse({"camera": target(inspector, camera)})
    with pytest.raises(AgentError):
        FollowRelease.parse({"camera": target(inspector, camera), "expected_follow_token": 123})


def test_m7_factory_registers_three_host_tools():
    factory = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(factory.catalog()) == MAX_REGISTERED_TOOLS == 249
    assert {"cinema.follow_preview", "cinema.follow_apply", "cinema.follow_release"} <= {
        tool["name"] for tool in factory.catalog()
    }
