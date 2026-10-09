import copy

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_architecture import (
    ArchitectureApply,
    ArchitectureClear,
    ArchitecturePreview,
    GeometryArchitectureOperations,
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
    architecture = GeometryArchitectureOperations(objects)
    registry = ToolRegistry(
        [*geometry.tools(), *architecture.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, geometry, architecture, registry


def create_group(registry, name="ArchitectureGroup"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def inspect(registry, name="ArchitectureGroup"):
    result = registry.dispatch(Request("geometry_nodes.tree_inspect", {"group_name": name}))
    assert result.status == Status.SUCCEEDED
    return result.data


def wall_parameters():
    return {
        "module_size": [2, 0.5, 3],
        "count": 4,
        "gap": 0.25,
        "base_offset": [1, 2, 0],
    }


def grid_parameters():
    return {
        "block_size": [2, 3, 1],
        "count_x": 3,
        "count_y": 2,
        "gap_x": 0.5,
        "gap_y": 1.0,
        "base_offset": [-2, 1, 0.5],
    }


def apply_payload(registry, recipe="MODULAR_WALL", prefix="ArchitectureDemo"):
    return {
        "group_name": "ArchitectureGroup",
        "expected_group_revision": inspect(registry)["group_revision"],
        "recipe": recipe,
        "prefix": prefix,
        "parameters": wall_parameters() if recipe == "MODULAR_WALL" else grid_parameters(),
    }


def test_factory_has_architecture_tools_within_raised_bounded_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 296
    assert MAX_REGISTERED_TOOLS == 296
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS
    names = {item["name"] for item in registry.catalog()}
    assert {
        "geometry_nodes.architecture_preview",
        "geometry_nodes.architecture_apply",
        "geometry_nodes.architecture_clear",
    }.issubset(names)


@pytest.mark.parametrize(
    ("recipe", "params", "module_count", "node_count", "link_count"),
    [
        ("MODULAR_WALL", wall_parameters(), 4, 10, 9),
        ("BLOCK_GRID", grid_parameters(), 6, 14, 13),
    ],
)
def test_preview_is_deterministic_and_reports_bounded_architecture(
    recipe,
    params,
    module_count,
    node_count,
    link_count,
):
    bpy, geometry, architecture, registry = setup()
    payload = {"recipe": recipe, "prefix": "Demo", "parameters": params}

    first = registry.dispatch(Request("geometry_nodes.architecture_preview", payload))
    second = registry.dispatch(Request("geometry_nodes.architecture_preview", payload))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["source_only"] is True
    assert first.data["real_runtime_verified"] is False
    assert first.data["architecture"] == {
        "module_count": module_count,
        "maximum_module_count": 24,
        "generated_node_count": node_count,
        "external_asset_references": False,
        "collection_references": False,
        "material_references": False,
    }
    assert len(first.data["nodes"]) == node_count
    assert len(first.data["links"]) == link_count
    assert len(first.data["architecture_revision"]) == 64


def test_modular_wall_plan_uses_exact_pitch_and_base_offset():
    bpy, geometry, architecture, registry = setup()
    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_preview",
            {
                "recipe": "MODULAR_WALL",
                "prefix": "Wall",
                "parameters": wall_parameters(),
            },
        )
    )
    assert result.status == Status.SUCCEEDED

    transforms = [
        item for item in result.data["nodes"] if item["node_type"] == "TRANSFORM_GEOMETRY"
    ]
    assert [item["inputs"]["Translation"] for item in transforms] == [
        [1.0, 2.0, 0.0],
        [3.25, 2.0, 0.0],
        [5.5, 2.0, 0.0],
        [7.75, 2.0, 0.0],
    ]


def test_block_grid_plan_uses_exact_xy_spacing():
    bpy, geometry, architecture, registry = setup()
    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_preview",
            {
                "recipe": "BLOCK_GRID",
                "prefix": "Grid",
                "parameters": grid_parameters(),
            },
        )
    )
    assert result.status == Status.SUCCEEDED

    transforms = [
        item for item in result.data["nodes"] if item["node_type"] == "TRANSFORM_GEOMETRY"
    ]
    assert [item["inputs"]["Translation"] for item in transforms] == [
        [-2.0, 1.0, 0.5],
        [0.5, 1.0, 0.5],
        [3.0, 1.0, 0.5],
        [-2.0, 5.0, 0.5],
        [0.5, 5.0, 0.5],
        [3.0, 5.0, 0.5],
    ]


