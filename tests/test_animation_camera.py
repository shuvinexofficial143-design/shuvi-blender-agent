from types import SimpleNamespace as NS

from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.animation_camera import CameraAnimationOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare


def setup():
    obj = FakeObject("ShotCamera", "CAMERA")
    bpy = fake_bpy([obj])
    obj.data = bpy.data.cameras.new("ShotCameraData")
    obj.data.dof.use_dof = True
    inspector = BpyInspector(bpy)
    camera_animation = CameraAnimationOperations(ObjectOperations(inspector))
    registry = ToolRegistry(
        camera_animation.tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, obj, inspector, registry


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def inspect(registry, inspector, obj):
    obj_id = inspector.snapshot(obj)["object_id"]
    result = registry.dispatch(Request("camera.optics_animation_inspect", {"object_id": obj_id}))
    assert result.status == Status.SUCCEEDED
    return result.data


def payload(inspector, obj, before, frame=10, **overrides):
    data = {
        "target": target(inspector, obj),
        "expected_camera_animation_revision": before["camera_animation_revision"],
        "frame": frame,
        "lens": 85.0,
        "focus_distance": 12.5,
        "interpolation": "LINEAR",
    }
    data.update(overrides)
    return data


def insert(registry, inspector, obj, before, frame=10, **overrides):
    return registry.dispatch(
        Request(
            "camera.optics_keyframe_insert",
            payload(inspector, obj, before, frame, **overrides),
        )
    )


def test_m6_inspect_empty_camera_data_action_is_read_only():
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    again = inspect(registry, inspector, obj)
    assert before["camera_animation_revision"] == again["camera_animation_revision"]
    assert before["curve_count"] == 0
    assert before["point_count"] == 0
    assert before["lens"] == 50.0
    assert before["focus_distance"] == 10.0
    assert before["managed_mutation_ready"] is True
    assert before["real_runtime_verified"] is False


def test_m6_insert_lens_focus_pair_exact_readback_and_ownership():
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    result = insert(registry, inspector, obj, before)
    assert result.status == Status.VERIFIED
    after = inspect(registry, inspector, obj)
    assert after["curve_count"] == 2
    assert after["point_count"] == 2
    assert after["managed_session_action"] is True
    assert after["camera_animation_revision"] != before["camera_animation_revision"]
    by_path = {item["data_path"]: item for item in after["channels"]}
    assert by_path["lens"]["points"][0]["value"] == 85.0
    assert by_path["dof.focus_distance"]["points"][0]["value"] == 12.5
    assert all(
        point["interpolation"] == "LINEAR"
        for channel in after["channels"]
        for point in channel["points"]
    )


def test_m6_second_key_adds_without_replacing_first_key():
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert insert(registry, inspector, obj, before).status == Status.VERIFIED
    middle = inspect(registry, inspector, obj)
    result = insert(
        registry,
        inspector,
        obj,
        middle,
        frame=20,
        lens=105.0,
        focus_distance=25.0,
        interpolation="BEZIER",
    )
    assert result.status == Status.VERIFIED
    after = inspect(registry, inspector, obj)
    assert after["point_count"] == 4
    assert {point["frame"] for channel in after["channels"] for point in channel["points"]} == {
        10.0,
        20.0,
    }
    assert obj.data.lens == 105.0
    assert obj.data.dof.focus_distance == 25.0


def test_m6_duplicate_keyframe_fail_closed_without_data_mutation():
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert insert(registry, inspector, obj, before).status == Status.VERIFIED
    fresh = inspect(registry, inspector, obj)
    denied = insert(registry, inspector, obj, fresh)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.AMBIGUOUS_TARGET
    assert (
        inspect(registry, inspector, obj)["camera_animation_revision"]
        == fresh["camera_animation_revision"]
    )


def test_m6_foreign_camera_data_action_is_never_adopted():
    _, obj, inspector, registry = setup()
    obj.data.keyframe_insert(data_path="lens", frame=5)
    before = inspect(registry, inspector, obj)
    assert "FOREIGN_CAMERA_ACTION" in before["blockers"]
    denied = insert(registry, inspector, obj, before)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m6_disabled_dof_focus_object_and_shared_camera_data_are_denied():
    _, obj, inspector, registry = setup()
    obj.data.dof.use_dof = False
    before = inspect(registry, inspector, obj)
    assert "DEPTH_OF_FIELD_DISABLED" in before["blockers"]
    assert insert(registry, inspector, obj, before).error.code == ErrorCode.SAFETY_DENIED

    obj.data.dof.use_dof = True
    obj.data.dof.focus_object = NS(name="OtherFocus")
    before = inspect(registry, inspector, obj)
    assert "FOCUS_OBJECT_OVERRIDES_DISTANCE" in before["blockers"]
    assert insert(registry, inspector, obj, before).error.code == ErrorCode.SAFETY_DENIED

    obj.data.dof.focus_object = None
    obj.data.users = 2
    before = inspect(registry, inspector, obj)
    assert "SHARED_CAMERA_DATABLOCK" in before["blockers"]
    assert insert(registry, inspector, obj, before).error.code == ErrorCode.SAFETY_DENIED


def test_m6_stale_camera_revision_even_with_fresh_object_target():
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    obj.data.dof.focus_distance = 22.0
    denied = insert(registry, inspector, obj, before)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.STALE_STATE
    assert obj.data.animation_data is None


def test_m6_verification_failure_recovers_initial_action_and_camera_values(monkeypatch):
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_camera.compare", fail_once)
    result = insert(registry, inspector, obj, before)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, inspector, obj)
    assert restored["camera_animation_revision"] == before["camera_animation_revision"]
    assert obj.data.animation_data is None
    assert obj.data.lens == 50.0
    assert obj.data.dof.focus_distance == 10.0


def test_m6_existing_action_rollback_restores_original_frame_and_revision(monkeypatch):
    _, obj, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert insert(registry, inspector, obj, before).status == Status.VERIFIED
    middle = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_camera.compare", fail_once)
    result = insert(registry, inspector, obj, middle, frame=30, lens=110.0)
    assert result.status == Status.FAILED
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, inspector, obj)
    assert restored["camera_animation_revision"] == middle["camera_animation_revision"]
    assert restored["point_count"] == 2
    assert obj.data.lens == 85.0
