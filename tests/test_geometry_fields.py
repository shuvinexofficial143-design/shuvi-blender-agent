import copy

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_fields import (
    FieldWorkflowApply,
    FieldWorkflowClear,
    FieldWorkflowPreview,
    GeometryFieldOperations,
)
from shuvi_blender_agent.geometry_nodes import GeometryNodeOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry
from shuvi_blender_agent.verification import compare


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    geometry = GeometryNodeOperations(objects)
    fields = GeometryFieldOperations(objects)
    registry = ToolRegistry(
        [*geometry.tools(), *fields.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, geometry, fields, registry


def create_group(registry, name="FieldGroup"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def inspect(registry, name="FieldGroup"):
    result = registry.dispatch(Request("geometry_nodes.tree_inspect", {"group_name": name}))
    assert result.status == Status.SUCCEEDED
    return result.data


def parameters(attribute_name="shuvi_field"):
    return {
        "size": [2, 3, 4],
        "vertices": 3,
        "attribute_name": attribute_name,
    }


def apply_payload(registry, workflow="INDEX_ATTRIBUTE", prefix="FieldDemo"):
    return {
        "group_name": "FieldGroup",
        "expected_group_revision": inspect(registry)["group_revision"],
        "workflow": workflow,
        "prefix": prefix,
        "parameters": parameters(),
    }


def test_factory_has_field_tools_within_raised_bounded_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 221
    assert MAX_REGISTERED_TOOLS == 221
    names = {item["name"] for item in registry.catalog()}
    assert {
        "geometry_nodes.field_preview",
        "geometry_nodes.field_apply",
        "geometry_nodes.field_clear",
    }.issubset(names)


@pytest.mark.parametrize(
    ("workflow", "field_type", "field_output", "data_type"),
    [
        ("INDEX_ATTRIBUTE", "INPUT_INDEX", "Index", "INT"),
        ("POSITION_ATTRIBUTE", "INPUT_POSITION", "Position", "FLOAT_VECTOR"),
        ("NORMAL_ATTRIBUTE", "INPUT_NORMAL", "Normal", "FLOAT_VECTOR"),
    ],
)
def test_preview_is_deterministic_and_typed(
    workflow,
    field_type,
    field_output,
    data_type,
):
    bpy, geometry, fields, registry = setup()
    payload = {
        "workflow": workflow,
        "prefix": "Demo",
        "parameters": parameters("shuvi_demo"),
    }

    first = registry.dispatch(Request("geometry_nodes.field_preview", payload))
    second = registry.dispatch(Request("geometry_nodes.field_preview", payload))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["source_only"] is True
    assert first.data["real_runtime_verified"] is False
    assert first.data["attribute"] == {
        "name": "shuvi_demo",
        "domain": "POINT",
        "data_type": data_type,
        "field_source": field_output,
    }
    node_types = {item["node_type"] for item in first.data["nodes"]}
    assert field_type in node_types
    assert "STORE_NAMED_ATTRIBUTE_INTERNAL" in node_types
    assert "GROUP_OUTPUT_INTERNAL" in node_types
    assert len(first.data["field_workflow_revision"]) == 64


@pytest.mark.parametrize(
    ("workflow", "field_bl_idname", "field_output", "data_type"),
    [
        ("INDEX_ATTRIBUTE", "GeometryNodeInputIndex", "Index", "INT"),
        ("POSITION_ATTRIBUTE", "GeometryNodeInputPosition", "Position", "FLOAT_VECTOR"),
        ("NORMAL_ATTRIBUTE", "GeometryNodeInputNormal", "Normal", "FLOAT_VECTOR"),
    ],
)
def test_apply_creates_exact_field_graph(
    workflow,
    field_bl_idname,
    field_output,
    data_type,
):
    bpy, geometry, fields, registry = setup()
    before = create_group(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.field_apply",
            apply_payload(registry, workflow, "Demo"),
        )
    )

    assert result.status == Status.VERIFIED
    assert result.data["before"]["group_revision"] == before["group_revision"]
    assert result.data["workflow"] == workflow
    assert result.data["attribute"]["data_type"] == data_type
    after = result.data["after"]
    assert after["node_count"] == 4
    assert after["link_count"] == 3
    assert len(after["interface"]) == 1

    cube = next(item for item in after["nodes"] if item["name"] == "Demo_Cube")
    field = next(item for item in after["nodes"] if item["name"] == "Demo_Field")
    store = next(item for item in after["nodes"] if item["name"] == "Demo_StoreAttribute")
    output = next(item for item in after["nodes"] if item["name"] == "Demo_Output")

    assert cube["node_type"] == "MESH_CUBE"
    assert field["bl_idname"] == field_bl_idname
    assert store["bl_idname"] == "GeometryNodeStoreNamedAttribute"
    assert store["managed_type"] is False
    assert store["field_settings"] == {"data_type": data_type, "domain": "POINT"}
    assert output["bl_idname"] == "NodeGroupOutput"

    store_values = {item["name"]: item["default_value"] for item in store["inputs"]}
    assert store_values["Selection"] is True
    assert store_values["Name"] == "shuvi_field"

    links = {
        (
            item["from_node"],
            item["from_socket"],
            item["to_node"],
            item["to_socket"],
        )
        for item in after["links"]
    }
    assert ("Demo_Cube", "Mesh", "Demo_StoreAttribute", "Geometry") in links
    assert ("Demo_Field", field_output, "Demo_StoreAttribute", "Value") in links
    assert ("Demo_StoreAttribute", "Geometry", "Demo_Output", "Geometry") in links


def test_apply_requires_empty_group_and_fresh_revision():
    bpy, geometry, fields, registry = setup()
    original = create_group(registry)
    stale = original["group_revision"]

    added = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": stale,
                "node_type": "MESH_CUBE",
                "node_name": "Existing",
            },
        )
    )
    assert added.status == Status.VERIFIED

    nonempty = registry.dispatch(
        Request(
            "geometry_nodes.field_apply",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "Demo",
                "parameters": parameters(),
            },
        )
    )
    assert nonempty.error.code == ErrorCode.SAFETY_DENIED

    stale_result = registry.dispatch(
        Request(
            "geometry_nodes.field_apply",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": stale,
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "Demo",
                "parameters": parameters(),
            },
        )
    )
    assert stale_result.error.code == ErrorCode.STALE_STATE


