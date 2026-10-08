"""Level 7 milestone 4: bounded multi-key timeline retiming workflows."""

from dataclasses import dataclass

from .animation_keyframes import AdvancedAnimationOperations
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, invalid, string

MAX_RETIME_KEYS = 32


@dataclass(frozen=True)
class RetimePair:
    source_frame: int
    target_frame: int

    @classmethod
    def parse(cls, data):
        fields(data, {"source_frame", "target_frame"})
        source = integer(data["source_frame"], "source_frame", 1, 100_000)
        target = integer(data["target_frame"], "target_frame", 1, 100_000)
        if source == target:
            raise invalid("Retime source and target frames must differ")
        return cls(source, target)


@dataclass(frozen=True)
class TimelineRetime:
    target: ObjectTarget
    expected_animation_revision: str
    mappings: tuple[RetimePair, ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_animation_revision", "mappings"})
        raw = data["mappings"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_RETIME_KEYS:
            raise invalid(f"mappings must contain 1..{MAX_RETIME_KEYS} frame pairs")
        mappings = tuple(
            sorted(
                (RetimePair.parse(item) for item in raw),
                key=lambda item: item.source_frame,
            )
        )
        sources = [item.source_frame for item in mappings]
        targets = [item.target_frame for item in mappings]
        if len(set(sources)) != len(sources):
            raise invalid("Retime source frames must be unique")
        if len(set(targets)) != len(targets):
            raise invalid("Retime target frames must be unique")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(
                data["expected_animation_revision"],
                "expected_animation_revision",
                limit=64,
            ),
            mappings,
        )


class AnimationTimelineOperations:
    def __init__(self, advanced: AdvancedAnimationOperations):
        self.advanced = advanced
        self.bpy = advanced.bpy

    @staticmethod
    def _point_state(point):
        return {
            "value": float(point.co[1]),
            "interpolation": point.interpolation,
            "easing": getattr(point, "easing", "AUTO"),
            "handle_left_type": getattr(point, "handle_left_type", "AUTO"),
            "handle_right_type": getattr(point, "handle_right_type", "AUTO"),
            "handle_left": [float(value) for value in getattr(point, "handle_left", point.co)],
            "handle_right": [float(value) for value in getattr(point, "handle_right", point.co)],
        }

    def _prepare(self, action):
        obj, object_before, before, curves = self.advanced._managed(
            action.target,
            action.expected_animation_revision,
        )
        existing = {int(frame) for frame in before["unique_frames"]}
        sources = {item.source_frame for item in action.mappings}
        targets = {item.target_frame for item in action.mappings}

        missing = sorted(sources - existing)
        if missing:
            raise AgentError(ErrorCode.NOT_FOUND, "One or more retime source frames do not exist")
        occupied = sorted(frame for frame in targets if frame in existing and frame not in sources)
        if occupied:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Retime target frame is occupied by a key not included in the move set",
            )

        source_points = {}
        source_state = {}
        for mapping in action.mappings:
            points = self.advanced._frame_points(curves, mapping.source_frame)
            source_points[mapping.source_frame] = points
            source_state[mapping.source_frame] = {
                channel: self._point_state(point) for channel, point in points.items()
            }

        resulting_frames = sorted((existing - sources) | targets)
        return obj, object_before, before, curves, source_points, source_state, resulting_frames

    def preview(self, request: Request, action: TimelineRetime):
        _, _, before, _, _, _, resulting_frames = self._prepare(action)
        mappings = [
            {"source_frame": item.source_frame, "target_frame": item.target_frame}
            for item in action.mappings
        ]
        data = {
            "object_id": before["object_id"],
            "animation_revision": before["animation_revision"],
            "mapping_count": len(mappings),
            "moved_point_count": len(mappings) * 9,
            "mappings": mappings,
            "source_frames": [item["source_frame"] for item in mappings],
            "target_frames": [item["target_frame"] for item in mappings],
            "resulting_unique_frames": [float(frame) for frame in resulting_frames],
            "preserves_values": True,
            "preserves_interpolation_easing_handles": True,
            "target_collision_free": True,
            "mutation_performed": False,
            "source_only": True,
            "real_runtime_verified": False,
        }
        data["workflow_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def apply(self, request: Request, action: TimelineRetime):
        (
            obj,
            object_before,
            before,
            curves,
            source_points,
            source_state,
            resulting_frames,
        ) = self._prepare(action)
        snapshot = self.advanced._snapshot(curves)

        for mapping in action.mappings:
            delta = float(mapping.target_frame - mapping.source_frame)
            for point in source_points[mapping.source_frame].values():
                point.co[0] = float(mapping.target_frame)
                if hasattr(point, "handle_left"):
                    point.handle_left[0] = float(point.handle_left[0]) + delta
                if hasattr(point, "handle_right"):
                    point.handle_right[0] = float(point.handle_right[0]) + delta

        for curve in curves.values():
            curve.update()
        self.bpy.context.view_layer.update()

        after = self.advanced._state(action.target.object_id)
        moved_expected = {}
        moved_actual = {}
        readback_curves = self.advanced._curve_map(obj)

        for mapping in action.mappings:
            delta = float(mapping.target_frame - mapping.source_frame)
            for channel in sorted(source_state[mapping.source_frame]):
                path, index = channel
                key = f"{mapping.source_frame}->{mapping.target_frame}:{path}:{index}"
                original = source_state[mapping.source_frame][channel]
                expected_point = {
                    "frame": float(mapping.target_frame),
                    "value": original["value"],
                    "interpolation": original["interpolation"],
                    "easing": original["easing"],
                    "handle_left_type": original["handle_left_type"],
                    "handle_right_type": original["handle_right_type"],
                    "handle_left": [
                        original["handle_left"][0] + delta,
                        original["handle_left"][1],
                    ],
                    "handle_right": [
                        original["handle_right"][0] + delta,
                        original["handle_right"][1],
                    ],
                }
                point = self.advanced._point(readback_curves[channel], mapping.target_frame)
                actual_point = self._point_state(point)
                actual_point["frame"] = float(point.co[0])
                moved_expected[key] = expected_point
                moved_actual[key] = actual_point

        expected = {
            "point_count": before["point_count"],
            "unique_frames": [float(frame) for frame in resulting_frames],
            "moved_points": moved_expected,
            "revision_changed": True,
        }
        actual = {
            "point_count": after["point_count"],
            "unique_frames": after["unique_frames"],
            "moved_points": moved_actual,
            "revision_changed": after["animation_revision"] != before["animation_revision"],
        }
        return self.advanced._finish(
            request,
            obj,
            object_before,
            before,
            snapshot,
            after,
            expected,
            actual,
        )

    def tools(self):
        return [
            Tool(
                "animation.retime_preview",
                SafetyClass.READ_ONLY,
                TimelineRetime.parse,
                self.preview,
            ),
            Tool(
                "animation.retime_apply",
                SafetyClass.MUTATION,
                TimelineRetime.parse,
                self.apply,
            ),
        ]
