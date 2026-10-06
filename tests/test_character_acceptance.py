import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.character_acceptance import (
    CharacterAcceptanceOperations,
    CharacterWorkflowPreview,
    Level3Acceptance,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    acceptance = CharacterAcceptanceOperations(objects)
    registry = ToolRegistry(acceptance.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, acceptance, registry


def cube_like(obj):
    obj.data.from_pydata(
        [
            [-1, -1, 0],
            [1, -1, 0],
            [1, 1, 0],
            [-1, 1, 0],
            [-1, -1, 2],
            [1, -1, 2],
            [1, 1, 2],
            [-1, 1, 2],
        ],
        [],
        [
            [0, 3, 2, 1],
            [4, 5, 6, 7],
            [0, 1, 5, 4],
            [1, 2, 6, 5],
            [2, 3, 7, 6],
            [3, 0, 4, 7],
        ],
    )


def payload(inspector, obj):
    return {
        "object_id": inspector.identity(obj),
        "preset": "ADULT_NEUTRAL",
        "front_direction": "POSITIVE_Y",
        "symmetry_tolerance": 0.001,
        "face_fit_threshold": 2,
        "recipe": "BODY_PRIMARY_FORMS",
        "intensity": 0.5,
    }


def test_character_workflow_preview_composes_level3_without_auto_mutation():
    bpy, inspector, acceptance, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(Request("character.workflow_preview", payload(inspector, obj)))
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["stage_count"] == 12
    assert data["fresh_state_required_per_mutation"] is True
    assert data["automatic_mutation_execution"] is False
    assert data["recovery_snapshot_required_before_mutation_group"] is True
    assert data["runtime_acceptance_required"] is True
    assert data["real_runtime_verified"] is False
    assert data["source_gate_status"] in {"READY", "REVIEW"}
    assert len(data["workflow_revision"]) == 64
    operations = [item["operation"] for item in data["stages"]]
    assert operations[0] == "character.landmark_fit"
    assert "character.sculpt_recovery_snapshot" in operations
    assert operations[-1] == "character.level3_acceptance"
    assert data["recipe_steps"]


def test_level3_source_acceptance_has_explicit_runtime_boundary():
    bpy, inspector, acceptance, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(Request("character.level3_acceptance", payload(inspector, obj)))
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["check_count"] == 8
    assert data["source_acceptance_status"] in {"READY", "REVIEW"}
    assert data["source_level_complete_when_passed"] == 3
    assert data["source_scope"] == "LEVEL_3_SOURCE_AND_FAKE_ADAPTER_ACCEPTANCE_ONLY"
    assert data["runtime_acceptance_required"] is True
    assert data["real_runtime_verified"] is False
    assert data["production_ready"] is False
    assert len(data["acceptance_revision"]) == 64
    names = {item["name"] for item in data["checks"]}
    assert {
        "BODY_LANDMARK_CANDIDATES",
        "BODY_REGION_PLAN",
        "FACE_LANDMARK_FIT",
        "FACE_REGION_PLAN",
        "FACE_SYMMETRY",
        "STRUCTURAL_SCULPT_QA",
        "RECIPE_PREVIEW",
        "SURFACE_BASELINE",
    } == names


def test_level3_source_acceptance_blocks_structurally_invalid_mesh():
    bpy, inspector, acceptance, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[-1, -1, 0], [1, -1, 0], [0, 1, 2], [0, 0, 1]],
        [],
        [[0, 1, 2]],
    )

    result = registry.dispatch(Request("character.level3_acceptance", payload(inspector, obj)))
    assert result.status == Status.SUCCEEDED
    assert result.data["source_acceptance_status"] == "BLOCKED"
    assert result.data["blockers"]


def test_workflow_acceptance_contract_validation():
    valid = {
        "object_id": "id",
        "preset": "ADULT_NEUTRAL",
        "front_direction": "POSITIVE_Y",
        "symmetry_tolerance": 0.001,
        "face_fit_threshold": 0.5,
        "recipe": "BODY_PRIMARY_FORMS",
        "intensity": 0.5,
    }
    assert CharacterWorkflowPreview.parse(valid).recipe == "BODY_PRIMARY_FORMS"
    assert Level3Acceptance.parse(valid).preset == "ADULT_NEUTRAL"

    with pytest.raises(AgentError):
        CharacterWorkflowPreview.parse(valid | {"preset": "UNKNOWN"})
    with pytest.raises(AgentError):
        CharacterWorkflowPreview.parse(valid | {"front_direction": "FRONT"})
    with pytest.raises(AgentError):
        CharacterWorkflowPreview.parse(valid | {"symmetry_tolerance": 0})
    with pytest.raises(AgentError):
        CharacterWorkflowPreview.parse(valid | {"face_fit_threshold": 0})
    with pytest.raises(AgentError):
        CharacterWorkflowPreview.parse(valid | {"recipe": "UNKNOWN"})
    with pytest.raises(AgentError):
        CharacterWorkflowPreview.parse(valid | {"intensity": 0})
