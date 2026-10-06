from math import pi

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh_transform import MeshTransformOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    operations = MeshTransformOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, operations, registry


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def payload(inspector, operations, obj):
    return {
        "target": target(inspector, obj),
        "expected_geometry_revision": operations.meshes.snapshot(obj)["geometry_revision"],
    }


def triangle(obj):
    obj.data.from_pydata([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [], [[0, 1, 2]])


def test_apply_full_object_transform_bakes_mesh_and_resets_channels():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    triangle(obj)
    obj.location = [10.0, 0.0, 0.0]
    obj.rotation_euler = [0.0, 0.0, pi / 2]
    obj.scale = [2.0, 1.0, 1.0]

    result = registry.dispatch(
        Request("mesh.apply_object_transform", payload(inspector, operations, obj))
    )
    assert result.status == Status.VERIFIED
    vertices = result.data["after"]["geometry"]["vertices"]
    assert vertices[0] == pytest.approx([10.0, 0.0, 0.0])
    assert vertices[1] == pytest.approx([10.0, 2.0, 0.0])
    assert vertices[2] == pytest.approx([9.0, 0.0, 0.0])
    transform = result.data["after"]["object"]["transform"]
    assert transform["location"] == [0.0, 0.0, 0.0]
    assert transform["rotation_euler"] == [0.0, 0.0, 0.0]
    assert transform["scale"] == [1.0, 1.0, 1.0]


def test_origin_to_centroid_preserves_geometry_in_world_space_for_identity_rotation():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [3, 0, 0], [0, 3, 0]], [], [[0, 1, 2]])
    obj.location = [1.0, 2.0, 3.0]

    result = registry.dispatch(Request("origin.to_centroid", payload(inspector, operations, obj)))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["centroid_local_before"] == [1.0, 1.0, 0.0]
    assert result.data["after"]["geometry"]["vertices"] == pytest.approx(
        [[-1.0, -1.0, 0.0], [2.0, -1.0, 0.0], [-1.0, 2.0, 0.0]]
    )
    assert result.data["after"]["object"]["transform"]["location"] == [2.0, 3.0, 3.0]


def test_mesh_transform_rejects_stale_geometry():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    triangle(obj)
    request_payload = payload(inspector, operations, obj)
    obj.data.vertices[0].co = [5, 5, 5]
    result = registry.dispatch(Request("mesh.apply_object_transform", request_payload))
    assert result.error.code == ErrorCode.STALE_STATE


@pytest.mark.parametrize("case", ["shared", "parented", "rotation_mode", "modifier"])
def test_mesh_transform_rejects_unsafe_targets(case):
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    triangle(obj)
    if case == "shared":
        obj.data.users = 2
    elif case == "parented":
        obj.parent = bpy.data.objects.get("Sphere")
    elif case == "rotation_mode":
        obj.rotation_mode = "QUATERNION"
    else:
        obj.modifiers.new("Existing", "SUBSURF")

    result = registry.dispatch(
        Request("mesh.apply_object_transform", payload(inspector, operations, obj))
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_origin_verification_failure_rolls_back_vertices_and_transform():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [3, 0, 0], [0, 3, 0]], [], [[0, 1, 2]])
    obj.location = [1.0, 2.0, 3.0]
    original_vertices = [list(vertex.co) for vertex in obj.data.vertices]
    original_location = list(obj.location)
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.location = [999.0, 0.0, 0.0]

    bpy.context.view_layer.update = corrupt_once
    result = registry.dispatch(Request("origin.to_centroid", payload(inspector, operations, obj)))
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert [list(vertex.co) for vertex in obj.data.vertices] == original_vertices
    assert list(obj.location) == original_location
