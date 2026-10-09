import copy

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_nodes import GeometryNodeOperations
from shuvi_blender_agent.geometry_scatter import (
    GeometryScatterOperations,
    ScatterApply,
    ScatterClear,
    ScatterPreview,
)
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
    scatter = GeometryScatterOperations(objects)
    registry = ToolRegistry(
        [*geometry.tools(), *scatter.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, geometry, scatter, registry


def create_group(registry, name="ScatterGroup"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def inspect(registry, name="ScatterGroup"):
    result = registry.dispatch(Request("geometry_nodes.tree_inspect", {"group_name": name}))
    assert result.status == Status.SUCCEEDED
    return result.data


def cube_parameters():
    return {
        "point_size": [8, 6, 4],
        "point_vertices": [4, 4, 4],
        "rotation": [0, 0, 0],
        "scale": [0.5, 0.5, 0.5],
        "instance_size": [1, 1, 1],
        "instance_vertices": 2,
    }


def ico_parameters():
    return {
        "point_size": [10, 8, 6],
        "point_vertices": [5, 4, 3],
        "rotation": [0.1, -0.2, 0.3],
        "scale": [0.75, 0.75, 0.75],
        "instance_radius": 0.5,
        "instance_subdivisions": 2,
    }


def apply_payload(registry, recipe="CUBE_SCATTER", prefix="ScatterDemo"):
    return {
        "group_name": "ScatterGroup",
        "expected_group_revision": inspect(registry)["group_revision"],
        "recipe": recipe,
        "prefix": prefix,
        "parameters": cube_parameters() if recipe == "CUBE_SCATTER" else ico_parameters(),
    }


def test_factory_has_scatter_tools_within_bounded_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 296
    assert MAX_REGISTERED_TOOLS == 296
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS
    names = {item["name"] for item in registry.catalog()}
    assert {
        "geometry_nodes.scatter_preview",
        "geometry_nodes.scatter_apply",
        "geometry_nodes.scatter_clear",
    }.issubset(names)


@pytest.mark.parametrize(
    ("recipe", "params", "instance_type", "estimated"),
    [
        ("CUBE_SCATTER", cube_parameters(), "MESH_CUBE", 56),
        ("ICO_SPHERE_SCATTER", ico_parameters(), "MESH_ICO_SPHERE", 54),
    ],
)
def test_preview_is_deterministic_and_reports_bounded_estimate(
    recipe,
    params,
    instance_type,
    estimated,
):
    bpy, geometry, scatter, registry = setup()
    payload = {"recipe": recipe, "prefix": "Demo", "parameters": params}

    first = registry.dispatch(Request("geometry_nodes.scatter_preview", payload))
    second = registry.dispatch(Request("geometry_nodes.scatter_preview", payload))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["source_only"] is True
    assert first.data["real_runtime_verified"] is False
    assert first.data["scatter"] == {
        "estimated_instance_count": estimated,
        "maximum_instance_count": 2048,
        "instances_realized": False,
        "external_asset_references": False,
        "collection_references": False,
    }
    assert len(first.data["nodes"]) == 4
    assert len(first.data["links"]) == 3
    assert any(
        item["name"] == "Demo_Instance" and item["node_type"] == instance_type
        for item in first.data["nodes"]
    )
    assert len(first.data["scatter_revision"]) == 64


@pytest.mark.parametrize(
    ("recipe", "instance_bl_idname", "params"),
    [
        ("CUBE_SCATTER", "GeometryNodeMeshCube", cube_parameters()),
        ("ICO_SPHERE_SCATTER", "GeometryNodeMeshIcoSphere", ico_parameters()),
    ],
)
def test_apply_creates_exact_scatter_graph(recipe, instance_bl_idname, params):
    bpy, geometry, scatter, registry = setup()
    before = create_group(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.scatter_apply",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": recipe,
                "prefix": "Demo",
                "parameters": params,
            },
        )
    )

    assert result.status == Status.VERIFIED
    assert result.data["before"]["group_revision"] == before["group_revision"]
    after = result.data["after"]
    assert after["node_count"] == 4
    assert after["link_count"] == 3
    assert len(after["interface"]) == 1

    points = next(item for item in after["nodes"] if item["name"] == "Demo_Points")
    instance = next(item for item in after["nodes"] if item["name"] == "Demo_Instance")
    scatter_node = next(item for item in after["nodes"] if item["name"] == "Demo_Scatter")
    output = next(item for item in after["nodes"] if item["name"] == "Demo_Output")

    assert points["bl_idname"] == "GeometryNodeMeshCube"
    assert instance["bl_idname"] == instance_bl_idname
    assert scatter_node["bl_idname"] == "GeometryNodeInstanceOnPoints"
    assert output["bl_idname"] == "NodeGroupOutput"

    values = {item["name"]: item["default_value"] for item in scatter_node["inputs"]}
    assert values["Selection"] is True
    assert values["Pick Instance"] is False
    assert values["Instance Index"] == 0
    assert values["Rotation"] == pytest.approx(params["rotation"])
    assert values["Scale"] == pytest.approx(params["scale"])

    links = {
        (
            item["from_node"],
            item["from_socket"],
            item["to_node"],
            item["to_socket"],
        )
        for item in after["links"]
    }
    assert links == {
        ("Demo_Points", "Mesh", "Demo_Scatter", "Points"),
        ("Demo_Instance", "Mesh", "Demo_Scatter", "Instance"),
        ("Demo_Scatter", "Instances", "Demo_Output", "Geometry"),
    }


def test_scatter_estimate_refuses_excessive_point_density():
    with pytest.raises(AgentError):
        ScatterPreview.parse(
            {
                "recipe": "CUBE_SCATTER",
                "prefix": "Dense",
                "parameters": {
                    **cube_parameters(),
                    "point_vertices": [20, 20, 20],
                },
            }
        )


def test_apply_requires_empty_group_and_fresh_revision():
    bpy, geometry, scatter, registry = setup()
    original = create_group(registry)
    stale = original["group_revision"]

    added = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": stale,
                "node_type": "MESH_CUBE",
                "node_name": "Existing",
            },
        )
    )
    assert added.status == Status.VERIFIED

    nonempty = registry.dispatch(
        Request(
            "geometry_nodes.scatter_apply",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": "CUBE_SCATTER",
                "prefix": "Demo",
                "parameters": cube_parameters(),
            },
        )
    )
    assert nonempty.error.code == ErrorCode.SAFETY_DENIED

    stale_result = registry.dispatch(
        Request(
            "geometry_nodes.scatter_apply",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": stale,
                "recipe": "CUBE_SCATTER",
                "prefix": "Demo",
                "parameters": cube_parameters(),
            },
        )
    )
    assert stale_result.error.code == ErrorCode.STALE_STATE


