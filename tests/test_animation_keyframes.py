from fake_bpy import fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_keyframes import AdvancedAnimationOperations
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
    registry = ToolRegistry(
        [*animation.tools(), *advanced.tools()],
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


def key_payload(inspector, obj, frame):
    return {
        "target": target(inspector, obj),
        "frame": frame,
        "interpolation": "LINEAR",
        "transform": {
            "location": [frame, 2, 3],
            "rotation_euler": [0, 0, 0],
            "scale": [1, 1, 1],
        },
    }


def insert_frame(registry, inspector, obj, frame):
    result = registry.dispatch(
        Request("animation.insert_keyframe", key_payload(inspector, obj, frame))
    )
    assert result.status == Status.VERIFIED


def inspect(registry, object_id):
    result = registry.dispatch(Request("animation.inspect", {"object_id": object_id}))
    assert result.status == Status.SUCCEEDED
    return result.data


def channel_point(state, data_path, index, frame):
    channel = next(
        item
        for item in state["channels"]
        if item["data_path"] == data_path and item["index"] == index
    )
    point = next(point for point in channel["points"] if point["frame"] == float(frame))
    return {
        "frame": point["frame"],
        "value": point["value"],
        "interpolation": point["interpolation"],
    }


def setup_two_frames():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    insert_frame(registry, inspector, obj, 10)
    insert_frame(registry, inspector, obj, 20)
    state = inspect(registry, inspector.snapshot(obj)["object_id"])
    return bpy, inspector, registry, obj, state


def test_m2_edit_one_managed_channel_with_fresh_animation_revision():
    _, inspector, registry, obj, before = setup_two_frames()
    result = registry.dispatch(
        Request(
            "animation.edit_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 10,
                "value": 42.0,
                "interpolation": "CONSTANT",
            },
        )
    )

    assert result.status == Status.VERIFIED
    after = inspect(registry, before["object_id"])
    point = channel_point(after, "location", 0, 10)
    assert point == {"frame": 10.0, "value": 42.0, "interpolation": "CONSTANT"}
    assert after["point_count"] == before["point_count"] == 18
    assert after["animation_revision"] != before["animation_revision"]


def test_m2_remove_exact_managed_transform_frame():
    _, inspector, registry, obj, before = setup_two_frames()
    result = registry.dispatch(
        Request(
            "animation.remove_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "frame": 10,
            },
        )
    )

    assert result.status == Status.VERIFIED
    after = inspect(registry, before["object_id"])
    assert after["point_count"] == 9
    assert after["unique_frames"] == [20.0]
    assert after["animation_revision"] != before["animation_revision"]


def test_m2_replace_exact_managed_transform_frame():
    _, inspector, registry, obj, before = setup_two_frames()
    transform = {
        "location": [7, 8, 9],
        "rotation_euler": [0.1, 0.2, 0.3],
        "scale": [2, 3, 4],
    }
    result = registry.dispatch(
        Request(
            "animation.replace_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "frame": 20,
                "transform": transform,
                "interpolation": "BEZIER",
            },
        )
    )

    assert result.status == Status.VERIFIED
    after = inspect(registry, before["object_id"])
    assert after["point_count"] == 18
    for data_path, values in transform.items():
        for index, value in enumerate(values):
            assert channel_point(after, data_path, index, 20) == {
                "frame": 20.0,
                "value": float(value),
                "interpolation": "BEZIER",
            }


def test_m2_stale_animation_revision_fails_closed_even_with_fresh_object_target():
    _, inspector, registry, obj, before = setup_two_frames()
    first = registry.dispatch(
        Request(
            "animation.edit_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 10,
                "value": 11.0,
                "interpolation": "LINEAR",
            },
        )
    )
    assert first.status == Status.VERIFIED

    stale = registry.dispatch(
        Request(
            "animation.remove_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "frame": 20,
            },
        )
    )
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE


def test_m2_rejects_missing_and_nonunique_channel_keys():
    _, inspector, registry, obj, before = setup_two_frames()
    missing = registry.dispatch(
        Request(
            "animation.edit_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 30,
                "value": 1.0,
                "interpolation": "LINEAR",
            },
        )
    )
    assert missing.error.code == ErrorCode.NOT_FOUND


def test_m2_verification_failure_rolls_back_and_recovers(monkeypatch):
    _, inspector, registry, obj, before = setup_two_frames()
    original = channel_point(before, "location", 0, 20)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_keyframes.compare", fail_once)
    result = registry.dispatch(
        Request(
            "animation.replace_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "frame": 20,
                "transform": {
                    "location": [99, 8, 9],
                    "rotation_euler": [0.1, 0.2, 0.3],
                    "scale": [2, 3, 4],
                },
                "interpolation": "CONSTANT",
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, before["object_id"])
    assert restored["animation_revision"] == before["animation_revision"]
    assert channel_point(restored, "location", 0, 20) == original
