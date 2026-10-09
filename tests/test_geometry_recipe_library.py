import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_recipe_library import (
    COMPATIBILITY,
    LIBRARY_VERSION,
    MIN_BLENDER_VERSION,
    RECIPE_SPECS,
    RecipeApply,
    RecipeCatalog,
    RecipeClear,
    RecipePreview,
)
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS

EXAMPLES = {
    "primitive.cube": {
        "parameters": {"size": [2, 3, 4], "vertices": 3},
        "direct_tool": "geometry_nodes.primitive_preview",
        "direct_key": "recipe",
        "direct_value": "CUBE",
    },
    "primitive.ico_sphere": {
        "parameters": {"radius": 2.0, "subdivisions": 2},
        "direct_tool": "geometry_nodes.primitive_preview",
        "direct_key": "recipe",
        "direct_value": "ICO_SPHERE",
    },
    "primitive.twin_cube": {
        "parameters": {
            "size": [1, 2, 3],
            "vertices": 4,
            "offset": [5, 0, 0],
        },
        "direct_tool": "geometry_nodes.primitive_preview",
        "direct_key": "recipe",
        "direct_value": "TWIN_CUBE",
    },
    "field.index_attribute": {
        "parameters": {
            "size": [2, 2, 2],
            "vertices": 3,
            "attribute_name": "shuvi_index",
        },
        "direct_tool": "geometry_nodes.field_preview",
        "direct_key": "workflow",
        "direct_value": "INDEX_ATTRIBUTE",
    },
    "field.position_attribute": {
        "parameters": {
            "size": [2, 2, 2],
            "vertices": 3,
            "attribute_name": "shuvi_position",
        },
        "direct_tool": "geometry_nodes.field_preview",
        "direct_key": "workflow",
        "direct_value": "POSITION_ATTRIBUTE",
    },
    "field.normal_attribute": {
        "parameters": {
            "size": [2, 2, 2],
            "vertices": 3,
            "attribute_name": "shuvi_normal",
        },
        "direct_tool": "geometry_nodes.field_preview",
        "direct_key": "workflow",
        "direct_value": "NORMAL_ATTRIBUTE",
    },
    "scatter.cube": {
        "parameters": {
            "point_size": [8, 6, 4],
            "point_vertices": [4, 4, 4],
            "rotation": [0, 0, 0],
            "scale": [0.5, 0.5, 0.5],
            "instance_size": [1, 1, 1],
            "instance_vertices": 2,
        },
        "direct_tool": "geometry_nodes.scatter_preview",
        "direct_key": "recipe",
        "direct_value": "CUBE_SCATTER",
    },
    "scatter.ico_sphere": {
        "parameters": {
            "point_size": [8, 6, 4],
            "point_vertices": [4, 4, 4],
            "rotation": [0.1, 0.2, 0.3],
            "scale": [0.5, 0.5, 0.5],
            "instance_radius": 0.5,
            "instance_subdivisions": 2,
        },
        "direct_tool": "geometry_nodes.scatter_preview",
        "direct_key": "recipe",
        "direct_value": "ICO_SPHERE_SCATTER",
    },
    "architecture.modular_wall": {
        "parameters": {
            "module_size": [2, 0.5, 3],
            "count": 4,
            "gap": 0.25,
            "base_offset": [1, 2, 0],
        },
        "direct_tool": "geometry_nodes.architecture_preview",
        "direct_key": "recipe",
        "direct_value": "MODULAR_WALL",
    },
    "architecture.block_grid": {
        "parameters": {
            "block_size": [2, 3, 1],
            "count_x": 3,
            "count_y": 2,
            "gap_x": 0.5,
            "gap_y": 1.0,
            "base_offset": [-2, 1, 0.5],
        },
        "direct_tool": "geometry_nodes.architecture_preview",
        "direct_key": "recipe",
        "direct_value": "BLOCK_GRID",
    },
}


def registry():
    return create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))


def create_group(reg, name="RecipeGroup"):
    result = reg.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def test_factory_registers_recipe_library_under_existing_cap():
    reg = registry()
    assert len(reg.catalog()) == 314
    assert MAX_REGISTERED_TOOLS == 314
    assert len(reg.catalog()) == MAX_REGISTERED_TOOLS
    names = {item["name"] for item in reg.catalog()}
    assert {
        "geometry_nodes.recipe_catalog",
        "geometry_nodes.recipe_preview",
        "geometry_nodes.recipe_apply",
        "geometry_nodes.recipe_clear",
    }.issubset(names)


def test_catalog_is_deterministic_versioned_and_complete():
    reg = registry()

    first = reg.dispatch(Request("geometry_nodes.recipe_catalog", {}))
    second = reg.dispatch(Request("geometry_nodes.recipe_catalog", {}))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["library_version"] == LIBRARY_VERSION == 1
    assert first.data["minimum_blender_version"] == MIN_BLENDER_VERSION == "4.2"
    assert first.data["compatibility"] == COMPATIBILITY
    assert first.data["recipe_count"] == len(RECIPE_SPECS) == 10
    assert [item["recipe_id"] for item in first.data["recipes"]] == sorted(RECIPE_SPECS)
    assert len(first.data["catalog_revision"]) == 64

    for item in first.data["recipes"]:
        assert item["recipe_version"] == 1
        assert item["library_version"] == 1
        assert item["operations"] == ["preview", "apply", "clear"]
        assert item["source_only"] is True
        assert item["real_runtime_verified"] is False
        assert item["parameter_schema"]


