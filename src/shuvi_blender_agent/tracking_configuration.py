"""Level 11 M5: owned native Blender MovieTrackingTrack configuration.

Changes existing local unlocked tracks, not footage files, tracking frames or camera solves.
"""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .tracking_clip import MovieClipInspectionOperations
from .tracking_markers import MarkerPlacementOperations
from .validation import fields, integer, number, string
from .verification import compare

MOTION_MODELS = {"Loc", "LocRot", "LocScale", "LocRotScale", "Affine", "Perspective"}
TRACK_FIELDS = (
    "motion_model",
    "pattern_match",
    "correlation_min",
    "frames_limit",
    "margin",
    "use_brute",
    "use_normalization",
    "weight",
)


@dataclass(frozen=True)
class TrackConfigurationPreview:
    clip_name: str
    tracking_object_name: str
    track_name: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"clip_name", "tracking_object_name", "track_name", "settings"})
        settings = data["settings"]
        fields(settings, set(TRACK_FIELDS))
        model = string(settings["motion_model"], "motion_model", limit=24)
        match = string(settings["pattern_match"], "pattern_match", limit=16)
        if model not in MOTION_MODELS or match not in {"KEYFRAME", "PREV_FRAME"}:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unsupported tracking model or pattern")
        brute = settings["use_brute"]
        normalize = settings["use_normalization"]
        if type(brute) is not bool or type(normalize) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Tracking toggles must be Boolean")
        prepared = {
            "motion_model": model,
            "pattern_match": match,
            "correlation_min": number(settings["correlation_min"], "correlation_min", 0, 1),
            "frames_limit": integer(settings["frames_limit"], "frames_limit", 0, 512),
            "margin": integer(settings["margin"], "margin", 0, 64),
            "use_brute": brute,
            "use_normalization": normalize,
            "weight": number(settings["weight"], "weight", 0, 1),
        }
        return cls(
            string(data["clip_name"], "clip_name", limit=120),
            string(data["tracking_object_name"], "tracking_object_name", limit=120),
            string(data["track_name"], "track_name", limit=120),
            prepared,
        )


@dataclass(frozen=True)
class TrackConfigurationApply:
    preview: TrackConfigurationPreview
    expected_track_config_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "clip_name",
                "tracking_object_name",
                "track_name",
                "settings",
                "expected_track_config_revision",
            },
        )
        params = dict(data)
        expected = string(
            params.pop("expected_track_config_revision"), "expected_track_config_revision", limit=64
        )
        return cls(TrackConfigurationPreview.parse(params), expected)


@dataclass(frozen=True)
class TrackConfigurationRestore:
    expected_track_config_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_track_config_token"})
        return cls(
            string(data["expected_track_config_token"], "expected_track_config_token", limit=64)
        )


class MovieTrackingTrackConfigOperations:
    def __init__(self, bpy):
        self.inspection = MovieClipInspectionOperations(bpy)
        self.markers = MarkerPlacementOperations(bpy)
        self._owned = {}

    @staticmethod
    def _read(track):
        values = {}
        for key in TRACK_FIELDS:
            value = getattr(track, key)
            if key in {"correlation_min", "weight"}:
                value = number(float(value), key, 0, 1)
            elif key in {"frames_limit", "margin"}:
                value = integer(int(value), key, 0, 32767 if key == "frames_limit" else 300)
            elif key in {"use_brute", "use_normalization"}:
                if type(value) is not bool:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid Blender tracking toggle")
            else:
                value = str(value)
                if key == "motion_model" and value not in MOTION_MODELS:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Unknown Blender tracking model")
                if key == "pattern_match" and value not in {"KEYFRAME", "PREV_FRAME"}:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Unknown tracking pattern")
            values[key] = value
        return values

    @staticmethod
    def _write(track, values):
        for key in TRACK_FIELDS:
            setattr(track, key, values[key])

    def _plan(self, action):
        clip, obj = self.inspection.resolve(action.clip_name, action.tracking_object_name)
        if len(obj.tracks) > 64:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many tracking tracks")
        track = obj.tracks.get(action.track_name)
        if track is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Tracking track not found")
        if bool(track.lock):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Locked tracking track")
        if any(s["track"] is track for s in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Track configuration already owned")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Active track ownership limit")
        before = self._read(track)
        markers = self.markers._signature(clip, obj, track)
        plan = {
            "clip_name": clip.name,
            "tracking_object_name": obj.name,
            "track_name": track.name,
            "before": before,
            "settings": action.settings,
            "marker_signature": markers,
            "mutation_performed": False,
            "tracking_executed": False,
            "source_only": True,
        }
        plan["track_config_revision"] = revision(plan)
        return clip, obj, track, plan

    def preview(self, request, action):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[3]
        )

    def apply(self, request, action):
        clip, obj, track, plan = self._plan(action.preview)
        if action.expected_track_config_revision != plan["track_config_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Stale tracking configuration preview")
        before = plan["before"]
        try:
            self._write(track, plan["settings"])
            actual = self._read(track)
            checked = compare(plan["settings"], actual)
            if not checked.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Track configuration readback mismatch"
                )
            if self.markers._signature(clip, obj, track) != plan["marker_signature"]:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED, "Markers changed during track configuration"
                )
        except Exception as exc:
            try:
                self._write(track, before)
                if not compare(before, self._read(track)).matched:
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Tracking rollback mismatch")
            except Exception as rollback:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Tracking rollback uncertain"
                ) from rollback
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Track config apply failed; original settings restored") from exc
        token = revision(
            {
                "clip": clip.name,
                "object": obj.name,
                "track": track.name,
                "before": before,
                "after": actual,
                "marker_signature": plan["marker_signature"],
            }
        )
        self._owned[token] = {
            "clip": clip,
            "object": obj,
            "track": track,
            "before": before,
            "after": actual,
            "markers": plan["marker_signature"],
        }
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"track_config_token": token, "source_only": True, "tracking_executed": False},
            verification=checked.to_dict(),
        )

    def restore(self, request, action):
        token = action.expected_track_config_token
        state = self._owned.get(token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown/used configuration token")
        clip, obj, track = state["clip"], state["object"], state["track"]
        resolved_clip, resolved_obj = self.inspection.resolve(clip.name, obj.name)
        if resolved_clip is not clip or resolved_obj is not obj:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Clip or tracking object replaced")
        if obj.tracks.get(track.name) is not track or bool(track.lock):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Track replaced or locked")
        if not compare(state["after"], self._read(track)).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Track settings edited by another user")
        if self.markers._signature(clip, obj, track) != state["markers"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Tracking markers changed externally")
        self._write(track, state["before"])
        checked = compare(state["before"], self._read(track))
        if not checked.matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Track restore mismatch")
        del self._owned[token]
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"track_configuration_restored": True, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "tracking.track_config_preview",
                SafetyClass.READ_ONLY,
                TrackConfigurationPreview.parse,
                self.preview,
            ),
            Tool(
                "tracking.track_config_apply",
                SafetyClass.MUTATION,
                TrackConfigurationApply.parse,
                self.apply,
            ),
            Tool(
                "tracking.track_config_restore",
                SafetyClass.MUTATION,
                TrackConfigurationRestore.parse,
                self.restore,
            ),
        ]
