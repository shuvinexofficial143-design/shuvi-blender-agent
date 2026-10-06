import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.sculpting_brushes import (
    SculptBrushOperations,
    SculptCrease,
    SculptFlatten,
    SculptGrab,
    SculptNormalizedBrush,
)
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    brushes = SculptBrushOperations(objects)
    registry = ToolRegistry(brushes.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, meshes, brushes, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def quad(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def fan(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [1, 1, 1]],
        [],
        [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
    )


def distance_xy(vertex, center=(0.5, 0.5)):
    return ((vertex[0] - center[0]) ** 2 + (vertex[1] - center[1]) ** 2) ** 0.5


def test_inflate_uses_radius_relative_normal_displacement():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_inflate",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.5,
                "strength": 1.0,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_indices"] == [0]
    assert after["vertices"][0] == pytest.approx([0, 0, 0.125])
    assert after["normal_displacement_scale"] == pytest.approx(0.125)
    assert after["faces"] == before["faces"]


def test_inflate_negative_strength_deflates():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_inflate",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.4,
                "strength": -0.5,
                "falloff": "SMOOTH",
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["vertices"][0] == pytest.approx([0, 0, -0.05])


def test_flatten_reduces_height_spread_on_symmetric_peak():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    fan(obj)
    before = meshes.snapshot(obj)
    before_z = [vertex[2] for vertex in before["vertices"]]

    result = registry.dispatch(
        Request(
            "sculpt.brush_flatten",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [1, 1, 0],
                "radius": 2.0,
                "strength": 1.0,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    after_z = [vertex[2] for vertex in after["vertices"]]
    assert max(after_z) - min(after_z) < max(before_z) - min(before_z)
    assert after["affected_vertex_count"] == 5
    assert after["plane_normal"][2] > 0
    assert after["faces"] == before["faces"]


def test_pinch_moves_planar_vertices_toward_brush_center():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_pinch",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0.5, 0.5, 0],
                "radius": 1.0,
                "strength": 1.0,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_indices"] == [0, 1, 2, 3]
    for old, new in zip(before["vertices"], after["vertices"], strict=True):
        assert distance_xy(new) < distance_xy(old)
        assert new[2] == pytest.approx(0)


def test_negative_pinch_expands_away_from_center():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_pinch",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0.5, 0.5, 0],
                "radius": 1.0,
                "strength": -0.5,
                "falloff": "SMOOTH",
            },
        )
    )
    assert result.status == Status.VERIFIED
    for old, new in zip(before["vertices"], result.data["after"]["vertices"], strict=True):
        assert distance_xy(new) > distance_xy(old)


def test_grab_moves_selected_vertices_by_weighted_delta_without_normals():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_grab",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.25,
                "delta": [1, 2, 3],
                "falloff": "LINEAR",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_indices"] == [0]
    assert after["vertices"][0] == pytest.approx([1, 2, 3])
    assert after["vertices"][1:] == before["vertices"][1:]


def test_crease_combines_tangent_pinch_and_negative_normal_depth():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_crease",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0.5, 0.5, 0],
                "radius": 1.0,
                "pinch": 0.5,
                "depth": 0.2,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_count"] == 4
    for old, new in zip(before["vertices"], after["vertices"], strict=True):
        assert distance_xy(new) < distance_xy(old)
        assert new[2] < 0


def test_normal_based_brush_rejects_degenerate_surface():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        [],
        [[0, 1, 2]],
    )
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_flatten",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [1, 0, 0],
                "radius": 2,
                "strength": 1,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj) == before


def test_expanded_brush_rejects_empty_selection_and_stale_geometry():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    stale = meshes.snapshot(obj)

    empty = registry.dispatch(
        Request(
            "sculpt.brush_grab",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": stale["geometry_revision"],
                "center": [99, 99, 99],
                "radius": 0.1,
                "delta": [1, 0, 0],
                "falloff": "LINEAR",
            },
        )
    )
    assert empty.error.code == ErrorCode.INVALID_REQUEST

    obj.data.vertices[0].co = [0, 0, 0.2]
    obj.data.update()
    stale_result = registry.dispatch(
        Request(
            "sculpt.brush_grab",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": stale["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 1,
                "delta": [1, 0, 0],
                "falloff": "LINEAR",
            },
        )
    )
    assert stale_result.error.code == ErrorCode.STALE_STATE


def test_expanded_brush_verification_failure_rolls_back_coordinates():
    bpy, inspector, meshes, brushes, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
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
            "sculpt.brush_grab",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.25,
                "delta": [0, 0, 1],
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]


def test_milestone2_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    common = {
        "target": object_target,
        "expected_geometry_revision": "y" * 64,
        "center": [0, 0, 0],
        "radius": 1,
        "falloff": "LINEAR",
    }

    with pytest.raises(AgentError):
        SculptNormalizedBrush.parse(common | {"strength": 0})
    with pytest.raises(AgentError):
        SculptNormalizedBrush.parse(common | {"strength": 1.1})
    with pytest.raises(AgentError):
        SculptFlatten.parse(common | {"strength": 0})
    with pytest.raises(AgentError):
        SculptGrab.parse(common | {"delta": [0, 0, 0]})
    with pytest.raises(AgentError):
        SculptCrease.parse(common | {"pinch": 0, "depth": 0})
    with pytest.raises(AgentError):
        SculptCrease.parse(common | {"pinch": 1.1, "depth": 0.1})
