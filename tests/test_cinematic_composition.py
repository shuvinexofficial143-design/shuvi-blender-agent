"""Level 8 M2: fixed screen-space camera compositions, safety and recovery."""

from math import cos, isclose, sin
from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_composition import (
    ANCHORS,
    CinematicCompositionOperations,
    CompositionApply,
    CompositionPreview,
)
from shuvi_blender_agent.cinematic_shots import CinematicShotOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("Camera", "CAMERA")
    subject = FakeObject("Subject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("CameraData")
    camera.data.sensor_width = 36
    camera.data.sensor_fit = "HORIZONTAL"
    subject.location = [1.0, 2.0, 3.0]
    subject.dimensions = [2.0, 3.0, 4.0]
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    composition = CinematicCompositionOperations(objects)
    registry = ToolRegistry(
        [*composition.tools(), *CinematicShotOperations(objects).tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, camera, subject, inspector, registry


def target(inspector, obj):
    data = inspector.snapshot(obj)
    return {
        "object_id": data["object_id"],
        "expected_name": data["name"],
        "expected_revision": data["revision"],
    }


def payload(inspector, camera, subject, anchor="UPPER_RIGHT_THIRD", **kwargs):
    result = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "azimuth_degrees": 20,
        "elevation_degrees": 15,
        "margin": 1.25,
        "make_active": True,
        "anchor": anchor,
    }
    result.update(kwargs)
    return result


def preview(registry, parameters):
    result = registry.dispatch(Request("cinema.composition_preview", parameters))
    assert result.status == Status.SUCCEEDED
    return result.data


def apply(registry, parameters, plan):
    return registry.dispatch(
        Request(
            "cinema.composition_apply",
            parameters | {"expected_composition_revision": plan["composition_revision"]},
        )
    )


def screen_center(camera, subject, plan):
    pitch, _, yaw = camera.rotation_euler
    right = [cos(yaw), sin(yaw), 0]
    up = [-sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch)]
    back = [sin(yaw) * sin(pitch), -cos(yaw) * sin(pitch), cos(pitch)]
    delta = [subject.location[i] - camera.location[i] for i in range(3)]
    depth = -sum(delta[i] * back[i] for i in range(3))
    horizontal = sum(delta[i] * right[i] for i in range(3))
    vertical = sum(delta[i] * up[i] for i in range(3))
    return (
        0.5 + horizontal / (2 * depth * plan["horizontal_half_tangent"]),
        0.5 + vertical / (2 * depth * plan["vertical_half_tangent"]),
        depth,
    )


def test_m2_catalog_contains_nine_fixed_composition_anchors():
    assert len(ANCHORS) == 9
    assert ANCHORS["CENTER"] == (0.5, 0.5)
    assert ANCHORS["UPPER_LEFT_THIRD"] == (1 / 3, 2 / 3)


def test_m2_preview_deterministic_without_mutation():
    bpy, camera, subject, inspector, registry = setup()
    before = inspector.snapshot(camera)
    params = payload(inspector, camera, subject)
    first = preview(registry, params)
    second = preview(registry, params)
    assert first == second
    assert first["ready"] is True
    assert first["mutation_performed"] is False
    assert first["composition_anchor"] == "UPPER_RIGHT_THIRD"
    assert first["subject_screen_target"] == {"x": 2 / 3, "y": 2 / 3}
    assert first["composition_revision"] == first["plan_revision"]
    assert len(first["composition_revision"]) == 64
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


@pytest.mark.parametrize("anchor", sorted(ANCHORS))
def test_m2_apply_positions_subject_at_selected_screen_anchor(anchor):
    bpy, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject, anchor=anchor)
    plan = preview(registry, params)
    assert plan["ready"]
    result = apply(registry, params, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"] is True
    assert bpy.context.scene.camera is camera
    assert list(camera.location) == plan["camera_location"]
    assert list(camera.rotation_euler) == plan["camera_rotation_euler"]
    x, y, depth = screen_center(camera, subject, plan)
    assert isclose(x, ANCHORS[anchor][0], abs_tol=1e-9)
    assert isclose(y, ANCHORS[anchor][1], abs_tol=1e-9)
    assert isclose(depth, plan["camera_distance"], abs_tol=1e-9)


def test_m2_center_anchor_matches_m1_position_and_rotation():
    _, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject, anchor="CENTER")
    plan = preview(registry, params)
    base_payload = {key: value for key, value in params.items() if key != "anchor"}
    original = registry.dispatch(Request("cinema.shot_preview", base_payload))
    assert original.status == Status.SUCCEEDED
    assert plan["camera_location"] == original.data["camera_location"]
    assert plan["camera_rotation_euler"] == original.data["camera_rotation_euler"]


