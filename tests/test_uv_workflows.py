import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.uv import UVOperations
from shuvi_blender_agent.uv_workflows import (
    UVIslandTransform,
    UVUnwrapApply,
    UVUnwrapPlan,
    UVWorkflowOperations,
)


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    uv = UVOperations(objects)
    workflows = UVWorkflowOperations(objects)
    registry = ToolRegistry(
        [*uv.tools(), *workflows.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, uv, workflows, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def quad(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def two_islands(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [3, 0, 0], [4, 0, 0], [3, 1, 0]],
        [],
        [[0, 1, 2], [3, 4, 5]],
    )
    layer = obj.data.uv_layers.new("UVMap")
    values = [[0, 0], [1, 0], [0, 1], [2, 0], [3, 0], [2, 1]]
    for item, value in zip(layer.data, values, strict=True):
        item.uv = value
    return layer


def unwrap_payload(inspector, uv, obj, layer_name="UVMap", projection="XY"):
    before = uv.snapshot(obj)
    return {
        "target": target(inspector, obj),
        "expected_geometry_revision": before["geometry_revision"],
        "expected_uv_revision": before["uv_revision"],
        "layer_name": layer_name,
        "projection": projection,
    }


def island_payload(inspector, uv, obj, face_indices=(0,), translation=(0.25, -0.1), scale=0.5):
    before = uv.snapshot(obj)
    return {
        "target": target(inspector, obj),
        "expected_geometry_revision": before["geometry_revision"],
        "expected_uv_revision": before["uv_revision"],
        "layer_name": "UVMap",
        "face_indices": list(face_indices),
        "translation": list(translation),
        "scale": scale,
    }


def test_unwrap_plan_is_read_only_and_bounded():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    result = registry.dispatch(
        Request(
            "uv.unwrap_plan",
            {"object_id": inspector.identity(obj), "projection": "XY"},
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["projection"] == "XY"
    assert result.data["source_extent"] == [2.0, 2.0]
    assert result.data["loop_count"] == 4
    assert result.data["execution_status"] == "SOURCE_PLANAR_PROJECTION_PREVIEW_ONLY"
    assert result.data["runtime_unwrap_equivalent"] is False
    assert uv.snapshot(obj)["missing_uv"] is True


def test_unwrap_apply_creates_verified_normalized_layer():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    result = registry.dispatch(Request("uv.unwrap_apply", unwrap_payload(inspector, uv, obj)))
    assert result.status == Status.VERIFIED
    assert result.data["created_layer"] is True
    after = result.data["after"]
    assert after["geometry_revision"] == result.data["before"]["geometry_revision"]
    assert after["active_uv_layer"] == "UVMap"
    assert after["uv_layer_count"] == 1
    assert after["layers"][0]["degenerate_uv_face_indices"] == []
    assert [list(item.uv) for item in obj.data.uv_layers.active.data] == [
        [0.0, 0.0],
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 1.0],
    ]


def test_unwrap_apply_replaces_existing_layer_without_touching_other_layer():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    first = obj.data.uv_layers.new("Keep")
    second = obj.data.uv_layers.new("UVMap")
    for item in first.data:
        item.uv = [0.25, 0.75]
    for item in second.data:
        item.uv = [0.0, 0.0]
    obj.data.uv_layers.active_index = 0
    keep_before = [list(item.uv) for item in first.data]

    result = registry.dispatch(Request("uv.unwrap_apply", unwrap_payload(inspector, uv, obj)))
    assert result.status == Status.VERIFIED
    assert result.data["created_layer"] is False
    assert [list(item.uv) for item in first.data] == keep_before
    assert obj.data.uv_layers.active.name == "UVMap"


def test_unwrap_apply_rejects_stale_uv_revision_and_zero_projection_extent():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    payload = unwrap_payload(inspector, uv, obj)
    obj.data.edges[0].use_seam = True
    stale = registry.dispatch(Request("uv.unwrap_apply", payload))
    assert stale.error.code == ErrorCode.STALE_STATE

    obj.data.edges[0].use_seam = False
    flat = unwrap_payload(inspector, uv, obj, projection="XZ")
    denied = registry.dispatch(Request("uv.unwrap_apply", flat))
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert uv.snapshot(obj)["missing_uv"] is True


def test_unwrap_verification_failure_removes_created_layer():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_first_update():
        calls["count"] += 1
        if calls["count"] == 1 and obj.data.uv_layers.active is not None:
            obj.data.uv_layers.active.data[0].uv = [9.0, 9.0]
        original_update()

    obj.data.update = corrupt_first_update
    result = registry.dispatch(Request("uv.unwrap_apply", unwrap_payload(inspector, uv, obj)))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert len(obj.data.uv_layers) == 0


def test_uv_inspect_exposes_island_face_membership():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_islands(obj)

    summary = uv.snapshot(obj)["layers"][0]
    assert summary["island_count"] == 2
    assert summary["islands"] == [[0], [1]]


def test_island_transform_moves_and_scales_exact_island_only():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    layer = two_islands(obj)
    before_second = [list(item.uv) for item in layer.data[3:]]

    result = registry.dispatch(
        Request(
            "uv.island_transform",
            island_payload(
                inspector,
                uv,
                obj,
                face_indices=(0,),
                translation=(0.25, 0.0),
                scale=0.5,
            ),
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["face_indices"] == [0]
    assert result.data["pivot"] == [0.5, 0.5]
    assert [list(item.uv) for item in layer.data[3:]] == before_second
    assert [list(item.uv) for item in layer.data[:3]] == [
        [0.5, 0.25],
        [1.0, 0.25],
        [0.5, 0.75],
    ]


def test_island_transform_requires_exact_current_island():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_islands(obj)

    result = registry.dispatch(
        Request(
            "uv.island_transform",
            island_payload(inspector, uv, obj, face_indices=(0, 1)),
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_island_transform_rejects_stale_uv_revision():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    layer = two_islands(obj)
    payload = island_payload(inspector, uv, obj)
    layer.data[0].uv = [0.1, 0.2]

    result = registry.dispatch(Request("uv.island_transform", payload))
    assert result.error.code == ErrorCode.STALE_STATE


def test_island_transform_verification_failure_restores_coordinates():
    bpy, inspector, uv, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    layer = two_islands(obj)
    before = [list(item.uv) for item in layer.data]
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_first_update():
        calls["count"] += 1
        if calls["count"] == 1:
            layer.data[0].uv = [9.0, 9.0]
        original_update()

    obj.data.update = corrupt_first_update
    result = registry.dispatch(
        Request("uv.island_transform", island_payload(inspector, uv, obj))
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert [list(item.uv) for item in layer.data] == before


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            UVUnwrapPlan.parse,
            {"object_id": "id", "projection": "AUTO"},
        ),
        (
            UVUnwrapApply.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_geometry_revision": "x" * 64,
                "expected_uv_revision": "y" * 64,
                "layer_name": "UVMap",
                "projection": "AUTO",
            },
        ),
        (
            UVIslandTransform.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_geometry_revision": "x" * 64,
                "expected_uv_revision": "y" * 64,
                "layer_name": "UVMap",
                "face_indices": [0, 0],
                "translation": [0, 0],
                "scale": 1,
            },
        ),
    ],
)
def test_uv_workflow_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
