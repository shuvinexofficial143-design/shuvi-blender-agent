import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.uv import UVOperations
from shuvi_blender_agent.uv_packing import (
    TexelDensityInspect,
    TexelDensityPlan,
    UVPackApply,
    UVPackingOperations,
    UVPackPlan,
)


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    uv = UVOperations(objects)
    packing = UVPackingOperations(objects)
    registry = ToolRegistry(
        [*uv.tools(), *packing.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, uv, packing, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def two_islands(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [3, 0, 0], [4, 0, 0], [3, 1, 0]],
        [],
        [[0, 1, 2], [3, 4, 5]],
    )
    layer = obj.data.uv_layers.new("UVMap")
    for item, value in zip(
        layer.data,
        [[0, 0], [1, 0], [0, 1], [2, 0], [3, 0], [2, 1]],
        strict=True,
    ):
        item.uv = value
    return layer


def quad(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
        [],
        [[0, 1, 2, 3]],
    )
    layer = obj.data.uv_layers.new("UVMap")
    for item, value in zip(
        layer.data,
        [[0, 0], [1, 0], [1, 1], [0, 1]],
        strict=True,
    ):
        item.uv = value
    return layer


def pack_payload(inspector, uv, obj, margin=0.05):
    before = uv.snapshot(obj)
    return {
        "target": target(inspector, obj),
        "expected_geometry_revision": before["geometry_revision"],
        "expected_uv_revision": before["uv_revision"],
        "layer_name": "UVMap",
        "margin": margin,
    }


def test_pack_plan_is_read_only_and_deterministic():
    bpy, inspector, uv, packing, registry = setup()
    obj = bpy.data.objects.get("Cube")
    layer = two_islands(obj)
    before = [list(item.uv) for item in layer.data]

    result = registry.dispatch(
        Request(
            "uv.pack_plan",
            {
                "object_id": inspector.identity(obj),
                "layer_name": "UVMap",
                "margin": 0.05,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["island_count"] == 2
    assert result.data["grid"] == {"columns": 2, "rows": 1}
    assert result.data["execution_status"] == "SOURCE_GRID_PACK_PREVIEW_ONLY"
    assert result.data["runtime_pack_equivalent"] is False
    assert [list(item.uv) for item in layer.data] == before


def test_pack_apply_verifies_nonoverlapping_bounded_result():
    bpy, inspector, uv, packing, registry = setup()
    obj = bpy.data.objects.get("Cube")
    two_islands(obj)

    result = registry.dispatch(Request("uv.pack_apply", pack_payload(inspector, uv, obj)))
    assert result.status == Status.VERIFIED
    assert result.data["grid"] == {"columns": 2, "rows": 1}
    after = uv.snapshot(obj)
    summary = after["layers"][0]
    assert summary["overlap_face_pairs"] == []
    for item in obj.data.uv_layers.active.data:
        assert 0.0 <= item.uv[0] <= 1.0
        assert 0.0 <= item.uv[1] <= 1.0


def test_pack_apply_rejects_stale_uv_revision():
    bpy, inspector, uv, packing, registry = setup()
    obj = bpy.data.objects.get("Cube")
    layer = two_islands(obj)
    payload = pack_payload(inspector, uv, obj)
    layer.data[0].uv = [0.2, 0.2]

    result = registry.dispatch(Request("uv.pack_apply", payload))
    assert result.error.code == ErrorCode.STALE_STATE


def test_pack_verification_failure_restores_coordinates():
    bpy, inspector, uv, packing, registry = setup()
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
    result = registry.dispatch(Request("uv.pack_apply", pack_payload(inspector, uv, obj)))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert [list(item.uv) for item in layer.data] == before


def test_texel_density_inspect_and_target_plan():
    bpy, inspector, uv, packing, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    inspected = registry.dispatch(
        Request(
            "uv.texel_density_inspect",
            {
                "object_id": inspector.identity(obj),
                "layer_name": "UVMap",
                "texture_size": 1024,
            },
        )
    )
    assert inspected.status == Status.SUCCEEDED
    assert inspected.data["median_pixels_per_unit"] == pytest.approx(512.0)
    assert inspected.data["valid_face_count"] == 1

    planned = registry.dispatch(
        Request(
            "uv.texel_density_plan",
            {
                "object_id": inspector.identity(obj),
                "layer_name": "UVMap",
                "texture_size": 1024,
                "target_density": 1024,
            },
        )
    )
    assert planned.status == Status.SUCCEEDED
    assert planned.data["uniform_uv_scale"] == pytest.approx(2.0)
    assert planned.data["predicted_median_pixels_per_unit"] == pytest.approx(1024.0)
    assert planned.data["execution_status"] == "TARGET_SCALE_PLAN_ONLY"


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            UVPackPlan.parse,
            {"object_id": "id", "layer_name": "UVMap", "margin": 0.2},
        ),
        (
            UVPackApply.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_geometry_revision": "x" * 64,
                "expected_uv_revision": "y" * 64,
                "layer_name": "UVMap",
                "margin": -0.1,
            },
        ),
        (
            TexelDensityInspect.parse,
            {"object_id": "id", "layer_name": "UVMap", "texture_size": 8},
        ),
        (
            TexelDensityPlan.parse,
            {
                "object_id": "id",
                "layer_name": "UVMap",
                "texture_size": 1024,
                "target_density": 0,
            },
        ),
    ],
)
def test_packing_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