def test_m2_corner_thirds_needs_more_distance_to_preserve_subject_margin():
    _, camera, subject, inspector, registry = setup()
    centered = preview(registry, payload(inspector, camera, subject, anchor="CENTER"))
    corner = preview(registry, payload(inspector, camera, subject))
    assert corner["camera_distance"] > centered["camera_distance"]
    assert corner["camera_up_offset"] != 0
    assert corner["camera_right_offset"] != 0


def test_m2_landscape_and_portrait_both_have_defined_compositions():
    bpy, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    landscape = preview(registry, params)
    bpy.context.scene.render.resolution_x = 1080
    bpy.context.scene.render.resolution_y = 1920
    portrait = preview(registry, params)
    assert portrait["ready"] is True
    assert portrait["camera_distance"] < landscape["camera_distance"]
    assert portrait["composition_revision"] != landscape["composition_revision"]


def test_m2_stale_render_settings_or_anchor_rejected_without_moving():
    bpy, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    bpy.context.scene.render.resolution_x = 1440
    failure = apply(registry, params, plan)
    assert failure.status == Status.FAILED
    assert failure.error.code == ErrorCode.STALE_STATE
    bpy.context.scene.render.resolution_x = 1920
    changed_anchor = params | {"anchor": "UPPER_LEFT_THIRD"}
    failure = apply(registry, changed_anchor, plan)
    assert failure.error.code == ErrorCode.STALE_STATE
    assert camera.location == [0.0, 0.0, 0.0]


def test_m2_stale_subject_revision_rejected():
    _, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    subject.location = [2.0, 2.0, 3.0]
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.STALE_STATE


@pytest.mark.parametrize("blocker", ["parent", "shared", "action", "lens_shift", "clip", "lock"])
def test_m2_inherits_m1_mutation_guards_and_added_lens_shift_guard(blocker):
    _, camera, subject, inspector, registry = setup()
    if blocker == "parent":
        camera.parent = subject
    elif blocker == "shared":
        camera.data.users = 2
    elif blocker == "action":
        camera.animation_data = NS(action=None, action_slot=None, drivers=[], nla_tracks=[])
    elif blocker == "lens_shift":
        camera.data.shift_x = 0.1
    elif blocker == "clip":
        camera.data.clip_end = 2
    elif blocker == "lock":
        camera.lock_location = [True, False, False]
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    assert plan["ready"] is False
    assert plan["blockers"]
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert camera.location == [0.0, 0.0, 0.0]


@pytest.mark.parametrize("anchor", ["FREEFORM", "x", "", "RIGHT_THIRD; arbitrary bpy"])
def test_m2_rejects_unapproved_composition_strings(anchor):
    _, camera, subject, inspector, _ = setup()
    with pytest.raises(AgentError):
        CompositionPreview.parse(payload(inspector, camera, subject, anchor=anchor))


def test_m2_rejects_missing_or_extra_input_fields():
    _, camera, subject, inspector, _ = setup()
    params = payload(inspector, camera, subject)
    with pytest.raises(AgentError):
        CompositionApply.parse(params)
    with pytest.raises(AgentError):
        CompositionPreview.parse(params | {"python": "import bpy"})


def test_m2_verification_mismatch_restores_original_camera_pose():
    bpy, camera, subject, inspector, registry = setup()
    camera.location = [3.0, 4.0, 5.0]
    camera.rotation_euler = [0.1, 0.2, 0.3]
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            camera.location = [999, 999, 999]

    bpy.context.view_layer.update = corrupt_once
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m2_interrupted_mutation_recovers_original_pose():
    bpy, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    calls = {"n": 0}

    def interrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Injected camera update interruption")

    bpy.context.view_layer.update = interrupt_once
    result = apply(registry, params, plan)
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert result.data["outcome"] == "unknown"
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m2_without_activation_retains_previous_scene_camera():
    bpy, camera, subject, inspector, registry = setup()
    params = payload(inspector, camera, subject, make_active=False)
    plan = preview(registry, params)
    assert apply(registry, params, plan).status == Status.VERIFIED
    assert bpy.context.scene.camera is None


def test_m2_factory_registers_host_contracts_at_229():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS == 243
    names = {item["name"] for item in registry.catalog()}
    assert {"cinema.composition_preview", "cinema.composition_apply"} <= names
