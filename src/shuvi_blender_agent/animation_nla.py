"""Level 7 M8: bounded push-down of one session-owned transform Action into NLA."""

from dataclasses import dataclass
from math import isfinite

from .animation import AnimationInspect, AnimationOperations
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .models import ObjectTarget, object_name
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, string
from .verification import compare

MAX_NLA_TRACKS = 64
MAX_NLA_STRIPS = 64
CHANNELS = {(path, index) for path in ("location", "rotation_euler", "scale") for index in range(3)}


@dataclass(frozen=True)
class NLAInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class NLAStripCreate:
    target: ObjectTarget
    expected_nla_revision: str
    track_name: str
    strip_name: str
    start_frame: int

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"target", "expected_nla_revision", "track_name", "strip_name", "start_frame"},
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_nla_revision"], "expected_nla_revision", limit=64),
            object_name(data["track_name"]),
            object_name(data["strip_name"]),
            integer(data["start_frame"], "start_frame", 1, 100_000),
        )


class ManagedNLAOperations:
    def __init__(self, animation: AnimationOperations):
        self.animation = animation
        self.inspector = animation.inspector
        self.bpy = animation.bpy
        self._owned_tracks = {}

    @staticmethod
    def _safe_number(value):
        if type(value) not in (int, float) or not isfinite(value):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid NLA numeric property")
        return float(value)

    def _action_evidence(self, action):
        if not hasattr(action, "fcurves"):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported layered NLA Action")
        curves = action.fcurves
        if len(curves) > 64:
            raise AgentError(ErrorCode.SAFETY_DENIED, "NLA Action FCurve limit exceeded")
        result = []
        total = 0
        for curve in curves:
            points = curve.keyframe_points
            if len(points) > 256:
                raise AgentError(ErrorCode.SAFETY_DENIED, "NLA keyframe limit exceeded")
            total += len(points)
            if total > 1024:
                raise AgentError(ErrorCode.SAFETY_DENIED, "NLA Action point limit exceeded")
            result.append(
                {
                    "path": bounded_text(curve.data_path, limit=256),
                    "index": curve.array_index,
                    "points": [
                        {
                            "frame": self._safe_number(point.co[0]),
                            "value": self._safe_number(point.co[1]),
                            "interpolation": bounded_text(point.interpolation, limit=32),
                        }
                        for point in points
                    ],
                }
            )
        result.sort(key=lambda item: (item["path"], item["index"]))
        return revision(result)

    def _state(self, object_id):
        action_state = self.animation.inspect(
            Request("animation.inspect", {"object_id": object_id}),
            AnimationInspect(object_id),
        ).data
        obj = self.inspector.resolve(object_id)
        ad = obj.animation_data
        tracks = list(getattr(ad, "nla_tracks", ())) if ad is not None else []
        if len(tracks) > MAX_NLA_TRACKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "NLA track limit exceeded")
        track_states = []
        total = 0
        owned = self._owned_tracks.get(object_id)
        for track in tracks:
            strips = list(track.strips)
            total += len(strips)
            if total > MAX_NLA_STRIPS:
                raise AgentError(ErrorCode.SAFETY_DENIED, "NLA strip limit exceeded")
            track_states.append(
                {
                    "name": bounded_text(track.name, limit=256),
                    "mute": bool(track.mute),
                    "managed": owned is track,
                    "strips": [
                        {
                            "name": bounded_text(strip.name, limit=256),
                            "action_name": bounded_text(strip.action.name, limit=256),
                            "action_fingerprint": self._action_evidence(strip.action),
                            "frame_start": self._safe_number(strip.frame_start),
                            "frame_end": self._safe_number(strip.frame_end),
                            "action_frame_start": self._safe_number(strip.action_frame_start),
                            "action_frame_end": self._safe_number(strip.action_frame_end),
                            "scale": self._safe_number(strip.scale),
                            "repeat": self._safe_number(strip.repeat),
                            "influence": self._safe_number(strip.influence),
                            "blend_type": bounded_text(strip.blend_type, limit=32),
                            "mute": bool(strip.mute),
                        }
                        for strip in strips
                    ],
                }
            )
        state = {
            "object_id": object_id,
            "active_action": action_state["action_name"],
            "active_animation_revision": action_state["animation_revision"],
            "active_action_owned": action_state["managed_session_action"],
            "track_count": len(track_states),
            "strip_count": total,
            "tracks": track_states,
            "source_only": True,
            "real_runtime_verified": False,
        }
        state["nla_revision"] = revision(
            {
                "active_animation_revision": state["active_animation_revision"],
                "tracks": track_states,
            }
        )
        blockers = list(action_state["blockers"])
        if tracks:
            blockers.append("NLA_TRACKS_ALREADY_PRESENT")
        if action_state["action_api"] != "LEGACY":
            blockers.append("LEGACY_ACTION_REQUIRED")
        if {(ch["data_path"], ch["index"]) for ch in action_state["channels"]} != CHANNELS:
            blockers.append("COMPLETE_NINE_TRANSFORM_CHANNELS_REQUIRED")
        frames = action_state["unique_frames"]
        if (
            len(frames) < 2
            or not all(frame.is_integer() for frame in frames)
            or any(
                [point["frame"] for point in ch["points"]] != frames
                for ch in action_state["channels"]
            )
        ):
            blockers.append("COMPLETE_INTEGER_FRAME_KEYS_REQUIRED")
        if ad is not None and getattr(ad, "action_slot", None) is not None:
            blockers.append("SLOTTED_ACTION_UNVERIFIED")
        state["blockers"] = sorted(set(blockers))
        state["managed_nla_ready"] = not blockers
        state["source_action_fingerprint"] = (
            self._action_evidence(ad.action) if ad is not None and ad.action is not None else None
        )
        state["source_frames"] = frames
        return state

    def inspect(self, request: Request, action: NLAInspect):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._state(action.object_id),
        )

    def _restore(self, obj, track, original_action):
        ad = obj.animation_data
        if track is not None and track in ad.nla_tracks:
            ad.nla_tracks.remove(track)
        ad.action = original_action
        self._owned_tracks.pop(self.inspector.identity(obj), None)
        self.bpy.context.view_layer.update()

    def create(self, request: Request, action: NLAStripCreate):
        obj, object_before = self.inspector.target(action.target)
        before = self._state(action.target.object_id)
        require_revision(action.expected_nla_revision, before["nla_revision"])
        if not before["managed_nla_ready"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "NLA Action is not eligible for managed push-down"
            )
        frames = before["source_frames"]
        duration = int(frames[-1] - frames[0])
        if duration < 1 or action.start_frame + duration > 100_000:
            raise AgentError(ErrorCode.SAFETY_DENIED, "NLA strip duration exceeds frame bound")

        ad = obj.animation_data
        original_action = ad.action
        original_fingerprint = before["source_action_fingerprint"]
        track = None
        try:
            ad.action = None
            track = ad.nla_tracks.new()
            track.name = action.track_name
            track.mute = False
            strip = track.strips.new(action.strip_name, action.start_frame, original_action)
            strip.blend_type = "REPLACE"
            strip.influence = 1.0
            strip.scale = 1.0
            strip.repeat = 1.0
            strip.mute = False
            self._owned_tracks[action.target.object_id] = track
            self.bpy.context.view_layer.update()
            after = self._state(action.target.object_id)
            state = after["tracks"][0]["strips"][0] if after["strip_count"] == 1 else {}
            expected = {
                "active_action": None,
                "track_count": 1,
                "strip_count": 1,
                "track_name": action.track_name,
                "strip_name": action.strip_name,
                "owned_track": True,
                "action_name": before["active_action"],
                "action_fingerprint": original_fingerprint,
                "frame_start": float(action.start_frame),
                "frame_end": float(action.start_frame + duration),
                "scale": 1.0,
                "repeat": 1.0,
                "influence": 1.0,
                "blend_type": "REPLACE",
                "mute": False,
                "revision_changed": True,
            }
            actual = {
                "active_action": after["active_action"],
                "track_count": after["track_count"],
                "strip_count": after["strip_count"],
                "track_name": after["tracks"][0]["name"] if after["track_count"] == 1 else None,
                "strip_name": state.get("name"),
                "owned_track": (
                    after["tracks"][0]["managed"] if after["track_count"] == 1 else False
                ),
                "action_name": state.get("action_name"),
                "action_fingerprint": state.get("action_fingerprint"),
                "frame_start": state.get("frame_start"),
                "frame_end": state.get("frame_end"),
                "scale": state.get("scale"),
                "repeat": state.get("repeat"),
                "influence": state.get("influence"),
                "blend_type": state.get("blend_type"),
                "mute": state.get("mute"),
                "revision_changed": after["nla_revision"] != before["nla_revision"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"object_before": object_before, "before": before, "after": after},
                    verification=verification.to_dict(),
                )
            self._restore(obj, track, original_action)
            recovered = self._state(action.target.object_id)
            restored = recovered["nla_revision"] == before["nla_revision"]
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "rolled_back": True,
                    "recovery_verified": restored,
                },
                AgentError(ErrorCode.VERIFICATION_FAILED, "NLA strip readback mismatch"),
                verification.to_dict(),
            )
        except Exception:
            try:
                self._restore(obj, track, original_action)
            except Exception:
                pass
            raise

    def tools(self):
        return [
            Tool("animation.nla_inspect", SafetyClass.READ_ONLY, NLAInspect.parse, self.inspect),
            Tool(
                "animation.nla_strip_create",
                SafetyClass.MUTATION,
                NLAStripCreate.parse,
                self.create,
            ),
        ]
