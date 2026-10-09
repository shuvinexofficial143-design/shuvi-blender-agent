"""Level 11 M2: bounded, source-verified marker insertion and restore."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.tracking_markers import MarkerPlacementOperations, MarkerPreview


class Named(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Markers(list):
    def find_frame(self, frame, exact=True):
        assert exact
        return next((item for item in self if item.frame == frame), None)

    def insert_frame(self, frame, co=(0, 0)):
        if self.find_frame(frame):
            raise ValueError("Marker exists")
        marker = NS(frame=frame, co=list(co), mute=False, is_keyed=True)
        self.append(marker)
        self.sort(key=lambda item: item.frame)
        return marker

    def delete_frame(self, frame):
        existing = self.find_frame(frame)
        if existing is None:
            raise RuntimeError("Marker not found")
        self.remove(existing)


def setup(allow=True):
    bpy = fake_bpy()
    markers = Markers([NS(frame=1, co=[0.1, 0.2], mute=False, is_keyed=True)])
    track = NS(name="Corner", markers=markers, lock=False, has_bundle=False)
    tracked = NS(name="Camera", is_camera=True, tracks=Named([track]))
    clip = NS(
        name="Footage",
        library=None,
        is_editable=True,
        size=[1920, 1080],
        frame_duration=100,
        tracking=NS(objects=Named([tracked])),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(
        MarkerPlacementOperations(bpy).tools(),
        SafetyPolicy(allow_mutations=allow),
    )
    args = {
        "clip_name": "Footage",
        "tracking_object_name": "Camera",
        "track_name": "Corner",
        "markers": [
            {"frame": 5, "co": [0.25, 0.75]},
            {"frame": 15, "co": [0.4, 0.6]},
        ],
    }
    return bpy, clip, track, reg, args


def preview(reg, args):
    return reg.dispatch(Request("tracking.marker_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "tracking.marker_apply",
            args | {"expected_marker_revision": plan.data["marker_revision"]},
        )
    )


def restore(reg, token):
    return reg.dispatch(Request("tracking.marker_restore", {"expected_marker_token": token}))


def test_m2_real_marker_insert_and_one_use_owned_restore():
    _, _, track, reg, args = setup()
    before = [item.frame for item in track.markers]
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    out = apply(reg, args, plan)
    assert out.status == Status.VERIFIED, out.error
    assert out.data["markers_created"] == 2
    assert [m.frame for m in track.markers] == [1, 5, 15]
    assert list(track.markers.find_frame(5).co) == [0.25, 0.75]
    removed = restore(reg, out.data["marker_token"])
    assert removed.status == Status.VERIFIED, removed.error
    assert [m.frame for m in track.markers] == before
    assert restore(reg, out.data["marker_token"]).error.code == ErrorCode.STALE_STATE


def test_m2_reject_overwrite_of_existing_markers():
    _, _, track, reg, args = setup()
    args["markers"][0]["frame"] = 1
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert [m.frame for m in track.markers] == [1]


def test_m2_reject_stale_preview():
    _, _, track, reg, args = setup()
    plan = preview(reg, args)
    track.markers.insert_frame(25, co=(0.7, 0.3))
    out = apply(reg, args, plan)
    assert out.error.code == ErrorCode.STALE_STATE
    assert [m.frame for m in track.markers] == [1, 25]


def test_m2_rollback_after_second_insert_fails():
    _, _, track, reg, args = setup()
    plan = preview(reg, args)
    original = track.markers.insert_frame
    calls = {"n": 0}

    def failing_insert(frame, co=(0, 0)):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("Injected RNA failure")
        return original(frame, co=co)

    track.markers.insert_frame = failing_insert
    out = apply(reg, args, plan)
    assert out.error.code == ErrorCode.EXECUTION_ERROR
    assert [m.frame for m in track.markers] == [1]


def test_m2_external_marker_change_blocks_restore():
    _, _, track, reg, args = setup()
    out = apply(reg, args, preview(reg, args))
    assert out.status == Status.VERIFIED
    track.markers.find_frame(5).co = [0.9, 0.9]
    denied = restore(reg, out.data["marker_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert [m.frame for m in track.markers] == [1, 5, 15]


def test_m2_locked_tracking_track_denies_preflight():
    _, _, track, reg, args = setup()
    track.lock = True
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED


def test_m2_read_only_policy_and_host_registry():
    bpy, _, track, _, args = setup()
    names = {t["name"] for t in create_registry(bpy).catalog()}
    assert len(names) == 302
    assert {"tracking.marker_preview", "tracking.marker_apply", "tracking.marker_restore"} <= names
    locked = ToolRegistry(
        MarkerPlacementOperations(bpy).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert [m.frame for m in track.markers] == [1]


@pytest.mark.parametrize(
    "markers",
    [
        [],
        [{"frame": 2, "co": [0.5, 0.5]}],
        [{"frame": 2, "co": [-0.1, 0.5]}, {"frame": 3, "co": [0.5, 0.5]}],
        [{"frame": 4, "co": [0.5, 0.5]}, {"frame": 3, "co": [0.5, 0.5]}],
        [{"frame": 4, "co": [0.5, 0.5]}, {"frame": 4, "co": [0.5, 0.5]}],
    ],
)
def test_m2_invalid_marker_payload(markers):
    _, _, _, _, args = setup()
    with pytest.raises(AgentError):
        MarkerPreview.parse(args | {"markers": markers})


def test_m2_unsupported_arbitrary_code_denied():
    _, _, _, reg, args = setup()
    payload = args | {"exec": "bpy.ops.wm.open_mainfile()"}
    assert preview(reg, payload).error.code == ErrorCode.INVALID_REQUEST
