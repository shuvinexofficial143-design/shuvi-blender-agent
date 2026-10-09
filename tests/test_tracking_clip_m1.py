        reg.dispatch(
            Request(
                "tracking.clip_inspect",
                payload
                | {
                    "run_python": "import bpy",
                },
            )
        ).error.code
        == ErrorCode.INVALID_REQUEST
    )
    assert ("""Level 11 M1: real MovieClip RNA inspection without mutation."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.tracking_clip import ClipInspect, MovieClipInspectionOperations


class Named(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Markers(list):
    def find_frame(self, frame, exact=True):
        assert exact
        return next((item for item in self if item.frame == frame), None)


def setup():
    bpy = fake_bpy()
    markers = Markers(
        [
            NS(frame=1, co=[0.25, 0.75], mute=False, is_keyed=True),
            NS(frame=15, co=[0.4, 0.6], mute=False, is_keyed=False),
        ]
    )
    track = NS(name="BuildingCorner", markers=markers, lock=False, has_bundle=False)
    tracking = NS(name="Camera", is_camera=True, tracks=Named([track]))
    clip = NS(
        name="Footage",
        library=None,
        is_editable=True,
        size=[1920, 1080],
        frame_duration=120,
        filepath="//private/footage.mp4",
        tracking=NS(objects=Named([tracking])),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(MovieClipInspectionOperations(bpy).tools(), SafetyPolicy())
    payload = {"clip_name": "Footage", "tracking_object_name": "Camera", "frames": [1, 2, 15]}
    return bpy, clip, track, reg, payload


def test_m1_reads_real_marker_co_without_mutating():
    _, clip, track, reg, payload = setup()
    result = reg.dispatch(Request("tracking.clip_inspect", payload))
    assert result.status == Status.SUCCEEDED, result.error
    assert result.data["size"] == [1920, 1080]
    assert result.data["camera_tracking"] is True
    assert result.data["track_count"] == 1
    assert result.data["tracks"][0]["sampled_markers"] == [
        {"frame": 1, "co": [0.25, 0.75], "mute": False, "is_keyed": True},
        {"frame": 15, "co": [0.4, 0.6], "mute": False, "is_keyed": False},
    ]
    assert "filepath" not in result.data
    assert [m.frame for m in track.markers] == [1, 15]
    assert clip.filepath == "//private/footage.mp4"


def test_m1_rejects_unknown_clip_or_tracking_object():
    _, _, _, reg, payload = setup()
    assert (
        reg.dispatch(
            Request(
                "tracking.clip_inspect",
                payload
                | {
                    "clip_name": "Missing",
                },
            )
        ).error.code
        == ErrorCode.NOT_FOUND
    )
    assert (
        reg.dispatch(
            Request(
                "tracking.clip_inspect",
                payload
                | {
                    "tracking_object_name": "Missing",
                },
            )
        ).error.code
        == ErrorCode.NOT_FOUND
    )


def test_m1_rejects_linked_clip_and_oversized_tracks():
    _, clip, track, reg, payload = setup()
    clip.library = NS()
    assert (
        reg.dispatch(Request("tracking.clip_inspect", payload)).error.code
        == ErrorCode.SAFETY_DENIED
    )
    clip.library = None
    clip.tracking.objects[0].tracks.extend(
        [NS(name=f"other{i}", markers=Markers(), lock=False, has_bundle=False) for i in range(64)]
    )
    assert (
        reg.dispatch(Request("tracking.clip_inspect", payload)).error.code
        == ErrorCode.SAFETY_DENIED
    )
    assert track.name == "BuildingCorner"


def test_m1_rejects_nonfinite_marker():
    _, _, track, reg, payload = setup()
    track.markers[0].co[0] = float("nan")
    assert (
        reg.dispatch(Request("tracking.clip_inspect", payload)).error.code
        == ErrorCode.SAFETY_DENIED
    )


@pytest.mark.parametrize("frames", [[], list(range(1, 18)), [2, 1], [1, 1], [0], [1048575]])
def test_m1_rejects_invalid_frame_requests(frames):
    _, _, _, _, payload = setup()
    payload["frames"] = frames
    with pytest.raises(AgentError):
        ClipInspect.parse(payload)


def test_m1_strict_host_allowlist():
    _, _, _, reg, payload = setup()

    assert (
        reg.dispatch(Request("tracking.clip_delete", payload)).error.code
        == ErrorCode.UNSUPPORTED_OPERATION
    )
