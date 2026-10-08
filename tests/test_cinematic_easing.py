"""Level 8 M5 source tests: actual BEZIER handles, temporal easing and safe rollback."""

from math import isclose

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.cinematic_easing import EasingApply, EasingPreview, CameraEasingOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    camera = FakeObject("EasedCamera", "CAMERA")
    subject = FakeObject("Subject", "MESH")
    bpy = fake_bpy([camera, subject])
    camera.data = bpy.data.cameras.new("EasedCameraData")
    camera.data.sensor_width = 36.0
    camera.data.sensor_fit = "HORIZONTAL"
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 2.0, 4.0]
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(
        CameraEasingOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, camera, subject, inspector, registry


def target(inspector, obj):
    state = inspector.snapshot(obj)
    return {
        "object_id": state["object_id"],
        "expected_name": state["name"],
        "expected_revision": state["revision"],
    }


def args(inspector, camera, subject, **overrides):
    values = {
        "camera": target(inspector, camera),
        "subject": target(inspector, subject),
        "start_frame": 10,
        "end_frame": 50,
        "azimuth_degrees": 15,
        "elevation_degrees": 20,
        "margin": 1.25,
        "control_a": [0.15, 0.2],
        "control_b": [-0.2, 0.1],
        "end_offset": [-0.15, -0.1],
        "make_active": True,
        "style": "EASE_IN_OUT",
        "strength": 1.0,
    }
    values.update(overrides)
    return values


def preview(registry, params):
    response = registry.dispatch(Request("cinema.easing_preview", params))
    assert response.status == Status.SUCCEEDED, response.error
    return response.data


def apply(registry, params, plan):
    return registry.dispatch(
        Request(
            "cinema.easing_apply",
            params | {"expected_easing_revision": plan["easing_revision"]},
        )
    )


@pytest.mark.parametrize("style", ["EASE_IN", "EASE_OUT", "EASE_IN_OUT"])
def test_m5_all_three_easing_styles_create_verified_bezier_handles(style):
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject, style=style)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    assert plan["ready"] is True
    assert plan["interpolation"] == "BEZIER"
    assert plan["handle_type"] == "FREE"
    assert plan["mutation_performed"] is False
    assert len(plan["key_poses"]) == 5
    assert plan == preview(registry, params)
    assert inspector.snapshot(camera)["revision"] == before["revision"]
    assert camera.animation_data is None

    outcome = apply(registry, params, plan)
    assert outcome.status == Status.VERIFIED, outcome.error
    assert outcome.verification["matched"] is True
    assert outcome.data["keyframe_count"] == 30
    assert outcome.data["channel_count"] == 6
    assert bpy.context.scene.camera is camera
    assert bpy.context.scene.frame_current == 1
    assert camera.animation_data.action.users == 1
    after = inspector.snapshot(camera)
    assert after["animation"]["action"] is not None
    assert len(after["animation"]["channels"]) == 6
    for channel in after["animation"]["channels"]:
        assert len(channel["points"]) == 5
        for index, point in enumerate(channel["points"]):
            expected = plan["key_poses"][index]["key_handles"][
                channel["data_path"]
            ][channel["index"]]
            assert point["interpolation"] == "BEZIER"
            assert point["handle_left_type"] == "FREE"
            assert point["handle_right_type"] == "FREE"
            assert point["handle_left"] == expected["left"]
            assert point["handle_right"] == expected["right"]


def test_m5_smoothstep_speed_reaches_zero_at_both_ends():
    _, camera, subject, inspector, registry = setup()
    plan = preview(registry, args(inspector, camera, subject))
    speeds = [pose["normalized_speed"] for pose in plan["key_poses"]]
    assert speeds[0] == speeds[-1] == 0
    assert isclose(speeds[2], 1.5)
    for path in ("location", "rotation_euler"):
        for key in (plan["key_poses"][0], plan["key_poses"][-1]):
            for axis in range(3):
                handles = key["key_handles"][path][axis]
                assert handles["left"][1] == key[path][axis]
                assert handles["right"][1] == key[path][axis]


def test_m5_strength_blends_linear_and_eased_profile():
    _, camera, subject, inspector, registry = setup()
    full = preview(registry, args(inspector, camera, subject, strength=1.0))
    partial = preview(registry, args(inspector, camera, subject, strength=0.25))
    assert full["easing_revision"] != partial["easing_revision"]
    assert full["key_poses"][0]["normalized_speed"] == 0
    assert partial["key_poses"][0]["normalized_speed"] == 0.75
    assert isclose(full["key_poses"][2]["path_parameter"], 0.5)
    assert isclose(partial["key_poses"][2]["path_parameter"], 0.5)
    assert full["key_poses"][1]["path_parameter"] < partial["key_poses"][1]["path_parameter"]


def test_m5_ease_in_starts_slow_and_ease_out_ends_slow():
    _, camera, subject, inspector, registry = setup()
    incoming = preview(registry, args(inspector, camera, subject, style="EASE_IN"))
    outgoing = preview(registry, args(inspector, camera, subject, style="EASE_OUT"))
    assert incoming["key_poses"][0]["normalized_speed"] == 0
    assert outgoing["key_poses"][-1]["normalized_speed"] == 0
    assert incoming["key_poses"][1]["path_parameter"] < 0.25
    assert outgoing["key_poses"][1]["path_parameter"] > 0.25
    assert incoming["key_poses"][-1]["normalized_speed"] == 2
    assert outgoing["key_poses"][0]["normalized_speed"] == 2


