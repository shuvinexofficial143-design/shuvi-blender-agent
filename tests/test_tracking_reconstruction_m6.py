"""Level11 M6: existing matchmove reconstruction read-only diagnostics."""

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


class Cameras(list):
    def find_frame(self, *, frame):
        return next((item for item in self if item.frame == frame), None)


def matrix(x=0.0):
    return [
        [1.0, 0.0, 0.0, x],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def setup(valid=True):
    bpy = fake_bpy()
    marks = Markers([NS(frame=1, co=[0.5, 0.4], is_keyed=True, mute=False)])
    track = NS(
        name="Window", markers=marks, lock=False, has_bundle=True,
        average_error=0.35, bundle=[0.0, 2.0, 1.0],
    )
    frames = Cameras([
        NS(frame=1, matrix=matrix(), average_error=0.4),
        NS(frame=5, matrix=matrix(1.0), average_error=0.5),
    ])
    reconstruction = NS(is_valid=valid, average_error=0.45, cameras=frames)
    tracked = NS(
        name="Camera", is_camera=True, tracks=Named([track]),
        reconstruction=reconstruction,
    )
    clip = NS(
        name="Clip", library=None, is_editable=True, size=[1920, 1080],
        frame_duration=80, tracking=NS(objects=Named([tracked]), reconstruction=reconstruction),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(MovieClipInspectionOperations(bpy).tools(), SafetyPolicy())
    request = {
        "clip_name": "Clip", "tracking_object_name": "Camera",
        "frames": [1, 5], "inspect_reconstruction": True,
    }
    return clip, tracked, frames, track, reg, request


def inspect(reg, request):
    return reg.dispatch(Request("tracking.clip_inspect", request))


def test_m6_valid_solved_camera_poses_and_3d_bundles():
    clip, _, frames, track, reg, request = setup()
    result = inspect(reg, request)
    assert result.status == Status.SUCCEEDED, result.error
    data = result.data["existing_reconstruction"]
    assert data["is_valid"] is True and data["available"] is True
    assert data["average_error"] == 0.45
    assert data["sampled_pose_coverage"] == 1
    assert data["heuristic_low_error"] is True
    assert [cam["frame"] for cam in data["sampled_cameras"]] == [1, 5]
    assert data["sampled_cameras"][1]["matrix"][0][3] == 1.0
    assert data["bundles"][0]["position"] == [0.0, 2.0, 1.0]
    assert data["bundles"][0]["average_error"] == 0.35
    assert len(frames) == 2 and track.bundle == [0.0, 2.0, 1.0]
    assert clip.tracking.reconstruction.is_valid is True
    assert result.data["matchmove_solved"] is False
    assert data["solve_executed"] is False


def test_m6_missing_sampled_solve_frame_is_not_interpolated():
    _, _, _, _, reg, request = setup()
    request["frames"] = [1, 3, 5]
    result = inspect(reg, request)
    data = result.data["existing_reconstruction"]
    assert data["missing_sample_frames"] == [3]
    assert data["sampled_pose_coverage"] == pytest.approx(2 / 3)
    assert data["heuristic_low_error"] is False


def test_m6_invalid_existing_solver_is_flagged_not_run():
    _, _, _, _, reg, request = setup(valid=False)
    data = inspect(reg, request).data["existing_reconstruction"]
    assert data["is_valid"] is False
    assert data["sampled_cameras"] == []
    assert data["missing_sample_frames"] == [1, 5]
    assert data["solve_executed"] is False


def test_m6_absent_solver_reported_without_crashing():
    _, tracked, _, _, reg, request = setup()
    tracked.reconstruction = None
    bpy_clip = reg._tools["tracking.clip_inspect"].execute.__self__.bpy.data.movieclips[0]
    bpy_clip.tracking.reconstruction = None
    data = inspect(reg, request).data["existing_reconstruction"]
    assert data["available"] is False
    assert data["is_valid"] is False


def test_m6_nonfinite_matrix_fails_closed():
    _, _, frames, _, reg, request = setup()
    frames[1].matrix[0][3] = float("nan")
    denied = inspect(reg, request)
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m6_nonfinite_camera_and_global_reprojection_error_denied():
    clip, _, frames, _, reg, request = setup()
    frames[0].average_error = float("nan")
    assert inspect(reg, request).error.code == ErrorCode.SAFETY_DENIED
    frames[0].average_error = 0.4
    clip.tracking.reconstruction.average_error = -1
    assert inspect(reg, request).error.code == ErrorCode.SAFETY_DENIED


def test_m6_invalid_reconstructed_track_bundle_denied():
    _, _, _, track, reg, request = setup()
    track.bundle[0] = float("inf")
    assert inspect(reg, request).error.code == ErrorCode.SAFETY_DENIED


def test_m6_oversized_camera_collection_denied():
    _, _, frames, _, reg, request = setup()
    frames.extend(NS(frame=i + 6, matrix=matrix(), average_error=0.2) for i in range(512))
    assert inspect(reg, request).error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize("invalid", [None, "true", 1, [], {}])
def test_m6_rejects_nonboolean_reconstruction_flag(invalid):
    _, _, _, _, _, request = setup()
    with pytest.raises(AgentError):
        ClipInspect.parse(request | {"inspect_reconstruction": invalid})


def test_m6_legacy_calls_do_not_read_or_expose_solve_matrices():
    _, _, _, _, reg, request = setup()
    request.pop("inspect_reconstruction")
    result = inspect(reg, request)
    assert result.status == Status.SUCCEEDED
    assert "existing_reconstruction" not in result.data


def test_m6_arbitrary_execution_field_denied():
    _, _, _, _, reg, request = setup()
    result = inspect(reg, request | {"execute": "bpy.ops.clip.solve_camera()"})
    assert result.error.code == ErrorCode.INVALID_REQUEST
