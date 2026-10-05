from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations, FrameRange, InsertKeyframe
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