def test_m5_bounded_handle_x_values_preserve_point_order():
    _, camera, subject, inspector, registry = setup()
    plan = preview(registry, args(inspector, camera, subject, end_frame=18))
    frames = [pose["frame"] for pose in plan["key_poses"]]
    assert frames == [10, 12, 14, 16, 18]
    for path in ("location", "rotation_euler"):
        for index, pose in enumerate(plan["key_poses"]):
            for axis in range(3):
                handles = pose["key_handles"][path][axis]
                left_x = handles["left"][0]
                right_x = handles["right"][0]
                assert (frames[index - 1] if index else frames[index]) <= left_x
                assert left_x <= frames[index] <= right_x
                assert right_x <= (frames[index + 1] if index < 4 else frames[index])


def test_m5_stale_lens_render_and_style_reject_before_mutation():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    assert apply(registry, params | {"style": "EASE_IN"}, plan).error.code == ErrorCode.STALE_STATE
    assert apply(registry, params | {"strength": 0.5}, plan).error.code == ErrorCode.STALE_STATE
    camera.data.lens = 65
    assert apply(registry, params, plan).error.code == ErrorCode.STALE_STATE
    camera.data.lens = 50
    bpy.context.scene.render.resolution_x = 1080
    assert apply(registry, params, plan).error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


def test_m5_stale_subject_revision_rejects_changes():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    subject.location = [5, 5, 5]
    assert apply(registry, params, plan).error.code == ErrorCode.STALE_STATE
    assert camera.animation_data is None


@pytest.mark.parametrize(
    "blocker", ["occupied", "shared", "parent", "lens_shift", "clip", "locked"]
)
def test_m5_reuses_rail_camera_safety_rules(blocker):
    _, camera, subject, inspector, registry = setup()
    if blocker == "occupied":
        camera.animation_data = type(
            "ExistingAnimation", (), {"action": None, "drivers": [], "nla_tracks": []}
        )()
    elif blocker == "shared":
        camera.data.users = 2
    elif blocker == "parent":
        camera.parent = subject
    elif blocker == "lens_shift":
        camera.data.shift_x = 0.1
    elif blocker == "clip":
        camera.data.clip_end = 2
    else:
        camera.lock_rotation = [True, False, False]
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    assert not plan["ready"]
    assert apply(registry, params, plan).error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize("value", ["LINEAR", "BEZIER", "SINE", "EASE_BOTH", ""])
def test_m5_unsupported_style_refused_by_contract(value):
    _, camera, subject, inspector, _ = setup()
    with pytest.raises(AgentError):
        EasingPreview.parse(args(inspector, camera, subject, style=value))


@pytest.mark.parametrize("value", [-1, 0, 0.1, 1.1, True, "0.5"])
def test_m5_invalid_strength_refused_by_contract(value):
    _, camera, subject, inspector, _ = setup()
    with pytest.raises(AgentError):
        EasingPreview.parse(args(inspector, camera, subject, strength=value))


def test_m5_payload_requires_revision_and_bans_unknown_fields():
    _, camera, subject, inspector, _ = setup()
    params = args(inspector, camera, subject)
    with pytest.raises(AgentError):
        EasingApply.parse(params)
    with pytest.raises(AgentError):
        EasingPreview.parse(params | {"script": "import bpy"})


def test_m5_failed_handle_readback_restores_clean_original_camera():
    bpy, camera, subject, inspector, registry = setup()
    camera.location = [4.0, 5.0, 6.0]
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    original_snapshot = inspector.snapshot
    calls = {"count": 0}

    def falsify_handle(obj):
        state = original_snapshot(obj)
        if obj is camera and obj.animation_data is not None:
            calls["count"] += 1
            if calls["count"] == 1:
                state["animation"]["channels"][0]["points"][0]["handle_right"] = [999, 999]
        return state

    inspector.snapshot = falsify_handle
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert camera.animation_data is None
    assert original_snapshot(camera)["revision"] == before["revision"]
    assert bpy.context.scene.camera is None


def test_m5_handle_write_interruption_removes_new_action():
    _, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject)
    plan = preview(registry, params)
    before = inspector.snapshot(camera)
    original_insert = camera.keyframe_insert
    count = {"n": 0}

    def interrupted_insert(**kw):
        count["n"] += 1
        if count["n"] == 7:
            raise RuntimeError("Synthetic keyframe authoring interruption")
        return original_insert(**kw)

    camera.keyframe_insert = interrupted_insert
    result = apply(registry, params, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert camera.animation_data is None
    assert inspector.snapshot(camera)["revision"] == before["revision"]


def test_m5_without_activation_retains_existing_scene_camera():
    bpy, camera, subject, inspector, registry = setup()
    params = args(inspector, camera, subject, make_active=False)
    plan = preview(registry, params)
    assert apply(registry, params, plan).status == Status.VERIFIED
    assert bpy.context.scene.camera is None


def test_m5_factory_tool_and_host_allowlist_count():
    factory = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(factory.catalog()) == MAX_REGISTERED_TOOLS == 235
    assert {"cinema.easing_preview", "cinema.easing_apply"} <= {
        row["name"] for row in factory.catalog()
    }
