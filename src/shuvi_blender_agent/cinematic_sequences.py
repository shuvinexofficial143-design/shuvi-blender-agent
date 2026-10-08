"""Level 8 M10: atomically frame two cameras and bind a timeline hard cut."""

from dataclasses import dataclass

from .cinematic_cuts import CameraCutOperations, CutPreview
from .cinematic_shots import CinematicShotOperations, ShotPreview
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .verification import compare

FIRST = "Shuvi_M10_Sequence_A"
SECOND = "Shuvi_M10_Sequence_B"


@dataclass(frozen=True)
class SequencePreview:
    camera_a: ObjectTarget
    camera_b: ObjectTarget
    subject: ObjectTarget
    azimuth_a: float
    elevation_a: float
    azimuth_b: float
    elevation_b: float
    margin: float
    start_frame: int
    cut_frame: int
    end_frame: int

    @classmethod
    def parse(cls, data):
        names = {
            "camera_a",
            "camera_b",
            "subject",
            "azimuth_a",
            "elevation_a",
            "azimuth_b",
            "elevation_b",
            "margin",
            "start_frame",
            "cut_frame",
            "end_frame",
        }
        fields(data, names)
        cut = CutPreview.parse(
            {
                "camera_a": data["camera_a"],
                "camera_b": data["camera_b"],
                "start_frame": data["start_frame"],
                "cut_frame": data["cut_frame"],
                "end_frame": data["end_frame"],
            }
        )
        return cls(
            cut.camera_a,
            cut.camera_b,
            ObjectTarget.parse(data["subject"]),
            number(data["azimuth_a"], "azimuth_a", -180, 180),
            number(data["elevation_a"], "elevation_a", -75, 75),
            number(data["azimuth_b"], "azimuth_b", -180, 180),
            number(data["elevation_b"], "elevation_b", -75, 75),
            number(data["margin"], "margin", 1.05, 2.5),
            cut.start_frame,
            cut.cut_frame,
            cut.end_frame,
        )


@dataclass(frozen=True)
class SequenceApply:
    preview: SequencePreview
    expected_sequence_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "camera_a",
                "camera_b",
                "subject",
                "azimuth_a",
                "elevation_a",
                "azimuth_b",
                "elevation_b",
                "margin",
                "start_frame",
                "cut_frame",
                "end_frame",
                "expected_sequence_revision",
            },
        )
        return cls(
            SequencePreview.parse(
                {key: val for key, val in data.items() if key != "expected_sequence_revision"}
            ),
            string(data["expected_sequence_revision"], "expected_sequence_revision", limit=64),
        )


@dataclass(frozen=True)
class SequenceRelease:
    expected_sequence_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_sequence_token"})
        return cls(
            string(data["expected_sequence_token"], "expected_sequence_token", limit=64)
        )


