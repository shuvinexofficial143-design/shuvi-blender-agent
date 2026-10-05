import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import Geometry, MeshOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def geometry():
    return {"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "faces": [[0, 1, 2]]}


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    operations = MeshOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, operations, registry


def test_indexed_mesh_create_and_inspect_readback():
    bpy, inspector, _, registry = setup()
    result = registry.dispatch(
        Request(
            "mesh.create",
            {
                "name": "Triangle",
                "geometry": geometry(),
                "transform": {
                    "location": [0, 0, 0],
                    "rotation_euler": [0, 0, 0],
                    "scale": [1, 1, 1],
                },
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    uid = result.data["after"]["object"]["object_id"]
    readback = registry.dispatch(Request("mesh.inspect", {"object_id": uid}))
    assert readback.data["vertices"] == geometry()["vertices"]
    assert readback.data["faces"] == [[0, 1, 2]]
    assert bpy.data.objects.get("Triangle") is not None


def test_vertex_translation_detects_stale_geometry_independently():
    bpy, inspector, operations, registry = setup()
    obj = bpy.context.scene.objects[0]
    obj.data.from_pydata(geometry()["vertices"], [], geometry()["faces"])
    obj_state = inspector.snapshot(obj)
    mesh_state = operations.snapshot(obj)
    payload = {
        "target": {
            "object_id": obj_state["object_id"],
            "expected_name": obj.name,
            "expected_revision": obj_state["revision"],
        },
        "expected_geometry_revision": mesh_state["geometry_revision"],
        "indices": [0],
        "delta": [1, 2, 3],
    }
    obj.data.vertices[1].co = [5, 5, 5]
    result = registry.dispatch(Request("mesh.translate_vertices", payload))
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.data.vertices[0].co == [0, 0, 0]
    payload["expected_geometry_revision"] = operations.snapshot(obj)["geometry_revision"]
    result = registry.dispatch(Request("mesh.translate_vertices", payload))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["vertices"][0] == [1, 2, 3]
    assert result.data["after"]["vertices"][1] == [5, 5, 5]


@pytest.mark.parametrize(
    "bad",
    [
        {"vertices": [[0, 0, 0]], "faces": [[0, 1, 2]]},
        {"vertices": geometry()["vertices"], "faces": [[0, 0, 2]]},
        {"vertices": geometry()["vertices"], "faces": [[0, 1, 8]]},
        {"vertices": [[0, 0, float("nan")]] * 3, "faces": [[0, 1, 2]]},
        {"vertices": geometry()["vertices"], "faces": [[0, 1, True]]},
    ],
)
def test_invalid_geometry(bad):
    with pytest.raises(AgentError):
        Geometry.parse(bad)


def test_out_of_bounds_vertex_does_not_partially_mutate():
    bpy, inspector, operations, registry = setup()
    obj = bpy.context.scene.objects[0]
    obj.data.from_pydata(geometry()["vertices"], [], geometry()["faces"])
    snap = inspector.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.translate_vertices",
            {
                "target": {
                    "object_id": snap["object_id"],
                    "expected_name": obj.name,
                    "expected_revision": snap["revision"],
                },
                "expected_geometry_revision": operations.snapshot(obj)["geometry_revision"],
                "indices": [0, 10],
                "delta": [1, 0, 0],
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert obj.data.vertices[0].co == [0, 0, 0]
