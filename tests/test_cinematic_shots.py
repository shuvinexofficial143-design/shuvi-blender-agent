"""Level 8 M1: source/fake-bpy tests for usable cinematic camera framing."""

from math import cos, isclose, sin, sqrt

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_shots import CinematicShotOperations, ShotApply, ShotPreview
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("CinematicCamera", "CAMERA")
    subject = FakeObject("Subject", "MESH")
    bpy = fake_bpy([camera, subject])
    data = bpy.data.cameras.new("CinematicData")
    data.sensor_width = 36.0
    data.sensor_fit = "HORIZONTAL"
    camera.data = data
    subject.location = [2.0, 3.0, 1.0]
    subject.dimensions = [2.0, 3.0, 4.0]
    inspector = BpyInspector(bpy)
    shots = CinematicShotOperations(ObjectOperations(inspector))
    registry = ToolRegistry(shots.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, registry, camera, subject


def target(inspector, obj):
    state = inspector.snapshot(obj)
    return {
        "object_id": state["object_id"],
        "expected_name": state["name"],
        "expected_revision": state["revision"],
    }


def payload(inspector, camera, subject, **changes):
    data = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "azimuth_degrees": 0,
        "elevation_degrees": 15,
        "margin": 1.2,
        "make_active": True,
    }
    data.update(changes)
    return data


def preview(registry, data):
    result = registry.dispatch(Request("cinema.shot_preview", data))
    assert result.status == Status.SUCCEEDED
    return result.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request("cinema.shot_frame", data | {"expected_plan_revision": plan["plan_revision"]})
    )


def test_m1_preview_is_deterministic_and_nonmutating():
    bpy, inspector, registry, camera, subject = setup()
    before = inspector.snapshot(camera)
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    same = preview(registry, params)
    assert plan["ready"] is True
    assert plan["blockers"] == []
    assert plan["plan_revision"] == same["plan_revision"]
    assert plan["mutation_performed"] is False
    assert plan["subject_center"] == [2.0, 3.0, 1.0]
    assert plan["camera_distance"] > plan["subject_enclosing_radius"]
    assert plan["vertical_fov_degrees"] < plan["horizontal_fov_degrees"]
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m1_frame_moves_real_camera_and_points_its_local_negative_z_to_subject():
    bpy, inspector, registry, camera, subject = setup()
    params = payload(inspector, camera, subject, azimuth_degrees=35, elevation_degrees=20)
    plan = preview(registry, params)
    result = apply(registry, params, plan)
    assert result.status == Status.VERIFIED
    assert bpy.context.scene.camera is camera
    assert result.verification["matched"] is True
    assert list(camera.location) == plan["camera_location"]
    assert list(camera.rotation_euler) == plan["camera_rotation_euler"]
    assert subject.location == [2.0, 3.0, 1.0]
    pitch, _, yaw = camera.rotation_euler
    look = [
        -sin(yaw) * sin(pitch),
        cos(yaw) * sin(pitch),
        -cos(pitch),
    ]
    direction = [
        (subject.location[i] - camera.location[i]) / plan["camera_distance"] for i in range(3)
    ]
    assert all(isclose(look[i], direction[i], abs_tol=1e-9) for i in range(3))
    assert isclose(sqrt(sum(item * item for item in look)), 1, abs_tol=1e-9)


def test_m1_landscape_and_portrait_framing_use_limiting_fov():
    bpy, inspector, registry, camera, subject = setup()
    landscape = preview(registry, payload(inspector, camera, subject))
    bpy.context.scene.render.resolution_x = 1080
    bpy.context.scene.render.resolution_y = 1920
    portrait = preview(registry, payload(inspector, camera, subject))
    assert portrait["camera_distance"] > 0
    assert portrait["camera_distance"] < landscape["camera_distance"]
    assert portrait["vertical_fov_degrees"] > landscape["vertical_fov_degrees"]


def test_m1_stale_plan_after_render_aspect_change():
    bpy, inspector, registry, camera, subject = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    bpy.context.scene.render.resolution_x = 1280
    changed = apply(registry, params, plan)
    assert changed.status == Status.FAILED
    assert changed.error.code == ErrorCode.STALE_STATE
    assert camera.location == [0.0, 0.0, 0.0]


