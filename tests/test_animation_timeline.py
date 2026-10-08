import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_keyframes import AdvancedAnimationOperations
from shuvi_blender_agent.animation_style import AnimationStyleOperations
from shuvi_blender_agent.animation_timeline import AnimationTimelineOperations, TimelineRetime
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
    timeline = AnimationTimelineOperations(advanced)
    registry = ToolRegistry(
        [
            *animation.tools(),
            *advanced.tools(),
            *styles.tools(),
            *timeline.tools(),
        ],
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


def setup_three_frames():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    insert_frame(registry, inspector, obj, 10)
    insert_frame(registry, inspector, obj, 20)
    insert_frame(registry, inspector, obj, 30)
    state = inspect(registry, inspector.snapshot(obj)["object_id"])
    return inspector, registry, obj, state


def retime_payload(inspector, obj, state, mappings):
    return {
        "target": target(inspector, obj),
        "expected_animation_revision": state["animation_revision"],
        "mappings": mappings,
    }


def test_m4_preview_is_read_only_and_reports_resulting_timeline():
    inspector, registry, obj, before = setup_three_frames()
    payload = retime_payload(
        inspector,
        obj,
        before,
        [
            {"source_frame": 10, "target_frame": 15},
            {"source_frame": 20, "target_frame": 25},
        ],
    )
    result = registry.dispatch(Request("animation.retime_preview", payload))

    assert result.status == Status.SUCCEEDED
    assert result.data["mapping_count"] == 2
    assert result.data["moved_point_count"] == 18
    assert result.data["source_frames"] == [10, 20]
    assert result.data["target_frames"] == [15, 25]
    assert result.data["resulting_unique_frames"] == [15.0, 25.0, 30.0]
    assert result.data["mutation_performed"] is False
    assert len(result.data["workflow_revision"]) == 64
    after = inspect(registry, before["object_id"])
    assert after["animation_revision"] == before["animation_revision"]


def test_m4_apply_retimes_multiple_complete_keys_and_preserves_style():
    inspector, registry, obj, before = setup_three_frames()
    styled = registry.dispatch(
        Request(
            "animation.keyframe_style_set",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 10,
                "interpolation": "BEZIER",
                "easing": "AUTO",
                "handle_left_type": "FREE",
                "handle_right_type": "FREE",
                "handle_left": [9.0, 8.0],
                "handle_right": [11.0, 12.0],
            },
        )
    )
    assert styled.status == Status.VERIFIED
    fresh = inspect(registry, before["object_id"])

    result = registry.dispatch(
        Request(
            "animation.retime_apply",
            retime_payload(
                inspector,
                obj,
                fresh,
                [
                    {"source_frame": 10, "target_frame": 15},
                    {"source_frame": 20, "target_frame": 25},
                ],
            ),
        )
    )

    assert result.status == Status.VERIFIED
    after = inspect(registry, fresh["object_id"])
    assert after["unique_frames"] == [15.0, 25.0, 30.0]
    assert after["point_count"] == fresh["point_count"] == 27
    moved = point(after, "location", 0, 15)
    assert moved["value"] == 10.0
    assert moved["interpolation"] == "BEZIER"
    assert moved["easing"] == "AUTO"
    assert moved["handle_left_type"] == "FREE"
    assert moved["handle_right_type"] == "FREE"
    assert moved["handle_left"] == [14.0, 8.0]
    assert moved["handle_right"] == [16.0, 12.0]
    assert after["animation_revision"] != fresh["animation_revision"]


def test_m4_allows_simultaneous_swap_without_collision():
    inspector, registry, obj, before = setup_three_frames()
    result = registry.dispatch(
        Request(
            "animation.retime_apply",
            retime_payload(
                inspector,
                obj,
                before,
                [
                    {"source_frame": 10, "target_frame": 20},
                    {"source_frame": 20, "target_frame": 10},
                ],
            ),
        )
    )

    assert result.status == Status.VERIFIED
    after = inspect(registry, before["object_id"])
    assert after["unique_frames"] == [10.0, 20.0, 30.0]
    assert point(after, "location", 0, 10)["value"] == 20.0
    assert point(after, "location", 0, 20)["value"] == 10.0


def test_m4_rejects_target_occupied_by_nonmoving_key():
    inspector, registry, obj, before = setup_three_frames()
    result = registry.dispatch(
        Request(
            "animation.retime_apply",
            retime_payload(
                inspector,
                obj,
                before,
                [{"source_frame": 10, "target_frame": 30}],
            ),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED
    after = inspect(registry, before["object_id"])
    assert after["animation_revision"] == before["animation_revision"]


def test_m4_stale_revision_fails_closed():
    inspector, registry, obj, before = setup_three_frames()
    edited = registry.dispatch(
        Request(
            "animation.edit_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 10,
                "value": 99.0,
                "interpolation": "LINEAR",
            },
        )
    )
    assert edited.status == Status.VERIFIED

    stale = registry.dispatch(
        Request(
            "animation.retime_apply",
            retime_payload(
                inspector,
                obj,
                before,
                [{"source_frame": 20, "target_frame": 25}],
            ),
        )
    )
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE


def test_m4_verification_failure_rolls_back_all_moved_keys(monkeypatch):
    inspector, registry, obj, before = setup_three_frames()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_keyframes.compare", fail_once)
    result = registry.dispatch(
        Request(
            "animation.retime_apply",
            retime_payload(
                inspector,
                obj,
                before,
                [
                    {"source_frame": 10, "target_frame": 15},
                    {"source_frame": 20, "target_frame": 25},
                ],
            ),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, before["object_id"])
    assert restored["animation_revision"] == before["animation_revision"]
    assert restored["unique_frames"] == [10.0, 20.0, 30.0]


def test_m4_contract_rejects_duplicate_sources_and_targets():
    inspector, _, obj, state = setup_three_frames()
    with pytest.raises(AgentError):
        TimelineRetime.parse(
            retime_payload(
                inspector,
                obj,
                state,
                [
                    {"source_frame": 10, "target_frame": 15},
                    {"source_frame": 10, "target_frame": 25},
                ],
            )
        )
    with pytest.raises(AgentError):
        TimelineRetime.parse(
            retime_payload(
                inspector,
                obj,
                state,
                [
                    {"source_frame": 10, "target_frame": 15},
                    {"source_frame": 20, "target_frame": 15},
                ],
            )
        )
