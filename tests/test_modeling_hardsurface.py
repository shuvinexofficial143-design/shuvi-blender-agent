import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.modeling_hardsurface import (
    BooleanAdd,
    HardSurfaceOperations,
    ModifierMove,
    ModifierUpdate,
    StackAdd,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    hard_surface = HardSurfaceOperations(objects)
    registry = ToolRegistry(
        hard_surface.tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, hard_surface, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def stack(registry, inspector, obj):
    return registry.dispatch(
        Request("modifier.stack_inspect", {"object_id": inspector.identity(obj)})
    ).data


def test_stack_inspect_returns_order_and_revision():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    first = obj.modifiers.new("Bevel", "BEVEL")
    first.width = 0.2
    first.segments = 3
    second = obj.modifiers.new("Solid", "SOLIDIFY")
    second.thickness = 0.1

    result = registry.dispatch(
        Request("modifier.stack_inspect", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["count"] == 2
    assert [item["name"] for item in result.data["items"]] == ["Bevel", "Solid"]
    assert result.data["items"][0]["settings"] == {"width": 0.2, "segments": 3}
    assert len(result.data["stack_revision"]) == 64


def test_stack_add_allows_bounded_multi_modifier_workflow():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")

    before = stack(registry, inspector, obj)
    result = registry.dispatch(
        Request(
            "modifier.stack_add",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Bevel",
                "kind": "BEVEL",
                "settings": {"width": 0.15, "segments": 4},
            },
        )
    )
    assert result.status == Status.VERIFIED

    before = stack(registry, inspector, obj)
    result = registry.dispatch(
        Request(
            "modifier.stack_add",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Solid",
                "kind": "SOLIDIFY",
                "settings": {"thickness": 0.08},
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert [item["name"] for item in result.data["after"]["items"]] == ["Bevel", "Solid"]


def test_boolean_add_links_explicit_cutter_and_verifies_settings():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cutter = bpy.data.objects.get("Sphere")
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.boolean_add",
            {
                "target": target(inspector, obj),
                "cutter": target(inspector, cutter),
                "expected_stack_revision": before["stack_revision"],
                "name": "CutSphere",
                "operation": "DIFFERENCE",
                "solver": "EXACT",
            },
        )
    )
    assert result.status == Status.VERIFIED
    item = result.data["after"]["items"][0]
    assert item["type"] == "BOOLEAN"
    assert item["settings"]["operation"] == "DIFFERENCE"
    assert item["settings"]["solver"] == "EXACT"
    assert item["settings"]["cutter_object_id"] == inspector.identity(cutter)
    assert item["settings"]["cutter_name"] == "Sphere"
    assert obj.modifiers.get("CutSphere").object == cutter


def test_boolean_add_rejects_self_cutter():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    before = stack(registry, inspector, obj)
    same = target(inspector, obj)
    result = registry.dispatch(
        Request(
            "modifier.boolean_add",
            {
                "target": same,
                "cutter": same,
                "expected_stack_revision": before["stack_revision"],
                "name": "BadBoolean",
                "operation": "UNION",
                "solver": "FAST",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("BadBoolean") is None


def test_modifier_update_changes_typed_settings_and_visibility():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    modifier = obj.modifiers.new("Bevel", "BEVEL")
    modifier.width = 0.1
    modifier.segments = 2
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.update",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Bevel",
                "kind": "BEVEL",
                "settings": {
                    "width": 0.4,
                    "segments": 6,
                    "show_viewport": False,
                },
            },
        )
    )
    assert result.status == Status.VERIFIED
    item = result.data["after"]["items"][0]
    assert item["settings"] == {"width": 0.4, "segments": 6}
    assert item["show_viewport"] is False
    assert item["show_render"] is True


def test_boolean_update_changes_operation_solver_and_render_visibility():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cutter = bpy.data.objects.get("Sphere")
    before = stack(registry, inspector, obj)
    added = registry.dispatch(
        Request(
            "modifier.boolean_add",
            {
                "target": target(inspector, obj),
                "cutter": target(inspector, cutter),
                "expected_stack_revision": before["stack_revision"],
                "name": "Boolean",
                "operation": "DIFFERENCE",
                "solver": "EXACT",
            },
        )
    )
    assert added.status == Status.VERIFIED

    before = stack(registry, inspector, obj)
    result = registry.dispatch(
        Request(
            "modifier.update",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Boolean",
                "kind": "BOOLEAN",
                "settings": {
                    "operation": "INTERSECT",
                    "solver": "FAST",
                    "show_render": False,
                },
            },
        )
    )
    assert result.status == Status.VERIFIED
    item = result.data["after"]["items"][0]
    assert item["settings"]["operation"] == "INTERSECT"
    assert item["settings"]["solver"] == "FAST"
    assert item["settings"]["cutter_name"] == "Sphere"
    assert item["show_render"] is False


def test_modifier_move_reorders_stack_and_verifies_order():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = 0.1
    bevel.segments = 2
    solid = obj.modifiers.new("Solid", "SOLIDIFY")
    solid.thickness = 0.1
    sub = obj.modifiers.new("Sub", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 2
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.move",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Sub",
                "index": 0,
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert [item["name"] for item in result.data["after"]["items"]] == [
        "Sub",
        "Bevel",
        "Solid",
    ]


def test_stale_stack_revision_blocks_update_and_move():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = 0.1
    bevel.segments = 2
    stale = stack(registry, inspector, obj)
    bevel.width = 0.2

    update = registry.dispatch(
        Request(
            "modifier.update",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": stale["stack_revision"],
                "name": "Bevel",
                "kind": "BEVEL",
                "settings": {"width": 0.3},
            },
        )
    )
    assert update.error.code == ErrorCode.STALE_STATE
    assert bevel.width == 0.2


def test_stack_add_verification_failure_removes_created_modifier():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    before = stack(registry, inspector, obj)
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        modifier = obj.modifiers.get("Bevel")
        if calls["count"] == 1 and modifier is not None:
            modifier.width = 99

    bpy.context.view_layer.update = corrupt_once
    result = registry.dispatch(
        Request(
            "modifier.stack_add",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Bevel",
                "kind": "BEVEL",
                "settings": {"width": 0.1, "segments": 2},
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert obj.modifiers.get("Bevel") is None


def test_modifier_update_verification_failure_restores_previous_settings():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    modifier = obj.modifiers.new("Bevel", "BEVEL")
    modifier.width = 0.1
    modifier.segments = 2
    before = stack(registry, inspector, obj)
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            modifier.width = 88

    bpy.context.view_layer.update = corrupt_once
    result = registry.dispatch(
        Request(
            "modifier.update",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "Bevel",
                "kind": "BEVEL",
                "settings": {"width": 0.5},
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert modifier.width == 0.1


def test_modifier_stack_limit_is_enforced():
    bpy, inspector, hard_surface, registry = setup()
    obj = bpy.data.objects.get("Cube")
    for index in range(16):
        modifier = obj.modifiers.new(f"Bevel{index}", "BEVEL")
        modifier.width = 0.1
        modifier.segments = 1
    before = stack(registry, inspector, obj)
    result = registry.dispatch(
        Request(
            "modifier.stack_add",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "TooMany",
                "kind": "SOLIDIFY",
                "settings": {"thickness": 0.1},
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("TooMany") is None


def test_milestone6_contract_validation():
    common = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_stack_revision": "y" * 64,
    }
    with pytest.raises(AgentError):
        StackAdd.parse(
            common
            | {
                "name": "Bad",
                "kind": "BOOLEAN",
                "settings": {"width": 1, "segments": 2},
            }
        )
    with pytest.raises(AgentError):
        BooleanAdd.parse(
            common
            | {
                "cutter": common["target"],
                "name": "Bool",
                "operation": "CUT",
                "solver": "EXACT",
            }
        )
    with pytest.raises(AgentError):
        ModifierUpdate.parse(
            common
            | {
                "name": "Bevel",
                "kind": "BEVEL",
                "settings": {"show_viewport": 1},
            }
        )
    with pytest.raises(AgentError):
        ModifierMove.parse(common | {"name": "Bevel", "index": 16})
