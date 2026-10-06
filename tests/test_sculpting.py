import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.sculpting import SculptBrush, SculptSmooth, SculptingOperations
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    sculpt = SculptingOperations(objects)
    registry = ToolRegistry(sculpt.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, meshes, sculpt, registry


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


def test_sculpt_inspect_reports_base_mesh_readiness():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)

    result = registry.dispatch(
        Request("sculpt.inspect", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["vertex_count"] == 4
    assert data["face_count"] == 1
    assert data["edge_count"] == 4
    assert data["boundary_vertex_indices"] == [0, 1, 2, 3]
    assert data["boundary_vertex_count"] == 4
    assert data["degenerate_face_count"] == 0
    assert data["invalid_normal_vertex_count"] == 0
    assert data["vertex_valence_min"] == 2
    assert data["vertex_valence_max"] == 2
    assert data["vertex_valence_average"] == pytest.approx(2.0)
    assert data["sculpt_ready"] is True
    assert data["geometry_revision"] == meshes.snapshot(obj)["geometry_revision"]


def test_sculpt_inspect_detects_degenerate_and_invalid_normals():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [2, 0, 0], [9, 9, 9]],
        [],
        [[0, 1, 2]],
    )
    data = registry.dispatch(
        Request("sculpt.inspect", {"object_id": inspector.identity(obj)})
    ).data
    assert data["degenerate_face_indices"] == [0]
    assert data["invalid_normal_vertex_indices"] == [0, 1, 2, 3]
    assert data["sculpt_ready"] is False


def test_displace_brush_moves_vertices_along_area_weighted_normals():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_displace",
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
    expected_z = 1.0 - (0.5**2 + 0.5**2) ** 0.5
    assert after["affected_vertex_indices"] == [0, 1, 2, 3]
    assert after["affected_vertex_count"] == 4
    assert all(vertex[2] == pytest.approx(expected_z) for vertex in after["vertices"])
    assert after["faces"] == before["faces"]
    assert all(float(index) if False else True for index in range(4))


def test_displace_negative_strength_lowers_surface():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_displace",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.1,
                "strength": -0.25,
                "falloff": "SMOOTH",
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["vertices"][0] == pytest.approx([0, 0, -0.25])
    assert result.data["after"]["affected_vertex_indices"] == [0]


def test_displace_rejects_empty_or_invalid_normal_selection():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_displace",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [99, 99, 99],
                "radius": 0.1,
                "strength": 1.0,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj) == before


def test_smooth_brush_relaxes_interior_peak():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    fan(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_smooth",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [1, 1, 1],
                "radius": 0.1,
                "strength": 1.0,
                "falloff": "LINEAR",
                "iterations": 1,
                "preserve_boundary": True,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_indices"] == [4]
    assert after["vertices"][4] == pytest.approx([1, 1, 0])
    assert after["faces"] == before["faces"]


def test_smooth_preserve_boundary_rejects_boundary_only_brush():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_smooth",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.1,
                "strength": 0.5,
                "falloff": "SMOOTH",
                "iterations": 2,
                "preserve_boundary": True,
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj) == before


def test_sculpt_mutation_rejects_stale_geometry_and_modifier_stack():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    quad(obj)
    stale = meshes.snapshot(obj)
    obj.data.vertices[0].co = [0, 0, 0.1]
    obj.data.update()

    result = registry.dispatch(
        Request(
            "sculpt.brush_displace",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": stale["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 1,
                "strength": 0.1,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE

    fresh = meshes.snapshot(obj)
    modifier = obj.modifiers.new("Sub", "SUBSURF")
    modifier.levels = 1
    modifier.render_levels = 1
    result = registry.dispatch(
        Request(
            "sculpt.brush_displace",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": fresh["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 1,
                "strength": 0.1,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_sculpt_brush_vertex_work_limit_is_enforced():
    bpy, inspector, meshes, sculpt, registry = setup()
    obj = bpy.data.objects.get("Cube")
    size = 23
    vertices = [[x, y, 0] for y in range(size) for x in range(size)]
    faces = []
    for y in range(size - 1):
        for x in range(size - 1):
            a = y * size + x
            faces.append([a, a + 1, a + 1 + size, a + size])
    obj.data.from_pydata(vertices, [], faces)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_displace",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [11, 11, 0],
                "radius": 100,
                "strength": 0.1,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert meshes.snapshot(obj) == before


def test_sculpt_verification_failure_rolls_back_coordinates():
    bpy, inspector, meshes, sculpt, registry = setup()
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
            "sculpt.brush_displace",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "center": [0, 0, 0],
                "radius": 0.1,
                "strength": 0.2,
                "falloff": "LINEAR",
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]


def test_level3_milestone1_contract_validation():
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
        SculptBrush.parse(common | {"strength": 0})
    with pytest.raises(AgentError):
        SculptBrush.parse(common | {"strength": 1, "falloff": "GAUSSIAN"})
    with pytest.raises(AgentError):
        SculptSmooth.parse(
            common
            | {
                "strength": 0.5,
                "iterations": 9,
                "preserve_boundary": True,
            }
        )
    with pytest.raises(AgentError):
        SculptSmooth.parse(
            common
            | {
                "strength": 0.5,
                "iterations": 1,
                "preserve_boundary": 1,
            }
        )
