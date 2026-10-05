from fake_bpy import fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry


def setup():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    return bpy, registry


def revision(registry):
    return registry.dispatch(Request("scene.inspect")).data["revision"]


def test_cursor_inspect_set_and_scene_revision():
    bpy, registry = setup()
    before_revision = revision(registry)
    inspected = registry.dispatch(Request("cursor.inspect"))
    assert inspected.status == Status.SUCCEEDED
    assert inspected.data["location"] == [0.0, 0.0, 0.0]

    result = registry.dispatch(
        Request(
            "cursor.set",
            {
                "location": [1.25, -2.5, 3.75],
                "expected_scene_revision": before_revision,
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert list(bpy.context.scene.cursor.location) == [1.25, -2.5, 3.75]
    assert revision(registry) != before_revision


def test_cursor_rejects_stale_revision_and_invalid_bounds():
    _, registry = setup()
    old = revision(registry)
    first = registry.dispatch(
        Request("cursor.set", {"location": [1, 2, 3], "expected_scene_revision": old})
    )
    assert first.status == Status.VERIFIED
    stale = registry.dispatch(
        Request("cursor.set", {"location": [0, 0, 0], "expected_scene_revision": old})
    )
    assert stale.error.code == ErrorCode.STALE_STATE
    invalid = registry.dispatch(
        Request(
            "cursor.set",
            {"location": [1_000_001, 0, 0], "expected_scene_revision": revision(registry)},
        )
    )
    assert invalid.error.code == ErrorCode.INVALID_REQUEST


def test_scene_rename_and_unit_settings_are_verified():
    bpy, registry = setup()
    result = registry.dispatch(
        Request(
            "scene.rename",
            {"name": "Shot001", "expected_scene_revision": revision(registry)},
        )
    )
    assert result.status == Status.VERIFIED
    assert bpy.context.scene.name == "Shot001"

    result = registry.dispatch(
        Request(
            "scene.set_units",
            {
                "units": {
                    "system": "METRIC",
                    "scale_length": 0.01,
                    "length_unit": "CENTIMETERS",
                },
                "expected_scene_revision": revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"] == {
        "system": "METRIC",
        "scale_length": 0.01,
        "length_unit": "CENTIMETERS",
    }
    scene = registry.dispatch(Request("scene.inspect")).data
    assert scene["units"]["system"] == "METRIC"
    assert scene["cursor"]["location"] == [0.0, 0.0, 0.0]


def test_invalid_unit_settings_do_not_write():
    bpy, registry = setup()
    before = (
        bpy.context.scene.unit_settings.system,
        bpy.context.scene.unit_settings.scale_length,
        bpy.context.scene.unit_settings.length_unit,
    )
    for units in (
        {},
        {"system": "GALACTIC"},
        {"scale_length": 0},
        {"length_unit": "PARSECS"},
    ):
        result = registry.dispatch(
            Request(
                "scene.set_units",
                {"units": units, "expected_scene_revision": revision(registry)},
            )
        )
        assert result.error.code == ErrorCode.INVALID_REQUEST
    after = (
        bpy.context.scene.unit_settings.system,
        bpy.context.scene.unit_settings.scale_length,
        bpy.context.scene.unit_settings.length_unit,
    )
    assert after == before


def test_mode_inspection_reports_active_type_without_mutating_mode():
    bpy, registry = setup()
    result = registry.dispatch(Request("mode.inspect"))
    assert result.status == Status.SUCCEEDED
    assert result.data == {
        "mode": "OBJECT",
        "active_object_id": None,
        "active_object_type": None,
    }
    bpy.context.view_layer.objects.active = bpy.data.objects.get("Cube")
    result = registry.dispatch(Request("mode.inspect"))
    assert result.data["active_object_type"] == "MESH"
    assert result.data["active_object_id"] is not None


def test_scene_inspection_reports_type_counts_and_world_presence():
    bpy, registry = setup()
    scene = registry.dispatch(Request("scene.inspect"))
    assert scene.status == Status.SUCCEEDED
    assert scene.data["object_count"] == 2
    assert scene.data["object_counts_by_type"] == {"MESH": 2}
    assert scene.data["world_present"] is False

    bpy.context.scene.world = object()
    scene = registry.dispatch(Request("scene.inspect"))
    assert scene.data["world_present"] is True


def test_transform_pivot_inspection_and_verified_mutation():
    _, registry = setup()
    before_revision = revision(registry)
    inspected = registry.dispatch(Request("pivot.inspect"))
    assert inspected.status == Status.SUCCEEDED
    assert inspected.data["pivot"] == "MEDIAN_POINT"

    result = registry.dispatch(
        Request(
            "pivot.set",
            {"pivot": "CURSOR", "expected_scene_revision": before_revision},
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["pivot"] == "CURSOR"
    assert revision(registry) != before_revision

    invalid = registry.dispatch(
        Request(
            "pivot.set",
            {"pivot": "RANDOM_POINT", "expected_scene_revision": revision(registry)},
        )
    )
    assert invalid.error.code == ErrorCode.INVALID_REQUEST
