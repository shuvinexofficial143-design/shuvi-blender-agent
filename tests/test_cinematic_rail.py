"""M4 bounded cubic Bezier camera rail: five poses and verified keyframe authoring."""

from math import cos, isclose, sin
from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_rail import CameraRailOperations, RailApply, RailPreview
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("RailCamera", "CAMERA")
    subject = FakeObject("RailSubject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("RailCameraData")
    camera.data.sensor_width = 36.0
    camera.data.sensor_fit = "HORIZONTAL"
    subject.location = [3.0, 2.0, 5.0]
    subject.dimensions = [2.0, 2.0, 4.0]
    inspector = BpyInspector(bpy)
    rail = CameraRailOperations(ObjectOperations(inspector))
    registry = ToolRegistry(rail.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, camera, subject, inspector, registry


def target(inspector, obj):
    state = inspector.snapshot(obj)
    return {
        "object_id": state["object_id"],
        "expected_name": state["name"],
        "expected_revision": state["revision"],
    }


def args(inspector, camera, subject, **changes):
    data = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "start_frame": 10,
        "end_frame": 50,
        "azimuth_degrees": 15,
        "elevation_degrees": 20,
        "margin": 1.25,
        "control_a": [0.1, 0.2],
        "control_b": [-0.2, 0.1],
        "end_offset": [-0.15, -0.1],
        "make_active": True,
    }
    data.update(changes)
    return data


def preview(registry, params):
    response = registry.dispatch(Request("cinema.rail_preview", params))
    assert response.status == Status.SUCCEEDED, response.error
    return response.data


def apply(registry, params, plan):
    return registry.dispatch(
        Request(
            "cinema.rail_apply",
            params | {"expected_rail_revision": plan["rail_revision"]},
        )
    )


def screen_projection(camera, subject, plan, pose):
    pitch, _, yaw = pose["rotation_euler"]
    right = [cos(yaw), sin(yaw), 0.0]
    up = [-sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch)]
    back = [sin(yaw) * sin(pitch), -cos(yaw) * sin(pitch), cos(pitch)]
    delta = [subject.location[i] - pose["location"][i] for i in range(3)]
    depth = -sum(delta[i] * back[i] for i in range(3))
    hx = camera.data.sensor_width / (2 * camera.data.lens)
    hy = hx / plan["render_aspect"]
    return (
        0.5 + sum(delta[i] * right[i] for i in range(3)) / (2 * depth * hx),
        0.5 + sum(delta[i] * up[i] for i in range(3)) / (2 * depth * hy),
        depth,
    )


def test_m4_preview_has_five_distinct_nonmutating_bezier_poses():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    before = inspector.snapshot(camera)
    plan = preview(registry, params)
    assert plan == preview(registry, params)
    assert plan["ready"] is True
    assert plan["curve"] == "CUBIC_BEZIER_CAMERA_IMAGE_PLANE"
    assert plan["sample_parameters"] == [0, 0.25, 0.5, 0.75, 1]
    assert [pose["frame"] for pose in plan["key_poses"]] == [10, 20, 30, 40, 50]
    assert plan["keyframe_count"] == 30
    assert plan["channel_count"] == 6
    assert len(plan["rail_revision"]) == 64
    assert plan["mutation_performed"] is False
    assert camera.animation_data is None
    assert bpy.context.scene.camera is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m4_five_poses_project_subject_to_bezier_screen_targets():
    _, camera, subject, inspector, registry = setup()
    plan = preview(registry, args(inspector, camera, subject))
    # Camera is fixed-orientation: camera movement induces opposite image movement.
    assert plan["key_poses"][0]["subject_screen_prediction"] == {"x": 0.5, "y": 0.5}
    for pose in plan["key_poses"]:
        x, y, depth = screen_projection(camera, subject, plan, pose)
        predicted = pose["subject_screen_prediction"]
        assert isclose(x, predicted["x"], abs_tol=1e-10)
        assert isclose(y, predicted["y"], abs_tol=1e-10)
        assert isclose(depth, pose["distance"], abs_tol=1e-10)
        assert 0.25 <= x <= 0.75
        assert 0.25 <= y <= 0.75


