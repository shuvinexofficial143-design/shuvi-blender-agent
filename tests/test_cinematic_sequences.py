"""M10 end-to-end source acceptance for atomic two-camera shot framing and hard cuts."""

from copy import copy

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_sequences import (
    CinematicSequenceOperations,
    SequenceApply,
    SequencePreview,
    SequenceRelease,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    a = FakeObject("SceneWideCam", "CAMERA")
    b = FakeObject("SceneCloseCam", "CAMERA")
    subject = FakeObject("MainCharacter", "MESH")
    bpy = fake_bpy([a, b, subject])
    a.data = bpy.data.cameras.new("WideLens")
    b.data = bpy.data.cameras.new("CloseLens")
    for cam in (a, b):
        cam.data.sensor_fit = "HORIZONTAL"
        cam.data.sensor_width = 36.0
    a.location = [5.0, 4.0, 3.0]
    b.location = [7.0, 8.0, 9.0]
    a.rotation_euler = [0.1, 0.2, 0.3]
    b.rotation_euler = [0.4, 0.1, 0.2]
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 3.0, 4.0]
    inspector = BpyInspector(bpy)
    operations = CinematicSequenceOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, a, b, subject, inspector, operations, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def args(inspector, a, b, subject, **updates):
    values = {
        "camera_a": target(inspector, a),
        "camera_b": target(inspector, b),
        "subject": target(inspector, subject),
        "azimuth_a": 35.0,
        "elevation_a": 20.0,
        "azimuth_b": -25.0,
        "elevation_b": 10.0,
        "margin": 1.2,
        "start_frame": 10,
        "cut_frame": 40,
        "end_frame": 80,
    }
    values.update(updates)
    return values


def preview(registry, params):
    result = registry.dispatch(Request("cinema.sequence_preview", params))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(registry, params, plan):
    return registry.dispatch(
        Request(
            "cinema.sequence_apply",
            params | {"expected_sequence_revision": plan["sequence_revision"]},
        )
    )


def release(registry, token):
    return registry.dispatch(Request("cinema.sequence_release", {"expected_sequence_token": token}))


def test_m10_preview_integrates_two_shots_and_hard_cut_without_changes():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    before_a = inspector.snapshot(a)
    before_b = inspector.snapshot(b)
    plan = preview(reg, params)
    assert plan == preview(reg, params)
    assert plan["ready"] is True, plan["blockers"]
    assert plan["transition"] == "TWO_FRAMED_CAMERAS_WITH_HARD_CUT"
    assert plan["marker_names"] == ["Shuvi_M10_Sequence_A", "Shuvi_M10_Sequence_B"]
    assert plan["segments"] == [
        {"camera_id": inspector.identity(a), "start": 10, "end": 39},
        {"camera_id": inspector.identity(b), "start": 40, "end": 80},
    ]
    assert plan["shot_a_location"] != plan["shot_b_location"]
    assert len(plan["sequence_revision"]) == 64
    assert plan["mutation_performed"] is False
    assert plan["real_runtime_verified"] is False
    assert inspector.snapshot(a)["revision"] == before_a["revision"]
    assert inspector.snapshot(b)["revision"] == before_b["revision"]
    assert bpy.context.scene.timeline_markers == []


