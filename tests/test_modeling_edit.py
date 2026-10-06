from math import pi

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling import ModelingOperations, topology_from_faces
from shuvi_blender_agent.modeling_edit import (
    DissolveEdge,
    MergeVertices,
    ModelingEditOperations,
    TransformElements,
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
            *ModelingEditOperations(objects).tools(),
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


def two_triangles(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )


def transform_payload(inspector, meshes, obj, domain, indices):
    return {
        "target": target(inspector, obj),
        "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
        "domain": domain,
        "indices": indices,
        "translation": [0, 0, 0],
        "rotation_euler": [0, 0, 0],
        "scale": [1, 1, 1],
        "pivot": [0, 0, 0],
    }


def test_vertex_element_transform_supports_scale_rotation_translation():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_triangles(obj)
    payload = transform_payload(inspector, meshes, obj, "VERTEX", [1])
    payload["translation"] = [1, 0, 0]
    payload["rotation_euler"] = [0, 0, pi / 2]
    payload["scale"] = [2, 1, 1]

    result = registry.dispatch(Request("mesh.transform_elements", payload))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["affected_vertex_indices"] == [1]
    assert result.data["after"]["vertices"][1] == pytest.approx([1, 2, 0])
    assert result.data["after"]["vertices"][0] == [0, 0, 0]


def test_edge_and_face_domain_transform_resolve_topology_indices():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_triangles(obj)

    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 1])
    payload = transform_payload(inspector, meshes, obj, "EDGE", [edge_index])
    payload["translation"] = [0, 0, 2]
    result = registry.dispatch(Request("mesh.transform_elements", payload))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["affected_vertex_indices"] == [0, 1]
    assert result.data["after"]["vertices"][0] == [0, 0, 2]
    assert result.data["after"]["vertices"][1] == [1, 0, 2]
    assert result.data["after"]["vertices"][2] == [1, 1, 0]

    payload = transform_payload(inspector, meshes, obj, "FACE", [1])
    payload["translation"] = [3, 0, 0]
    result = registry.dispatch(Request("mesh.transform_elements", payload))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["affected_vertex_indices"] == [0, 2, 3]


def test_element_transform_rejects_stale_geometry_and_missing_element():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_triangles(obj)
    payload = transform_payload(inspector, meshes, obj, "VERTEX", [0])
    payload["translation"] = [1, 0, 0]
    obj.data.vertices[1].co = [5, 5, 5]
    result = registry.dispatch(Request("mesh.transform_elements", payload))
    assert result.error.code == ErrorCode.STALE_STATE

    payload = transform_payload(inspector, meshes, obj, "FACE", [99])
    payload["translation"] = [1, 0, 0]
    result = registry.dispatch(Request("mesh.transform_elements", payload))
    assert result.error.code == ErrorCode.INVALID_REQUEST


def test_merge_adjacent_vertices_to_center_compacts_mesh():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )
    result = registry.dispatch(
        Request(
            "mesh.merge_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "indices": [0, 1],
                "mode": "CENTER",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["vertices"] == [[1.0, 0.0, 0.0], [2, 2, 0], [0, 2, 0]]
    assert after["faces"] == [[0, 1, 2]]
    assert after["result_vertex_index"] == 0


def test_merge_first_and_last_choose_requested_position():
    for mode, expected in (("FIRST", [0, 0, 0]), ("LAST", [2, 0, 0])):
        bpy, inspector, meshes, registry = setup()
        obj = bpy.data.objects.get("Cube")
        obj.data.from_pydata(
            [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
            [],
            [[0, 1, 2, 3]],
        )
        result = registry.dispatch(
            Request(
                "mesh.merge_vertices",
                {
                    "target": target(inspector, obj),
                    "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                    "indices": [0, 1],
                    "mode": mode,
                },
            )
        )
        assert result.status == Status.VERIFIED
        index = result.data["after"]["result_vertex_index"]
        assert result.data["after"]["vertices"][index] == expected


def test_merge_rejects_nonadjacent_vertices_that_repeat_polygon():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.merge_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "indices": [0, 2],
                "mode": "CENTER",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert meshes.snapshot(obj)["faces"] == before["faces"]


def test_dissolve_shared_edge_merges_two_faces_into_quad():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_triangles(obj)
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 2])

    result = registry.dispatch(
        Request(
            "mesh.dissolve_edge",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": edge_index,
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["faces"] == [[0, 1, 2, 3]]
    assert result.data["after"]["dissolved_edge"] == [0, 2]
    assert len(result.data["after"]["vertices"]) == 4


def test_dissolve_rejects_boundary_edge():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_triangles(obj)
    topology = topology_from_faces(meshes.snapshot(obj)["faces"])
    edge_index = topology["edges"].index([0, 1])
    result = registry.dispatch(
        Request(
            "mesh.dissolve_edge",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "edge_index": edge_index,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_topology_rebuild_rejects_material_metadata():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_triangles(obj)
    material = bpy.data.materials.new("Protected")
    obj.data.materials.append(material)
    result = registry.dispatch(
        Request(
            "mesh.merge_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": meshes.snapshot(obj)["geometry_revision"],
                "indices": [0, 1],
                "mode": "CENTER",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_merge_verification_failure_rolls_back_geometry():
    bpy, inspector, meshes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )
    before = meshes.snapshot(obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.data.vertices[0].co = [999, 999, 999]
        original_update()

    obj.data.update = corrupt_once
    result = registry.dispatch(
        Request(
            "mesh.merge_vertices",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "indices": [0, 1],
                "mode": "CENTER",
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    restored = meshes.snapshot(obj)
    assert restored["vertices"] == before["vertices"]
    assert restored["faces"] == before["faces"]


def test_milestone2_contract_validation():
    common = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_geometry_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        TransformElements.parse(
            common
            | {
                "domain": "VERTEX",
                "indices": [0],
                "translation": [0, 0, 0],
                "rotation_euler": [0, 0, 0],
                "scale": [1, 1, 1],
                "pivot": [0, 0, 0],
            }
        )
    with pytest.raises(AgentError):
        MergeVertices.parse(common | {"indices": [0], "mode": "CENTER"})
    with pytest.raises(AgentError):
        DissolveEdge.parse(common | {"edge_index": -1})
