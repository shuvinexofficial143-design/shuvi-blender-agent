"""Level11 M5: native MovieTrackingTrack strategy edits, readback and recovery."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.tracking_configuration import (
    MovieTrackingTrackConfigOperations,
    TrackConfigurationPreview,
)


class Named(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Markers(list):
    def find_frame(self, frame, exact=True):
        return next((item for item in self if item.frame == frame), None)


class Track(NS):
    fail_once = False

    def __setattr__(self, key, value):
        if key == "weight" and getattr(self, "fail_once", False):
            self.fail_once = False
            raise RuntimeError("Injected Blender RNA write failure")
        super().__setattr__(key, value)


def setup(allow=True):
    bpy = fake_bpy()
    track = Track(
        name="Corner",
        lock=False,
        motion_model="Loc",
        pattern_match="KEYFRAME",
        correlation_min=0.65,
        frames_limit=0,
        margin=12,
        use_brute=False,
        use_normalization=False,
        weight=0.5,
        markers=Markers([NS(frame=1, co=[0.2, 0.4], mute=False, is_keyed=True)]),
    )
    obj = NS(name="Camera", is_camera=True, tracks=Named([track]))
    clip = NS(
        name="Clip",
        library=None,
        is_editable=True,
        size=[1920, 1080],
        frame_duration=150,
        tracking=NS(objects=Named([obj])),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(
        MovieTrackingTrackConfigOperations(bpy).tools(), SafetyPolicy(allow_mutations=allow)
    )
    payload = {
        "clip_name": "Clip",
        "tracking_object_name": "Camera",
        "track_name": "Corner",
        "settings": {
            "motion_model": "Affine",
            "pattern_match": "PREV_FRAME",
            "correlation_min": 0.8,
            "frames_limit": 24,
            "margin": 16,
            "use_brute": True,
            "use_normalization": True,
            "weight": 0.75,
        },
    }
    return bpy, clip, track, reg, payload


def preview(reg, payload):
    return reg.dispatch(Request("tracking.track_config_preview", payload))


def apply(reg, payload, plan):
    return reg.dispatch(
        Request(
            "tracking.track_config_apply",
            payload | {"expected_track_config_revision": plan.data["track_config_revision"]},
        )
    )


def restore(reg, token):
    return reg.dispatch(
        Request("tracking.track_config_restore", {"expected_track_config_token": token})
    )


def test_m5_native_track_settings_and_same_session_restore():
    _, _, track, reg, payload = setup()
    before = track.__dict__.copy()
    plan = preview(reg, payload)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    result = apply(reg, payload, plan)
    assert result.status == Status.VERIFIED, result.error
    assert track.motion_model == "Affine" and track.pattern_match == "PREV_FRAME"
    assert track.frames_limit == 24 and track.use_normalization is True
    assert track.weight == 0.75
    assert [m.frame for m in track.markers] == [1]
    undone = restore(reg, result.data["track_config_token"])
    assert undone.status == Status.VERIFIED, undone.error
    assert track.motion_model == before["motion_model"]
    assert track.correlation_min == before["correlation_min"]
    assert restore(reg, result.data["track_config_token"]).error.code == ErrorCode.STALE_STATE


def test_m5_stale_revision_blocks_mutation():
    _, _, track, reg, payload = setup()
    plan = preview(reg, payload)
    track.margin = 19
    denied = apply(reg, payload, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert track.motion_model == "Loc"


def test_m5_foreign_edits_block_release():
    _, _, track, reg, payload = setup()
    done = apply(reg, payload, preview(reg, payload))
    assert done.status == Status.VERIFIED
    track.frames_limit = 42
    result = restore(reg, done.data["track_config_token"])
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_m5_foreign_marker_changes_block_release():
    _, _, track, reg, payload = setup()
    done = apply(reg, payload, preview(reg, payload))
    assert done.status == Status.VERIFIED
    track.markers[0].co = [0.99, 0.99]
    result = restore(reg, done.data["track_config_token"])
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_m5_write_failure_restores_all_prior_fields():
    _, _, track, reg, payload = setup()
    plan = preview(reg, payload)
    before = track.__dict__.copy()
    track.fail_once = True
    failed = apply(reg, payload, plan)
    assert failed.error.code == ErrorCode.EXECUTION_ERROR
    assert track.motion_model == before["motion_model"]
    assert track.pattern_match == before["pattern_match"]
    assert track.weight == before["weight"]


def test_m5_refuses_locked_track_and_linked_clip():
    _, clip, track, reg, payload = setup()
    track.lock = True
    assert preview(reg, payload).error.code == ErrorCode.SAFETY_DENIED
    track.lock = False
    clip.library = NS()
    assert preview(reg, payload).error.code == ErrorCode.SAFETY_DENIED


def test_m5_rejects_duplicate_active_ownership():
    _, _, _, reg, payload = setup()
    done = apply(reg, payload, preview(reg, payload))
    assert done.status == Status.VERIFIED
    assert preview(reg, payload).error.code == ErrorCode.SAFETY_DENIED


def test_m5_registry_and_read_only_permissions():
    bpy, _, track, _, payload = setup()
    catalog = create_registry(bpy).catalog()
    names = {t["name"] for t in catalog}
    assert len(names) == 308
    assert {
        "tracking.track_config_preview",
        "tracking.track_config_apply",
        "tracking.track_config_restore",
    } <= names
    locked = ToolRegistry(
        MovieTrackingTrackConfigOperations(bpy).tools(), SafetyPolicy(allow_mutations=False)
    )
    plan = preview(locked, payload)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, payload, plan).status == Status.FAILED
    assert track.motion_model == "Loc"


@pytest.mark.parametrize(
    "key,value",
    [
        ("motion_model", "EVIL"),
        ("pattern_match", "ALL"),
        ("frames_limit", -1),
        ("margin", 100),
        ("weight", -0.1),
        ("use_brute", 1),
        ("use_normalization", "true"),
        ("correlation_min", float("nan")),
    ],
)
def test_m5_rejects_invalid_rna_settings(key, value):
    _, _, _, _, payload = setup()
    with pytest.raises(AgentError):
        TrackConfigurationPreview.parse(payload | {"settings": payload["settings"] | {key: value}})


def test_m5_no_arbitrary_python_fields():
    _, _, _, reg, payload = setup()
    denied = preview(reg, payload | {"exec": "import os"})
    assert denied.error.code == ErrorCode.INVALID_REQUEST