def test_m4_creates_thirty_actual_keyframes_on_six_transform_curves():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    result = apply(registry, params, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.data["keyframe_count"] == 30
    assert result.data["channel_count"] == 6
    assert result.data["keyframe_frames"] == [10, 20, 30, 40, 50]
    assert camera.animation_data.action.users == 1
    assert bpy.context.scene.camera is camera
    assert bpy.context.scene.frame_current == 1
    assert list(camera.location) == plan["key_poses"][-1]["location"]
    assert list(camera.rotation_euler) == plan["key_poses"][-1]["rotation_euler"]
    curves = camera.animation_data.action.fcurves
    assert len(curves) == 6
    assert {(c.data_path, c.array_index) for c in curves} == {
        (path, i) for path in ("location", "rotation_euler") for i in range(3)
    }
    for curve in curves:
        assert [p.co[0] for p in curve.keyframe_points] == [10, 20, 30, 40, 50]
        assert all(p.interpolation == "LINEAR" for p in curve.keyframe_points)


def test_m4_short_duration_keeps_five_unique_integer_frames():
    _, camera, subject, inspector, registry = setup()
    plan = preview(registry, args(inspector, camera, subject, end_frame=18))
    assert [pose["frame"] for pose in plan["key_poses"]] == [10, 12, 14, 16, 18]


def test_m4_safe_envelope_accounts_for_control_extremes():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    base = preview(registry, params)
    extremes = preview(
        registry,
        params
        | {
            "control_a": [0.25, 0.25],
            "control_b": [-0.25, -0.25],
            "end_offset": [0.25, -0.25],
        },
    )
    assert extremes["key_poses"][0]["distance"] >= base["key_poses"][0]["distance"]
    assert extremes["ready"] is True


def test_m4_change_to_render_settings_invalidates_revision_without_mutation():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    bpy.context.scene.render.resolution_x = 1080
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


def test_m4_changes_to_control_point_or_subject_invalidate_revision():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    bad = apply(registry, params | {"end_offset": [0.1, 0.1]}, plan)
    assert bad.error.code == ErrorCode.STALE_STATE
    subject.location = [4, 2, 5]
    bad = apply(registry, params, plan)
    assert bad.error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


@pytest.mark.parametrize(
    "blocker",
    [
        "occupied",
        "shared",
        "parent",
        "constraint",
        "linked",
        "locked",
        "lens_shift",
        "clip",
    ],
)
def test_m4_does_not_author_rail_on_unsafe_camera(blocker):
    _, camera, subject, inspector, registry = setup()
    if blocker == "occupied":
        camera.animation_data = NS(action=None, action_slot=None, drivers=[], nla_tracks=[])
    elif blocker == "shared":
        camera.data.users = 2
    elif blocker == "parent":
        camera.parent = subject
    elif blocker == "constraint":
        camera.constraints.append(NS(name="Follow", type="TRACK_TO"))
    elif blocker == "linked":
        camera.library = "EXTERNAL"
    elif blocker == "locked":
        camera.lock_rotation = [True, False, False]
    elif blocker == "lens_shift":
        camera.data.shift_y = 0.2
    else:
        camera.data.clip_end = 2
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    assert not plan["ready"]
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize(
    "change",
    [
        {"control_a": [0.35, 0]},
        {"control_a": [1, 2, 3]},
        {"control_a": "0,0"},
        {"control_b": [False, 0]},
        {"control_b": [-0.5, 0]},
        {"end_offset": [0, 0], "control_a": [0, 0], "control_b": [0, 0]},
        {"start_frame": 0},
        {"end_frame": 17},
        {"end_frame": 900},
        {"make_active": "true"},
    ],
)
def test_m4_strict_validation_fails_closed(change):
    _, camera, subject, inspector, _ = setup()
    with pytest.raises(AgentError):
        RailPreview.parse(args(inspector, camera, subject, **change))


def test_m4_rejects_unknown_fields_and_missing_revision():
    _, camera, subject, inspector, _ = setup()
    params = args(inspector, camera, subject)
    with pytest.raises(AgentError):
        RailPreview.parse(params | {"python": "import bpy"})
    with pytest.raises(AgentError):
        RailApply.parse(params)


def test_m4_existing_action_not_adopted_even_after_success():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    assert apply(registry, params, plan).status == Status.VERIFIED
    second = args(inspector, camera, subject)
    blocked = preview(registry, second)
    assert "EXISTING_CAMERA_ACTION_CANNOT_BE_ADOPTED" in blocked["blockers"]
    assert apply(registry, second, blocked).error.code == ErrorCode.SAFETY_DENIED


def test_m4_partial_keyframe_failure_removes_created_action_and_restores():
    _, camera, subject, inspector, registry = setup()
    camera.location = [2, 4, 6]
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    insert = camera.keyframe_insert
    calls = {"n": 0}

    def interrupt(**kw):
        calls["n"] += 1
        if calls["n"] == 6:
            raise RuntimeError("injected camera motion failure")
        return insert(**kw)

    camera.keyframe_insert = interrupt
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m4_corrupt_readback_forces_verified_rollback():
    bpy, camera, subject, inspector, registry = setup()
    camera.location = [2, 4, 6]
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def corrupt():
        calls["n"] += 1
        if calls["n"] == 1:
            camera.location = [123, 1, 1]

    bpy.context.view_layer.update = corrupt
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["recovery_verified"] is True
    assert result.data["rolled_back"] is True
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m4_without_activation_does_not_change_scene_camera():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject, make_active=False)
    plan = preview(registry, params)
    assert apply(registry, params, plan).status == Status.VERIFIED
    assert bpy.context.scene.camera is None


def test_m4_factory_and_host_contracts_register_233_tools():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS == 253
    assert {"cinema.rail_preview", "cinema.rail_apply"} <= {
        row["name"] for row in registry.catalog()
    }
