import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling import ModelingOperations, topology_from_faces
from shuvi_blender_agent.modeling_topology import (
    BridgeBoundaryLoops,
    FillBoundaryLoop,
    LoopCutQuadStrip,
    ModelingTopologyOperations,
    SubdivideEdge,
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
            *ModelingTopologyOperations(objects).tools(),
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


def single_quad(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def two_quad_strip(obj):
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [2, 0, 0],
            [0, 1, 0],
            [1, 1, 0],
            [2, 1, 0],
        ],
        [],
        [[0, 1, 4, 3], [1, 2, 5, 4]],
    )


def test_subdivide_edge_inserts_vertex_into_all_edge_users():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 1])

    result = registry.dispatch(
        Request(
            "mesh.subdivide_edge",
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
    assert after["new_vertex_index"] == 4
    assert after["vertices"][4] == [0.5, 0.0, 0.0]
    assert after["faces"] == [[0, 4, 1, 2, 3]]
    assert after["affected_face_indices"] == [0]


def test_subdivide_shared_edge_updates_both_faces():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 2])
    result = registry.dispatch(
        Request(
            "mesh.subdivide_edge",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": edge_index,
                "factor": 0.5,
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["affected_face_indices"] == [0, 1]
    assert result.data["after"]["faces"] == [[0, 1, 2, 4], [0, 4, 2, 3]]


def test_loop_cut_quad_strip_splits_all_connected_quads():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_quad_strip(obj)
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    seed_index = topology["edges"].index([0, 3])

    result = registry.dispatch(
        Request(
            "mesh.loop_cut_quad_strip",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": seed_index,
                "factor": 0.5,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["ring_edges"] == [[0, 3], [1, 4], [2, 5]]
    assert after["affected_face_indices"] == [0, 1]
    assert len(after["new_vertex_indices"]) == 3
    assert len(after["vertices"]) == 9
    assert len(after["faces"]) == 4
    assert all(len(face) == 4 for face in after["faces"])


def test_loop_cut_rejects_triangle_strip_entry():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [], [[0, 1, 2]])
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    result = registry.dispatch(
        Request(
            "mesh.loop_cut_quad_strip",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": topology["edges"].index([0, 1]),
                "factor": 0.5,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_bridge_equal_boundary_loops_adds_quad_ring():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0, 0, 2],
            [1, 0, 2],
            [1, 1, 2],
            [0, 1, 2],
        ],
        [],
        [[0, 1, 2, 3], [4, 5, 6, 7]],
    )
    result = registry.dispatch(
        Request(
            "mesh.bridge_boundary_loops",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "loop_a": [0, 1, 2, 3],
                "loop_b": [4, 5, 6, 7],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["bridge_face_indices"] == [2, 3, 4, 5]
    assert after["faces"][2:] == [
        [0, 1, 5, 4],
        [1, 2, 6, 5],
        [2, 3, 7, 6],
        [3, 0, 4, 7],
    ]


def test_bridge_rejects_non_boundary_loop_edge():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_quad_strip(obj)
    result = registry.dispatch(
        Request(
            "mesh.bridge_boundary_loops",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "loop_a": [0, 1, 4, 3],
                "loop_b": [1, 2, 5, 4],
            },
        )
    )
    assert result.error.code in (ErrorCode.INVALID_REQUEST, ErrorCode.SAFETY_DENIED)


def test_fill_boundary_loop_closes_open_box_top():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0, 0, 1],
            [1, 0, 1],
            [1, 1, 1],
            [0, 1, 1],
        ],
        [],
        [
            [0, 3, 2, 1],
            [0, 1, 5, 4],
            [1, 2, 6, 5],
            [2, 3, 7, 6],
            [3, 0, 4, 7],
        ],
    )
    result = registry.dispatch(
        Request(
            "mesh.fill_boundary_loop",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "vertex_indices": [4, 5, 6, 7],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["fill_face_index"] == 5
    assert after["faces"][-1] == [4, 5, 6, 7]
    assert after["filled_boundary_edges"] == [[4, 5], [5, 6], [6, 7], [4, 7]]


def test_fill_rejects_already_filled_face():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    result = registry.dispatch(
        Request(
            "mesh.fill_boundary_loop",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "vertex_indices": [0, 1, 2, 3],
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_subdivide_verification_failure_rolls_back_geometry():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    single_quad(obj)
    before = meshes.snapshot(obj)
    topology = topology_from_faces(before["faces"])
    edge_index = topology["edges"].index([0, 1])
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
            "mesh.subdivide_edge",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "edge_index": edge_index,
                "factor": 0.5,
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    restored = meshes.snapshot(obj)
    assert restored["vertices"] == before["vertices"]
    assert restored["faces"] == before["faces"]


def test_milestone4_contract_validation():
    common = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_geometry_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        SubdivideEdge.parse(common | {"edge_index": 0, "factor": 1.0})
    with pytest.raises(AgentError):
        LoopCutQuadStrip.parse(common | {"edge_index": 0, "factor": 0.0})
    with pytest.raises(AgentError):
        BridgeBoundaryLoops.parse(
            common | {"loop_a": [0, 1, 2], "loop_b": [3, 4, 5, 6]}
        )
    with pytest.raises(AgentError):
        FillBoundaryLoop.parse(common | {"vertex_indices": [0, 0, 1]})
