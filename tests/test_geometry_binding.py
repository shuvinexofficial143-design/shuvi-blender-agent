import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_binding import (
    GeometryBindingOperations,
    GeometryModifierBind,
    GeometryModifierInspect,
    GeometryModifierRemove,
)
from shuvi_blender_agent.geometry_nodes import GeometryNodeOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    geometry = GeometryNodeOperations(objects)
    binding = GeometryBindingOperations(objects)
    registry = ToolRegistry(
        [*geometry.tools(), *binding.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    obj = bpy.context.scene.objects[0]
    return bpy, inspector, geometry, binding, registry, obj


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def create_group(registry, name="Procedural"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def bind_payload(inspector, obj, group_snapshot, modifier_name="GeometryNodes"):
    return {
        "target": target(inspector, obj),
        "group_name": group_snapshot["group_name"],
        "expected_group_revision": group_snapshot["group_revision"],
        "modifier_name": modifier_name,
    }


def test_factory_has_three_binding_tools_within_bounded_cap():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 258
    assert MAX_REGISTERED_TOOLS == 258
    names = {item["name"] for item in registry.catalog()}
    assert {
        "geometry_nodes.modifier_inspect",
        "geometry_nodes.modifier_bind",
        "geometry_nodes.modifier_remove",
    }.issubset(names)


def test_modifier_bind_and_inspect_verify_exact_group():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    before = inspector.snapshot(obj)

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert result.status == Status.VERIFIED
    modifier = obj.modifiers.get("GeometryNodes")
    assert modifier is not None
    assert modifier.type == "NODES"
    assert modifier.node_group is bpy.data.node_groups.get("Procedural")
    assert result.data["after"]["revision"] != before["revision"]
    row = next(
        item for item in result.data["after"]["modifiers"] if item["name"] == "GeometryNodes"
    )
    assert row["settings"]["node_group_name"] == "Procedural"

    inspected = registry.dispatch(
        Request(
            "geometry_nodes.modifier_inspect",
            {"object_id": inspector.identity(obj)},
        )
    )
    assert inspected.status == Status.SUCCEEDED
    assert inspected.data["geometry_nodes_modifier_count"] == 1
    binding_row = inspected.data["bindings"][0]
    assert binding_row["modifier_name"] == "GeometryNodes"
    assert binding_row["group_name"] == "Procedural"
    assert binding_row["group_local"] is True
    assert binding_row["group_tree_type"] == "GeometryNodeTree"
    assert binding_row["group_revision"] == group["group_revision"]
    assert len(inspected.data["binding_revision"]) == 64


def test_modifier_bind_preserves_existing_modifier_stack():
    bpy, inspector, geometry, binding, registry, obj = setup()
    obj.modifiers.new("Existing", "BEVEL")
    group = create_group(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert result.status == Status.VERIFIED
    assert [item.name for item in obj.modifiers] == ["Existing", "GeometryNodes"]


def test_modifier_bind_rejects_stale_object_revision():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    stale_target = target(inspector, obj)
    obj.modifiers.new("External", "BEVEL")

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            {
                "target": stale_target,
                "group_name": "Procedural",
                "expected_group_revision": group["group_revision"],
                "modifier_name": "GeometryNodes",
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.modifiers.get("GeometryNodes") is None


def test_modifier_bind_rejects_stale_group_revision():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    add = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "Procedural",
                "expected_group_revision": group["group_revision"],
                "node_type": "MESH_CUBE",
                "node_name": "CubeNode",
            },
        )
    )
    assert add.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            {
                "target": target(inspector, obj),
                "group_name": "Procedural",
                "expected_group_revision": group["group_revision"],
                "modifier_name": "GeometryNodes",
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.modifiers.get("GeometryNodes") is None


def test_modifier_bind_rejects_linked_group_and_shape_key_mesh():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    group_obj = bpy.data.node_groups.get("Procedural")
    group_obj.library = object()

    linked = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert linked.error.code == ErrorCode.SAFETY_DENIED

    group_obj.library = None
    obj.data.shape_keys = object()
    shape_keyed = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert shape_keyed.error.code == ErrorCode.SAFETY_DENIED


def test_modifier_bind_collision_does_not_replace_existing_modifier():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    existing = obj.modifiers.new("GeometryNodes", "BEVEL")

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert result.error.code == ErrorCode.AMBIGUOUS_TARGET
    assert obj.modifiers.get("GeometryNodes") is existing
    assert existing.type == "BEVEL"


def test_modifier_bind_verification_failure_removes_created_modifier():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    before = inspector.snapshot(obj)
    original = binding._binding_evidence
    calls = {"count": 0}

    def corrupt_first(bound_obj, bound_group, name):
        calls["count"] += 1
        evidence = original(bound_obj, bound_group, name)
        if calls["count"] == 1:
            evidence["binding"]["group_name"] = "WrongGroup"
        return evidence

    binding._binding_evidence = corrupt_first
    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert obj.modifiers.get("GeometryNodes") is None
    assert inspector.snapshot(obj)["revision"] == before["revision"]


def test_modifier_remove_verifies_absence_and_changes_object_revision():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    bound = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert bound.status == Status.VERIFIED
    before_remove = inspector.snapshot(obj)

    removed = registry.dispatch(
        Request(
            "geometry_nodes.modifier_remove",
            {
                "target": target(inspector, obj),
                "group_name": "Procedural",
                "expected_group_revision": group["group_revision"],
                "modifier_name": "GeometryNodes",
            },
        )
    )
    assert removed.status == Status.VERIFIED
    assert obj.modifiers.get("GeometryNodes") is None
    assert removed.data["after"]["modifier_count"] == 0
    assert removed.data["after"]["revision"] != before_remove["revision"]


def test_modifier_remove_requires_exact_bound_group():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group_a = create_group(registry, "GroupA")
    group_b = create_group(registry, "GroupB")
    bound = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group_a),
        )
    )
    assert bound.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_remove",
            {
                "target": target(inspector, obj),
                "group_name": "GroupB",
                "expected_group_revision": group_b["group_revision"],
                "modifier_name": "GeometryNodes",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("GeometryNodes") is not None


def test_modifier_remove_failure_restores_stack_position_flags_and_revision():
    bpy, inspector, geometry, binding, registry, obj = setup()
    group = create_group(registry)
    first = obj.modifiers.new("Before", "BEVEL")
    first.width = 0.1
    bound = registry.dispatch(
        Request(
            "geometry_nodes.modifier_bind",
            bind_payload(inspector, obj, group),
        )
    )
    assert bound.status == Status.VERIFIED
    nodes_modifier = obj.modifiers.get("GeometryNodes")
    nodes_modifier.show_viewport = False
    nodes_modifier.show_render = False
    after = obj.modifiers.new("After", "SOLIDIFY")
    after.thickness = 0.2
    before = inspector.snapshot(obj)
    original = binding._binding_evidence
    calls = {"count": 0}

    def corrupt_first(bound_obj, bound_group, name):
        calls["count"] += 1
        evidence = original(bound_obj, bound_group, name)
        if calls["count"] == 1:
            evidence["binding"]["present"] = True
        return evidence

    binding._binding_evidence = corrupt_first
    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_remove",
            {
                "target": target(inspector, obj),
                "group_name": "Procedural",
                "expected_group_revision": group["group_revision"],
                "modifier_name": "GeometryNodes",
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert [item.name for item in obj.modifiers] == ["Before", "GeometryNodes", "After"]
    restored = obj.modifiers.get("GeometryNodes")
    assert restored.node_group is bpy.data.node_groups.get("Procedural")
    assert restored.show_viewport is False
    assert restored.show_render is False
    assert inspector.snapshot(obj)["revision"] == before["revision"]


def test_modifier_inspect_reports_unbound_nodes_modifier_without_claiming_group():
    bpy, inspector, geometry, binding, registry, obj = setup()
    obj.modifiers.new("BrokenNodes", "NODES")

    result = registry.dispatch(
        Request(
            "geometry_nodes.modifier_inspect",
            {"object_id": inspector.identity(obj)},
        )
    )
    assert result.status == Status.SUCCEEDED
    row = result.data["bindings"][0]
    assert row["group_name"] is None
    assert row["group_local"] is False
    assert row["group_tree_type"] is None
    assert row["group_revision"] is None


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (GeometryModifierInspect.parse, {"object_id": ""}),
        (
            GeometryModifierBind.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "group_name": "",
                "expected_group_revision": "y" * 64,
                "modifier_name": "GeometryNodes",
            },
        ),
        (
            GeometryModifierRemove.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "group_name": "Procedural",
                "expected_group_revision": "y" * 64,
                "modifier_name": "",
            },
        ),
    ],
)
def test_geometry_binding_contracts_reject_invalid_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
