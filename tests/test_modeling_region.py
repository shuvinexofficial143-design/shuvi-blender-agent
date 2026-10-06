import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling import ModelingOperations, topology_from_faces
from shuvi_blender_agent.modeling_region import (
    BevelBoundaryEdge,
    ExtrudeRegion,
    InsetFace,
    ModelingRegionOperations,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    registry = ToolRegistry(
        [
            *meshes.tools(),
            *ModelingOperations(objects).tools(),
            *ModelingRegionOperations(objects).tools(),
        ],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def quad_two_triangles(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )


def single_quad(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def test_region_extrude_two_connected_faces_adds_only_outer_side_walls():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_two_triangles(obj)
    result = registry.dispatch(
        Request(
            "mesh.extrude_region",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "face_indices": [0, 1],
                "offset": [0, 0, 3],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert len(after["vertices"]) == 8
    assert len(after["faces"]) == 6
    assert after["boundary_edge_count"] == 4
    assert after["source_vertex_indices"] == [0, 1, 2, 3]
    assert after["new_vertex_indices"] == [4, 5, 6, 7]
    assert after["faces"][0] == [4, 5, 6]
    assert after["faces"][1] == [4, 6, 7]
    assert [0, 2, 6, 4] not in after["faces"]
    topology = topology_from_faces(after["faces"])
    assert topology["edge_count"] >= 12


def test_region_extrude_rejects_disconnected_faces():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [10, 0, 0], [11, 0, 0], [10, 1, 0]],
        [],
        [[0, 1, 2], [3, 4, 5]],
    )
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.extrude_region",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "face_indices": [0, 1],
                "offset": [0, 0, 1],
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]


def test_face_inset_creates_inner_cap_and_ring():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    result = registry.dispatch(
        Request(
            "mesh.inset_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "face_index": 0,
                "factor": 0.25,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert len(after["vertices"]) == 8
    assert len(after["faces"]) == 5
    assert after["inner_vertex_indices"] == [4, 5, 6, 7]
    assert after["vertices"][4:] == [
        [0.25, 0.25, 0.0],
        [1.75, 0.25, 0.0],
        [1.75, 1.75, 0.0],
        [0.25, 1.75, 0.0],
    ]
    assert after["faces"][0] == [4, 5, 6, 7]


def test_boundary_edge_bevel_creates_inner_edge_and_strip():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 1])
    result = registry.dispatch(
        Request(
            "mesh.bevel_boundary_edge",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": edge_index,
                "factor": 0.25,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["new_vertex_indices"] == [4, 5]
    assert after["vertices"][4] == [0.0, 0.5, 0.0]
    assert after["vertices"][5] == [2.0, 0.5, 0.0]
    assert after["faces"] == [[4, 5, 2, 3], [0, 1, 5, 4]]


def test_boundary_edge_bevel_rejects_shared_edge():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_two_triangles(obj)
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 2])
    result = registry.dispatch(
        Request(
            "mesh.bevel_boundary_edge",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": edge_index,
                "factor": 0.2,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_region_topology_rebuild_rejects_material_metadata():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    material = bpy.data.materials.new("Protected")
    obj.data.materials.append(material)
    result = registry.dispatch(
        Request(
            "mesh.inset_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "face_index": 0,
                "factor": 0.2,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_inset_verification_failure_rolls_back_geometry():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    before = meshes.snapshot(obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.data.vertices[-1].co = [999, 999, 999]
        original_update()

    obj.data.update = corrupt_once
    result = registry.dispatch(
        Request(
            "mesh.inset_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "face_index": 0,
                "factor": 0.2,
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    restored = meshes.snapshot(obj)
    assert restored["vertices"] == before["vertices"]
    assert restored["faces"] == before["faces"]


def test_milestone3_contract_validation():
    common = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_geometry_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        ExtrudeRegion.parse(common | {"face_indices": [0], "offset": [0, 0, 0]})
    with pytest.raises(AgentError):
        InsetFace.parse(common | {"face_index": 0, "factor": 1.0})
    with pytest.raises(AgentError):
        BevelBoundaryEdge.parse(common | {"edge_index": 0, "factor": 0.5})
