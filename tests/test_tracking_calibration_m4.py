"""M4 native MovieTrackingCamera intrinsics: preview/apply/restore safety."""

from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.tracking_calibration import (
    CameraCalibrationPreview,
    MovieClipCameraCalibrationOperations,
)


class Named(list):
    def get(self, name):
        return next((x for x in self if x.name == name), None)


class Camera(NS):
    fail_once = False

    def __setattr__(self, name, value):
        if name == "k2" and self.fail_once:
            self.fail_once = False
            raise RuntimeError("Injected lens property failure")
        super().__setattr__(name, value)


def setup(allow=True):
    bpy = fake_bpy()
    cam = Camera(
        units="PIXELS",
        distortion_model="POLYNOMIAL",
        sensor_width=36.0,
        focal_length=800.0,
        pixel_aspect=1.0,
        principal_point=[0.0, 0.0],
        k1=0.0,
        k2=0.0,
        k3=0.0,
    )
    tracked = NS(name="Camera", is_camera=True, tracks=Named())
    clip = NS(
        name="Footage",
        library=None,
        is_editable=True,
        size=[1920, 1080],
        frame_duration=60,
        tracking=NS(objects=Named([tracked]), camera=cam, reconstruction=NS(is_valid=False)),
    )
    bpy.data.movieclips = Named([clip])
    reg = ToolRegistry(
        MovieClipCameraCalibrationOperations(bpy).tools(),
        SafetyPolicy(allow_mutations=allow),
    )
    args = {
        "clip_name": "Footage",
        "tracking_object_name": "Camera",
        "settings": {
            "focal_length": 35.0,
            "sensor_width": 36.0,
            "pixel_aspect": 1.0,
            "principal_point": [0.02, -0.03],
            "k1": 0.012,
            "k2": -0.005,
            "k3": 0.0004,
        },
    }
    return bpy, clip, cam, reg, args


def preview(reg, args):
    return reg.dispatch(Request("tracking.calibration_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "tracking.calibration_apply",
            args | {"expected_calibration_revision": plan.data["calibration_revision"]},
        )
    )


def restore(reg, token):
    return reg.dispatch(
        Request("tracking.calibration_restore", {"expected_calibration_token": token})
    )


def test_m4_actual_lens_rna_write_readback_and_restore():
    _, _, cam, reg, args = setup()
    before = vars(cam).copy()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    assert cam.units == "MILLIMETERS"
    assert cam.distortion_model == "POLYNOMIAL"
    assert cam.focal_length == 35.0
    assert cam.sensor_width == 36.0
    assert cam.principal_point == [0.02, -0.03] or cam.principal_point == (0.02, -0.03)
    assert cam.k1 == 0.012 and cam.k2 == -0.005
    result = restore(reg, done.data["calibration_token"])
    assert result.status == Status.VERIFIED, result.error
    assert cam.units == before["units"] and cam.focal_length == before["focal_length"]
    assert list(cam.principal_point) == before["principal_point"]
    assert restore(reg, done.data["calibration_token"]).error.code == ErrorCode.STALE_STATE


def test_m4_stale_preview_rejected_without_lens_mutation():
    _, _, cam, reg, args = setup()
    plan = preview(reg, args)
    cam.focal_length = 910
    out = apply(reg, args, plan)
    assert out.error.code == ErrorCode.STALE_STATE
    assert cam.focal_length == 910
    assert cam.units == "PIXELS"


def test_m4_external_edit_blocks_owned_restore():
    _, _, cam, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    cam.k1 = 0.1
    denied = restore(reg, done.data["calibration_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert cam.units == "MILLIMETERS"


def test_m4_write_failure_restores_original_camera():
    _, _, cam, reg, args = setup()
    before = vars(cam).copy()
    plan = preview(reg, args)
    cam.fail_once = True
    denied = apply(reg, args, plan)
    assert denied.error.code == ErrorCode.EXECUTION_ERROR
    assert cam.units == before["units"]
    assert cam.focal_length == before["focal_length"]
    assert cam.k1 == before["k1"]


def test_m4_rejects_solved_camera_and_linked_clips():
    _, clip, cam, reg, args = setup()
    clip.tracking.reconstruction.is_valid = True
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    clip.tracking.reconstruction.is_valid = False
    clip.library = NS()
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert cam.units == "PIXELS"


def test_m4_rejects_object_tracking_with_camera_intrinsics():
    _, clip, _, reg, args = setup()
    clip.tracking.objects[0].is_camera = False
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED


def test_m4_competing_changes_on_same_clip_blocked():
    _, _, _, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED


def test_m4_registry_and_permissions():
    bpy, _, cam, _, args = setup()
    catalog = create_registry(bpy).catalog()
    names = {item["name"] for item in catalog}
    assert len(names) == 299
    assert {
        "tracking.calibration_preview",
        "tracking.calibration_apply",
        "tracking.calibration_restore",
    } <= names
    locked = ToolRegistry(
        MovieClipCameraCalibrationOperations(bpy).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert cam.units == "PIXELS"


@pytest.mark.parametrize(
    "key,value",
    [
        ("focal_length", 0),
        ("sensor_width", 0),
        ("pixel_aspect", 3),
        ("k1", 0.6),
        ("principal_point", [1.2, 0]),
        ("k2", -0.6),
    ],
)
def test_m4_rejects_unbounded_intrinsics(key, value):
    _, _, _, _, args = setup()
    args["settings"][key] = value
    with pytest.raises(AgentError):
        CameraCalibrationPreview.parse(args)


def test_m4_no_code_execution_or_external_file_loading():
    _, _, cam, reg, args = setup()
    denied = preview(reg, args | {"python": "import bpy"})
    assert denied.error.code == ErrorCode.INVALID_REQUEST
    assert cam.units == "PIXELS"
