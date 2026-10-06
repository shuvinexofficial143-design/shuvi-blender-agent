import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Result, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling_qa import (
    ModelingQAOperations,
    QAInspect,
    WorkflowApply,
    WorkflowPreview,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    qa = ModelingQAOperations(objects)
    registry = ToolRegistry(qa.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, meshes, qa, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def qa_state(registry, inspector, obj, distance=0.001, area_epsilon=0.0):
    return registry.dispatch(
        Request(
            "modeling.qa_inspect",
            {
                "object_id": inspector.identity(obj),
                "distance": distance,
                "area_epsilon": area_epsilon,
            },
        )
    ).data


def test_qa_inspect_clean_quad_reports_clean_source_status():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2, 3]],
    )

    data = qa_state(registry, inspector, obj)
    assert data["qa_status"] == "CLEAN"
    assert data["blockers"] == []
    assert data["advisories"] == []
    assert data["quad_ratio"] == 1.0
    assert data["boundary_edge_count"] == 4
    assert data["high_degree_nonmanifold_edge_count"] == 0
    assert len(data["qa_revision"]) == 64


def test_qa_inspect_aggregates_repair_shading_retopology_and_modifier_findings():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [2, 0, 0],
            [0.0001, 0, 0],
            [9, 9, 9],
        ],
        [],
        [[0, 1, 2], [2, 1, 0], [0, 1, 3]],
    )
    broken = obj.modifiers.new("Broken", "BOOLEAN")
    broken.operation = "DIFFERENCE"
    broken.solver = "EXACT"
    broken.object = None

    data = qa_state(registry, inspector, obj)
    assert data["qa_status"] == "BLOCKED"
    assert "DEGENERATE_FACES" in data["blockers"]
    assert "DUPLICATE_FACES" in data["blockers"]
    assert "MISSING_MODIFIER_REFERENCES" in data["blockers"]
    assert "NEAR_DUPLICATE_VERTICES" in data["advisories"]
    assert "LOOSE_VERTICES" in data["advisories"]
    assert "TRIANGLE_FACES_PRESENT" in data["advisories"]
    assert data["modifier_diagnostics"]["missing_reference_indices"] == [0]


def test_workflow_preview_exposes_initial_triggers_without_mutation():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0.0001, 0, 0],
            [9, 9, 9],
        ],
        [],
        [[4, 1, 2, 3], [3, 2, 1, 4]],
    )
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "modeling.workflow_preview",
            {
                "object_id": inspector.identity(obj),
                "workflow": "CLEAN_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["initial_planned_steps"] == [
        "mesh.merge_by_distance",
        "mesh.cleanup_faces",
        "mesh.remove_loose_vertices",
    ]
    assert data["re_evaluate_after_each_step"] is True
    assert data["no_op"] is False
    assert len(data["workflow_revision"]) == 64
    assert meshes.snapshot(obj) == before


def test_clean_base_mesh_workflow_is_verified_and_preserves_surviving_smoothing():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0.0001, 0, 0],
            [9, 9, 9],
        ],
        [],
        [[4, 1, 2, 3], [3, 2, 1, 4]],
    )
    obj.data.polygons[0].use_smooth = True
    initial = qa_state(registry, inspector, obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "modeling.workflow_apply",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_qa_revision": initial["qa_revision"],
                "workflow": "CLEAN_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert [step["operation"] for step in after["executed_steps"]] == [
        "mesh.merge_by_distance",
        "mesh.remove_loose_vertices",
    ]
    assert after["qa"]["near_duplicate_vertex_group_count"] == 0
    assert after["qa"]["duplicate_face_group_count"] == 0
    assert after["qa"]["loose_vertex_count"] == 0
    assert meshes.snapshot(obj)["faces"] == [[0, 1, 2, 3]]
    assert [face.use_smooth for face in obj.data.polygons] == [True]


def test_clean_orient_workflow_fixes_winding_conflict():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 3, 2]],
    )
    initial = qa_state(registry, inspector, obj)
    assert initial["winding_conflict_edge_count"] == 1
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "modeling.workflow_apply",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_qa_revision": initial["qa_revision"],
                "workflow": "CLEAN_ORIENT_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert [step["operation"] for step in after["executed_steps"]] == [
        "mesh.orient_faces_consistently"
    ]
    assert after["qa"]["winding_conflict_edge_count"] == 0


def test_workflow_rejects_noop_clean_mesh():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2, 3]],
    )
    initial = qa_state(registry, inspector, obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "modeling.workflow_apply",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_qa_revision": initial["qa_revision"],
                "workflow": "CLEAN_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj) == before


def test_workflow_rejects_stale_qa_revision_before_mutation():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]],
        [],
        [[0, 1, 2]],
    )
    initial = qa_state(registry, inspector, obj)
    before = meshes.snapshot(obj)
    obj.data.polygons[0].use_smooth = True

    result = registry.dispatch(
        Request(
            "modeling.workflow_apply",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_qa_revision": initial["qa_revision"],
                "workflow": "CLEAN_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert meshes.snapshot(obj) == before


def test_workflow_failure_after_prior_step_restores_initial_geometry_and_smoothing():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0.0001, 0, 0],
        ],
        [],
        [[4, 1, 2], [4, 3, 2]],
    )
    obj.data.polygons[0].use_smooth = True
    before = meshes.snapshot(obj)
    smooth_before = [face.use_smooth for face in obj.data.polygons]
    initial = qa_state(registry, inspector, obj)

    def fail_orientation(request, action):
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {},
            AgentError(ErrorCode.EXECUTION_ERROR, "Injected orientation failure"),
        )

    qa.shading.orient_faces_consistently = fail_orientation
    result = registry.dispatch(
        Request(
            "modeling.workflow_apply",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_qa_revision": initial["qa_revision"],
                "workflow": "CLEAN_ORIENT_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert result.data["outcome"] == "known"
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert [step["operation"] for step in result.data["executed_steps"]] == [
        "mesh.merge_by_distance"
    ]
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]
    assert meshes.snapshot(obj)["faces"] == before["faces"]
    assert [face.use_smooth for face in obj.data.polygons] == smooth_before


def test_workflow_rebuild_metadata_guard_remains_in_force():
    bpy, inspector, meshes, qa, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]],
        [],
        [[0, 1, 2]],
    )
    material = bpy.data.materials.new("Protected")
    obj.data.materials.append(material)
    initial = qa_state(registry, inspector, obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "modeling.workflow_apply",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_qa_revision": initial["qa_revision"],
                "workflow": "CLEAN_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_milestone10_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        QAInspect.parse({"object_id": "id", "distance": 0, "area_epsilon": 0})
    with pytest.raises(AgentError):
        WorkflowPreview.parse(
            {
                "object_id": "id",
                "workflow": "UNKNOWN",
                "distance": 0.001,
                "area_epsilon": 0,
            }
        )
    with pytest.raises(AgentError):
        WorkflowApply.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "x" * 64,
                "expected_qa_revision": "y" * 64,
                "workflow": "CLEAN_BASE_MESH",
                "distance": 0.001,
                "area_epsilon": -1,
            }
        )