def test_m10_apply_atomically_frames_two_cameras_and_binds_cut_markers():
    bpy, a, b, subject, inspector, _, reg = setup()
    bpy.context.scene.camera = b
    bpy.context.scene.frame_current = 25
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    subject_before = inspector.snapshot(subject)["revision"]
    result = apply(reg, params, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert result.data["framed_cameras"] == 2
    assert result.data["bound_cut_markers"] == 2
    assert list(a.location) == plan["shot_a_location"]
    assert list(a.rotation_euler) == plan["shot_a_rotation"]
    assert list(b.location) == plan["shot_b_location"]
    assert list(b.rotation_euler) == plan["shot_b_rotation"]
    assert len(bpy.context.scene.timeline_markers) == 2
    assert [m.frame for m in bpy.context.scene.timeline_markers] == [10, 40]
    assert [m.camera for m in bpy.context.scene.timeline_markers] == [a, b]
    assert bpy.context.scene.camera is b
    assert bpy.context.scene.frame_current == 25
    assert a.animation_data is None and b.animation_data is None
    assert inspector.snapshot(subject)["revision"] == subject_before


def test_m10_release_restores_both_original_camera_poses_and_foreign_marker():
    bpy, a, b, subject, inspector, _, reg = setup()
    original_a = inspector.snapshot(a)
    original_b = inspector.snapshot(b)
    foreign = bpy.context.scene.timeline_markers.new("MusicCue", frame=90)
    foreign.select = True
    params = args(inspector, a, b, subject)
    result = apply(reg, params, preview(reg, params))
    assert result.status == Status.VERIFIED, result.error
    scene = bpy.context.scene
    scene.frame_current = 60
    released = release(reg, result.data["sequence_token"])
    assert released.status == Status.VERIFIED, released.error
    assert released.verification["matched"] is True
    assert released.data["restored_camera_poses"] == 2
    assert released.data["removed_owned_markers"] == 2
    assert scene.timeline_markers == [foreign]
    assert foreign.select is True and foreign.frame == 90
    assert inspector.snapshot(a)["revision"] == original_a["revision"]
    assert inspector.snapshot(b)["revision"] == original_b["revision"]
    assert scene.frame_current == 60


def test_m10_existing_offscreen_camera_marker_is_preserved():
    bpy, a, b, subject, inspector, _, reg = setup()
    marker = bpy.context.scene.timeline_markers.new("OlderCut", frame=5)
    marker.camera = b
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    assert plan["ready"]
    result = apply(reg, params, plan)
    assert result.status == Status.VERIFIED
    assert release(reg, result.data["sequence_token"]).status == Status.VERIFIED
    assert bpy.context.scene.timeline_markers == [marker]
    assert marker.camera is b


def test_m10_host_factory_allows_full_preview_apply_release_pipeline():
    bpy, a, b, subject, inspector, _, _ = setup()
    full = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    names = {row["name"] for row in full.catalog()}
    assert {"cinema.sequence_preview", "cinema.sequence_apply", "cinema.sequence_release"} <= names
    assert len(names) == MAX_REGISTERED_TOOLS == 268
    adapter = full._tools["cinema.sequence_preview"].execute.__self__
    params = args(adapter.inspector, a, b, subject)
    plan = preview(full, params)
    outcome = apply(full, params, plan)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert release(full, outcome.data["sequence_token"]).status == Status.VERIFIED


@pytest.mark.parametrize(
    "problem",
    [
        "shared_camera",
        "parented_camera",
        "camera_animation",
        "camera_constraint",
        "camera_linked",
        "locked_rotation",
        "bad_clip",
        "wrong_mode",
        "shared_data",
        "wrong_lens_shift",
    ],
)
def test_m10_reuses_strict_M1_shot_safety(problem):
    bpy, a, b, subject, inspector, _, reg = setup()
    if problem == "shared_camera":
        a.data.users = 2
    elif problem == "parented_camera":
        b.parent = subject
    elif problem == "camera_animation":
        a.keyframe_insert(data_path="location", frame=1)
    elif problem == "camera_constraint":
        b.constraints.new(type="TRACK_TO")
    elif problem == "camera_linked":
        a.library = "foreign"
    elif problem == "locked_rotation":
        b.lock_rotation = [True, False, False]
    elif problem == "bad_clip":
        a.data.clip_end = 2
    elif problem == "wrong_mode":
        bpy.context.mode = "EDIT_MESH"
    elif problem == "shared_data":
        b.data.users = 2
    else:
        a.data.shift_x = 0.15
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    assert not plan["ready"], problem
    assert apply(reg, params, plan).error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize(
    "change",
    [
        {"azimuth_a": 50},
        {"azimuth_b": -10},
        {"elevation_b": 25},
        {"margin": 1.5},
        {"cut_frame": 50},
        {"end_frame": 95},
    ],
)
def test_m10_plan_parameters_are_revision_bound(change):
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    changed = apply(reg, params | change, plan)
    assert changed.error.code == ErrorCode.STALE_STATE
    assert not bpy.context.scene.timeline_markers


def test_m10_stale_subject_denies_both_cameras():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    original_a = list(a.location)
    original_b = list(b.location)
    subject.location = [5, 5, 5]
    result = apply(reg, params, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert list(a.location) == original_a
    assert list(b.location) == original_b


def test_m10_stale_foreign_marker_denies_apply():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    bpy.context.scene.timeline_markers.new("NewCue", frame=150)
    result = apply(reg, params, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert len(bpy.context.scene.timeline_markers) == 1


@pytest.mark.parametrize("cut_start,cut_frame", [(10, 10), (12, 15), (40, 41)])
def test_m10_invalid_cut_ranges_rejected(cut_start, cut_frame):
    _, a, b, subject, inspector, _, _ = setup()
    with pytest.raises(AgentError):
        SequencePreview.parse(
            args(inspector, a, b, subject, start_frame=cut_start, cut_frame=cut_frame)
        )


def test_m10_foreign_cut_overlap_and_reserved_sequence_name_rejected():
    bpy, a, b, subject, inspector, _, reg = setup()
    foreign = bpy.context.scene.timeline_markers.new("OtherCamCut", frame=55)
    foreign.camera = b
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    assert not plan["ready"]
    assert apply(reg, params, plan).error.code == ErrorCode.SAFETY_DENIED
    foreign.camera = None
    foreign.name = "Shuvi_M10_Sequence_A"
    plan2 = preview(reg, params)
    assert not plan2["ready"]


def test_m10_partial_marker_write_recovers_both_camera_poses():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    original_a, original_b = inspector.snapshot(a), inspector.snapshot(b)
    markers = bpy.context.scene.timeline_markers
    original_new = markers.new
    counter = {"n": 0}

    def fail_second(name, frame):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("Injected second marker creation failure")
        return original_new(name, frame=frame)

    markers.new = fail_second
    result = apply(reg, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert markers == []
    assert inspector.snapshot(a)["revision"] == original_a["revision"]
    assert inspector.snapshot(b)["revision"] == original_b["revision"]


def test_m10_corrupt_camera_readback_recovers_original_sequence_state():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    plan = preview(reg, params)
    original_a, original_b = inspector.snapshot(a), inspector.snapshot(b)
    orig_update = bpy.context.view_layer.update
    count = {"n": 0}

    def corrupt_camera_once():
        count["n"] += 1
        if count["n"] == 1:
            a.location = [999, 999, 999]
        return orig_update()

    bpy.context.view_layer.update = corrupt_camera_once
    result = apply(reg, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert inspector.snapshot(a)["revision"] == original_a["revision"]
    assert inspector.snapshot(b)["revision"] == original_b["revision"]
    assert bpy.context.scene.timeline_markers == []


def test_m10_release_interrupted_second_marker_recovers_both_cameras_and_cuts():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    result = apply(reg, params, preview(reg, params))
    assert result.status == Status.VERIFIED
    before_a, before_b = inspector.snapshot(a), inspector.snapshot(b)
    markers = bpy.context.scene.timeline_markers
    old_remove = markers.remove
    calls = {"n": 0}

    def fail_second(item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("Injected interruption during release")
        return old_remove(item)

    markers.remove = fail_second
    refused = release(reg, result.data["sequence_token"])
    assert refused.status == Status.FAILED
    assert refused.error.code == ErrorCode.EXECUTION_ERROR
    assert len(markers) == 2
    assert inspector.snapshot(a)["revision"] == before_a["revision"]
    assert inspector.snapshot(b)["revision"] == before_b["revision"]
    assert release(reg, result.data["sequence_token"]).status == Status.VERIFIED


def test_m10_release_refuses_foreign_replacement_marker():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    result = apply(reg, params, preview(reg, params))
    assert result.status == Status.VERIFIED
    markers = bpy.context.scene.timeline_markers
    foreign = copy(markers[0])
    markers[0] = foreign
    assert release(reg, result.data["sequence_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert markers[0] is foreign


def test_m10_release_refuses_later_camera_edits_and_foreign_marker_additions():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    result = apply(reg, params, preview(reg, params))
    assert result.status == Status.VERIFIED
    a.location = [444, 0, 0]
    denied = release(reg, result.data["sequence_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(bpy.context.scene.timeline_markers) == 2


def test_m10_release_token_replay_and_unknown_session_refused():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    result = apply(reg, params, preview(reg, params))
    assert release(reg, "a" * 64).error.code == ErrorCode.STALE_STATE
    outside = CameraSequenceIndependent(bpy)
    assert outside.unknown(result.data["sequence_token"]) == ErrorCode.STALE_STATE
    assert release(reg, result.data["sequence_token"]).status == Status.VERIFIED
    assert release(reg, result.data["sequence_token"]).error.code == ErrorCode.STALE_STATE


class CameraSequenceIndependent:
    def __init__(self, bpy):
        ops = CinematicSequenceOperations(ObjectOperations(BpyInspector(bpy)))
        self.reg = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))

    def unknown(self, token):
        return release(self.reg, token).error.code


def test_m10_strict_payload_and_permission_gates():
    bpy, a, b, subject, inspector, _, reg = setup()
    params = args(inspector, a, b, subject)
    with pytest.raises(AgentError):
        SequencePreview.parse(params | {"python": "import bpy"})
    with pytest.raises(AgentError):
        SequenceApply.parse(params)
    with pytest.raises(AgentError):
        SequenceRelease.parse({})
    with pytest.raises(AgentError):
        SequenceRelease.parse({"expected_sequence_token": 123})
    denied = ToolRegistry(
        CinematicSequenceOperations(ObjectOperations(BpyInspector(bpy))).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    outcome = denied.dispatch(
        Request("cinema.sequence_apply", params | {"expected_sequence_revision": "x" * 64})
    )
    assert outcome.status == Status.FAILED
