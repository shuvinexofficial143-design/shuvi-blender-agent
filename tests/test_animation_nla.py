from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_nla import ManagedNLAOperations, NLAStripCreate
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare


def setup(frames=(10, 20)):
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    animation = AnimationOperations(objects)
    nla = ManagedNLAOperations(animation)
    registry = ToolRegistry(
        [*animation.tools(), *nla.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    obj = bpy.context.scene.objects[0]
    for frame in frames:
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
    return bpy, inspector, registry, obj


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def inspect(registry, inspector, obj):
    snapshot = inspector.snapshot(obj)
    result = registry.dispatch(
        Request("animation.nla_inspect", {"object_id": snapshot["object_id"]})
    )
    assert result.status == Status.SUCCEEDED
    return result.data


def payload(inspector, obj, state, **kwargs):
    value = {
        "target": target(inspector, obj),
        "expected_nla_revision": state["nla_revision"],
        "track_name": "Shuvi_Clip",
        "strip_name": "Shot_A",
        "start_frame": 30,
    }
    value.update(kwargs)
    return value


def create(registry, inspector, obj, before, **kwargs):
    return registry.dispatch(
        Request("animation.nla_strip_create", payload(inspector, obj, before, **kwargs))
    )


def test_m8_inspection_previews_eligible_owned_action_without_mutation():
    _, inspector, registry, obj = setup()
    original = obj.animation_data.action
    before = inspect(registry, inspector, obj)
    assert before["active_action_owned"] is True
    assert before["managed_nla_ready"] is True
    assert before["track_count"] == 0
    assert before["source_frames"] == [10.0, 20.0]
    assert before["source_action_fingerprint"]
    assert obj.animation_data.action is original
    assert inspect(registry, inspector, obj)["nla_revision"] == before["nla_revision"]


def test_m8_creates_exact_nla_track_and_strip_without_changing_action_keys():
    _, inspector, registry, obj = setup()
    original = obj.animation_data.action
    before = inspect(registry, inspector, obj)
    result = create(registry, inspector, obj, before)
    assert result.status == Status.VERIFIED
    after = inspect(registry, inspector, obj)
    assert after["nla_revision"] != before["nla_revision"]
    assert after["track_count"] == 1
    assert after["strip_count"] == 1
    assert after["active_action"] is None
    strip = obj.animation_data.nla_tracks[0].strips[0]
    assert strip.action is original
    assert strip.frame_start == 30.0
    assert strip.frame_end == 40.0
    assert after["tracks"][0]["name"] == "Shuvi_Clip"
    assert after["tracks"][0]["strips"][0]["name"] == "Shot_A"
    assert after["tracks"][0]["strips"][0]["action_fingerprint"] == before[
        "source_action_fingerprint"
    ]
    assert after["managed_nla_ready"] is False
    assert after["real_runtime_verified"] is False


def test_m8_rejects_stale_nla_revision_even_with_fresh_target():
    _, inspector, registry, obj = setup()
    before = inspect(registry, inspector, obj)
    obj.keyframe_insert("location", 30)
    denied = create(registry, inspector, obj, before)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.STALE_STATE
    assert len(obj.animation_data.nla_tracks) == 0


def test_m8_rejects_foreign_action_and_preexisting_nla_tracks():
    _, inspector, registry, obj = setup()
    original = obj.animation_data.action
    obj.animation_data.action = NS(
        name="OtherAction", users=1, fcurves=list(original.fcurves)
    )
    before = inspect(registry, inspector, obj)
    assert "FOREIGN_ACTION" in before["blockers"]
    denied = create(registry, inspector, obj, before)
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.animation_data.nla_tracks) == 0

    obj.animation_data.action = original
    obj.animation_data.nla_tracks.new()
    state = inspect(registry, inspector, obj)
    assert "NLA_TRACKS_ALREADY_PRESENT" in state["blockers"]
    denied = create(registry, inspector, obj, state)
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert obj.animation_data.action is original


def test_m8_rejects_shared_action_and_slotted_action():
    _, inspector, registry, obj = setup()
    action = obj.animation_data.action
    action.users = 2
    state = inspect(registry, inspector, obj)
    assert "SHARED_ACTION" in state["blockers"]
    assert create(registry, inspector, obj, state).error.code == ErrorCode.SAFETY_DENIED
    action.users = 1
    obj.animation_data.action_slot = NS(identifier="slot")
    state = inspect(registry, inspector, obj)
    assert "SLOTTED_ACTION_UNVERIFIED" in state["blockers"]
    assert create(registry, inspector, obj, state).error.code == ErrorCode.SAFETY_DENIED


def test_m8_requires_two_complete_frame_keys_and_declines_partial_channels():
    _, inspector, registry, obj = setup(frames=(10,))
    state = inspect(registry, inspector, obj)
    assert "COMPLETE_INTEGER_FRAME_KEYS_REQUIRED" in state["blockers"]
    assert create(registry, inspector, obj, state).error.code == ErrorCode.SAFETY_DENIED

    _, inspector, registry, obj = setup()
    obj.animation_data.action.fcurves.pop()
    state = inspect(registry, inspector, obj)
    assert "COMPLETE_NINE_TRANSFORM_CHANNELS_REQUIRED" in state["blockers"]
    assert create(registry, inspector, obj, state).error.code == ErrorCode.SAFETY_DENIED


def test_m8_rejects_invalid_contract_and_out_of_bounds_strip_end():
    _, inspector, registry, obj = setup()
    before = inspect(registry, inspector, obj)
    with pytest.raises(AgentError):
        NLAStripCreate.parse(payload(inspector, obj, before, track_name=""))
    with pytest.raises(AgentError):
        NLAStripCreate.parse(payload(inspector, obj, before, start_frame=0))
    denied = create(registry, inspector, obj, before, start_frame=99_995)
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.animation_data.nla_tracks) == 0


def test_m8_forced_verification_mismatch_restores_original_action(monkeypatch):
    _, inspector, registry, obj = setup()
    original = obj.animation_data.action
    before = inspect(registry, inspector, obj)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_nla.compare", fail_once)
    result = create(registry, inspector, obj, before)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert obj.animation_data.action is original
    assert len(obj.animation_data.nla_tracks) == 0
    restored = inspect(registry, inspector, obj)
    assert restored["nla_revision"] == before["nla_revision"]
    assert restored["source_action_fingerprint"] == before["source_action_fingerprint"]


def test_m8_track_creation_failure_restores_action(monkeypatch):
    _, inspector, registry, obj = setup()
    before = inspect(registry, inspector, obj)
    original = obj.animation_data.action

    def fail_track():
        raise RuntimeError("injected NLA allocation failure")

    monkeypatch.setattr(obj.animation_data.nla_tracks, "new", fail_track, raising=False)
    result = create(registry, inspector, obj, before)
    assert result.status == Status.FAILED
    assert obj.animation_data.action is original
    assert inspect(registry, inspector, obj)["nla_revision"] == before["nla_revision"]
