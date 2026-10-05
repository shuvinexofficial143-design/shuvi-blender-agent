import pytest
from fake_bpy import fake_bpy
from test_operations import target

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry


def setup():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    return bpy, registry


def snapshot(registry, index=0):
    return registry.dispatch(Request("objects.list")).data["items"][index]


def revision(registry):
    return registry.dispatch(Request("scene.inspect")).data["revision"]


def test_rename_identity_stale_target_and_collision():
    bpy, registry = setup()
    before = snapshot(registry)
    collision = registry.dispatch(
        Request("object.rename", {"target": target(before), "name": "Sphere"})
    )
    assert collision.error.code == ErrorCode.AMBIGUOUS_TARGET
    result = registry.dispatch(
        Request("object.rename", {"target": target(before), "name": "Renamed"})
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["object_id"] == before["object_id"]
    stale = registry.dispatch(Request("object.rename", {"target": target(before), "name": "Again"}))
    assert stale.error.code == ErrorCode.STALE_STATE
    assert bpy.data.objects.get("Renamed") is not None


def test_partial_quaternion_preserves_unwritten_channels_and_mismatch():
    bpy, registry = setup()
    before = snapshot(registry)
    result = registry.dispatch(
        Request(
            "object.patch_transform",
            {"target": target(before), "transform": {"rotation_quaternion": [0, 1, 0, 0]}},
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["transform"]["location"] == before["transform"]["location"]
    assert after["transform"]["rotation_mode"] == "QUATERNION"
    bpy.context.view_layer.update = lambda: setattr(bpy.data.objects[0], "scale", [2, 2, 2])
    result = registry.dispatch(
        Request(
            "object.patch_transform",
            {"target": target(after), "transform": {"location": [1, 2, 3]}},
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED


@pytest.mark.parametrize(
    "values",
    [
        {"rotation_quaternion": [1, 1, 0, 0]},
        {"location": [True, 0, 0]},
        {"scale": [10001, 1, 1]},
        {},
        {"rotation_euler": [0, 0, 0], "rotation_quaternion": [1, 0, 0, 0]},
    ],
)
def test_invalid_transform_does_not_write(values):
    bpy, registry = setup()
    result = registry.dispatch(
        Request(
            "object.patch_transform", {"target": target(snapshot(registry)), "transform": values}
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert bpy.data.objects[0].location == [0, 0, 0]


def test_visibility_channels_are_independent():
    _, registry = setup()
    for key in ("hide_render", "hide_viewport", "hidden_in_view_layer"):
        before = snapshot(registry)
        result = registry.dispatch(
            Request("object.set_visibility", {"target": target(before), "visibility": {key: True}})
        )
        assert result.status == Status.VERIFIED
        assert result.data["after"]["visibility"] == before["visibility"] | {key: True}


def test_properties_bounds_and_revision():
    _, registry = setup()
    before = snapshot(registry)
    for values in (
        {"pass_index": 32768},
        {"show_name": 1},
        {"location": [0, 0, 0]},
        {"display_type": "UNKNOWN"},
    ):
        result = registry.dispatch(
            Request("object.set_properties", {"target": target(before), "properties": values})
        )
        assert result.error.code == ErrorCode.INVALID_REQUEST
    result = registry.dispatch(
        Request(
            "object.set_properties",
            {
                "target": target(before),
                "properties": {
                    "show_name": True,
                    "lock_location": [True, False, True],
                    "color": [0.1, 0.2, 0.3, 1],
                },
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["revision"] != before["revision"]


def test_selection_active_deselect_all_and_scene_stale():
    bpy, registry = setup()
    old = revision(registry)
    payload = {
        "target": target(snapshot(registry)),
        "selected": True,
        "active": True,
        "expected_scene_revision": old,
    }
    result = registry.dispatch(Request("selection.set", payload))
    assert result.status == Status.VERIFIED
    assert bpy.context.view_layer.objects.active == bpy.data.objects[0]
    assert result.data["after"]["selected_count"] == 1
    assert registry.dispatch(Request("selection.set", payload)).error.code == ErrorCode.STALE_STATE
    result = registry.dispatch(
        Request(
            "selection.set",
            {
                "target": None,
                "selected": False,
                "active": False,
                "expected_scene_revision": revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["selected_count"] == 0
    assert result.data["after"]["active_object_id"] is None


def test_selection_mismatch_and_policy_denial():
    bpy, registry = setup()
    bpy.data.objects[0].select_set = lambda value: None
    payload = {
        "target": target(snapshot(registry)),
        "selected": True,
        "active": None,
        "expected_scene_revision": revision(registry),
    }
    assert (
        registry.dispatch(Request("selection.set", payload)).error.code
        == ErrorCode.VERIFICATION_FAILED
    )
    denied = create_registry(fake_bpy())
    assert denied.dispatch(Request("selection.set", payload)).error.code == ErrorCode.SAFETY_DENIED