def test_shared_group_is_denied_for_apply_and_clear():
    bpy, geometry, fields, registry = setup()
    create_group(registry)
    group = bpy.data.node_groups.get("FieldGroup")
    group.users = 2

    denied = registry.dispatch(Request("geometry_nodes.field_apply", apply_payload(registry)))
    assert denied.error.code == ErrorCode.SAFETY_DENIED

    group.users = 0
    applied = registry.dispatch(Request("geometry_nodes.field_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED
    group.users = 2

    clear_payload = {
        "group_name": "FieldGroup",
        "expected_group_revision": inspect(registry)["group_revision"],
        "workflow": "INDEX_ATTRIBUTE",
        "prefix": "FieldDemo",
        "parameters": parameters(),
    }
    cleared = registry.dispatch(Request("geometry_nodes.field_clear", clear_payload))
    assert cleared.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["node_count"] == 4


def test_clear_exact_field_workflow_restores_empty_group():
    bpy, geometry, fields, registry = setup()
    empty = create_group(registry)
    applied = registry.dispatch(Request("geometry_nodes.field_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.field_clear",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "FieldDemo",
                "parameters": parameters(),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["node_count"] == 0
    assert result.data["after"]["link_count"] == 0
    assert result.data["after"]["interface"] == []
    assert result.data["after"]["group_revision"] == empty["group_revision"]


def test_clear_refuses_modified_attribute_settings_or_name():
    bpy, geometry, fields, registry = setup()
    create_group(registry)
    applied = registry.dispatch(Request("geometry_nodes.field_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED
    group = bpy.data.node_groups.get("FieldGroup")
    store = group.nodes.get("FieldDemo_StoreAttribute")
    store.domain = "FACE"
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.field_clear",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": before["group_revision"],
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "FieldDemo",
                "parameters": parameters(),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["group_revision"] == before["group_revision"]

    store.domain = "POINT"
    store.inputs["Name"].default_value = "shuvi_other"
    before_name = inspect(registry)
    result_name = registry.dispatch(
        Request(
            "geometry_nodes.field_clear",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": before_name["group_revision"],
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "FieldDemo",
                "parameters": parameters(),
            },
        )
    )
    assert result_name.error.code == ErrorCode.SAFETY_DENIED


def test_apply_verification_failure_rolls_back_to_empty_group():
    bpy, geometry, fields, registry = setup()
    before = create_group(registry)
    original = fields._verify_exact_plan
    calls = {"count": 0}

    def fail_once(snapshot, plan):
        calls["count"] += 1
        if calls["count"] == 1:
            return compare({"value": 1}, {"value": 2})
        return original(snapshot, plan)

    fields._verify_exact_plan = fail_once
    result = registry.dispatch(Request("geometry_nodes.field_apply", apply_payload(registry)))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_clear_verification_failure_rebuilds_exact_field_workflow():
    bpy, geometry, fields, registry = setup()
    create_group(registry)
    applied = registry.dispatch(Request("geometry_nodes.field_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED
    before = inspect(registry)
    original_snapshot = fields.geometry._snapshot
    calls = {"count": 0}

    def corrupt_empty_once(group):
        calls["count"] += 1
        snapshot = original_snapshot(group)
        if calls["count"] == 2 and snapshot["node_count"] == 0:
            broken = copy.deepcopy(snapshot)
            broken["node_count"] = 1
            return broken
        return snapshot

    fields.geometry._snapshot = corrupt_empty_once
    result = registry.dispatch(
        Request(
            "geometry_nodes.field_clear",
            {
                "group_name": "FieldGroup",
                "expected_group_revision": before["group_revision"],
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "FieldDemo",
                "parameters": parameters(),
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = original_snapshot(bpy.data.node_groups.get("FieldGroup"))
    assert restored["group_revision"] == before["group_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            FieldWorkflowPreview.parse,
            {
                "workflow": "UNSAFE",
                "prefix": "Demo",
                "parameters": parameters(),
            },
        ),
        (
            FieldWorkflowPreview.parse,
            {
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "",
                "parameters": parameters(),
            },
        ),
        (
            FieldWorkflowPreview.parse,
            {
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "Demo",
                "parameters": parameters("index"),
            },
        ),
        (
            FieldWorkflowPreview.parse,
            {
                "workflow": "POSITION_ATTRIBUTE",
                "prefix": "Demo",
                "parameters": parameters("shuvi_bad-name"),
            },
        ),
        (
            FieldWorkflowApply.parse,
            {
                "group_name": "FieldGroup",
                "expected_group_revision": "x" * 64,
                "workflow": "NORMAL_ATTRIBUTE",
                "prefix": "Demo",
                "parameters": {
                    "size": [1, 1],
                    "vertices": 2,
                    "attribute_name": "shuvi_normal",
                },
            },
        ),
        (
            FieldWorkflowClear.parse,
            {
                "group_name": "FieldGroup",
                "expected_group_revision": "x" * 64,
                "workflow": "INDEX_ATTRIBUTE",
                "prefix": "Demo",
                "parameters": {
                    "size": [1, 1, 1],
                    "vertices": 1,
                    "attribute_name": "shuvi_index",
                },
            },
        ),
    ],
)
def test_field_workflow_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
