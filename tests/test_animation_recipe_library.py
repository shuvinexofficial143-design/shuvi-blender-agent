"""M9 source/fake-bpy coverage: versioned recipes reuse verified M4 retime."""

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_keyframes import AdvancedAnimationOperations
from shuvi_blender_agent.animation_recipe_library import (
    AnimationRecipeAction,
    AnimationRecipeLibraryOperations,
)
from shuvi_blender_agent.animation_timeline import AnimationTimelineOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    animation = AnimationOperations(objects)
    advanced = AdvancedAnimationOperations(animation)
    timeline = AnimationTimelineOperations(advanced)
    recipes = AnimationRecipeLibraryOperations(timeline)
    registry = ToolRegistry(
        [*animation.tools(), *advanced.tools(), *timeline.tools(), *recipes.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    obj = bpy.context.scene.objects[0]
    for frame in (10, 20, 30):
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
    return inspector, registry, obj, state(registry, inspector, obj)


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def state(registry, inspector, obj):
    object_id = inspector.snapshot(obj)["object_id"]
    result = registry.dispatch(Request("animation.inspect", {"object_id": object_id}))
    assert result.status == Status.SUCCEEDED
    return result.data


def payload(inspector, obj, before, recipe_id, parameters):
    return {
        "recipe_id": recipe_id,
        "recipe_version": 1,
        "target": target(inspector, obj),
        "expected_animation_revision": before["animation_revision"],
        "parameters": parameters,
    }


def value_at(state_data, frame):
    location = next(
        curve
        for curve in state_data["channels"]
        if curve["data_path"] == "location" and curve["index"] == 0
    )
    return next(point["value"] for point in location["points"] if point["frame"] == float(frame))


def test_m9_catalog_is_fixed_versioned_and_read_only():
    inspector, registry, obj, before = setup()
    catalog = registry.dispatch(Request("animation.recipe_catalog", {}))
    assert catalog.status == Status.SUCCEEDED
    assert catalog.data["library_version"] == 1
    assert catalog.data["recipe_count"] == 3
    assert [item["recipe_id"] for item in catalog.data["recipes"]] == [
        "timeline.reverse",
        "timeline.shift",
        "timeline.stretch",
    ]
    assert all(item["recipe_version"] == 1 for item in catalog.data["recipes"])
    assert len(catalog.data["catalog_revision"]) == 64
    assert state(registry, inspector, obj)["animation_revision"] == before["animation_revision"]


def test_m9_shift_preview_is_pure_and_reports_atomic_mapping():
    inspector, registry, obj, before = setup()
    recipe = payload(inspector, obj, before, "timeline.shift", {"frames": [20, 10], "offset": 5})
    result = registry.dispatch(Request("animation.recipe_preview", recipe))
    assert result.status == Status.SUCCEEDED
    assert result.data["preview"]["mappings"] == [
        {"source_frame": 10, "target_frame": 15},
        {"source_frame": 20, "target_frame": 25},
    ]
    assert result.data["preview"]["mutation_performed"] is False
    assert state(registry, inspector, obj)["animation_revision"] == before["animation_revision"]


def test_m9_shift_apply_moves_two_keys_and_preserves_values():
    inspector, registry, obj, before = setup()
    recipe = payload(inspector, obj, before, "timeline.shift", {"frames": [10, 20], "offset": 5})
    result = registry.dispatch(Request("animation.recipe_apply", recipe))
    assert result.status == Status.VERIFIED
    after = state(registry, inspector, obj)
    assert after["unique_frames"] == [15.0, 25.0, 30.0]
    assert value_at(after, 15) == 10.0
    assert value_at(after, 25) == 20.0
    assert after["point_count"] == before["point_count"]


def test_m9_reverse_applies_swaps_without_overwriting_middle_key():
    inspector, registry, obj, before = setup()
    recipe = payload(inspector, obj, before, "timeline.reverse", {"frames": [30, 10, 20]})
    result = registry.dispatch(Request("animation.recipe_apply", recipe))
    assert result.status == Status.VERIFIED
    after = state(registry, inspector, obj)
    assert after["unique_frames"] == [10.0, 20.0, 30.0]
    assert [value_at(after, frame) for frame in (10, 20, 30)] == [30.0, 20.0, 10.0]


def test_m9_stretch_uses_earliest_anchor_and_atomic_retime():
    inspector, registry, obj, before = setup()
    recipe = payload(
        inspector, obj, before, "timeline.stretch", {"frames": [30, 20, 10], "factor": 2}
    )
    result = registry.dispatch(Request("animation.recipe_apply", recipe))
    assert result.status == Status.VERIFIED
    after = state(registry, inspector, obj)
    assert after["unique_frames"] == [10.0, 30.0, 50.0]
    assert value_at(after, 30) == 20.0
    assert value_at(after, 50) == 30.0


@pytest.mark.parametrize(
    ("recipe_id", "params"),
    [
        ("timeline.shift", {"frames": [10], "offset": 0}),
        ("timeline.shift", {"frames": [10, 10], "offset": 3}),
        ("timeline.shift", {"frames": [10], "offset": 3, "unknown": 1}),
        ("timeline.reverse", {"frames": [10]}),
        ("timeline.stretch", {"frames": [10, 20], "factor": 5}),
        ("timeline.stretch", {"frames": [99990, 99999], "factor": 4}),
    ],
)
def test_m9_rejects_invalid_or_unbounded_recipe_arguments(recipe_id, params):
    inspector, _, obj, before = setup()
    with pytest.raises(AgentError):
        AnimationRecipeAction.parse(payload(inspector, obj, before, recipe_id, params))


def test_m9_rejects_unknown_recipe_or_version():
    inspector, _, obj, before = setup()
    unknown = payload(inspector, obj, before, "arbitrary.bpy", {"frames": [10], "offset": 5})
    with pytest.raises(AgentError):
        AnimationRecipeAction.parse(unknown)
    version = payload(inspector, obj, before, "timeline.shift", {"frames": [10], "offset": 5})
    version["recipe_version"] = 2
    with pytest.raises(AgentError):
        AnimationRecipeAction.parse(version)


def test_m9_refuses_collision_with_untouched_key():
    inspector, registry, obj, before = setup()
    recipe = payload(inspector, obj, before, "timeline.shift", {"frames": [10], "offset": 20})
    result = registry.dispatch(Request("animation.recipe_apply", recipe))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert state(registry, inspector, obj)["animation_revision"] == before["animation_revision"]


def test_m9_stale_revision_fails_closed():
    inspector, registry, obj, before = setup()
    recipe = payload(inspector, obj, before, "timeline.shift", {"frames": [10], "offset": 5})
    changed = registry.dispatch(
        Request(
            "animation.edit_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 10,
                "value": 999.0,
                "interpolation": "LINEAR",
            },
        )
    )
    assert changed.status == Status.VERIFIED
    result = registry.dispatch(Request("animation.recipe_apply", recipe))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE


def test_m9_verification_mismatch_restores_original_action(monkeypatch):
    inspector, registry, obj, before = setup()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_keyframes.compare", fail_once)
    recipe = payload(inspector, obj, before, "timeline.shift", {"frames": [10, 20], "offset": 5})
    result = registry.dispatch(Request("animation.recipe_apply", recipe))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["delegate_result"]["rolled_back"] is True
    assert result.data["delegate_result"]["recovery_verified"] is True
    after = state(registry, inspector, obj)
    assert after["animation_revision"] == before["animation_revision"]
    assert after["unique_frames"] == before["unique_frames"]


def test_m9_factory_registers_all_recipe_contracts_at_new_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 235
    assert MAX_REGISTERED_TOOLS == 235
    names = {item["name"] for item in registry.catalog()}
    assert {
        "animation.recipe_catalog",
        "animation.recipe_preview",
        "animation.recipe_apply",
    } <= names
    assert registry.catalog() == registry.catalog()
