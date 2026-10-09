"""Level 11 M2: add 2–8 manual tracking markers to an existing Blender MovieClip track.

Never creates/loads footage, solves motion, invokes operators, or writes to filesystem.
Only newly-owned, unchanged markers can be removed by the one-use restore token.
"""

from dataclasses import dataclass
from math import isfinite

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .tracking_clip import MovieClipInspectionOperations
from .validation import fields, integer, number, string
from .verification import compare

MAX_EXISTING_MARKERS = 512
MAX_NEW_MARKERS = 8


@dataclass(frozen=True)
class MarkerPreview:
    clip_name: str
    tracking_object_name: str
    track_name: str
    frames: tuple[tuple[int, tuple[float, float]], ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"clip_name", "tracking_object_name", "track_name", "markers"})
        markers = data["markers"]
        if not isinstance(markers, list) or not 2 <= len(markers) <= MAX_NEW_MARKERS:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Provide two to eight manual markers")
        converted = []
        for item in markers:
            fields(item, {"frame", "co"})
            frame = integer(item["frame"], "frame", 1, 1048574)
            co = item["co"]
            if not isinstance(co, list) or len(co) != 2:
                raise AgentError(ErrorCode.INVALID_REQUEST, "Marker coordinates must be XY")
            x, y = (number(v, "co", 0, 1) for v in co)
            converted.append((frame, (x, y)))
        frames = [frame for frame, _ in converted]
        if sorted(set(frames)) != frames:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Marker frames must increase uniquely")
        return cls(
            string(data["clip_name"], "clip_name", limit=120),
            string(data["tracking_object_name"], "tracking_object_name", limit=120),
            string(data["track_name"], "track_name", limit=120),
            tuple(converted),
        )


@dataclass(frozen=True)
class MarkerApply:
    preview: MarkerPreview
    expected_marker_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"clip_name", "tracking_object_name", "track_name", "markers",
                      "expected_marker_revision"})
        data = dict(data)
        expected = string(data.pop("expected_marker_revision"), "expected_marker_revision",
                          limit=64)
        return cls(MarkerPreview.parse(data), expected)


@dataclass(frozen=True)
class MarkerRestore:
    expected_marker_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_marker_token"})
        return cls(string(data["expected_marker_token"], "expected_marker_token", limit=64))


