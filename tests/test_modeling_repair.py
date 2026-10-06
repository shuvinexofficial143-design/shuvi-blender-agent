import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling_repair import (
    CleanupFaces,
    MergeByDistance,
    ModelingRepairOperations,
    RemoveLooseVertices,
    RepairInspect,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    repair = ModelingRepairOperations(objects)
    registry = ToolRegistry(
        repair.tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, repair, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def test_repair_inspect_reports_duplicate_near_duplicate_degenerate_and_loose_data():
    bpy, inspector, meshes, repair, registry = setup()
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

    result = registry.dispatch(
        Request(
            "mesh.repair_inspect",
            {
                "object_id": inspector.identity(obj),
                "distance": 0.001,
                "area_epsilon": 0.0,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["near_duplicate_vertex_groups"] == [[0, 4]]
    assert data["duplicate_face_groups"] == [[0, 1]]
    assert data["degenerate_face_indices"] == [2]
    assert data["loose_vertex_indices"] == [4, 5]
    assert data["face_component_count"] == 1
    assert data["zero_length_edge_count"] == 0
    assert len(data["repair_revision"]) == 64
    assert data["geometry_revision"] == meshes.snapshot(obj)["geometry_revision"]


def test_merge_by_distance_compacts_vertices_and_preserves_smoothing():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.0001, 0, 0]],
        [],
        [[4, 1, 2, 3]],
    )
    obj.data.polygons[0].use_smooth = True
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "mesh.merge_by_distance",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "distance": 0.001,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["vertices"] == [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
    assert after["faces"] == [[0, 1, 2, 3]]
    assert after["merged_vertex_groups"] == [[0, 4]]
    assert after["merged_vertex_count"] == 1
    assert after["face_smooth"] == [True]


def test_merge_by_distance_removes_faces_collapsed_by_merge():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [0.001, 0, 0], [0, 1, 0], [2, 0, 0], [2, 1, 0]],
        [],
        [[0, 1, 2], [1, 3, 4, 2]],
    )
    obj.data.polygons[1].use_smooth = True
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "mesh.merge_by_distance",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "distance": 0.01,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["removed_degenerate_face_indices"] == [0]
    assert after["faces"] == [[0, 2, 3, 1]]
    assert after["face_smooth"] == [True]


def test_merge_by_distance_rejects_noop():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [], [[0, 1, 2]])
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.merge_by_distance",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "distance": 0.001,
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]


def test_cleanup_faces_removes_degenerate_and_duplicate_faces_preserving_smooth():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [4, 0, 0]],
        [],
        [[0, 1, 2, 3], [3, 2, 1, 0], [0, 1, 4]],
    )
    obj.data.polygons[0].use_smooth = True
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "mesh.cleanup_faces",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "area_epsilon": 0.0,
                "remove_duplicate_faces": True,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["faces"] == [[0, 1, 2, 3]]
    assert after["removed_duplicate_face_indices"] == [1]
    assert after["removed_degenerate_face_indices"] == [2]
    assert after["face_smooth"] == [True]


def test_cleanup_faces_rejects_when_nothing_matches():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [], [[0, 1, 2]])
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.cleanup_faces",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "area_epsilon": 0.0,
                "remove_duplicate_faces": True,
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST


def test_remove_loose_vertices_compacts_indices_and_preserves_smoothing():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[9, 9, 9], [0, 0, 0], [1, 0, 0], [0, 1, 0], [8, 8, 8]],
        [],
        [[1, 2, 3]],
    )
    obj.data.polygons[0].use_smooth = True
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "mesh.remove_loose_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["removed_loose_vertex_indices"] == [0, 4]
    assert after["vertices"] == [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    assert after["faces"] == [[0, 1, 2]]
    assert after["face_smooth"] == [True]


def test_remove_loose_vertices_rejects_noop():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [], [[0, 1, 2]])
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.remove_loose_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST


def test_repair_mutation_rejects_mesh_metadata_that_rebuild_cannot_preserve():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]],
        [],
        [[0, 1, 2]],
    )
    material = bpy.data.materials.new("Protected")
    obj.data.materials.append(material)
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.remove_loose_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_repair_verification_failure_restores_geometry_and_smoothing():
    bpy, inspector, meshes, repair, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[9, 9, 9], [0, 0, 0], [1, 0, 0], [0, 1, 0]],
        [],
        [[1, 2, 3]],
    )
    obj.data.polygons[0].use_smooth = True
    before = meshes.snapshot(obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 2:
            obj.data.vertices[0].co = [999, 999, 999]
        original_update()

    obj.data.update = corrupt_once
    result = registry.dispatch(
        Request(
            "mesh.remove_loose_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]
    assert [face.use_smooth for face in obj.data.polygons] == [True]


def test_milestone7_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        RepairInspect.parse(
            {"object_id": "id", "distance": 0, "area_epsilon": 0}
        )
    with pytest.raises(AgentError):
        MergeByDistance.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "x" * 64,
                "distance": 101,
            }
        )
    with pytest.raises(AgentError):
        CleanupFaces.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "x" * 64,
                "area_epsilon": 0,
                "remove_duplicate_faces": 1,
            }
        )
    action = RemoveLooseVertices.parse(
        {
            "target": object_target,
            "expected_geometry_revision": "x" * 64,
        }
    )
    assert action.expected_geometry_revision == "x" * 64
