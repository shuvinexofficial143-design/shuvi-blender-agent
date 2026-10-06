import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling_shading import (
    ModelingShadingOperations,
    OrientFaces,
    SetFaceSmoothing,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    shading = ModelingShadingOperations(objects)
    registry = ToolRegistry(
        [*meshes.tools(), *shading.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, shading, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def single_quad(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def inconsistent_triangles(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 3, 2]],
    )


def test_shading_inspect_reports_normals_area_smoothing_and_topology_diagnostics():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [9, 9, 9]],
        [],
        [[0, 1, 2, 3]],
    )
    obj.data.polygons[0].use_smooth = True

    result = registry.dispatch(
        Request("mesh.shading_inspect", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["face_normals"][0] == pytest.approx([0, 0, 1])
    assert data["face_areas"] == pytest.approx([4.0])
    assert data["face_smooth"] == [True]
    assert data["smooth_face_indices"] == [0]
    assert data["flat_face_indices"] == []
    assert data["isolated_vertex_indices"] == [4]
    assert data["degenerate_face_indices"] == []
    assert data["boundary_edge_count"] == 4
    assert data["nonmanifold_edge_count"] == 4
    assert data["winding_conflict_edge_count"] == 0
    assert len(data["shading_revision"]) == 64
    assert data["geometry_revision"] == meshes.snapshot(obj)["geometry_revision"]


def test_shading_inspect_detects_degenerate_face_and_winding_conflict():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 3, 2]],
    )
    data = registry.dispatch(
        Request("mesh.shading_inspect", {"object_id": inspector.identity(obj)})
    ).data
    assert data["degenerate_face_indices"] == [0]
    assert [0, 2] in data["winding_conflict_edges"]
    assert data["winding_conflict_edge_count"] == 1


def test_set_face_smoothing_changes_only_requested_faces():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    inconsistent_triangles(obj)
    before = shading.shading_snapshot(obj)

    result = registry.dispatch(
        Request(
            "mesh.set_face_smoothing",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
                "face_indices": [1],
                "smooth": True,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["geometry_revision"] == before["geometry_revision"]
    assert after["face_smooth"] == [False, True]
    assert after["smooth_face_indices"] == [1]
    assert after["flat_face_indices"] == [0]
    assert after["shading_revision"] != before["shading_revision"]


def test_set_face_smoothing_rejects_stale_shading_revision():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    inconsistent_triangles(obj)
    before = shading.shading_snapshot(obj)
    obj.data.polygons[0].use_smooth = True

    result = registry.dispatch(
        Request(
            "mesh.set_face_smoothing",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
                "face_indices": [1],
                "smooth": True,
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.data.polygons[1].use_smooth is False


def test_smoothing_verification_failure_restores_flags():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    inconsistent_triangles(obj)
    before = shading.shading_snapshot(obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.data.polygons[1].use_smooth = False
        original_update()

    obj.data.update = corrupt_once
    result = registry.dispatch(
        Request(
            "mesh.set_face_smoothing",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
                "face_indices": [1],
                "smooth": True,
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert [face.use_smooth for face in obj.data.polygons] == [False, False]


def test_orient_faces_consistently_removes_shared_edge_winding_conflict():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    inconsistent_triangles(obj)
    obj.data.polygons[1].use_smooth = True
    before = shading.shading_snapshot(obj)
    assert before["winding_conflict_edge_count"] == 1

    result = registry.dispatch(
        Request(
            "mesh.orient_faces_consistently",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["winding_conflict_edge_count"] == 0
    assert after["flipped_face_indices"] == [1]
    assert after["orientation_component_count"] == 1
    assert after["face_smooth"] == [False, True]
    assert after["faces"] if "faces" in after else True
    geometry = meshes.snapshot(obj)
    assert geometry["faces"] == [[0, 1, 2], [2, 3, 0]]


def test_orient_faces_keeps_already_consistent_mesh_unchanged():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )
    before_geometry = meshes.snapshot(obj)
    before = shading.shading_snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.orient_faces_consistently",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["flipped_face_indices"] == []
    assert meshes.snapshot(obj)["faces"] == before_geometry["faces"]


def test_orient_faces_rejects_more_than_two_users_on_edge():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]],
        [],
        [[0, 1, 2], [1, 0, 3], [0, 1, 4]],
    )
    before = shading.shading_snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.orient_faces_consistently",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_orient_verification_failure_rolls_back_faces_and_smoothing():
    bpy, inspector, meshes, shading, registry = setup()
    obj = bpy.data.objects.get("Cube")
    inconsistent_triangles(obj)
    obj.data.polygons[0].use_smooth = True
    before_geometry = meshes.snapshot(obj)
    before = shading.shading_snapshot(obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 2:
            obj.data.polygons[0].use_smooth = False
        original_update()

    obj.data.update = corrupt_once
    result = registry.dispatch(
        Request(
            "mesh.orient_faces_consistently",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "expected_shading_revision": before["shading_revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(obj)["faces"] == before_geometry["faces"]
    assert [face.use_smooth for face in obj.data.polygons] == [True, False]


def test_milestone5_contract_validation():
    common = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_geometry_revision": "x" * 64,
        "expected_shading_revision": "y" * 64,
    }
    with pytest.raises(AgentError):
        SetFaceSmoothing.parse(common | {"face_indices": [], "smooth": True})
    with pytest.raises(AgentError):
        SetFaceSmoothing.parse(common | {"face_indices": [0], "smooth": 1})
    with pytest.raises(AgentError):
        SetFaceSmoothing.parse(common | {"face_indices": [0, 0], "smooth": False})
    action = OrientFaces.parse(common)
    assert action.expected_shading_revision == "y" * 64