def test_shared_group_is_denied_for_apply_and_clear():
    bpy, geometry, scatter, registry = setup()
    create_group(registry)
    group = bpy.data.node_groups.get("ScatterGroup")
    group.users = 2

    denied = registry.dispatch(Request("geometry_nodes.scatter_apply", apply_payload(registry)))
    assert denied.error.code == ErrorCode.SAFETY_DENIED

    group.users = 0
    applied = registry.dispatch(Request("geometry_nodes.scatter_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED
    group.users = 2

    clear_payload = {
        "group_name": "ScatterGroup",
        "expected_group_revision": inspect(registry)["group_revision"],
        "recipe": "CUBE_SCATTER",
        "prefix": "ScatterDemo",
        "parameters": cube_parameters(),
    }
    cleared = registry.dispatch(Request("geometry_nodes.scatter_clear", clear_payload))
    assert cleared.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["node_count"] == 4


def test_clear_exact_scatter_restores_empty_group():
    bpy, geometry, scatter, registry = setup()
    empty = create_group(registry)
    applied = registry.dispatch(Request("geometry_nodes.scatter_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.scatter_clear",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": "CUBE_SCATTER",
                "prefix": "ScatterDemo",
                "parameters": cube_parameters(),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["node_count"] == 0
    assert result.data["after"]["link_count"] == 0
    assert result.data["after"]["interface"] == []
    assert result.data["after"]["group_revision"] == empty["group_revision"]


def test_clear_refuses_modified_scatter_defaults():
    bpy, geometry, scatter, registry = setup()
    create_group(registry)
    applied = registry.dispatch(Request("geometry_nodes.scatter_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED
    group = bpy.data.node_groups.get("ScatterGroup")
    scatter_node = group.nodes.get("ScatterDemo_Scatter")
    scatter_node.inputs["Scale"].default_value = [9.0, 9.0, 9.0]
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.scatter_clear",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": before["group_revision"],
                "recipe": "CUBE_SCATTER",
                "prefix": "ScatterDemo",
                "parameters": cube_parameters(),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_apply_verification_failure_rolls_back_to_empty_group():
    bpy, geometry, scatter, registry = setup()
    before = create_group(registry)
    original = scatter._verify_exact_plan
    calls = {"count": 0}

    def fail_once(snapshot, plan):
        calls["count"] += 1
        if calls["count"] == 1:
            return compare({"value": 1}, {"value": 2})
        return original(snapshot, plan)

    scatter._verify_exact_plan = fail_once
    result = registry.dispatch(Request("geometry_nodes.scatter_apply", apply_payload(registry)))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_clear_verification_failure_rebuilds_exact_scatter():
    bpy, geometry, scatter, registry = setup()
    create_group(registry)
    applied = registry.dispatch(Request("geometry_nodes.scatter_apply", apply_payload(registry)))
    assert applied.status == Status.VERIFIED
    before = inspect(registry)
    original_snapshot = scatter.geometry._snapshot
    calls = {"count": 0}

    def corrupt_empty_once(group):
        calls["count"] += 1
        snapshot = original_snapshot(group)
        if calls["count"] == 2 and snapshot["node_count"] == 0:
            broken = copy.deepcopy(snapshot)
            broken["node_count"] = 1
            return broken
        return snapshot

    scatter.geometry._snapshot = corrupt_empty_once
    result = registry.dispatch(
        Request(
            "geometry_nodes.scatter_clear",
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": before["group_revision"],
                "recipe": "CUBE_SCATTER",
                "prefix": "ScatterDemo",
                "parameters": cube_parameters(),
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = original_snapshot(bpy.data.node_groups.get("ScatterGroup"))
    assert restored["group_revision"] == before["group_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            ScatterPreview.parse,
            {
                "recipe": "UNSAFE",
                "prefix": "Demo",
                "parameters": cube_parameters(),
            },
        ),
        (
            ScatterPreview.parse,
            {
                "recipe": "CUBE_SCATTER",
                "prefix": "",
                "parameters": cube_parameters(),
            },
        ),
        (
            ScatterPreview.parse,
            {
                "recipe": "CUBE_SCATTER",
                "prefix": "Demo",
                "parameters": {
                    **cube_parameters(),
                    "point_vertices": [2, 2],
                },
            },
        ),
        (
            ScatterPreview.parse,
            {
                "recipe": "CUBE_SCATTER",
                "prefix": "Demo",
                "parameters": {
                    **cube_parameters(),
                    "instance_vertices": 9,
                },
            },
        ),
        (
            ScatterApply.parse,
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": "x" * 64,
                "recipe": "ICO_SPHERE_SCATTER",
                "prefix": "Demo",
                "parameters": {
                    **ico_parameters(),
                    "instance_subdivisions": 4,
                },
            },
        ),
        (
            ScatterClear.parse,
            {
                "group_name": "ScatterGroup",
                "expected_group_revision": "x" * 64,
                "recipe": "CUBE_SCATTER",
                "prefix": "Demo",
                "parameters": {
                    **cube_parameters(),
                    "scale": [0, 1, 1],
                },
            },
        ),
    ],
)
def test_scatter_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