def test_maximum_grid_stays_under_geometry_node_work_limit():
    bpy, geometry, architecture, registry = setup()
    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_preview",
            {
                "recipe": "BLOCK_GRID",
                "prefix": "MaxGrid",
                "parameters": {
                    **grid_parameters(),
                    "count_x": 6,
                    "count_y": 4,
                },
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["architecture"]["module_count"] == 24
    assert result.data["architecture"]["generated_node_count"] == 50
    assert len(result.data["nodes"]) == 50


def test_grid_rejects_module_count_above_24():
    with pytest.raises(AgentError):
        ArchitecturePreview.parse(
            {
                "recipe": "BLOCK_GRID",
                "prefix": "TooMany",
                "parameters": {
                    **grid_parameters(),
                    "count_x": 5,
                    "count_y": 5,
                },
            }
        )


@pytest.mark.parametrize(
    ("recipe", "params", "module_count"),
    [
        ("MODULAR_WALL", wall_parameters(), 4),
        ("BLOCK_GRID", grid_parameters(), 6),
    ],
)
def test_apply_creates_exact_architecture_graph(recipe, params, module_count):
    bpy, geometry, architecture, registry = setup()
    before = create_group(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_apply",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": recipe,
                "prefix": "Demo",
                "parameters": params,
            },
        )
    )

    assert result.status == Status.VERIFIED
    assert result.data["before"]["group_revision"] == before["group_revision"]
    assert result.data["architecture"]["module_count"] == module_count
    after = result.data["after"]
    assert after["node_count"] == module_count * 2 + 2
    assert after["link_count"] == module_count * 2 + 1
    assert len(after["interface"]) == 1

    join = next(item for item in after["nodes"] if item["name"] == "Demo_Join")
    output = next(item for item in after["nodes"] if item["name"] == "Demo_Output")
    assert join["bl_idname"] == "GeometryNodeJoinGeometry"
    assert output["bl_idname"] == "NodeGroupOutput"

    links_to_join = [
        item
        for item in after["links"]
        if item["to_node"] == "Demo_Join" and item["to_socket"] == "Geometry"
    ]
    assert len(links_to_join) == module_count
    assert (
        "Demo_Join",
        "Geometry",
        "Demo_Output",
        "Geometry",
    ) in {
        (
            item["from_node"],
            item["from_socket"],
            item["to_node"],
            item["to_socket"],
        )
        for item in after["links"]
    }


def test_apply_requires_empty_group_and_fresh_revision():
    bpy, geometry, architecture, registry = setup()
    original = create_group(registry)
    stale = original["group_revision"]

    added = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": stale,
                "node_type": "MESH_CUBE",
                "node_name": "Existing",
            },
        )
    )
    assert added.status == Status.VERIFIED

    nonempty = registry.dispatch(
        Request(
            "geometry_nodes.architecture_apply",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": "MODULAR_WALL",
                "prefix": "Demo",
                "parameters": wall_parameters(),
            },
        )
    )
    assert nonempty.error.code == ErrorCode.SAFETY_DENIED

    stale_result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_apply",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": stale,
                "recipe": "MODULAR_WALL",
                "prefix": "Demo",
                "parameters": wall_parameters(),
            },
        )
    )
    assert stale_result.error.code == ErrorCode.STALE_STATE


def test_shared_group_is_denied_for_apply_and_clear():
    bpy, geometry, architecture, registry = setup()
    create_group(registry)
    group = bpy.data.node_groups.get("ArchitectureGroup")
    group.users = 2

    denied = registry.dispatch(
        Request("geometry_nodes.architecture_apply", apply_payload(registry))
    )
    assert denied.error.code == ErrorCode.SAFETY_DENIED

    group.users = 0
    applied = registry.dispatch(
        Request("geometry_nodes.architecture_apply", apply_payload(registry))
    )
    assert applied.status == Status.VERIFIED
    group.users = 2

    clear_payload = {
        "group_name": "ArchitectureGroup",
        "expected_group_revision": inspect(registry)["group_revision"],
        "recipe": "MODULAR_WALL",
        "prefix": "ArchitectureDemo",
        "parameters": wall_parameters(),
    }
    cleared = registry.dispatch(Request("geometry_nodes.architecture_clear", clear_payload))
    assert cleared.error.code == ErrorCode.SAFETY_DENIED


