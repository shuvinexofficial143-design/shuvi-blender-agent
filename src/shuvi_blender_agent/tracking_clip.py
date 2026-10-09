"""Level 11 M1: inspect existing MovieClip camera/object tracking data.

Read-only: no clip loading, disk paths, automatic tracking, camera solves or renders.
"""

from dataclasses import dataclass
from math import hypot, isfinite

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, string

MAX_CLIPS = 32
MAX_TRACKS = 64
MAX_SAMPLE_FRAMES = 16


@dataclass(frozen=True)
class ClipInspect:
    clip_name: str
    tracking_object_name: str
    frames: tuple[int, ...]
    analyze_motion: bool = False

    @classmethod
    def parse(cls, data):
        fields(data, {"clip_name", "tracking_object_name", "frames"}, {"analyze_motion"})
        analyze = data.get("analyze_motion", False)
        if type(analyze) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "analyze_motion must be Boolean")
        frames = data["frames"]
        if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_SAMPLE_FRAMES:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Provide 1–16 sample frames")
        checked = tuple(integer(frame, "frame", 1, 1048574) for frame in frames)
        if len(set(checked)) != len(checked) or list(checked) != sorted(checked):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Frames must be unique and increasing")
        return cls(
            string(data["clip_name"], "clip_name", limit=120),
            string(data["tracking_object_name"], "tracking_object_name", limit=120),
            checked,
            analyze,
        )


class MovieClipInspectionOperations:
    def __init__(self, bpy):
        self.bpy = bpy

    def resolve(self, clip_name, tracking_object_name):
        clips = self.bpy.data.movieclips
        if len(clips) > MAX_CLIPS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many loaded MovieClips")
        clip = clips.get(clip_name)
        if clip is None:
            raise AgentError(ErrorCode.NOT_FOUND, "MovieClip is not loaded")
        if getattr(clip, "library", None) is not None or not getattr(clip, "is_editable", True):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local editable MovieClip required")
        objects = clip.tracking.objects
        if len(objects) > 16:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many tracking objects")
        tracked = objects.get(tracking_object_name)
        if tracked is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Tracking object not found")
        return clip, tracked

    @staticmethod
    def motion_quality(requested, samples, image_size):
        """Heuristic only; does not measure reprojection error or solve a camera."""
        visible = [m for m in samples if not m["mute"]]
        missing = [f for f in requested if all(m["frame"] != f for m in visible)]
        speeds = []
        for before, after in zip(visible, visible[1:]):
            frames = after["frame"] - before["frame"]
            if frames <= 0:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Unsorted track markers")
            dx = (after["co"][0] - before["co"][0]) * image_size[0]
            dy = (after["co"][1] - before["co"][1]) * image_size[1]
            speeds.append(hypot(dx, dy) / frames)
        jump_limit = 0.1 * hypot(*image_size)
        jumps = sum(speed > jump_limit for speed in speeds)
        coverage = len(visible) / len(requested)
        return {
            "sample_count": len(visible),
            "coverage": coverage,
            "missing_or_muted_frames": missing,
            "mean_speed_px_per_frame": sum(speeds) / len(speeds) if speeds else 0.0,
            "max_speed_px_per_frame": max(speeds, default=0.0),
            "jump_count": jumps,
            "heuristic_ready": len(visible) >= 3 and coverage >= 0.75 and jumps == 0,
            "heuristic_only": True,
        }

    def inspect(self, request, action):
        clip, obj = self.resolve(action.clip_name, action.tracking_object_name)
        tracks = obj.tracks
        if len(tracks) > MAX_TRACKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Tracking inspection limit exceeded")
        summary = []
        for track in tracks:
            name = string(track.name, "track name", limit=120)
            markers = []
            for frame in action.frames:
                found = track.markers.find_frame(frame, exact=True)
                if found is None:
                    continue
                coords = [float(x) for x in found.co]
                if len(coords) != 2 or not all(isfinite(x) for x in coords):
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Non-finite tracking marker")
                markers.append(
                    {
                        "frame": frame,
                        "co": coords,
                        "mute": bool(found.mute),
                        "is_keyed": bool(found.is_keyed),
                    }
                )
            summary.append(
                {
                    "name": name,
                    "locked": bool(track.lock),
                    "has_bundle": bool(track.has_bundle),
                    "sampled_markers": markers,
                }
            )
        size = [int(x) for x in clip.size]
        if len(size) != 2 or any(x < 0 or x > 100000 for x in size):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid MovieClip dimensions")
        if action.analyze_motion:
            if not all(size):
                raise AgentError(ErrorCode.SAFETY_DENIED, "Footage dimensions required")
            for entry in summary:
                entry["motion_quality"] = self.motion_quality(
                    action.frames, entry["sampled_markers"], size
                )
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "clip_name": clip.name,
                "tracking_object_name": obj.name,
                "camera_tracking": bool(obj.is_camera),
                "size": size,
                "frame_duration": max(0, int(clip.frame_duration)),
                "track_count": len(tracks),
                "tracks": summary,
                "sample_frames": list(action.frames),
                "motion_analyzed": action.analyze_motion,
                "source_only": True,
                "matchmove_solved": False,
                "mutation_performed": False,
            },
        )

    def tools(self):
        return [
            Tool(
                "tracking.clip_inspect",
                SafetyClass.READ_ONLY,
                ClipInspect.parse,
                self.inspect,
            )
        ]