@pytest.mark.parametrize("recipe_id", sorted(EXAMPLES))
def test_recipe_preview_matches_direct_managed_family(recipe_id):
    reg = registry()
    example = EXAMPLES[recipe_id]
    prefix = "LibraryDemo"

    library_result = reg.dispatch(
        Request(
            "geometry_nodes.recipe_preview",
            {
                "recipe_id": recipe_id,
                "prefix": prefix,
                "parameters": example["parameters"],
            },
        )
    )
    direct_result = reg.dispatch(
        Request(
            example["direct_tool"],
            {
                example["direct_key"]: example["direct_value"],
                "prefix": prefix,
                "parameters": example["parameters"],
            },
        )
    )

    assert library_result.status == Status.SUCCEEDED
    assert direct_result.status == Status.SUCCEEDED
    assert library_result.data["family_result"] == direct_result.data

    metadata = library_result.data["recipe"]
    assert metadata["recipe_id"] == recipe_id
    assert metadata["family"] == RECIPE_SPECS[recipe_id]["family"]
    assert metadata["family_recipe"] == RECIPE_SPECS[recipe_id]["family_recipe"]
    assert metadata["library_version"] == 1
    assert metadata["recipe_version"] == 1
    assert metadata["minimum_blender_version"] == "4.2"
    assert metadata["compatibility"] == COMPATIBILITY
    assert metadata["source_only"] is True
    assert metadata["real_runtime_verified"] is False


@pytest.mark.parametrize("recipe_id", sorted(EXAMPLES))
def test_all_library_recipes_apply_and_clear_through_verified_family_path(recipe_id):
    reg = registry()
    empty = create_group(reg)
    example = EXAMPLES[recipe_id]
    prefix = "RoundTrip"

    applied = reg.dispatch(
        Request(
            "geometry_nodes.recipe_apply",
            {
                "recipe_id": recipe_id,
                "group_name": "RecipeGroup",
                "expected_group_revision": empty["group_revision"],
                "prefix": prefix,
                "parameters": example["parameters"],
            },
        )
    )

    assert applied.status == Status.VERIFIED
    assert applied.verification["matched"] is True
    family_applied = applied.data["family_result"]
    assert family_applied["before"]["group_revision"] == empty["group_revision"]
    changed_revision = family_applied["after"]["group_revision"]
    assert changed_revision != empty["group_revision"]

    cleared = reg.dispatch(
        Request(
            "geometry_nodes.recipe_clear",
            {
                "recipe_id": recipe_id,
                "group_name": "RecipeGroup",
                "expected_group_revision": changed_revision,
                "prefix": prefix,
                "parameters": example["parameters"],
            },
        )
    )

    assert cleared.status == Status.VERIFIED
    assert cleared.verification["matched"] is True
    family_cleared = cleared.data["family_result"]
    assert family_cleared["after"]["node_count"] == 0
    assert family_cleared["after"]["link_count"] == 0
    assert family_cleared["after"]["interface"] == []
    assert family_cleared["after"]["group_revision"] == empty["group_revision"]


def test_library_apply_preserves_underlying_stale_revision_guard():
    reg = registry()
    empty = create_group(reg)
    changed = reg.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "RecipeGroup",
                "expected_group_revision": empty["group_revision"],
                "node_type": "MESH_CUBE",
                "node_name": "External",
            },
        )
    )
    assert changed.status == Status.VERIFIED

    result = reg.dispatch(
        Request(
            "geometry_nodes.recipe_apply",
            {
                "recipe_id": "primitive.cube",
                "group_name": "RecipeGroup",
                "expected_group_revision": empty["group_revision"],
                "prefix": "LibraryDemo",
                "parameters": EXAMPLES["primitive.cube"]["parameters"],
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (RecipeCatalog.parse, {"unexpected": True}),
        (
            RecipePreview.parse,
            {
                "recipe_id": "unknown.recipe",
                "prefix": "Demo",
                "parameters": {},
            },
        ),
        (
            RecipePreview.parse,
            {
                "recipe_id": "field.index_attribute",
                "prefix": "Demo",
                "parameters": {
                    "size": [1, 1, 1],
                    "vertices": 3,
                    "attribute_name": "unsafe",
                },
            },
        ),
        (
            RecipeApply.parse,
            {
                "recipe_id": "scatter.cube",
                "group_name": "RecipeGroup",
                "expected_group_revision": "x" * 64,
                "prefix": "Demo",
                "parameters": {
                    **EXAMPLES["scatter.cube"]["parameters"],
                    "point_vertices": [20, 20, 20],
                },
            },
        ),
        (
            RecipeClear.parse,
            {
                "recipe_id": "architecture.modular_wall",
                "group_name": "RecipeGroup",
                "expected_group_revision": "x" * 64,
                "prefix": "Demo",
                "parameters": {
                    **EXAMPLES["architecture.modular_wall"]["parameters"],
                    "count": 17,
                },
            },
        ),
    ],
)
def test_recipe_library_contracts_reject_invalid_or_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
