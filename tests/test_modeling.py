import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling import ExtrudeFace, ModelingOperations, topology_from_faces
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    modeling = ModelingOperations(objects)
    registry = ToolRegistry(
        [*meshes.tools(), *modeling.tools()],
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


def quad_geometry(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def test_topology_inspect_derives_edges_boundary_and_adjacency():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )
    result = registry.dispatch(
        Request("mesh.topology_inspect", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["edge_count"] == 5
    assert result.data["boundary_edge_count"] == 4
    assert result.data["nonmanifold_edge_count"] == 4
    assert result.data["face_adjacency"] == [[1], [0]]
    assert result.data["edges"] == [[0, 1], [0, 2], [0, 3], [1, 2], [2, 3]]
    assert result.data["geometry_revision"] == meshes.snapshot(obj)["geometry_revision"]


def test_topology_detects_nonmanifold_edge_with_three_faces():
    data = topology_from_faces([[0, 1, 2], [1, 0, 3], [0, 1, 4]])
    assert [0, 1] in data["nonmanifold_edges"]
    assert data["boundary_edge_count"] == 6


def test_single_face_extrude_replaces_cap_and_adds_side_quads():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_geometry(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "mesh.extrude_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "face_index": 0,
                "offset": [0, 0, 3],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert len(after["vertices"]) == 8
    assert len(after["faces"]) == 5
    assert after["new_cap_indices"] == [4, 5, 6, 7]
    assert after["faces"][0] == [4, 5, 6, 7]
    assert after["vertices"][4:] == [
        [0.0, 0.0, 3.0],
        [2.0, 0.0, 3.0],
        [2.0, 2.0, 3.0],
        [0.0, 2.0, 3.0],
    ]
    assert after["faces"][1:] == [
        [0, 1, 5, 4],
        [1, 2, 6, 5],
        [2, 3, 7, 6],
        [3, 0, 4, 7],
    ]


def test_extrude_requires_fresh_geometry_revision():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_geometry(obj)
    before = meshes.snapshot(obj)
    payload = {
        "target": target(inspector, obj),
        "expected_geometry_revision": before["geometry_revision"],
        "face_index": 0,
        "offset": [0, 0, 1],
    }
    obj.data.vertices[0].co = [9, 9, 9]
    result = registry.dispatch(Request("mesh.extrude_face", payload))
    assert result.error.code == ErrorCode.STALE_STATE
    assert len(obj.data.vertices) == 4
    assert len(obj.data.polygons) == 1


def test_extrude_rejects_invalid_face_index_without_mutating():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_geometry(obj)
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.extrude_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "face_index": 12,
                "offset": [0, 0, 1],
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]
    assert meshes.snapshot(obj)["faces"] == before["faces"]


@pytest.mark.parametrize("case", ["shared", "modifier", "shape_keys", "wrong_mode"])
def test_extrude_rejects_unsafe_mesh_states(case):
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_geometry(obj)
    if case == "shared":
        obj.data.users = 2
    elif case == "modifier":
        obj.modifiers.new("Subsurf", "SUBSURF")
    elif case == "shape_keys":
        obj.data.shape_keys = object()
    else:
        bpy.context.mode = "EDIT_MESH"

    result = registry.dispatch(
        Request(
            "mesh.extrude_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "face_index": 0,
                "offset": [0, 0, 1],
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_extrude_verification_failure_rolls_back_geometry():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad_geometry(obj)
    before = meshes.snapshot(obj)
    calls = {"count": 0}
    original_update = obj.data.update

    def corrupt_update():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.data.vertices[-1].co = [999, 999, 999]
        original_update()

    obj.data.update = corrupt_update
    result = registry.dispatch(
        Request(
            "mesh.extrude_face",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "face_index": 0,
                "offset": [0, 0, 1],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    restored = meshes.snapshot(obj)
    assert restored["vertices"] == before["vertices"]
    assert restored["faces"] == before["faces"]


def test_extrude_contract_rejects_bad_payloads():
    base = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_geometry_revision": "x" * 64,
        "face_index": 0,
        "offset": [0, 0, 1],
    }
    bad = dict(base)
    bad["offset"] = [0, 0, 1001]
    with pytest.raises(AgentError):
        ExtrudeFace.parse(bad)
    bad = dict(base)
    bad["face_index"] = -1
    with pytest.raises(AgentError):
        ExtrudeFace.parse(bad)
