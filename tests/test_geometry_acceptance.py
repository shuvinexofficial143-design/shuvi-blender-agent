import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_acceptance import (
    GeometryAcceptanceOperations,
    GeometryWorkflowPreview,
    Level5Acceptance,
)
from shuvi_blender_agent.geometry_nodes import GeometryNodeOperations
from shuvi_blender_agent.geometry_recipe_library import GeometryRecipeLibraryOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry
from shuvi_blender_agent.verification import compare

PAYLOADS = {
    "primitive.cube": {"size": [2, 3, 4], "vertices": 3},
    "primitive.ico_sphere": {"radius": 2.0, "subdivisions": 2},
    "primitive.twin_cube": {
        "size": [1, 2, 3],
        "vertices": 4,
        "offset": [5, 0, 0],
    },
    "field.index_attribute": {
        "size": [2, 2, 2],
        "vertices": 3,
        "attribute_name": "shuvi_index",
    },
    "field.position_attribute": {
        "size": [2, 2, 2],
        "vertices": 3,
        "attribute_name": "shuvi_position",
    },
    "field.normal_attribute": {
        "size": [2, 2, 2],
        "vertices": 3,
        "attribute_name": "shuvi_normal",
    },
    "scatter.cube": {
        "point_size": [8, 6, 4],
        "point_vertices": [4, 4, 4],
        "rotation": [0, 0, 0],
        "scale": [0.5, 0.5, 0.5],
        "instance_size": [1, 1, 1],
        "instance_vertices": 2,
    },
    "scatter.ico_sphere": {
        "point_size": [8, 6, 4],
        "point_vertices": [4, 4, 4],
        "rotation": [0.1, 0.2, 0.3],
        "scale": [0.5, 0.5, 0.5],
        "instance_radius": 0.5,
        "instance_subdivisions": 2,
    },
    "architecture.modular_wall": {
        "module_size": [2, 0.5, 3],
        "count": 4,
        "gap": 0.25,
        "base_offset": [1, 2, 0],
    },
    "architecture.block_grid": {
        "block_size": [2, 3, 1],
        "count_x": 3,
        "count_y": 2,
        "gap_x": 0.5,
        "gap_y": 1.0,
        "base_offset": [-2, 1, 0.5],
    },
}

REPRESENTATIVE_RECIPES = [
    "primitive.cube",
    "field.index_attribute",
    "scatter.cube",
    "architecture.modular_wall",
]


def acceptance_payload(recipe_id="primitive.cube"):
    return {
        "recipe_id": recipe_id,
        "prefix": "Acceptance",
        "parameters": PAYLOADS[recipe_id],
    }


