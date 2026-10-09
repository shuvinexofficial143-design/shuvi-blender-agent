"""Level 11 M6: inspect existing solve poses and 3D track bundles, never run a solve."""

from math import isfinite

from .errors import AgentError, ErrorCode
from .validation import string

MAX_RECONSTRUCTED_CAMERAS = 512


def reconstruction_quality(clip, obj, tracks, sample_frames):
    """Read existing Blender solver RNA without evaluating frames or writing any data."""
    reconstructed = getattr(obj, "reconstruction", None)
    if reconstructed is None and bool(obj.is_camera):
        reconstructed = getattr(clip.tracking, "reconstruction", None)
    if reconstructed is None:
        return {
            "available": False,
            "is_valid": False,
            "sampled_cameras": [],
            "missing_sample_frames": list(sample_frames),
            "bundles": [],
            "source_only": True,
            "solve_executed": False,
        }
    valid = bool(reconstructed.is_valid)
    cameras = reconstructed.cameras
    if len(cameras) > MAX_RECONSTRUCTED_CAMERAS:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Reconstruction work limit exceeded")
    average = float(reconstructed.average_error)
    if not isfinite(average) or not 0 <= average <= 1e6:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid stored reconstruction error")
    samples = []
    missing = []
    if valid:
        for frame in sample_frames:
            camera = cameras.find_frame(frame=frame)
            if camera is None or int(camera.frame) != frame:
                missing.append(frame)
                continue
            matrix = [[float(value) for value in row] for row in camera.matrix]
            if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid reconstructed pose matrix")
            if not all(isfinite(v) and abs(v) <= 1e9 for row in matrix for v in row):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Nonfinite reconstructed camera pose")
            error = float(camera.average_error)
            if not isfinite(error) or not 0 <= error <= 1e6:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid stored camera error")
            samples.append({"frame": frame, "matrix": matrix, "average_error": error})
    else:
        missing = list(sample_frames)
    bundles = []
    for track in tracks:
        if not bool(track.has_bundle):
            continue
        position = [float(value) for value in track.bundle]
        error = float(track.average_error)
        if (
            len(position) != 3
            or not all(isfinite(v) and abs(v) <= 1e9 for v in position)
            or not isfinite(error)
            or not 0 <= error <= 1e6
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid reconstructed track bundle")
        bundles.append(
            {
                "track_name": string(track.name, "track name", limit=120),
                "position": position,
                "average_error": error,
            }
        )
    return {
        "available": True,
        "is_valid": valid,
        "average_error": average,
        "sampled_cameras": samples,
        "missing_sample_frames": missing,
        "bundles": bundles,
        "sampled_pose_coverage": len(samples) / len(sample_frames),
        "heuristic_low_error": valid and average <= 1.0 and len(missing) == 0,
        "heuristic_only": True,
        "source_only": True,
        "solve_executed": False,
    }
