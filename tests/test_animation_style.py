import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_keyframes import AdvancedAnimationOperations
from shuvi_blender_agent.animation_style import AnimationStyleOperations, KeyframeStyleSet
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    animation = AnimationOperations(objects)
    advanced = AdvancedAnimationOperations(animation)
    styles = AnimationStyleOperations(advanced)
    registry = ToolRegistry(
        [*animation.tools(), *advanced.tools(), *styles.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, registry


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def insert_frame(registry, inspector, obj, frame):
    result = registry.dispatch(
        Request(
            "animation.insert_keyframe",
            {
                "target": target(inspector, obj),
                "frame": frame,
                "interpolation": "LINEAR",
                "transform": {
                    "location": [frame, 2, 3],
                    "rotation_euler": [0, 0, 0],
                    "scale": [1, 1, 1],
                },
            },
        )
    )
    assert result.status == Status.VERIFIED


def inspect(registry, object_id):
    result = registry.dispatch(Request("animation.inspect", {"object_id": object_id}))
    assert result.status == Status.SUCCEEDED
    return result.data


def point(state, data_path, index, frame):
    channel = next(
        item
        for item in state["channels"]
        if item["data_path"] == data_path and item["index"] == index
    )
    return next(item for item in channel["points"] if item["frame"] == float(frame))


def setup_two_frames():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    insert_frame(registry, inspector, obj, 10)
    insert_frame(registry, inspector, obj, 20)
    state = inspect(registry, inspector.snapshot(obj)["object_id"])
    return bpy, inspector, registry, obj, state


def style_payload(inspector, obj, state, **overrides):
    payload = {
        "target": target(inspector, obj),
        "expected_animation_revision": state["animation_revision"],
        "data_path": "location",
        "array_index": 0,
        "frame": 10,
        "interpolation": "BEZIER",
        "easing": "AUTO",
        "handle_left_type": "FREE",
        "handle_right_type": "FREE",
        "handle_left": [9.0, 8.0],
        "handle_right": [11.0, 12.0],
    }
    payload.update(overrides)
    return payload


def test_m3_sets_free_bezier_handles_with_exact_readback():
    _, inspector, registry, obj, before = setup_two_frames()
    result = registry.dispatch(
        Request(
            "animation.keyframe_style_set",
            style_payload(inspector, obj, before),
        )
    )

    assert result.status == Status.VERIFIED
    after = inspect(registry, before["object_id"])
    styled = point(after, "location", 0, 10)
    assert styled["interpolation"] == "BEZIER"
    assert styled["easing"] == "AUTO"
    assert styled["handle_left_type"] == "FREE"
    assert styled["handle_right_type"] == "FREE"
    assert styled["handle_left"] == [9.0, 8.0]
    assert styled["handle_right"] == [11.0, 12.0]
    assert after["animation_revision"] != before["animation_revision"]


def test_m3_sets_eased_non_bezier_interpolation_without_manual_handles():
    _, inspector, registry, obj, before = setup_two_frames()
    result = registry.dispatch(
        Request(
            "animation.keyframe_style_set",
            style_payload(
                inspector,
                obj,
                before,
                interpolation="SINE",
                easing="EASE_IN_OUT",
                handle_left_type="AUTO",
                handle_right_type="AUTO",
                handle_left=None,
                handle_right=None,
            ),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.INVALID_REQUEST

    payload = style_payload(
        inspector,
        obj,
        before,
        interpolation="SINE",
        easing="EASE_IN_OUT",
        handle_left_type="AUTO",
        handle_right_type="AUTO",
    )
    payload.pop("handle_left")
    payload.pop("handle_right")
    result = registry.dispatch(Request("animation.keyframe_style_set", payload))

    assert result.status == Status.VERIFIED
    after = inspect(registry, before["object_id"])
    styled = point(after, "location", 0, 10)
    assert styled["interpolation"] == "SINE"
    assert styled["easing"] == "EASE_IN_OUT"
    assert styled["handle_left_type"] == "AUTO"
    assert styled["handle_right_type"] == "AUTO"
    assert after["easing_counts"]["EASE_IN_OUT"] == 1


def test_m3_contract_rejects_irrelevant_easing_and_missing_free_handle():
    _, inspector, _, obj, before = setup_two_frames()
    bad_easing = style_payload(
        inspector,
        obj,
        before,
        interpolation="LINEAR",
        easing="EASE_IN",
        handle_left_type="AUTO",
        handle_right_type="AUTO",
    )
    bad_easing.pop("handle_left")
    bad_easing.pop("handle_right")
    with pytest.raises(AgentError):
        KeyframeStyleSet.parse(bad_easing)

    missing = style_payload(inspector, obj, before)
    missing.pop("handle_left")
    with pytest.raises(AgentError):
        KeyframeStyleSet.parse(missing)


def test_m3_stale_animation_revision_fails_closed():
    _, inspector, registry, obj, before = setup_two_frames()
    first = registry.dispatch(
        Request(
            "animation.keyframe_style_set",
            style_payload(inspector, obj, before),
        )
    )
    assert first.status == Status.VERIFIED

    stale = registry.dispatch(
        Request(
            "animation.keyframe_style_set",
            style_payload(
                inspector,
                obj,
                before,
                frame=20,
                handle_left=[19.0, 18.0],
                handle_right=[21.0, 22.0],
            ),
        )
    )
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE


def test_m3_verification_failure_restores_style_and_revision(monkeypatch):
    _, inspector, registry, obj, before = setup_two_frames()
    original = dict(point(before, "location", 0, 10))
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_keyframes.compare", fail_once)
    result = registry.dispatch(
        Request(
            "animation.keyframe_style_set",
            style_payload(inspector, obj, before),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, before["object_id"])
    assert restored["animation_revision"] == before["animation_revision"]
    assert point(restored, "location", 0, 10) == original
