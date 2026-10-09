"""Level 8 M9: source-only scene marker camera cuts, ownership and rollback."""

from copy import copy

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_cuts import (
    CameraCutOperations,
    CutApply,
    CutPreview,
    CutRelease,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    a = FakeObject("WideShot", "CAMERA")
    b = FakeObject("CloseShot", "CAMERA")
    subject = FakeObject("BackgroundSubject", "MESH")
    bpy = fake_bpy([a, b, subject])
    a.data = bpy.data.cameras.new("WideCameraData")
    b.data = bpy.data.cameras.new("CloseCameraData")
    inspector = BpyInspector(bpy)
    ops = CameraCutOperations(ObjectOperations(inspector))
    reg = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, a, b, subject, inspector, ops, reg


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def params(inspector, a, b, **changes):
    payload = {
        "camera_a": target(inspector, a),
        "camera_b": target(inspector, b),
        "start_frame": 10,
        "cut_frame": 40,
        "end_frame": 80,
    }
    payload.update(changes)
    return payload


def preview(reg, payload):
    r = reg.dispatch(Request("cinema.cut_preview", payload))
    assert r.status == Status.SUCCEEDED, r.error
    return r.data


def apply(reg, payload, plan):
    return reg.dispatch(
        Request(
            "cinema.cut_apply",
            payload | {"expected_cut_revision": plan["cut_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("cinema.cut_release", {"expected_cut_token": token}))


def test_m9_preview_is_deterministic_and_read_only():
    bpy, a, b, _, inspector, _, reg = setup()
    scene = bpy.context.scene
    state = preview(reg, params(inspector, a, b))
    assert state == preview(reg, params(inspector, a, b))
    assert state["ready"] is True
    assert state["transition"] == "HARD_CAMERA_CUT"
    assert state["segments"] == [
        {"camera_id": inspector.identity(a), "start": 10, "end": 39},
        {"camera_id": inspector.identity(b), "start": 40, "end": 80},
    ]
    assert state["marker_names"] == ["Shuvi_M9_Shot_A", "Shuvi_M9_Shot_B"]
    assert len(state["cut_revision"]) == 64
    assert state["real_runtime_verified"] is False
    assert state["mutation_performed"] is False
    assert scene.timeline_markers == []
    assert scene.camera is None
    assert scene.frame_current == 1


def test_m9_apply_writes_two_real_camera_bound_timeline_markers():
    bpy, a, b, _, inspector, _, reg = setup()
    scene = bpy.context.scene
    before_a = inspector.snapshot(a)["revision"]
    before_b = inspector.snapshot(b)["revision"]
    scene.camera = b
    scene.frame_current = 20
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    result = apply(reg, payload, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert result.data["created_bound_markers"] == 2
    assert [m.frame for m in scene.timeline_markers] == [10, 40]
    assert [m.camera for m in scene.timeline_markers] == [a, b]
    assert [m.select for m in scene.timeline_markers] == [False, False]
    assert scene.camera is b
    assert scene.frame_current == 20
    assert inspector.snapshot(a)["revision"] == before_a
    assert inspector.snapshot(b)["revision"] == before_b
    assert a.animation_data is None and b.animation_data is None
    assert result.data["cut_token"]


def test_m9_preserves_unrelated_non_camera_markers():
    bpy, a, b, _, inspector, _, reg = setup()
    scene = bpy.context.scene
    m = scene.timeline_markers.new("MusicCue", frame=25)
    m.select = True
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    assert plan["ready"]
    saved = (m.name, m.frame, m.camera, m.select)
    result = apply(reg, payload, plan)
    assert result.status == Status.VERIFIED, result.error
    assert m in scene.timeline_markers
    assert (m.name, m.frame, m.camera, m.select) == saved
    released = release(reg, result.data["cut_token"])
    assert released.status == Status.VERIFIED, released.error
    assert scene.timeline_markers == [m]
    assert (m.name, m.frame, m.camera, m.select) == saved


def test_m9_existing_camera_cut_outside_sequence_is_not_edited():
    bpy, a, b, _, inspector, _, reg = setup()
    scene = bpy.context.scene
    marker = scene.timeline_markers.new("OldShot", frame=4)
    marker.camera = a
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    assert plan["ready"]
    result = apply(reg, payload, plan)
    assert result.status == Status.VERIFIED, result.error
    assert release(reg, result.data["cut_token"]).status == Status.VERIFIED
    assert scene.timeline_markers == [marker]
    assert marker.camera is a


def test_m9_release_removes_only_own_markers_and_keeps_scene_selection():
    bpy, a, b, _, inspector, _, reg = setup()
    scene = bpy.context.scene
    scene.camera = a
    payload = params(inspector, a, b)
    result = apply(reg, payload, preview(reg, payload))
    assert result.status == Status.VERIFIED
    scene.frame_current = 65
    released = release(reg, result.data["cut_token"])
    assert released.status == Status.VERIFIED, released.error
    assert released.verification["matched"] is True
    assert released.data["removed_own_markers"] == 2
    assert scene.timeline_markers == []
    assert scene.camera is a
    assert scene.frame_current == 65


@pytest.mark.parametrize(
    "existing_frame,bound",
    [(10, False), (40, False), (25, True), (80, True)],
)
def test_m9_blocks_overlapping_or_colliding_marker(existing_frame, bound):
    bpy, a, b, _, inspector, _, reg = setup()
    marker = bpy.context.scene.timeline_markers.new("Other", frame=existing_frame)
    if bound:
        marker.camera = a
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    assert not plan["ready"]
    result = apply(reg, payload, plan)
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert bpy.context.scene.timeline_markers == [marker]


def test_m9_reserved_name_anywhere_refuses_adoption():
    bpy, a, b, _, inspector, _, reg = setup()
    marker = bpy.context.scene.timeline_markers.new("Shuvi_M9_Shot_A", frame=100)
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    assert not plan["ready"]
    assert "RESERVED_CAMERA_MARKER_NAME_EXISTS" in plan["blockers"]
    assert apply(reg, payload, plan).error.code == ErrorCode.SAFETY_DENIED
    assert bpy.context.scene.timeline_markers == [marker]


def test_m9_frame_outside_scene_blocks_non_mutating_preview():
    bpy, a, b, _, inspector, _, reg = setup()
    bpy.context.scene.frame_start = 20
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    assert "INVALID_SCENE_SHOT_FRAMES" in plan["blockers"]
    assert apply(reg, payload, plan).error.code == ErrorCode.SAFETY_DENIED


def test_m9_stale_scene_marker_changes_deny_apply():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    bpy.context.scene.timeline_markers.new("LaterCue", frame=100)
    result = apply(reg, payload, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert len(bpy.context.scene.timeline_markers) == 1


def test_m9_stale_camera_revision_denies_apply():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    a.location = [5, 0, 0]
    result = apply(reg, payload, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert not bpy.context.scene.timeline_markers


def test_m9_changed_cut_frame_denies_apply_revision():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    result = apply(reg, payload | {"cut_frame": 50}, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert not bpy.context.scene.timeline_markers


@pytest.mark.parametrize(
    "bad",
    [
        {"start_frame": 0},
        {"start_frame": 39},
        {"cut_frame": 80},
        {"end_frame": 42},
        {"end_frame": 2000},
        {"cut_frame": 40.5},
        {"start_frame": True},
        {"end_frame": "100"},
    ],
)
def test_m9_cut_contract_strict_validation(bad):
    _, a, b, _, inspector, _, _ = setup()
    with pytest.raises(AgentError):
        CutPreview.parse(params(inspector, a, b, **bad))


def test_m9_requires_distinct_camera_objects():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, a)
    result = reg.dispatch(Request("cinema.cut_preview", payload))
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert not bpy.context.scene.timeline_markers


def test_m9_rejects_noncamera_object():
    bpy, a, b, subject, inspector, _, reg = setup()
    payload = params(inspector, a, subject)
    result = reg.dispatch(Request("cinema.cut_preview", payload))
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_m9_second_marker_creation_interrupt_rolls_back_first_marker():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    before = list(bpy.context.scene.timeline_markers)
    collection = bpy.context.scene.timeline_markers
    original_new = collection.new
    calls = {"count": 0}

    def break_second(name, frame):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("Simulated interrupted timeline marker creation")
        return original_new(name, frame=frame)

    collection.new = break_second
    result = apply(reg, payload, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert collection == before


def test_m9_corrupt_created_marker_readback_causes_complete_rollback():
    bpy, a, b, _, inspector, ops, reg = setup()
    payload = params(inspector, a, b)
    plan = preview(reg, payload)
    original_state = ops._state
    calls = {"n": 0}

    def forged_once(scene):
        state = original_state(scene)
        if len(scene.timeline_markers) == 2:
            calls["n"] += 1
            if calls["n"] == 1:
                state["markers"][0]["frame"] = 999
        return state

    ops._state = forged_once
    result = apply(reg, payload, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert bpy.context.scene.timeline_markers == []


def test_m9_release_refuses_modified_own_marker():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    result = apply(reg, payload, preview(reg, payload))
    marker = bpy.context.scene.timeline_markers[1]
    marker.frame = 60
    rejected = release(reg, result.data["cut_token"])
    assert rejected.status == Status.FAILED
    assert rejected.error.code == ErrorCode.SAFETY_DENIED
    assert len(bpy.context.scene.timeline_markers) == 2


def test_m9_release_does_not_adopt_value_equal_foreign_marker():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    result = apply(reg, payload, preview(reg, payload))
    markers = bpy.context.scene.timeline_markers
    foreign = copy(markers[0])
    assert foreign == markers[0] and foreign is not markers[0]
    markers[0] = foreign
    denied = release(reg, result.data["cut_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert markers[0] is foreign
    assert len(markers) == 2


def test_m9_release_refuses_new_foreign_marker():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    result = apply(reg, payload, preview(reg, payload))
    bpy.context.scene.timeline_markers.new("Foreign", frame=120)
    denied = release(reg, result.data["cut_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(bpy.context.scene.timeline_markers) == 3


def test_m9_release_second_remove_failure_restores_own_markers():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    applied = apply(reg, payload, preview(reg, payload))
    assert applied.status == Status.VERIFIED
    markers = bpy.context.scene.timeline_markers
    original_remove = markers.remove
    counter = {"n": 0}

    def fail_second(marker):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("Simulated second camera marker removal failure")
        return original_remove(marker)

    markers.remove = fail_second
    failed = release(reg, applied.data["cut_token"])
    assert failed.status == Status.FAILED
    assert failed.error.code == ErrorCode.EXECUTION_ERROR
    assert [(item.frame, item.camera) for item in markers] == [(10, a), (40, b)]
    assert release(reg, applied.data["cut_token"]).status == Status.VERIFIED


def test_m9_release_readback_failure_restores_own_markers():
    bpy, a, b, _, inspector, ops, reg = setup()
    payload = params(inspector, a, b)
    applied = apply(reg, payload, preview(reg, payload))
    original_state = ops._state
    calls = {"n": 0}

    def corrupt_final_once(scene):
        state = original_state(scene)
        if not scene.timeline_markers:
            calls["n"] += 1
            if calls["n"] == 1:
                state["markers"] = [{"injected": "bad"}]
        return state

    ops._state = corrupt_final_once
    failed = release(reg, applied.data["cut_token"])
    assert failed.status == Status.FAILED
    assert failed.error.code == ErrorCode.EXECUTION_ERROR
    assert [(item.frame, item.camera) for item in bpy.context.scene.timeline_markers] == [
        (10, a),
        (40, b),
    ]
    assert release(reg, applied.data["cut_token"]).status == Status.VERIFIED


def test_m9_release_wrong_token_and_replay_fail_closed():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    applied = apply(reg, payload, preview(reg, payload))
    assert release(reg, "a" * 64).error.code == ErrorCode.STALE_STATE
    assert release(reg, applied.data["cut_token"]).status == Status.VERIFIED
    assert release(reg, applied.data["cut_token"]).error.code == ErrorCode.STALE_STATE


def test_m9_release_other_session_cannot_adopt_saved_markers():
    bpy, a, b, _, inspector, _, reg = setup()
    payload = params(inspector, a, b)
    applied = apply(reg, payload, preview(reg, payload))
    new_session_ops = CameraCutOperations(ObjectOperations(BpyInspector(bpy)))
    foreign_reg = ToolRegistry(new_session_ops.tools(), SafetyPolicy(allow_mutations=True))
    assert release(foreign_reg, applied.data["cut_token"]).error.code == ErrorCode.STALE_STATE


def test_m9_host_payload_rejects_unexpected_fields_and_missing_token():
    _, a, b, _, inspector, _, _ = setup()
    payload = params(inspector, a, b)
    with pytest.raises(AgentError):
        CutApply.parse(payload)
    with pytest.raises(AgentError):
        CutPreview.parse(payload | {"operator": "exec"})
    with pytest.raises(AgentError):
        CutRelease.parse({"camera_a": payload["camera_a"]})
    with pytest.raises(AgentError):
        CutRelease.parse({"expected_cut_token": 12})


def test_m9_factory_and_host_allowlist_246_tools():
    reg = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(reg.catalog()) == MAX_REGISTERED_TOOLS == 253
    assert {"cinema.cut_preview", "cinema.cut_apply", "cinema.cut_release"} <= {
        x["name"] for x in reg.catalog()
    }
