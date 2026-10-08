from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.animation import (
    AnimationInspect,
    AnimationOperations,
    FrameRange,
    InsertKeyframe,
)
from shuvi_blender_agent.animation_state import action_curves
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(
        AnimationOperations(ObjectOperations(inspector)).tools(), SafetyPolicy(allow_mutations=True)
    )
    return bpy, inspector, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def key_payload(inspector, obj, frame):
    return {
        "target": target(inspector, obj),
        "frame": frame,
        "interpolation": "LINEAR",
        "transform": {"location": [frame, 2, 3], "rotation_euler": [0, 0, 0], "scale": [1, 1, 1]},
    }


def test_frame_range_and_frame_selection_verified():
    bpy, inspector, registry = setup()
    result = registry.dispatch(
        Request(
            "animation.set_range",
            {"start": 10, "end": 20, "expected_scene_revision": inspector.summary()["revision"]},
        )
    )
    assert result.status == Status.VERIFIED
    result = registry.dispatch(
        Request(
            "animation.set_frame",
            {"frame": 15, "expected_scene_revision": inspector.summary()["revision"]},
        )
    )
    assert result.status == Status.VERIFIED
    assert bpy.context.scene.frame_current == 15
    result = registry.dispatch(
        Request(
            "animation.set_frame",
            {"frame": 30, "expected_scene_revision": inspector.summary()["revision"]},
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_keys_created_and_repeated_frame_rejected():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    result = registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, 10))
    )
    assert result.status == Status.VERIFIED
    assert len(result.data["after"]["inserted_keys"]) == 9
    assert result.data["after"]["inserted_keys"]["location:0"]["value"] == 10
    second = registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, 20))
    )
    assert second.status == Status.VERIFIED
    repeat = registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, 20))
    )
    assert repeat.error.code == ErrorCode.AMBIGUOUS_TARGET


def test_existing_action_cannot_be_overwritten():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    obj.keyframe_insert("location", 1)
    result = registry.dispatch(Request("animation.insert_keyframe", key_payload(inspector, obj, 2)))
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_legacy_and_slotted_action_readback():
    bpy = fake_bpy()
    obj = bpy.context.scene.objects[0]
    obj.keyframe_insert("location", 10)
    legacy = action_curves(obj)
    slot = object()
    seen = []
    strip = NS(type="KEYFRAME", channelbag=lambda given: seen.append(given) or NS(fcurves=legacy))
    obj.animation_data.action = NS(name="Slotted", users=1, layers=[NS(strips=[strip])])
    obj.animation_data.action_slot = slot
    assert action_curves(obj) is legacy
    assert seen == [slot]
    assert BpyInspector(bpy).snapshot(obj)["animation"]["channels"][0]["points"][0]["co"] == [10, 0]


def test_keyframe_failure_never_reports_success():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    obj.keyframe_insert = lambda **kwargs: False
    result = registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, 10))
    )
    assert result.error.code == ErrorCode.EXECUTION_ERROR


def test_animation_bounds():
    with pytest.raises(AgentError):
        FrameRange.parse({"start": 20, "end": 10, "expected_scene_revision": "x"})
    bpy, inspector, _ = setup()
    payload = key_payload(inspector, bpy.context.scene.objects[0], 10)
    payload["interpolation"] = "eval"
    with pytest.raises(AgentError):
        InsertKeyframe.parse(payload)


def test_level7_m1_animation_inspect_reports_empty_exact_state():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    result = registry.dispatch(
        Request("animation.inspect", {"object_id": inspector.snapshot(obj)["object_id"]})
    )

    assert result.status == Status.SUCCEEDED
    assert result.data["action_name"] is None
    assert result.data["action_api"] == "NONE"
    assert result.data["curve_count"] == 0
    assert result.data["point_count"] == 0
    assert result.data["unique_frames"] == []
    assert result.data["frame_range"] is None
    assert result.data["blockers"] == []
    assert result.data["managed_mutation_ready"] is True
    assert result.data["source_only"] is True
    assert result.data["real_runtime_verified"] is False
    assert len(result.data["animation_revision"]) == 64


def test_level7_m1_animation_inspect_summarizes_owned_keyframes_deterministically():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    assert registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, 10))
    ).status == Status.VERIFIED
    assert registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, 20))
    ).status == Status.VERIFIED

    object_id = inspector.snapshot(obj)["object_id"]
    first = registry.dispatch(Request("animation.inspect", {"object_id": object_id}))
    second = registry.dispatch(Request("animation.inspect", {"object_id": object_id}))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["action_name"] == obj.name + "Action"
    assert first.data["action_api"] == "LEGACY"
    assert first.data["action_users"] == 1
    assert first.data["managed_session_action"] is True
    assert first.data["curve_count"] == 9
    assert first.data["point_count"] == 18
    assert first.data["unique_frame_count"] == 2
    assert first.data["unique_frames"] == [10.0, 20.0]
    assert first.data["frame_range"] == {"start": 10.0, "end": 20.0}
    assert first.data["interpolation_counts"] == {"LINEAR": 18}
    assert first.data["drivers_count"] == 0
    assert first.data["nla_track_count"] == 0
    assert first.data["blockers"] == []
    assert first.data["managed_mutation_ready"] is True


def test_level7_m1_animation_inspect_reports_foreign_driver_nla_and_shared_blockers():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    obj.keyframe_insert("location", 1)
    obj.animation_data.action.users = 2
    obj.animation_data.drivers.append(object())
    obj.animation_data.nla_tracks.append(object())

    result = registry.dispatch(
        Request("animation.inspect", {"object_id": inspector.snapshot(obj)["object_id"]})
    )

    assert result.status == Status.SUCCEEDED
    assert result.data["managed_session_action"] is False
    assert result.data["drivers_count"] == 1
    assert result.data["nla_track_count"] == 1
    assert result.data["blockers"] == [
        "DRIVERS_PRESENT",
        "NLA_TRACKS_PRESENT",
        "FOREIGN_ACTION",
        "SHARED_ACTION",
    ]
    assert result.data["managed_mutation_ready"] is False


def test_level7_m1_animation_inspect_fails_closed_when_detail_budget_is_truncated():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    curves = [
        NS(
            data_path="location",
            array_index=index,
            keyframe_points=[NS(co=[1.0, 0.0], interpolation="LINEAR")],
        )
        for index in range(65)
    ]
    obj.animation_data = NS(
        action=NS(name="TooManyCurves", users=1, fcurves=curves),
        action_slot=None,
        drivers=[],
        nla_tracks=[],
    )

    result = registry.dispatch(
        Request("animation.inspect", {"object_id": inspector.snapshot(obj)["object_id"]})
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_level7_m1_animation_inspect_contract_rejects_extra_fields():
    with pytest.raises(AgentError):
        AnimationInspect.parse({"object_id": "id", "extra": True})