class MarkerPlacementOperations:
    def __init__(self, bpy):
        self.inspection = MovieClipInspectionOperations(bpy)
        self._owned = {}

    @staticmethod
    def _read_marker(marker):
        coords = [float(value) for value in marker.co]
        if len(coords) != 2 or not all(isfinite(value) for value in coords):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid marker coordinates")
        return {
            "frame": int(marker.frame),
            "co": coords,
            "mute": bool(marker.mute),
            "is_keyed": bool(marker.is_keyed),
        }

    def _signature(self, clip, tracking_object, track):
        markers = track.markers
        if len(markers) > MAX_EXISTING_MARKERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Existing marker work limit exceeded")
        return revision({
            "clip_name": clip.name,
            "clip_size": [int(v) for v in clip.size],
            "duration": int(clip.frame_duration),
            "tracking_object_name": tracking_object.name,
            "track_name": track.name,
            "locked": bool(track.lock),
            "markers": sorted(
                (self._read_marker(marker) for marker in markers),
                key=lambda item: item["frame"],
            ),
        })

    def _plan(self, action):
        clip, obj = self.inspection.resolve(action.clip_name, action.tracking_object_name)
        if len(obj.tracks) > 64:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many tracking tracks")
        track = obj.tracks.get(action.track_name)
        if track is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Existing motion tracking track not found")
        if track.lock:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Locked tracking track")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Marker ownership capacity exceeded")
        duration = int(clip.frame_duration)
        for frame, _ in action.frames:
            if duration > 0 and frame > duration:
                raise AgentError(ErrorCode.INVALID_REQUEST, "Marker outside clip duration")
            if track.markers.find_frame(frame, exact=True) is not None:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Existing marker cannot be overwritten")
        before = self._signature(clip, obj, track)
        planned = {
            "clip_name": clip.name,
            "tracking_object_name": obj.name,
            "track_name": track.name,
            "before_tracking_revision": before,
            "markers": [{"frame": f, "co": list(co)} for f, co in action.frames],
            "source_only": True,
            "mutation_performed": False,
            "automatic_tracking": False,
            "matchmove_solved": False,
        }
        planned["marker_revision"] = revision(planned)
        return clip, obj, track, planned

    def preview(self, request, action):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED,
            self._plan(action)[3],
        )

    @staticmethod
    def _remove_created(track, created):
        for frame in reversed(created):
            if track.markers.find_frame(frame, exact=True) is not None:
                track.markers.delete_frame(frame)
        if any(track.markers.find_frame(f, exact=True) is not None for f in created):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Marker rollback uncertain")

    def apply(self, request, action):
        clip, obj, track, plan = self._plan(action.preview)
        if action.expected_marker_revision != plan["marker_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Stale marker placement plan")
        created = []
        try:
            for frame, co in action.preview.frames:
                track.markers.insert_frame(frame, co=co)
                created.append(frame)
                marker = track.markers.find_frame(frame, exact=True)
                if marker is None:
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Marker insertion not visible")
                expected = {"frame": frame, "co": list(co), "mute": False}
                actual = self._read_marker(marker)
                if not compare(expected, actual).matched:
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Marker RNA readback mismatch")
            actual = [self._read_marker(track.markers.find_frame(f, exact=True))
                      for f, _ in action.preview.frames]
            expected = [{"frame": frame, "co": list(co), "mute": False}
                        for frame, co in action.preview.frames]
            checked = compare({"markers": expected}, {"markers": actual})
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Inserted marker mismatch")
            token = revision({
                "track": track.name, "pre": plan["before_tracking_revision"],
                "post": self._signature(clip, obj, track),
                "frames": created,
            })
            self._owned[token] = {
                "clip": clip, "object": obj, "track": track,
                "frames": list(created),
                "before": plan["before_tracking_revision"],
                "after": self._signature(clip, obj, track),
            }
            return Result(
                request.request_id, request.command_id, Status.VERIFIED,
                {"marker_token": token, "markers_created": len(created), "source_only": True,
                 "matchmove_solved": False},
                verification=checked.to_dict(),
            )
        except Exception as exc:
            self._remove_created(track, created)
            if self._signature(clip, obj, track) != plan["before_tracking_revision"]:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Marker rollback did not restore prior state"
                ) from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Marker apply failed; only owned frames reverted") from exc

    def restore(self, request, action):
        token = action.expected_marker_token
        owned = self._owned.get(token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Foreign or used marker token")
        clip, obj, track = owned["clip"], owned["object"], owned["track"]
        current_clip, current_obj = self.inspection.resolve(clip.name, obj.name)
        if current_clip is not clip or current_obj is not obj:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Tracking object was replaced")
        if obj.tracks.get(track.name) is not track or track.lock:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Tracking track was replaced or locked")
        if self._signature(clip, obj, track) != owned["after"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Existing tracking data was edited")
        self._remove_created(track, owned["frames"])
        if self._signature(clip, obj, track) != owned["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Marker restore not verified")
        del self._owned[token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id, request.command_id, Status.VERIFIED,
            {"removed_owned_markers": len(owned["frames"]), "restored": True,
             "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool("tracking.marker_preview", SafetyClass.READ_ONLY,
                 MarkerPreview.parse, self.preview),
            Tool("tracking.marker_apply", SafetyClass.MUTATION,
                 MarkerApply.parse, self.apply),
            Tool("tracking.marker_restore", SafetyClass.MUTATION,
                 MarkerRestore.parse, self.restore),
        ]
