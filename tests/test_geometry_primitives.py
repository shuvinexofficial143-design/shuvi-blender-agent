import copy

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_nodes import GeometryNodeOperations
from shuvi_blender_agent.geometry_primitives import (
    PrimitiveApply,
    PrimitiveClear,
    PrimitivePreview,
    ProceduralPrimitiveOperations,
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
    primitives = ProceduralPrimitiveOperations(objects)
    registry = ToolRegistry(
        [*geometry.tools(), *primitives.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, geometry, primitives, registry


def create_group(registry, name="Procedural"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def inspect(registry, name="Procedural"):
    result = registry.dispatch(Request("geometry_nodes.tree_inspect", {"group_name": name}))
    assert result.status == Status.SUCCEEDED
    return result.data


def apply_payload(registry, recipe="CUBE", prefix="Block", parameters=None):
    if parameters is None:
        parameters = {"size": [2, 3, 4], "vertices": 3}
    return {
        "group_name": "Procedural",
        "expected_group_revision": inspect(registry)["group_revision"],
        "recipe": recipe,
        "prefix": prefix,
        "parameters": parameters,
    }


def test_factory_reaches_bounded_cap_exactly():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 274
    assert MAX_REGISTERED_TOOLS == 274
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS


@pytest.mark.parametrize(
    ("recipe", "parameters", "expected_nodes", "expected_links"),
    [
        ("CUBE", {"size": [2, 3, 4], "vertices": 3}, 2, 1),
        ("ICO_SPHERE", {"radius": 2.5, "subdivisions": 3}, 2, 1),
        (
            "TWIN_CUBE",
            {"size": [1, 2, 3], "vertices": 4, "offset": [5, 0, 0]},
            5,
            4,
        ),
    ],
)
def test_preview_is_deterministic_and_source_only(
    recipe,
    parameters,
    expected_nodes,
    expected_links,
):
    bpy, geometry, primitives, registry = setup()
    payload = {"recipe": recipe, "prefix": "Demo", "parameters": parameters}

    first = registry.dispatch(Request("geometry_nodes.primitive_preview", payload))
    second = registry.dispatch(Request("geometry_nodes.primitive_preview", payload))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["source_only"] is True
    assert first.data["real_runtime_verified"] is False
    assert len(first.data["nodes"]) == expected_nodes
    assert len(first.data["links"]) == expected_links
    assert first.data["interface"] == [
        {
            "name": "Geometry",
            "direction": "OUTPUT",
            "socket_type": "NodeSocketGeometry",
        }
    ]
    assert len(first.data["primitive_revision"]) == 64


@pytest.mark.parametrize(
    ("recipe", "parameters", "node_count", "link_count"),
    [
        ("CUBE", {"size": [2, 3, 4], "vertices": 3}, 2, 1),
        ("ICO_SPHERE", {"radius": 2.5, "subdivisions": 3}, 2, 1),
        (
            "TWIN_CUBE",
            {"size": [1, 2, 3], "vertices": 4, "offset": [5, 0, 0]},
            5,
            4,
        ),
    ],
)
def test_apply_creates_exact_recipe_graph(recipe, parameters, node_count, link_count):
    bpy, geometry, primitives, registry = setup()
    before = create_group(registry)
    payload = apply_payload(registry, recipe, "Demo", parameters)

    result = registry.dispatch(Request("geometry_nodes.primitive_apply", payload))

    assert result.status == Status.VERIFIED
    assert result.data["before"]["group_revision"] == before["group_revision"]
    after = result.data["after"]
    assert after["node_count"] == node_count
    assert after["link_count"] == link_count
    assert after["interface"] == [
        {
            "name": "Geometry",
            "identifier": "Geometry",
            "direction": "OUTPUT",
            "socket_type": "NodeSocketGeometry",
        }
    ]
    output = next(item for item in after["nodes"] if item["name"] == "Demo_Output")
    assert output["bl_idname"] == "NodeGroupOutput"
    assert output["managed_type"] is False
    assert result.data["primitive_revision"]


def test_twin_cube_exact_links_and_defaults_are_read_back():
    bpy, geometry, primitives, registry = setup()
    create_group(registry)
    payload = apply_payload(
        registry,
        "TWIN_CUBE",
        "Pair",
        {"size": [1, 2, 3], "vertices": 5, "offset": [4, -2, 1]},
    )

    result = registry.dispatch(Request("geometry_nodes.primitive_apply", payload))
    assert result.status == Status.VERIFIED
    after = result.data["after"]

    names = {item["name"] for item in after["nodes"]}
    assert names == {
        "Pair_CubeA",
        "Pair_CubeB",
        "Pair_TransformB",
        "Pair_Join",
        "Pair_Output",
    }
    transform = next(item for item in after["nodes"] if item["name"] == "Pair_TransformB")
    values = {item["name"]: item["default_value"] for item in transform["inputs"]}
    assert values["Translation"] == [4.0, -2.0, 1.0]
    assert values["Rotation"] == [0.0, 0.0, 0.0]
    assert values["Scale"] == [1.0, 1.0, 1.0]
    assert {
        (
            item["from_node"],
            item["from_socket"],
            item["to_node"],
            item["to_socket"],
        )
        for item in after["links"]
    } == {
        ("Pair_CubeA", "Mesh", "Pair_Join", "Geometry"),
        ("Pair_CubeB", "Mesh", "Pair_TransformB", "Geometry"),
        ("Pair_TransformB", "Geometry", "Pair_Join", "Geometry"),
        ("Pair_Join", "Geometry", "Pair_Output", "Geometry"),
    }


def test_apply_requires_empty_group_and_fresh_revision():
    bpy, geometry, primitives, registry = setup()
    group = create_group(registry)
    stale = group["group_revision"]

    added = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "Procedural",
                "expected_group_revision": stale,
                "node_type": "MESH_CUBE",
                "node_name": "Existing",
            },
        )
    )
    assert added.status == Status.VERIFIED

    nonempty = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            {
                "group_name": "Procedural",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": "CUBE",
                "prefix": "Block",
                "parameters": {"size": [1, 1, 1], "vertices": 2},
            },
        )
    )
    assert nonempty.error.code == ErrorCode.SAFETY_DENIED

    stale_result = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            {
                "group_name": "Procedural",
                "expected_group_revision": stale,
                "recipe": "CUBE",
                "prefix": "Block",
                "parameters": {"size": [1, 1, 1], "vertices": 2},
            },
        )
    )
    assert stale_result.error.code == ErrorCode.STALE_STATE


