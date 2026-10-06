import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.uv import SeamSet, UVOperations


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    uv = UVOperations(objects)
    registry = ToolRegistry(uv.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, uv, registry


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


def seam_payload(inspector, uv, obj, edge_indices, seam):
    before = uv.snapshot(obj)
    return {
        "target": target(inspector, obj),
        "expected_geometry_revision": before["geometry_revision"],
        "expected_uv_revision": before["uv_revision"],
        "edge_indices": edge_indices,
        "seam": seam,
    }


def test_uv_inspect_reports_missing_uv_and_seam_baseline():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    result = registry.dispatch(Request("uv.inspect", {"object_id": inspector.identity(obj)}))
    assert result.status == Status.SUCCEEDED
    assert result.data["missing_uv"] is True
    assert result.data["uv_layer_count"] == 0
    assert result.data["edge_count"] == 4
    assert result.data["seam_edge_indices"] == []
    assert len(result.data["uv_revision"]) == 64


def test_uv_inspect_reports_layer_island_area_and_no_overlap():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    layer = obj.data.uv_layers.new("UVMap")
    for item, value in zip(layer.data, [[0, 0], [1, 0], [1, 1], [0, 1]], strict=True):
        item.uv = value

    data = registry.dispatch(Request("uv.inspect", {"object_id": inspector.identity(obj)})).data
    assert data["missing_uv"] is False
    assert data["active_uv_layer"] == "UVMap"
    summary = data["layers"][0]
    assert summary["island_count"] == 1
    assert summary["degenerate_uv_face_indices"] == []
    assert summary["overlap_face_pairs"] == []
    assert summary["uv_area_total"] == pytest.approx(1.0)
    assert summary["max_stretch_factor"] == pytest.approx(1.0)


def test_uv_overlap_diagnostic_detects_positive_area_overlap():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [3, 0, 0], [4, 0, 0], [3, 1, 0]],
        [],
        [[0, 1, 2], [3, 4, 5]],
    )
    layer = obj.data.uv_layers.new("UVMap")
    for item, value in zip(
        layer.data,
        [[0, 0], [1, 0], [0, 1], [0, 0], [1, 0], [0, 1]],
        strict=True,
    ):
        item.uv = value

    summary = uv.snapshot(obj)["layers"][0]
    assert summary["overlap_face_pairs"] == [[0, 1]]
    assert summary["island_count"] == 2


def test_uv_island_count_uses_shared_geometry_and_uv_continuity():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )
    layer = obj.data.uv_layers.new("UVMap")
    continuous = [[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]]
    for item, value in zip(layer.data, continuous, strict=True):
        item.uv = value
    assert uv.snapshot(obj)["layers"][0]["island_count"] == 1

    layer.data[3].uv = [2, 0]
    assert uv.snapshot(obj)["layers"][0]["island_count"] == 2


def test_seam_preview_is_read_only_and_edge_explicit():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    result = registry.dispatch(
        Request(
            "uv.seam_preview",
            {"object_id": inspector.identity(obj), "edge_indices": [0, 2]},
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["execution_status"] == "PREVIEW_ONLY"
    assert [item["edge_index"] for item in result.data["edges"]] == [0, 2]
    assert all(item["seam"] is False for item in result.data["edges"])
    assert uv.snapshot(obj)["seam_edge_indices"] == []


def test_seam_set_marks_and_clears_with_full_readback():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    marked = registry.dispatch(
        Request("uv.seam_set", seam_payload(inspector, uv, obj, [0, 2], True))
    )
    assert marked.status == Status.VERIFIED
    assert marked.data["after"]["seam_edge_indices"] == [0, 2]
    assert marked.data["after"]["geometry_revision"] == marked.data["before"]["geometry_revision"]

    cleared = registry.dispatch(
        Request("uv.seam_set", seam_payload(inspector, uv, obj, [2], False))
    )
    assert cleared.status == Status.VERIFIED
    assert cleared.data["after"]["seam_edge_indices"] == [0]


def test_seam_set_rejects_stale_uv_revision():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    payload = seam_payload(inspector, uv, obj, [0], True)
    obj.data.edges[1].use_seam = True

    result = registry.dispatch(Request("uv.seam_set", payload))
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.data.edges[0].use_seam is False


def test_seam_set_rejects_shared_mesh_data():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    payload = seam_payload(inspector, uv, obj, [0], True)
    obj.data.users = 2

    result = registry.dispatch(Request("uv.seam_set", payload))
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert obj.data.edges[0].use_seam is False


def test_seam_verification_failure_restores_previous_flags():
    bpy, inspector, uv, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    payload = seam_payload(inspector, uv, obj, [0], True)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_first_update():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.data.edges[0].use_seam = False
        original_update()

    obj.data.update = corrupt_first_update
    result = registry.dispatch(Request("uv.seam_set", payload))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert obj.data.edges[0].use_seam is False


def test_seam_contract_rejects_duplicate_indices():
    base = {
        "target": {
            "object_id": "id",
            "expected_name": "Cube",
            "expected_revision": "x" * 64,
        },
        "expected_geometry_revision": "x" * 64,
        "expected_uv_revision": "y" * 64,
        "edge_indices": [0, 0],
        "seam": True,
    }
    with pytest.raises(AgentError):
        SeamSet.parse(base)
