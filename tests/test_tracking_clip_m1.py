"""Level 11 M1: MovieClip tracking inspection from bounded Blender RNA."""

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
    marks = Markers(
        [
            NS(frame=1, co=[0.25, 0.75], mute=False, is_keyed=True),
            NS(frame=15, co=[0.4, 0.6], mute=False, is_keyed=False),
        ]
    )
    track = NS(name="Corner", markers=marks, lock=False, has_bundle=False)
    tracked = NS(name="Camera", is_camera=True, tracks=Named([track]))
    clip = NS(
        name="Footage",
        library=None,
        is_editable=True,
        size=[1920, 1080],
        frame_duration=120,
        filepath="//secret/footage.mp4",
        tracking=NS(objects=Named([tracked])),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(MovieClipInspectionOperations(bpy).tools(), SafetyPolicy())
    payload = {
        "clip_name": "Footage",
        "tracking_object_name": "Camera",
        "frames": [1, 2, 15],
    }
    return bpy, clip, track, reg, payload


def test_m1_reads_exact_marker_positions_and_hides_filepath():
    _, clip, track, reg, payload = setup()
    out = reg.dispatch(Request("tracking.clip_inspect", payload))
    assert out.status == Status.SUCCEEDED, out.error
    assert out.data["size"] == [1920, 1080]
    assert out.data["camera_tracking"] is True
    assert out.data["track_count"] == 1
    assert out.data["tracks"][0]["sampled_markers"] == [
        {"frame": 1, "co": [0.25, 0.75], "mute": False, "is_keyed": True},
        {"frame": 15, "co": [0.4, 0.6], "mute": False, "is_keyed": False},
    ]
    assert "filepath" not in out.data
    assert len(track.markers) == 2
    assert clip.filepath == "//secret/footage.mp4"


def test_m1_rejects_unloaded_clip_and_missing_tracking_object():
    _, _, _, reg, payload = setup()
    for key in ("clip_name", "tracking_object_name"):
        denied = reg.dispatch(Request("tracking.clip_inspect", payload | {key: "Missing"}))
        assert denied.error.code == ErrorCode.NOT_FOUND


def test_m1_rejects_linked_clip_and_too_many_tracks():
    _, clip, track, reg, payload = setup()
    clip.library = NS()
    denied = reg.dispatch(Request("tracking.clip_inspect", payload))
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    clip.library = None
    tracks = clip.tracking.objects[0].tracks
    tracks.extend(
        NS(name=f"T{i}", markers=Markers(), lock=False, has_bundle=False) for i in range(64)
    )
    denied = reg.dispatch(Request("tracking.clip_inspect", payload))
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert track.name == "Corner"


def test_m1_nonfinite_marker_fails_closed():
    _, _, track, reg, payload = setup()
    track.markers[0].co[0] = float("nan")
    denied = reg.dispatch(Request("tracking.clip_inspect", payload))
    assert denied.error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize("frames", [[], list(range(1, 18)), [2, 1], [1, 1], [0], [1048575]])
def test_m1_rejects_invalid_frame_lists(frames):
    _, _, _, _, payload = setup()
    with pytest.raises(AgentError):
        ClipInspect.parse(payload | {"frames": frames})


def test_m1_no_arbitrary_operations_or_fields():
    _, _, _, reg, payload = setup()
    wrong = reg.dispatch(Request("tracking.clip_inspect", payload | {"run_python": "import bpy"}))
    assert wrong.error.code == ErrorCode.INVALID_REQUEST
    wrong = reg.dispatch(Request("tracking.clip_delete", payload))
    assert wrong.error.code == ErrorCode.UNSUPPORTED_OPERATION
