"""Level 11 M4: source-verifiable lens calibration for an existing MovieClip camera.

No file reads, video tracking, solve operators or Blender rendering.
"""

from dataclasses import dataclass
from math import isfinite

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .tracking_clip import MovieClipInspectionOperations
from .validation import fields, number, string
from .verification import compare

CALIBRATION_FIELDS = (
    "units",
    "distortion_model",
    "sensor_width",
    "focal_length",
    "pixel_aspect",
    "principal_point",
    "k1",
    "k2",
    "k3",
)


@dataclass(frozen=True)
class CameraCalibrationPreview:
    clip_name: str
    tracking_object_name: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"clip_name", "tracking_object_name", "settings"})
        values = data["settings"]
        fields(
            values,
            {
                "focal_length",
                "sensor_width",
                "pixel_aspect",
                "principal_point",
                "k1",
                "k2",
                "k3",
            },
        )
        point = values["principal_point"]
        if not isinstance(point, list) or len(point) != 2:
            raise AgentError(ErrorCode.INVALID_REQUEST, "principal_point must contain XY")
        result = {
            "units": "MILLIMETERS",
            "distortion_model": "POLYNOMIAL",
            "focal_length": number(values["focal_length"], "focal_length", 1, 300),
            "sensor_width": number(values["sensor_width"], "sensor_width", 1, 100),
            "pixel_aspect": number(values["pixel_aspect"], "pixel_aspect", 0.5, 2),
            "principal_point": [
                number(value, "principal_point", -1, 1) for value in point
            ],
            "k1": number(values["k1"], "k1", -0.5, 0.5),
            "k2": number(values["k2"], "k2", -0.5, 0.5),
            "k3": number(values["k3"], "k3", -0.5, 0.5),
        }
        return cls(
            string(data["clip_name"], "clip_name", limit=120),
            string(data["tracking_object_name"], "tracking_object_name", limit=120),
            result,
        )


@dataclass(frozen=True)
class CameraCalibrationApply:
    preview: CameraCalibrationPreview
    expected_calibration_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "clip_name",
                "tracking_object_name",
                "settings",
                "expected_calibration_revision",
            },
        )
        prepared = dict(data)
        rev = string(
            prepared.pop("expected_calibration_revision"),
            "expected_calibration_revision",
            limit=64,
        )
        return cls(CameraCalibrationPreview.parse(prepared), rev)


@dataclass(frozen=True)
class CameraCalibrationRestore:
    expected_calibration_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_calibration_token"})
        return cls(
            string(data["expected_calibration_token"], "expected_calibration_token", limit=64)
        )


class MovieClipCameraCalibrationOperations:
    def __init__(self, bpy):
        self.inspection = MovieClipInspectionOperations(bpy)
        self._owned = {}

    @staticmethod
    def _read(cam):
        out = {}
        for key in CALIBRATION_FIELDS:
            value = getattr(cam, key)
            if key == "principal_point":
                value = [float(part) for part in value]
                if len(value) != 2:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid lens optical center")
            elif key not in {"units", "distortion_model"}:
                value = float(value)
            else:
                value = str(value)
            out[key] = value
        numbers = (
            out["principal_point"]
            + [
                out[key]
                for key in CALIBRATION_FIELDS
                if key not in {"units", "distortion_model", "principal_point"}
            ]
        )
        if (
            not all(isfinite(value) and abs(value) < 1e8 for value in numbers)
            or out["units"] not in {"PIXELS", "MILLIMETERS"}
            or out["distortion_model"] not in {"POLYNOMIAL", "DIVISION", "NUKE", "BROWN"}
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Invalid existing tracking calibration")
        return out

    @staticmethod
    def _write(cam, data):
        cam.units = data["units"]
        cam.distortion_model = data["distortion_model"]
        cam.sensor_width = data["sensor_width"]
        cam.pixel_aspect = data["pixel_aspect"]
        cam.focal_length = data["focal_length"]
        cam.principal_point = tuple(data["principal_point"])
        for key in ("k1", "k2", "k3"):
            setattr(cam, key, data[key])

    def _plan(self, action):
        clip, obj = self.inspection.resolve(action.clip_name, action.tracking_object_name)
        if not obj.is_camera:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Camera tracking object required")
        reconstruction = getattr(clip.tracking, "reconstruction", None)
        if reconstruction is not None and bool(getattr(reconstruction, "is_valid", False)):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Solved camera requires separate review")
        cam = clip.tracking.camera
        if any(state["clip"] is clip for state in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Clip calibration already owned")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Active calibration limit reached")
        before = self._read(cam)
        plan = {
            "clip_name": clip.name,
            "tracking_object_name": obj.name,
            "before": before,
            "after": action.settings,
            "source_only": True,
            "mutation_performed": False,
            "camera_solved": False,
        }
        plan["calibration_revision"] = revision(plan)
        return clip, obj, cam, plan

    def preview(self, request, action):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._plan(action)[3],
        )

    def apply(self, request, action):
        clip, obj, cam, plan = self._plan(action.preview)
        if action.expected_calibration_revision != plan["calibration_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Camera calibration preview is stale")
        before = plan["before"]
        try:
            self._write(cam, plan["after"])
            actual = self._read(cam)
            checked = compare(plan["after"], actual)
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lens calibration readback failed")
        except Exception as exc:
            try:
                self._write(cam, before)
                if not compare(before, self._read(cam)).matched:
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lens rollback mismatch")
            except Exception as rollback:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Lens rollback uncertain"
                ) from rollback
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Calibration failed; prior lens restored") from exc
        token = revision(
            {
                "clip": clip.name,
                "object": obj.name,
                "old": before,
                "new": actual,
                "plan": plan["calibration_revision"],
            }
        )
        self._owned[token] = {
            "clip": clip,
            "tracking_object": obj,
            "camera": cam,
            "before": before,
            "after": actual,
        }
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"calibration_token": token, "source_only": True, "camera_solved": False},
            verification=checked.to_dict(),
        )

    def restore(self, request, action):
        token = action.expected_calibration_token
        owned = self._owned.get(token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used calibration token")
        clip, obj, cam = (
            owned["clip"],
            owned["tracking_object"],
            owned["camera"],
        )
        current_clip, current_obj = self.inspection.resolve(clip.name, obj.name)
        if current_clip is not clip or current_obj is not obj:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Clip or tracking object replaced")
        if clip.tracking.camera is not cam:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Tracking camera replaced")
        reconstruction = getattr(clip.tracking, "reconstruction", None)
        if reconstruction is not None and bool(getattr(reconstruction, "is_valid", False)):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Solved camera changed externally")
        if not compare(owned["after"], self._read(cam)).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "External lens calibration edits")
        self._write(cam, owned["before"])
        checked = compare(owned["before"], self._read(cam))
        if not checked.matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lens restoration mismatch")
        del self._owned[token]
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"calibration_restored": True, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "tracking.calibration_preview",
                SafetyClass.READ_ONLY,
                CameraCalibrationPreview.parse,
                self.preview,
            ),
            Tool(
                "tracking.calibration_apply",
                SafetyClass.MUTATION,
                CameraCalibrationApply.parse,
                self.apply,
            ),
            Tool(
                "tracking.calibration_restore",
                SafetyClass.MUTATION,
                CameraCalibrationRestore.parse,
                self.restore,
            ),
        ]
