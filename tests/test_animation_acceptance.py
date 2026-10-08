"""M10 source acceptance and managed Action recovery regression coverage."""

from fake_bpy import fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_acceptance import AnimationAcceptanceOperations
from shuvi_blender_agent.animation_keyframes import AdvancedAnimationOperations
from shuvi_blender_agent.animation_nla import ManagedNLAOperations
from shuvi_blender_agent.animation_recipe_library import AnimationRecipeLibraryOperations
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
    nla = ManagedNLAOperations(animation)
    recipes = AnimationRecipeLibraryOperations(timeline)
    acceptance = AnimationAcceptanceOperations(advanced, recipes, nla)
    registry = ToolRegistry(
        [
            *animation.tools(),
            *advanced.tools(),
            *timeline.tools(),
            *nla.tools(),
            *recipes.tools(),
            *acceptance.tools(),
        ],
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
                    "transform": {
                        "location": [frame, 2, 3],
                        "rotation_euler": [0, 0, 0],
                        "scale": [1, 1, 1],
                    },
                    "interpolation": "LINEAR",
                },
            )
        )
        assert result.status == Status.VERIFIED
    return inspector, registry, acceptance, obj


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def inspect(registry, inspector, obj):
    result = registry.dispatch(
        Request("animation.inspect", {"object_id": target(inspector, obj)["object_id"]})
    )
    assert result.status == Status.SUCCEEDED
    return result.data


def capture_payload(inspector, obj, before):
    return {
        "target": target(inspector, obj),
        "expected_animation_revision": before["animation_revision"],
    }


def capture(registry, inspector, obj):
    before = inspect(registry, inspector, obj)
    result = registry.dispatch(
        Request("animation.recovery_capture", capture_payload(inspector, obj, before))
    )
    assert result.status == Status.SUCCEEDED
    return before, result.data["recovery_revision"]


def edit(registry, inspector, obj, before, value=99.0):
    return registry.dispatch(
        Request(
            "animation.edit_keyframe",
            {
                "target": target(inspector, obj),
                "expected_animation_revision": before["animation_revision"],
                "data_path": "location",
                "array_index": 0,
                "frame": 10,
                "value": value,
                "interpolation": "LINEAR",
            },
        )
    )


def restore_payload(inspector, obj, before, recovery_revision):
    return {
        "target": target(inspector, obj),
        "expected_animation_revision": before["animation_revision"],
        "recovery_revision": recovery_revision,
    }


def location_value(state, frame):
    channel = next(
        curve
        for curve in state["channels"]
        if curve["data_path"] == "location" and curve["index"] == 0
    )
    return next(point["value"] for point in channel["points"] if point["frame"] == float(frame))


def recipe_payload(inspector, obj, before, offset=5):
    return {
        "recipe_id": "timeline.shift",
        "recipe_version": 1,
        "target": target(inspector, obj),
        "expected_animation_revision": before["animation_revision"],
        "parameters": {"frames": [10, 20], "offset": offset},
    }


def test_m10_qa_reports_integrity_with_deterministic_revision():
    inspector, registry, _, obj = setup()
    before = inspect(registry, inspector, obj)
    result = registry.dispatch(Request("animation.qa_inspect", {"object_id": before["object_id"]}))
    assert result.status == Status.SUCCEEDED
    qa = result.data
    assert qa["qa_status"] == "READY"
    assert qa["check_count"] == 6
    assert all(item["status"] == "PASS" for item in qa["checks"])
    assert len(qa["qa_revision"]) == 64
    assert (
        registry.dispatch(Request("animation.qa_inspect", {"object_id": before["object_id"]})).data[
            "qa_revision"
        ]
        == qa["qa_revision"]
    )
    assert inspect(registry, inspector, obj)["animation_revision"] == before["animation_revision"]


def test_m10_qa_detects_incomplete_channel_frames():
    inspector, registry, _, obj = setup()
    channel = next(
        curve
        for curve in obj.animation_data.action.fcurves
        if curve.data_path == "location" and curve.array_index == 0
    )
    point = next(point for point in channel.keyframe_points if point.co[0] == 20)
    channel.keyframe_points.remove(point)
    channel.update()
    result = registry.dispatch(
        Request("animation.qa_inspect", {"object_id": target(inspector, obj)["object_id"]})
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["qa_status"] == "BLOCKED"
    assert (
        next(
            check
            for check in result.data["checks"]
            if check["name"] == "COMPLETE_UNIQUE_FRAME_KEYS"
        )["status"]
        == "BLOCKED"
    )


def test_m10_capture_is_nonmutating_and_restore_actually_recovers_keys():
    inspector, registry, _, obj = setup()
    before, token = capture(registry, inspector, obj)
    assert len(token) == 64
    assert edit(registry, inspector, obj, before).status == Status.VERIFIED
    modified = inspect(registry, inspector, obj)
    assert location_value(modified, 10) == 99.0
    result = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, modified, token))
    )
    assert result.status == Status.VERIFIED
    assert result.data["capture_consumed"] is True
    after = inspect(registry, inspector, obj)
    assert after["animation_revision"] == before["animation_revision"]
    assert location_value(after, 10) == 10.0
    repeat = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, after, token))
    )
    assert repeat.status == Status.FAILED