def acceptance_setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    acceptance = GeometryAcceptanceOperations(objects)
    registry = ToolRegistry(acceptance.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, acceptance, registry


def library_setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    geometry = GeometryNodeOperations(objects)
    library = GeometryRecipeLibraryOperations(objects)
    registry = ToolRegistry(
        [*geometry.tools(), *library.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, library, registry


def create_group(registry, name="AcceptanceGroup"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def recipe_apply_payload(recipe_id, revision_value):
    return {
        "recipe_id": recipe_id,
        "group_name": "AcceptanceGroup",
        "expected_group_revision": revision_value,
        "prefix": "Acceptance",
        "parameters": PAYLOADS[recipe_id],
    }


def test_factory_registers_final_level5_acceptance_under_existing_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 249
    assert MAX_REGISTERED_TOOLS == 249
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS
    names = {item["name"] for item in registry.catalog()}
    assert {
        "geometry_nodes.workflow_preview",
        "geometry_nodes.level5_acceptance",
    }.issubset(names)


def test_workflow_preview_is_deterministic_bounded_and_nonexecuting():
    bpy, acceptance, registry = acceptance_setup()

    first = registry.dispatch(Request("geometry_nodes.workflow_preview", acceptance_payload()))
    second = registry.dispatch(Request("geometry_nodes.workflow_preview", acceptance_payload()))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["source_gate_status"] == "READY"
    assert first.data["check_count"] == 7
    assert first.data["stage_count"] == 9
    assert first.data["fresh_group_revision_required_for_mutations"] is True
    assert first.data["automatic_mutation_execution"] is False
    assert first.data["cross_family_payloads_fail_closed"] is True
    assert first.data["verified_recovery_required"] is True
    assert first.data["runtime_acceptance_required"] is True
    assert first.data["real_runtime_verified"] is False
    assert first.data["production_ready"] is False
    assert len(first.data["workflow_revision"]) == 64


@pytest.mark.parametrize("recipe_id", sorted(PAYLOADS))
def test_level5_acceptance_passes_every_managed_recipe(recipe_id):
    bpy, acceptance, registry = acceptance_setup()

    result = registry.dispatch(
        Request(
            "geometry_nodes.level5_acceptance",
            acceptance_payload(recipe_id),
        )
    )

    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["source_acceptance_status"] == "READY"
    assert data["check_count"] == 7
    assert all(item["status"] == "PASS" for item in data["checks"])
    assert data["source_level_complete_when_passed"] == 5
    assert data["source_scope"] == "LEVEL_5_SOURCE_AND_FAKE_BPY_ACCEPTANCE_ONLY"
    assert data["fresh_state_required_for_mutations"] is True
    assert data["stale_state_must_fail_closed"] is True
    assert data["exact_readback_required"] is True
    assert data["verified_recovery_required"] is True
    assert data["runtime_acceptance_required"] is True
    assert data["real_runtime_verified"] is False
    assert data["production_ready"] is False
    assert len(data["catalog_revision"]) == 64
    assert len(data["acceptance_revision"]) == 64


@pytest.mark.parametrize("recipe_id", REPRESENTATIVE_RECIPES)
def test_recipe_library_preserves_stale_state_guard_across_all_families(recipe_id):
    bpy, library, registry = library_setup()
    empty = create_group(registry)

    changed = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "AcceptanceGroup",
                "expected_group_revision": empty["group_revision"],
                "node_type": "MESH_CUBE",
                "node_name": "External",
            },
        )
    )
    assert changed.status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.recipe_apply",
            recipe_apply_payload(recipe_id, empty["group_revision"]),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE


@pytest.mark.parametrize("recipe_id", REPRESENTATIVE_RECIPES)
def test_recipe_library_apply_recovery_is_verified_across_all_families(recipe_id):
    bpy, library, registry = library_setup()
    empty = create_group(registry)
    family = library._operation(recipe_id)
    original = family._verify_exact_plan
    calls = {"count": 0}

    def fail_once(snapshot, plan):
        calls["count"] += 1
        if calls["count"] == 1:
            return compare({"value": 1}, {"value": 2})
        return original(snapshot, plan)

    family._verify_exact_plan = fail_once

    result = registry.dispatch(
        Request(
            "geometry_nodes.recipe_apply",
            recipe_apply_payload(recipe_id, empty["group_revision"]),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    family_result = result.data["family_result"]
    assert family_result["rolled_back"] is True
    assert family_result["recovery_verified"] is True

    inspected = registry.dispatch(
        Request(
            "geometry_nodes.tree_inspect",
            {"group_name": "AcceptanceGroup"},
        )
    )
    assert inspected.status == Status.SUCCEEDED
    assert inspected.data["group_revision"] == empty["group_revision"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "recipe_id": "primitive.cube",
            "prefix": "Mismatch",
            "parameters": PAYLOADS["field.index_attribute"],
        },
        {
            "recipe_id": "field.index_attribute",
            "prefix": "Mismatch",
            "parameters": PAYLOADS["scatter.cube"],
        },
        {
            "recipe_id": "scatter.cube",
            "prefix": "Mismatch",
            "parameters": PAYLOADS["architecture.modular_wall"],
        },
        {
            "recipe_id": "architecture.modular_wall",
            "prefix": "Mismatch",
            "parameters": PAYLOADS["primitive.cube"],
        },
    ],
)
def test_acceptance_contract_rejects_cross_family_payloads(payload):
    with pytest.raises(AgentError):
        GeometryWorkflowPreview.parse(payload)
    with pytest.raises(AgentError):
        Level5Acceptance.parse(payload)
