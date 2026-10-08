from types import SimpleNamespace as NS

from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_controls import AnimationControlOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.rigging import RiggingOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare


def setup(is_rig=False):
    obj = FakeObject("Rig" if is_rig else "Prop", "ARMATURE" if is_rig else "MESH")
    constraint = None
    if is_rig:
        bone_data = NS(
            name="Root",
            parent=None,
            head_local=[0, 0, 0],
            tail_local=[0, 0, 1],
            matrix_local=None,
            use_connect=False,
            use_deform=True,
            inherit_scale="FULL",
        )
        constraint = NS(
            name="Limit",
            type="LIMIT_ROTATION",
            influence=0.4,
            mute=False,
            path_from_id=lambda prop: 'pose.bones["Root"].constraints["Limit"].' + prop,
        )
        bone = NS(
            name="Root",
            rotation_mode="XYZ",
            location=[0.0, 0.0, 0.0],
            rotation_euler=[0.0, 0.0, 0.0],
            rotation_quaternion=[1.0, 0.0, 0.0, 0.0],
            scale=[1.0, 1.0, 1.0],
            constraints=[constraint],
        )
        obj.data = NS(name="RigData", users=0, library=None, bones=[bone_data])
        obj.pose = NS(bones=[bone])
    bpy = fake_bpy([obj])
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    animation = AnimationOperations(objects)
    rigging = RiggingOperations(objects)
    controls = AnimationControlOperations(animation, rigging)
    registry = ToolRegistry(
        [*animation.tools(), *controls.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return obj, constraint, inspector, registry


def target(inspector, obj):
    item = inspector.snapshot(obj)
    return {
        "object_id": item["object_id"],
        "expected_name": item["name"],
        "expected_revision": item["revision"],
    }


def inspect(registry, inspector, obj):
    obj_id = inspector.snapshot(obj)["object_id"]
    result = registry.dispatch(Request("animation.control_inspect", {"object_id": obj_id}))
    assert result.status == Status.SUCCEEDED
    return result.data


def payload(inspector, obj, before, frame=10, kind="VISIBILITY", **overrides):
    data = {
        "target": target(inspector, obj),
        "expected_animation_revision": before["animation_revision"],
        "frame": frame,
        "kind": kind,
        "interpolation": "CONSTANT",
    }
    if kind == "VISIBILITY":
        data.update({"hide_render": True, "hide_viewport": True})
    else:
        data.update(
            {
                "bone_name": "Root",
                "constraint_name": "Limit",
                "expected_rig_revision": before["rig_revision"],
                "influence": 0.8,
            }
        )
    data.update(overrides)
    return data


def insert(registry, inspector, obj, before, frame=10, kind="VISIBILITY", **overrides):
    return registry.dispatch(
        Request(
            "animation.control_keyframe_insert",
            payload(inspector, obj, before, frame, kind, **overrides),
        )
    )


def test_m7_inspect_empty_object_and_visibility_keyframe():
    obj, _, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert before["managed_control_ready"] is True
    assert before["action_name"] is None

    result = insert(registry, inspector, obj, before)
    assert result.status == Status.VERIFIED
    after = inspect(registry, inspector, obj)
    assert after["managed_control_action"] is True
    assert after["point_count"] == 2
    assert {channel["data_path"] for channel in after["channels"]} == {
        "hide_render",
        "hide_viewport",
    }
    assert after["animation_revision"] != before["animation_revision"]
    assert obj.hide_render is True and obj.hide_viewport is True


def test_m7_visibility_second_frame_retains_first_without_overwrite():
    obj, _, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert insert(registry, inspector, obj, before).status == Status.VERIFIED
    middle = inspect(registry, inspector, obj)
    second = insert(
        registry,
        inspector,
        obj,
        middle,
        frame=20,
        hide_render=False,
        hide_viewport=False,
        interpolation="LINEAR",
    )
    assert second.status == Status.VERIFIED
    after = inspect(registry, inspector, obj)
    assert after["point_count"] == 4
    assert {point["frame"] for channel in after["channels"] for point in channel["points"]} == {
        10.0,
        20.0,
    }


def test_m7_duplicate_visibility_frame_and_stale_revision_fail_closed():
    obj, _, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert insert(registry, inspector, obj, before).status == Status.VERIFIED
    fresh = inspect(registry, inspector, obj)
    duplicate = insert(registry, inspector, obj, fresh)
    assert duplicate.status == Status.FAILED
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET
    stale = insert(registry, inspector, obj, before, frame=30)
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE


def test_m7_rejects_foreign_action_and_no_unmanaged_channel_adoption():
    obj, _, inspector, registry = setup()
    obj.keyframe_insert("location", 5)
    before = inspect(registry, inspector, obj)
    assert "FOREIGN_CONTROL_ACTION" in before["control_blockers"]
    denied = insert(registry, inspector, obj, before)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m7_constraint_influence_inserts_exact_key_and_tracks_rig_revision():
    obj, constraint, inspector, registry = setup(is_rig=True)
    before = inspect(registry, inspector, obj)
    assert before["rig_revision"]
    result = insert(
        registry,
        inspector,
        obj,
        before,
        kind="POSE_CONSTRAINT_INFLUENCE",
        interpolation="LINEAR",
    )
    assert result.status == Status.VERIFIED
    after = inspect(registry, inspector, obj)
    assert after["point_count"] == 1
    assert after["managed_control_action"] is True
    assert constraint.influence == 0.8
    assert after["rig_revision"] != before["rig_revision"]
    assert after["animation_revision"] != before["animation_revision"]
    assert after["channels"][0]["data_path"] == (
        'pose.bones["Root"].constraints["Limit"].influence'
    )


def test_m7_constraint_rig_stale_state_rejects_before_mutation():
    obj, constraint, inspector, registry = setup(is_rig=True)
    before = inspect(registry, inspector, obj)
    constraint.influence = 0.6
    denied = insert(registry, inspector, obj, before, kind="POSE_CONSTRAINT_INFLUENCE")
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.STALE_STATE
    assert obj.animation_data is None


def test_m7_visibility_forced_verification_failure_restores_action(monkeypatch):
    obj, _, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_controls.compare", fail_once)
    result = insert(registry, inspector, obj, before)
    assert result.status == Status.FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    after = inspect(registry, inspector, obj)
    assert after["animation_revision"] == before["animation_revision"]
    assert obj.animation_data is None
    assert obj.hide_render is False
    assert obj.hide_viewport is False


def test_m7_constraint_verification_failure_restores_rig_and_action(monkeypatch):
    obj, constraint, inspector, registry = setup(is_rig=True)
    before = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_controls.compare", fail_once)
    result = insert(registry, inspector, obj, before, kind="POSE_CONSTRAINT_INFLUENCE")
    assert result.status == Status.FAILED
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, inspector, obj)
    assert restored["animation_revision"] == before["animation_revision"]
    assert restored["rig_revision"] == before["rig_revision"]
    assert obj.animation_data is None
    assert constraint.influence == 0.4


def test_m7_existing_action_rollback_keeps_previous_frames(monkeypatch):
    obj, _, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    assert insert(registry, inspector, obj, before).status == Status.VERIFIED
    middle = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_controls.compare", fail_once)
    result = insert(
        registry,
        inspector,
        obj,
        middle,
        frame=20,
        hide_render=False,
        hide_viewport=False,
    )
    assert result.status == Status.FAILED
    assert result.data["recovery_verified"] is True
    restored = inspect(registry, inspector, obj)
    assert restored["animation_revision"] == middle["animation_revision"]
    assert restored["point_count"] == 2
    assert obj.hide_render is True
    assert obj.hide_viewport is True


def test_m7_enforces_total_fcurve_capacity_before_visibility_mutation(monkeypatch):
    obj, _, inspector, registry = setup()
    before = inspect(registry, inspector, obj)
    monkeypatch.setattr("shuvi_blender_agent.animation_controls.MAX_ANIMATION_CURVES", 1)
    denied = insert(registry, inspector, obj, before)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert obj.animation_data is None