def test_m10_restore_refuses_stale_and_wrong_capture_tokens():
    inspector, registry, _, obj = setup()
    before, token = capture(registry, inspector, obj)
    assert edit(registry, inspector, obj, before).status == Status.VERIFIED
    changed = inspect(registry, inspector, obj)
    wrong = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, changed, "0" * 64))
    )
    assert wrong.status == Status.FAILED
    assert wrong.error.code == ErrorCode.SAFETY_DENIED
    stale = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, before, token))
    )
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE
    assert location_value(inspect(registry, inspector, obj), 10) == 99.0


def test_m10_verification_failure_rolls_back_to_pre_restore_state(monkeypatch):
    inspector, registry, _, obj = setup()
    before, token = capture(registry, inspector, obj)
    assert edit(registry, inspector, obj, before).status == Status.VERIFIED
    modified = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_first(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_acceptance.compare", fail_first)
    result = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, modified, token))
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert result.data["capture_consumed"] is False
    after = inspect(registry, inspector, obj)
    assert after["animation_revision"] == modified["animation_revision"]
    assert location_value(after, 10) == 99.0


def test_m10_interrupted_restore_recovers_pre_restore_snapshot(monkeypatch):
    inspector, registry, acceptance, obj = setup()
    before, token = capture(registry, inspector, obj)
    assert edit(registry, inspector, obj, before).status == Status.VERIFIED
    modified = inspect(registry, inspector, obj)
    original = acceptance.advanced._restore
    calls = {"count": 0}

    def interrupted(obj_value, snapshot):
        calls["count"] += 1
        original(obj_value, snapshot)
        if calls["count"] == 1:
            raise RuntimeError("simulated post-mutation exception")

    monkeypatch.setattr(acceptance.advanced, "_restore", interrupted)
    result = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, modified, token))
    )
    assert result.status == Status.FAILED
    assert result.data["recovery_verified"] is True
    assert inspect(registry, inspector, obj)["animation_revision"] == modified["animation_revision"]


def test_m10_recovery_denies_foreign_action_after_capture():
    inspector, registry, acceptance, obj = setup()
    before, token = capture(registry, inspector, obj)
    assert edit(registry, inspector, obj, before).status == Status.VERIFIED
    changed = inspect(registry, inspector, obj)
    acceptance.animation._owned_actions.clear()
    result = registry.dispatch(
        Request("animation.recovery_restore", restore_payload(inspector, obj, changed, token))
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_m10_acceptance_previews_recipe_without_modification():
    inspector, registry, _, obj = setup()
    before = inspect(registry, inspector, obj)
    payload = recipe_payload(inspector, obj, before)
    result = registry.dispatch(Request("animation.level7_acceptance", payload))
    assert result.status == Status.SUCCEEDED
    assert result.data["source_acceptance_status"] == "READY"
    assert result.data["check_count"] == 5
    assert len(result.data["acceptance_revision"]) == 64
    assert result.data["recipe_preview_revision"]
    assert result.data["real_runtime_verified"] is False
    assert result.data["production_ready"] is False
    assert inspect(registry, inspector, obj)["animation_revision"] == before["animation_revision"]


def test_m10_acceptance_reports_recipe_collisions_as_blocked():
    inspector, registry, _, obj = setup()
    before = inspect(registry, inspector, obj)
    result = registry.dispatch(
        Request("animation.level7_acceptance", recipe_payload(inspector, obj, before, 20))
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["source_acceptance_status"] == "BLOCKED"
    assert result.data["recipe_preview_revision"] is None


def test_m10_acceptance_rejects_stale_revision():
    inspector, registry, _, obj = setup()
    before = inspect(registry, inspector, obj)
    payload = recipe_payload(inspector, obj, before)
    assert edit(registry, inspector, obj, before).status == Status.VERIFIED
    result = registry.dispatch(Request("animation.level7_acceptance", payload))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE


def test_m10_factory_registers_all_tools_with_host_contracts():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS == 229
    names = {item["name"] for item in registry.catalog()}
    assert {
        "animation.qa_inspect",
        "animation.recovery_capture",
        "animation.recovery_restore",
        "animation.level7_acceptance",
    } <= names