class CinematicSequenceOperations:
    """One verified transaction across camera A, camera B and timeline markers."""

    def __init__(self, objects: ObjectOperations):
        self.shots = CinematicShotOperations(objects)
        self.cuts = CameraCutOperations(objects)
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned = {}

    def _plan(self, action: SequencePreview):
        shot_a = ShotPreview(
            action.camera_a,
            action.subject,
            action.azimuth_a,
            action.elevation_a,
            action.margin,
            False,
        )
        shot_b = ShotPreview(
            action.camera_b,
            action.subject,
            action.azimuth_b,
            action.elevation_b,
            action.margin,
            False,
        )
        camera_a, subject_a, before_a, before_subject, plan_a = self.shots._plan(shot_a)
        camera_b, subject_b, before_b, subject_revision, plan_b = self.shots._plan(shot_b)
        scene, cut_camera_a, cut_camera_b, cut_plan = self.cuts._plan(
            CutPreview(
                action.camera_a, action.camera_b,
                action.start_frame, action.cut_frame, action.end_frame
            )
        )
        if camera_a is camera_b or subject_a is not subject_b:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Two cameras and one common subject required")
        if camera_a is subject_a or camera_b is subject_a or subject_a.type == "CAMERA":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subject must be a noncamera object")
        if cut_camera_a is not camera_a or cut_camera_b is not camera_b:
            raise AgentError(ErrorCode.STALE_STATE, "Camera identities changed while planning")
        if before_subject["revision"] != subject_revision["revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Subject state changed while planning")

        blockers = {
            *("SHOT_A_" + reason for reason in plan_a["blockers"]),
            *("SHOT_B_" + reason for reason in plan_b["blockers"]),
            *("CUT_" + reason for reason in cut_plan["blockers"]),
        }
        if any(
            item["name"] in (FIRST, SECOND) for item in cut_plan["scene_state"]["markers"]
        ):
            blockers.add("SEQUENCE_MARKER_NAME_ALREADY_PRESENT")
        if any(
            item["camera_pointer"] is not None
            and action.start_frame <= item["frame"] <= action.end_frame
            for item in cut_plan["scene_state"]["markers"]
        ):
            blockers.add("EXISTING_CAMERA_SEQUENCE_COLLISION")
        if self.bpy.context.mode != "OBJECT":
            blockers.add("OBJECT_MODE_REQUIRED")
        if self._owned:
            blockers.add("SEQUENCE_ALREADY_MANAGED_IN_SESSION")
        plan = {
            "camera_a_id": before_a["object_id"],
            "camera_b_id": before_b["object_id"],
            "subject_id": before_subject["object_id"],
            "camera_a_revision": before_a["revision"],
            "camera_b_revision": before_b["revision"],
            "subject_revision": before_subject["revision"],
            "shot_a_revision": plan_a["plan_revision"],
            "shot_b_revision": plan_b["plan_revision"],
            "cut_revision": cut_plan["cut_revision"],
            "scene_state": cut_plan["scene_state"],
            "active_camera_pointer": self.cuts._pointer(scene.camera),
            "current_frame": scene.frame_current,
            "shot_a_location": plan_a["camera_location"],
            "shot_a_rotation": plan_a["camera_rotation_euler"],
            "shot_b_location": plan_b["camera_location"],
            "shot_b_rotation": plan_b["camera_rotation_euler"],
            "shot_a_lens": plan_a["lens_mm"],
            "shot_b_lens": plan_b["lens_mm"],
            "segments": cut_plan["segments"],
            "marker_names": [FIRST, SECOND],
            "transition": "TWO_FRAMED_CAMERAS_WITH_HARD_CUT",
            "mutates_camera_transforms": True,
            "mutates_existing_markers": False,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "source_only": True,
            "real_runtime_verified": False,
            "mutation_performed": False,
        }
        plan["sequence_revision"] = revision(plan)
        return scene, camera_a, camera_b, subject_a, before_a, before_b, before_subject, plan

    def preview(self, request: Request, action: SequencePreview):
        return Result(
            request.request_id, request.command_id,
            Status.SUCCEEDED, self._plan(action)[-1]
        )

    def _expected_marker_state(self, before, camera_a, camera_b, plan):
        markers = [
            *before["markers"],
            self.cuts._expected_marker(
                FIRST, plan["segments"][0]["start"], self.cuts._pointer(camera_a)
            ),
            self.cuts._expected_marker(
                SECOND, plan["segments"][1]["start"], self.cuts._pointer(camera_b)
            ),
        ]
        markers.sort(
            key=lambda row: (
                row["frame"],
                row["name"],
                -1 if row["camera_pointer"] is None else row["camera_pointer"],
            )
        )
        return {**before, "markers": markers}

    def apply(self, request: Request, action: SequenceApply):
        (
            scene, a, b, subject, before_a, before_b, before_subject, plan
        ) = self._plan(action.preview)
        if plan["sequence_revision"] != action.expected_sequence_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Sequence changed since preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe two-camera framing or cut markers")

        original_markers = self.cuts._state(scene)
        old_active, old_frame = scene.camera, scene.frame_current
        old_poses = [
            (list(a.location), list(a.rotation_euler)),
            (list(b.location), list(b.rotation_euler)),
        ]
        made = []

        def rollback():
            for marker in reversed(made):
                if not self.cuts._contains(scene.timeline_markers, marker):
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Sequence marker identity lost")
                scene.timeline_markers.remove(marker)
            for camera, (position, rotation) in zip((a, b), old_poses, strict=True):
                camera.location = position
                camera.rotation_euler = rotation
            self.bpy.context.view_layer.update()
            if (
                self.inspector.snapshot(a)["revision"] != before_a["revision"]
                or self.inspector.snapshot(b)["revision"] != before_b["revision"]
                or self.inspector.snapshot(subject)["revision"] != before_subject["revision"]
                or self.cuts._state(scene) != original_markers
                or scene.camera is not old_active
                or scene.frame_current != old_frame
            ):
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Sequence setup rollback unverified")

        try:
            a.location = list(plan["shot_a_location"])
            a.rotation_euler = list(plan["shot_a_rotation"])
            b.location = list(plan["shot_b_location"])
            b.rotation_euler = list(plan["shot_b_rotation"])
            for name, frame, camera in (
                (FIRST, plan["segments"][0]["start"], a),
                (SECOND, plan["segments"][1]["start"], b),
            ):
                marker = scene.timeline_markers.new(name, frame=frame)
                made.append(marker)
                self.cuts._configure(marker, name, frame, camera)
            self.bpy.context.view_layer.update()
            actual_markers = self.cuts._state(scene)
            snap_a, snap_b = self.inspector.snapshot(a), self.inspector.snapshot(b)
            expected = {
                "markers": self._expected_marker_state(original_markers, a, b, plan),
                "markers_owned": True,
                "marker_count": len(original_markers["markers"]) + 2,
                "shot_a_location": plan["shot_a_location"],
                "shot_a_rotation": plan["shot_a_rotation"],
                "shot_b_location": plan["shot_b_location"],
                "shot_b_rotation": plan["shot_b_rotation"],
                "lens_a": plan["shot_a_lens"],
                "lens_b": plan["shot_b_lens"],
                "subject_revision": before_subject["revision"],
                "active_unchanged": True,
                "frame_unchanged": True,
                "both_camera_revisions_changed": True,
            }
            actual = {
                "markers": actual_markers,
                "markers_owned": (
                    len(made) == 2
                    and all(self.cuts._contains(scene.timeline_markers, m) for m in made)
                ),
                "marker_count": len(scene.timeline_markers),
                "shot_a_location": snap_a["transform"]["location"],
                "shot_a_rotation": snap_a["transform"]["rotation_euler"],
                "shot_b_location": snap_b["transform"]["location"],
                "shot_b_rotation": snap_b["transform"]["rotation_euler"],
                "lens_a": snap_a["camera"]["lens"],
                "lens_b": snap_b["camera"]["lens"],
                "subject_revision": self.inspector.snapshot(subject)["revision"],
                "active_unchanged": scene.camera is old_active,
                "frame_unchanged": scene.frame_current == old_frame,
                "both_camera_revisions_changed": (
                    snap_a["revision"] != before_a["revision"]
                    and snap_b["revision"] != before_b["revision"]
                ),
            }
            checked = compare(expected, actual)
            if checked.matched:
                token = revision(
                    {
                        "scene_after": actual_markers,
                        "camera_a_after": snap_a["revision"],
                        "camera_b_after": snap_b["revision"],
                    }
                )
                self._owned[token] = {
                    "scene": scene,
                    "a": a,
                    "b": b,
                    "subject": subject,
                    "markers": list(made),
                    "original_markers": original_markers,
                    "after_markers": actual_markers,
                    "original_poses": old_poses,
                    "before_a": before_a["revision"],
                    "before_b": before_b["revision"],
                    "after_a": snap_a["revision"],
                    "after_b": snap_b["revision"],
                    "after_poses": [
                        (list(a.location), list(a.rotation_euler)),
                        (list(b.location), list(b.rotation_euler)),
                    ],
                }
                return Result(
                    request.request_id, request.command_id, Status.VERIFIED,
                    {
                        "sequence_token": token,
                        "framed_cameras": 2,
                        "bound_cut_markers": 2,
                        "shot_segments": plan["segments"],
                        "real_runtime_verified": False,
                    },
                    verification=checked.to_dict(),
                )
        except Exception as exc:
            try:
                rollback()
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Sequence creation rollback unverified"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Sequence creation interrupted; original state restored"
            ) from exc

        rollback()
        return Result(
            request.request_id, request.command_id, Status.FAILED,
            {"rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Sequence readback mismatch"),
            checked.to_dict(),
        )

    def release(self, request: Request, action: SequenceRelease):
        owned = self._owned.get(action.expected_sequence_token)
        if owned is None or self.bpy.context.scene is not owned["scene"]:
            raise AgentError(ErrorCode.STALE_STATE, "Sequence token not owned in current session")
        scene, a, b = owned["scene"], owned["a"], owned["b"]
        first, second = owned["markers"]
        if (
            self.cuts._state(scene) != owned["after_markers"]
            or not self.cuts._contains(scene.timeline_markers, first)
            or not self.cuts._contains(scene.timeline_markers, second)
            or self.inspector.snapshot(a)["revision"] != owned["after_a"]
            or self.inspector.snapshot(b)["revision"] != owned["after_b"]
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Sequence markers/cameras changed externally")

        old_active, old_frame = scene.camera, scene.frame_current

        def restore():
            for marker in owned["markers"]:
                if self.cuts._contains(scene.timeline_markers, marker):
                    continue
                marker_name, frame, camera = (
                    (FIRST, owned["after_markers"]["markers"], a)
                    if marker is first
                    else (SECOND, owned["after_markers"]["markers"], b)
                )
                start = next(
                    item["frame"]
                    for item in frame
                    if item["name"] == marker_name
                )
                fresh = scene.timeline_markers.new(marker_name, frame=start)
                self.cuts._configure(fresh, marker_name, start, camera)
                owned["markers"][0 if marker is first else 1] = fresh
            for camera, (position, rotation) in zip(
                (a, b), owned["after_poses"], strict=True
            ):
                camera.location, camera.rotation_euler = position, rotation
            self.bpy.context.view_layer.update()
            if (
                self.cuts._state(scene) != owned["after_markers"]
                or self.inspector.snapshot(a)["revision"] != owned["after_a"]
                or self.inspector.snapshot(b)["revision"] != owned["after_b"]
                or scene.camera is not old_active
                or scene.frame_current != old_frame
            ):
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Sequence release rollback unverified"
                )

        try:
            scene.timeline_markers.remove(second)
            scene.timeline_markers.remove(first)
            for camera, (position, rotation) in zip(
                (a, b), owned["original_poses"], strict=True
            ):
                camera.location, camera.rotation_euler = position, rotation
            self.bpy.context.view_layer.update()
            expected = {
                "marker_state": owned["original_markers"],
                "before_a": owned["before_a"],
                "before_b": owned["before_b"],
                "camera_unchanged": True,
                "frame_unchanged": True,
            }
            actual = {
                "marker_state": self.cuts._state(scene),
                "before_a": self.inspector.snapshot(a)["revision"],
                "before_b": self.inspector.snapshot(b)["revision"],
                "camera_unchanged": scene.camera is old_active,
                "frame_unchanged": scene.frame_current == old_frame,
            }
            checked = compare(expected, actual)
            if checked.matched:
                del self._owned[action.expected_sequence_token]
                return Result(
                    request.request_id, request.command_id, Status.VERIFIED,
                    {"released_sequence": True, "restored_camera_poses": 2,
                     "removed_owned_markers": 2},
                    verification=checked.to_dict(),
                )
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Sequence release readback mismatch")
        except Exception as exc:
            try:
                restore()
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Sequence release rollback unverified"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Sequence release interrupted; owned state restored"
            ) from exc

    def tools(self):
        return [
            Tool(
                "cinema.sequence_preview", SafetyClass.READ_ONLY,
                SequencePreview.parse, self.preview
            ),
            Tool(
                "cinema.sequence_apply", SafetyClass.MUTATION,
                SequenceApply.parse, self.apply
            ),
            Tool(
                "cinema.sequence_release", SafetyClass.MUTATION,
                SequenceRelease.parse, self.release
            ),
        ]