def test_shared_group_is_denied_before_apply_or_clear():
    bpy, geometry, primitives, registry = setup()
    create_group(registry)
    group = bpy.data.node_groups.get("Procedural")
    group.users = 2

    denied = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            apply_payload(registry),
        )
    )
    assert denied.error.code == ErrorCode.SAFETY_DENIED

    group.users = 0
    applied = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            apply_payload(registry),
        )
    )
    assert applied.status == Status.VERIFIED
    group.users = 2

    clear_payload = {
        "group_name": "Procedural",
        "expected_group_revision": inspect(registry)["group_revision"],
        "recipe": "CUBE",
        "prefix": "Block",
        "parameters": {"size": [2, 3, 4], "vertices": 3},
    }
    cleared = registry.dispatch(Request("geometry_nodes.primitive_clear", clear_payload))
    assert cleared.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["node_count"] == 2


def test_clear_exact_recipe_restores_empty_group():
    bpy, geometry, primitives, registry = setup()
    empty = create_group(registry)
    applied = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            apply_payload(registry),
        )
    )
    assert applied.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.primitive_clear",
            {
                "group_name": "Procedural",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": "CUBE",
                "prefix": "Block",
                "parameters": {"size": [2, 3, 4], "vertices": 3},
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["node_count"] == 0
    assert result.data["after"]["link_count"] == 0
    assert result.data["after"]["interface"] == []
    assert result.data["after"]["group_revision"] == empty["group_revision"]


def test_clear_refuses_graph_that_no_longer_exactly_matches_recipe():
    bpy, geometry, primitives, registry = setup()
    create_group(registry)
    applied = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            apply_payload(registry),
        )
    )
    assert applied.status == Status.VERIFIED
    group = bpy.data.node_groups.get("Procedural")
    cube = group.nodes.get("Block_Cube")
    cube.inputs["Size"].default_value = [9.0, 9.0, 9.0]
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.primitive_clear",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "recipe": "CUBE",
                "prefix": "Block",
                "parameters": {"size": [2, 3, 4], "vertices": 3},
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_apply_verification_failure_rolls_back_to_exact_empty_revision():
    bpy, geometry, primitives, registry = setup()
    before = create_group(registry)
    original = primitives._verify_exact_plan
    calls = {"count": 0}

    def fail_once(snapshot, plan):
        calls["count"] += 1
        if calls["count"] == 1:
            return compare({"value": 1}, {"value": 2})
        return original(snapshot, plan)

    primitives._verify_exact_plan = fail_once
    result = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            apply_payload(registry),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_clear_verification_failure_rebuilds_exact_recipe():
    bpy, geometry, primitives, registry = setup()
    create_group(registry)
    applied = registry.dispatch(
        Request(
            "geometry_nodes.primitive_apply",
            apply_payload(registry),
        )
    )
    assert applied.status == Status.VERIFIED
    before = inspect(registry)
    original_snapshot = primitives.geometry._snapshot
    calls = {"count": 0}

    def corrupt_empty_once(group):
        calls["count"] += 1
        snapshot = original_snapshot(group)
        if calls["count"] == 2 and snapshot["node_count"] == 0:
            broken = copy.deepcopy(snapshot)
            broken["node_count"] = 1
            return broken
        return snapshot

    primitives.geometry._snapshot = corrupt_empty_once
    result = registry.dispatch(
        Request(
            "geometry_nodes.primitive_clear",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "recipe": "CUBE",
                "prefix": "Block",
                "parameters": {"size": [2, 3, 4], "vertices": 3},
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = original_snapshot(bpy.data.node_groups.get("Procedural"))
    assert restored["group_revision"] == before["group_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            PrimitivePreview.parse,
            {"recipe": "UNSAFE", "prefix": "Demo", "parameters": {}},
        ),
        (
            PrimitivePreview.parse,
            {
                "recipe": "CUBE",
                "prefix": "",
                "parameters": {"size": [1, 1, 1], "vertices": 2},
            },
        ),
        (
            PrimitivePreview.parse,
            {
                "recipe": "CUBE",
                "prefix": "Demo",
                "parameters": {"size": [1, 1], "vertices": 2},
            },
        ),
        (
            PrimitiveApply.parse,
            {
                "group_name": "Procedural",
                "expected_group_revision": "x" * 64,
                "recipe": "ICO_SPHERE",
                "prefix": "Demo",
                "parameters": {"radius": 0, "subdivisions": 2},
            },
        ),
        (
            PrimitiveClear.parse,
            {
                "group_name": "Procedural",
                "expected_group_revision": "x" * 64,
                "recipe": "TWIN_CUBE",
                "prefix": "Demo",
                "parameters": {
                    "size": [1, 1, 1],
                    "vertices": 2,
                    "offset": [1001, 0, 0],
                },
            },
        ),
    ],
)
def test_primitive_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
