"""M3: exact Blender marker samples with bounded, read-only motion metrics."""

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
        return next((m for m in self if m.frame == frame), None)


def setup(coords=None, muted=()):
    bpy = fake_bpy()
    if coords is None:
        coords = [[0.2, 0.3], [0.21, 0.3], [0.22, 0.3], [0.23, 0.3]]
    marks = Markers(
        [
            NS(frame=i + 1, co=list(co), mute=i + 1 in muted, is_keyed=True)
            for i, co in enumerate(coords)
        ]
    )
    track = NS(name="Window", lock=False, has_bundle=False, markers=marks)
    obj = NS(name="Camera", is_camera=True, tracks=Named([track]))
    clip = NS(
        name="Footage",
        library=None,
        is_editable=True,
        size=[1000, 1000],
        frame_duration=80,
        tracking=NS(objects=Named([obj])),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(MovieClipInspectionOperations(bpy).tools(), SafetyPolicy())
    args = {
        "clip_name": "Footage",
        "tracking_object_name": "Camera",
        "frames": [1, 2, 3, 4],
        "analyze_motion": True,
    }
    return track, reg, args


def quality(reg, args):
    result = reg.dispatch(Request("tracking.clip_inspect", args))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data["tracks"][0]["motion_quality"]


def test_m3_velocities_coverage_and_source_data_unchanged():
    track, reg, args = setup()
    before = [tuple(marker.co) for marker in track.markers]
    data = quality(reg, args)
    assert data["sample_count"] == 4
    assert data["coverage"] == 1.0
    assert data["missing_or_muted_frames"] == []
    assert data["mean_speed_px_per_frame"] == pytest.approx(10)
    assert data["max_speed_px_per_frame"] == pytest.approx(10)
    assert data["jump_count"] == 0
    assert data["heuristic_ready"] is True
    assert data["heuristic_only"] is True
    assert [tuple(marker.co) for marker in track.markers] == before


def test_m3_flags_discontinuous_track_not_camera_solve():
    _, reg, args = setup([[0.1, 0.1], [0.11, 0.1], [0.95, 0.9], [0.96, 0.9]])
    result = quality(reg, args)
    assert result["jump_count"] == 1
    assert result["heuristic_ready"] is False


def test_m3_muted_marker_reduces_coverage():
    _, reg, args = setup(muted=[2])
    result = quality(reg, args)
    assert result["coverage"] == 0.75
    assert result["missing_or_muted_frames"] == [2]
    assert result["sample_count"] == 3
    assert result["heuristic_ready"] is True


def test_m3_short_track_not_ready():
    _, reg, args = setup()
    args["frames"] = [1, 2]
    assert quality(reg, args)["heuristic_ready"] is False


def test_m3_optional_extension_preserves_legacy_inspection():
    _, reg, args = setup()
    args.pop("analyze_motion")
    result = reg.dispatch(Request("tracking.clip_inspect", args))
    assert result.status == Status.SUCCEEDED
    assert "motion_quality" not in result.data["tracks"][0]


@pytest.mark.parametrize("invalid", [1, None, "yes", [], {}])
def test_m3_invalid_analysis_flag_is_denied(invalid):
    _, _, args = setup()
    with pytest.raises(AgentError):
        ClipInspect.parse(args | {"analyze_motion": invalid})


def test_m3_nonfinite_marker_and_arbitrary_fields_denied():
    track, reg, args = setup()
    track.markers[0].co[0] = float("nan")
    result = reg.dispatch(Request("tracking.clip_inspect", args))
    assert result.error.code == ErrorCode.SAFETY_DENIED
    result = reg.dispatch(Request("tracking.clip_inspect", args | {"exec": "import os"}))
    assert result.error.code == ErrorCode.INVALID_REQUEST