def test_m1_stale_subject_or_camera_target_fails_before_mutation():
    _, inspector, registry, camera, subject = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    subject.location = [5.0, 5.0, 5.0]
    rejected = apply(registry, params, plan)
    assert rejected.status == Status.FAILED
    assert rejected.error.code == ErrorCode.STALE_STATE
    assert camera.location == [0.0, 0.0, 0.0]


@pytest.mark.parametrize(
    "field",
    ["shared", "parent", "constraints", "animated", "wrong_mode", "locked", "scale", "data_link"],
)
def test_m1_safety_blockers_prevent_mutation(field):
    bpy, inspector, registry, camera, subject = setup()
    if field == "shared":
        camera.data.users = 2
    elif field == "parent":
        camera.parent = subject
    elif field == "constraints":
        camera.constraints.append(type("Constraint", (), {"type": "TRACK_TO", "name": "Follow"})())
    elif field == "animated":
        camera.animation_data = type(
            "Animation", (), {"action": None, "drivers": [], "nla_tracks": []}
        )()
    elif field == "wrong_mode":
        bpy.context.mode = "EDIT_MESH"
    elif field == "locked":
        camera.lock_rotation = [True, False, False]
    elif field == "scale":
        camera.scale = [2.0, 1.0, 1.0]
    else:
        camera.data.library = "externally-linked"

    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    assert plan["ready"] is False
    assert plan["blockers"]
    attempted = apply(registry, params, plan)
    assert attempted.status == Status.FAILED
    assert attempted.error.code == ErrorCode.SAFETY_DENIED


def test_m1_clip_end_out_of_range_blocks_shot():
    _, inspector, registry, camera, subject = setup()
    camera.data.clip_end = 3.0
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    assert "SUBJECT_OUTSIDE_CAMERA_CLIP" in plan["blockers"]
    assert apply(registry, params, plan).error.code == ErrorCode.SAFETY_DENIED


def test_m1_unsupported_auto_portrait_sensor_fit_blocked():
    bpy, inspector, registry, camera, subject = setup()
    camera.data.sensor_fit = "AUTO"
    bpy.context.scene.render.resolution_x = 1080
    bpy.context.scene.render.resolution_y = 1920
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    assert "HORIZONTAL_SENSOR_FIT_REQUIRED" in plan["blockers"]


def test_m1_validation_refuses_malicious_or_out_of_bound_angles():
    _, inspector, _, camera, subject = setup()
    params = payload(inspector, camera, subject)
    for field, value in (
        ("margin", 0.5),
        ("azimuth_degrees", 999),
        ("elevation_degrees", -90),
        ("make_active", "true"),
    ):
        bad = params | {field: value}
        with pytest.raises(AgentError):
            ShotPreview.parse(bad)
    with pytest.raises(AgentError):
        ShotApply.parse(params)


def test_m1_corrupted_pose_readback_restores_full_original_pose():
    bpy, inspector, registry, camera, subject = setup()
    camera.location = [4.0, 5.0, 6.0]
    camera.rotation_euler = [0.1, 0.2, 0.3]
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    counter = {"n": 0}

    def alter_once():
        counter["n"] += 1
        if counter["n"] == 1:
            camera.location = [999.0, 0.0, 0.0]

    bpy.context.view_layer.update = alter_once
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m1_interrupted_pose_write_restores_before_and_marks_unknown():
    bpy, inspector, registry, camera, subject = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    counter = {"n": 0}

    def interrupt_once():
        counter["n"] += 1
        if counter["n"] == 1:
            raise RuntimeError("Synthetic view update interruption")

    bpy.context.view_layer.update = interrupt_once
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert result.data["outcome"] == "unknown"
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m1_frame_without_activation_does_not_replace_scene_camera():
    bpy, inspector, registry, camera, subject = setup()
    params = payload(inspector, camera, subject, make_active=False)
    plan = preview(registry, params)
    result = apply(registry, params, plan)
    assert result.status == Status.VERIFIED
    assert bpy.context.scene.camera is None


def test_m1_factory_contracts_and_bounded_registry_count():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 305
    assert MAX_REGISTERED_TOOLS == 305
    names = {item["name"] for item in registry.catalog()}
    assert {"cinema.shot_preview", "cinema.shot_frame"} <= names