def test_clear_exact_architecture_restores_empty_group():
    bpy, geometry, architecture, registry = setup()
    empty = create_group(registry)
    applied = registry.dispatch(
        Request("geometry_nodes.architecture_apply", apply_payload(registry))
    )
    assert applied.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_clear",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": inspect(registry)["group_revision"],
                "recipe": "MODULAR_WALL",
                "prefix": "ArchitectureDemo",
                "parameters": wall_parameters(),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["node_count"] == 0
    assert result.data["after"]["link_count"] == 0
    assert result.data["after"]["interface"] == []
    assert result.data["after"]["group_revision"] == empty["group_revision"]


def test_clear_refuses_modified_architecture_transform():
    bpy, geometry, architecture, registry = setup()
    create_group(registry)
    applied = registry.dispatch(
        Request("geometry_nodes.architecture_apply", apply_payload(registry))
    )
    assert applied.status == Status.VERIFIED

    group = bpy.data.node_groups.get("ArchitectureGroup")
    transform = group.nodes.get("ArchitectureDemo_Module01_Transform")
    transform.inputs["Translation"].default_value = [99.0, 2.0, 0.0]
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_clear",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": before["group_revision"],
                "recipe": "MODULAR_WALL",
                "prefix": "ArchitectureDemo",
                "parameters": wall_parameters(),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_apply_verification_failure_rolls_back_to_empty_group():
    bpy, geometry, architecture, registry = setup()
    before = create_group(registry)
    original = architecture._verify_exact_plan
    calls = {"count": 0}

    def fail_once(snapshot, plan):
        calls["count"] += 1
        if calls["count"] == 1:
            return compare({"value": 1}, {"value": 2})
        return original(snapshot, plan)

    architecture._verify_exact_plan = fail_once
    result = registry.dispatch(
        Request("geometry_nodes.architecture_apply", apply_payload(registry))
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_clear_verification_failure_rebuilds_exact_architecture():
    bpy, geometry, architecture, registry = setup()
    create_group(registry)
    applied = registry.dispatch(
        Request("geometry_nodes.architecture_apply", apply_payload(registry))
    )
    assert applied.status == Status.VERIFIED
    before = inspect(registry)
    original_snapshot = architecture.geometry._snapshot
    calls = {"count": 0}

    def corrupt_empty_once(group):
        calls["count"] += 1
        snapshot = original_snapshot(group)
        if calls["count"] == 2 and snapshot["node_count"] == 0:
            broken = copy.deepcopy(snapshot)
            broken["node_count"] = 1
            return broken
        return snapshot

    architecture.geometry._snapshot = corrupt_empty_once
    result = registry.dispatch(
        Request(
            "geometry_nodes.architecture_clear",
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": before["group_revision"],
                "recipe": "MODULAR_WALL",
                "prefix": "ArchitectureDemo",
                "parameters": wall_parameters(),
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = original_snapshot(bpy.data.node_groups.get("ArchitectureGroup"))
    assert restored["group_revision"] == before["group_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            ArchitecturePreview.parse,
            {
                "recipe": "UNSAFE",
                "prefix": "Demo",
                "parameters": wall_parameters(),
            },
        ),
        (
            ArchitecturePreview.parse,
            {
                "recipe": "MODULAR_WALL",
                "prefix": "",
                "parameters": wall_parameters(),
            },
        ),
        (
            ArchitecturePreview.parse,
            {
                "recipe": "MODULAR_WALL",
                "prefix": "Demo",
                "parameters": {**wall_parameters(), "count": 17},
            },
        ),
        (
            ArchitecturePreview.parse,
            {
                "recipe": "BLOCK_GRID",
                "prefix": "Demo",
                "parameters": {**grid_parameters(), "gap_x": -1},
            },
        ),
        (
            ArchitectureApply.parse,
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": "x" * 64,
                "recipe": "BLOCK_GRID",
                "prefix": "Demo",
                "parameters": {**grid_parameters(), "count_x": 0},
            },
        ),
        (
            ArchitectureClear.parse,
            {
                "group_name": "ArchitectureGroup",
                "expected_group_revision": "x" * 64,
                "recipe": "MODULAR_WALL",
                "prefix": "Demo",
                "parameters": {
                    **wall_parameters(),
                    "module_size": [0, 1, 1],
                },
            },
        ),
    ],
)
def test_architecture_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
