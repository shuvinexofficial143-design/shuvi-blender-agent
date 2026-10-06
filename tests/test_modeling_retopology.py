import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling_hardsurface import HardSurfaceOperations
from shuvi_blender_agent.modeling_retopology import (
    ModelingRetopologyOperations,
    ProjectVertices,
    ProjectionInspect,
    RelaxVertices,
    ShrinkwrapAdd,
    _closest_point_triangle,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    retopo = ModelingRetopologyOperations(objects)
    hard_surface = HardSurfaceOperations(objects)
    registry = ToolRegistry(
        [*retopo.tools(), *hard_surface.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, retopo, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def source_triangle(obj, z=1.0):
    obj.data.from_pydata(
        [[0.25, 0.25, z], [0.75, 0.25, z], [0.25, 0.75, z]],
        [],
        [[0, 1, 2]],
    )


def target_quad(obj, z=0.0):
    obj.data.from_pydata(
        [[0, 0, z], [1, 0, z], [1, 1, z], [0, 1, z]],
        [],
        [[0, 1, 2, 3]],
    )


def test_closest_point_triangle_handles_face_edge_and_vertex_regions():
    a, b, c = (0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)
    assert _closest_point_triangle((0.5, 0.5, 2.0), a, b, c) == pytest.approx(
        (0.5, 0.5, 0.0)
    )
    assert _closest_point_triangle((3.0, -1.0, 0.0), a, b, c) == pytest.approx(b)
    assert _closest_point_triangle((1.5, 1.5, 0.0), a, b, c) == pytest.approx(
        (1.0, 1.0, 0.0)
    )


def test_retopology_inspect_reports_quad_ratio_valence_boundary_and_poles():
    bpy, inspector, meshes, retopo, registry = setup()
    obj = bpy.data.objects.get("Cube")
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

    result = registry.dispatch(
        Request("mesh.retopology_inspect", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["quad_face_indices"] == [0, 1]
    assert data["triangle_face_indices"] == []
    assert data["ngon_face_indices"] == []
    assert data["quad_ratio"] == 1.0
    assert data["boundary_vertex_indices"] == [0, 1, 2, 3, 4, 5]
    assert data["vertex_valence"] == [2, 3, 2, 2, 3, 2]
    assert data["interior_pole_vertex_indices"] == []


def test_projection_inspect_maps_source_vertices_to_target_surface():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source, 2.0)
    target_quad(surface, 0.0)

    result = registry.dispatch(
        Request(
            "mesh.retopology_projection_inspect",
            {
                "source_id": inspector.identity(source),
                "target_id": inspector.identity(surface),
                "vertex_indices": [0, 1, 2],
                "max_distance": 3.0,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["matched_count"] == 3
    assert data["unmatched_vertex_indices"] == []
    assert data["triangle_count"] == 2
    assert data["projection_checks"] == 6
    assert data["max_observed_distance"] == pytest.approx(2.0)
    assert all(item["point_world"][2] == pytest.approx(0.0) for item in data["matches"])
    assert all(item["normal_world"] == pytest.approx([0, 0, 1]) for item in data["matches"])


def test_projection_inspect_respects_object_translation():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source, 1.0)
    target_quad(surface, 0.0)
    source.location = [5.0, 0.0, 0.0]
    surface.location = [5.0, 0.0, 0.0]

    result = registry.dispatch(
        Request(
            "mesh.retopology_projection_inspect",
            {
                "source_id": inspector.identity(source),
                "target_id": inspector.identity(surface),
                "vertex_indices": [0],
                "max_distance": 2.0,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["matches"][0]["point_world"] == pytest.approx([5.25, 0.25, 0.0])
    assert result.data["matches"][0]["distance"] == pytest.approx(1.0)


def test_retopology_project_moves_vertices_to_surface_with_normal_offset():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source, 2.0)
    target_quad(surface, 0.0)
    source_geometry = meshes.snapshot(source)
    target_geometry = meshes.snapshot(surface)

    result = registry.dispatch(
        Request(
            "mesh.retopology_project",
            {
                "source": target(inspector, source),
                "target": target(inspector, surface),
                "expected_source_geometry_revision": source_geometry["geometry_revision"],
                "expected_target_geometry_revision": target_geometry["geometry_revision"],
                "vertex_indices": [0, 1],
                "max_distance": 3.0,
                "offset": 0.1,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["vertices"][0] == pytest.approx([0.25, 0.25, 0.1])
    assert after["vertices"][1] == pytest.approx([0.75, 0.25, 0.1])
    assert after["vertices"][2] == [0.25, 0.75, 2.0]
    assert after["projected_vertex_indices"] == [0, 1]
    assert after["target_object_id"] == inspector.identity(surface)


def test_retopology_project_denies_vertices_outside_distance_without_mutating():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source, 2.0)
    target_quad(surface, 0.0)
    source_geometry = meshes.snapshot(source)
    target_geometry = meshes.snapshot(surface)

    result = registry.dispatch(
        Request(
            "mesh.retopology_project",
            {
                "source": target(inspector, source),
                "target": target(inspector, surface),
                "expected_source_geometry_revision": source_geometry["geometry_revision"],
                "expected_target_geometry_revision": target_geometry["geometry_revision"],
                "vertex_indices": [0],
                "max_distance": 1.0,
                "offset": 0.0,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert meshes.snapshot(source)["vertices"] == source_geometry["vertices"]


def test_projection_target_rejects_ngons_and_modifier_evaluated_surface():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source, 1.0)
    surface.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [2, 1, 0], [1, 2, 0], [0, 1, 0]],
        [],
        [[0, 1, 2, 3, 4]],
    )
    result = registry.dispatch(
        Request(
            "mesh.retopology_projection_inspect",
            {
                "source_id": inspector.identity(source),
                "target_id": inspector.identity(surface),
                "vertex_indices": [0],
                "max_distance": 3.0,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED

    target_quad(surface)
    modifier = surface.modifiers.new("Sub", "SUBSURF")
    modifier.levels = 1
    modifier.render_levels = 1
    result = registry.dispatch(
        Request(
            "mesh.retopology_projection_inspect",
            {
                "source_id": inspector.identity(source),
                "target_id": inspector.identity(surface),
                "vertex_indices": [0],
                "max_distance": 3.0,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_retopology_relax_moves_interior_vertex_and_preserves_faces():
    bpy, inspector, meshes, retopo, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [1, 1, 1]],
        [],
        [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
    )
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.retopology_relax",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "vertex_indices": [4],
                "factor": 1.0,
                "iterations": 1,
                "preserve_boundary": True,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["vertices"][4] == pytest.approx([1, 1, 0])
    assert after["faces"] == before["faces"]
    assert after["relaxed_vertex_indices"] == [4]


def test_retopology_relax_preserve_boundary_rejects_boundary_only_selection():
    bpy, inspector, meshes, retopo, registry = setup()
    obj = bpy.data.objects.get("Cube")
    target_quad(obj)
    before = meshes.snapshot(obj)
    result = registry.dispatch(
        Request(
            "mesh.retopology_relax",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "vertex_indices": [0, 1],
                "factor": 0.5,
                "iterations": 2,
                "preserve_boundary": True,
            },
        )
    )
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]


def test_shrinkwrap_add_records_target_and_typed_settings():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source)
    target_quad(surface)
    stack = registry.dispatch(
        Request("modifier.stack_inspect", {"object_id": inspector.identity(source)})
    ).data

    result = registry.dispatch(
        Request(
            "modifier.shrinkwrap_add",
            {
                "source": target(inspector, source),
                "target": target(inspector, surface),
                "expected_stack_revision": stack["stack_revision"],
                "name": "RetopoWrap",
                "wrap_method": "NEAREST_SURFACEPOINT",
                "wrap_mode": "ABOVE_SURFACE",
                "offset": 0.02,
            },
        )
    )
    assert result.status == Status.VERIFIED
    item = result.data["after"]["items"][0]
    assert item["type"] == "SHRINKWRAP"
    assert item["settings"]["target_object_id"] == inspector.identity(surface)
    assert item["settings"]["target_name"] == "Sphere"
    assert item["settings"]["wrap_method"] == "NEAREST_SURFACEPOINT"
    assert item["settings"]["wrap_mode"] == "ABOVE_SURFACE"
    assert item["settings"]["offset"] == pytest.approx(0.02)


def test_existing_modifier_update_can_patch_shrinkwrap_settings():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source)
    target_quad(surface)
    modifier = source.modifiers.new("Wrap", "SHRINKWRAP")
    modifier.target = surface
    modifier.wrap_method = "NEAREST_SURFACEPOINT"
    modifier.wrap_mode = "ON_SURFACE"
    modifier.offset = 0.0
    stack = registry.dispatch(
        Request("modifier.stack_inspect", {"object_id": inspector.identity(source)})
    ).data

    result = registry.dispatch(
        Request(
            "modifier.update",
            {
                "target": target(inspector, source),
                "expected_stack_revision": stack["stack_revision"],
                "name": "Wrap",
                "kind": "SHRINKWRAP",
                "settings": {
                    "wrap_method": "NEAREST_VERTEX",
                    "wrap_mode": "ABOVE_SURFACE",
                    "offset": 0.05,
                },
            },
        )
    )
    assert result.status == Status.VERIFIED
    item = result.data["after"]["items"][0]
    assert item["settings"]["wrap_method"] == "NEAREST_VERTEX"
    assert item["settings"]["wrap_mode"] == "ABOVE_SURFACE"
    assert item["settings"]["offset"] == pytest.approx(0.05)
    assert item["settings"]["target_name"] == "Sphere"


def test_projection_verification_failure_rolls_back_source_vertices():
    bpy, inspector, meshes, retopo, registry = setup()
    source = bpy.data.objects.get("Cube")
    surface = bpy.data.objects.get("Sphere")
    source_triangle(source, 1.0)
    target_quad(surface)
    before = meshes.snapshot(source)
    target_geometry = meshes.snapshot(surface)
    original_update = source.data.update
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            source.data.vertices[0].co = [999, 999, 999]
        original_update()

    source.data.update = corrupt_once
    result = registry.dispatch(
        Request(
            "mesh.retopology_project",
            {
                "source": target(inspector, source),
                "target": target(inspector, surface),
                "expected_source_geometry_revision": before["geometry_revision"],
                "expected_target_geometry_revision": target_geometry["geometry_revision"],
                "vertex_indices": [0],
                "max_distance": 2.0,
                "offset": 0.0,
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(source)["vertices"] == before["vertices"]


def test_milestone8_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        ProjectionInspect.parse(
            {
                "source_id": "a",
                "target_id": "b",
                "vertex_indices": [],
                "max_distance": 1,
            }
        )
    with pytest.raises(AgentError):
        ProjectVertices.parse(
            {
                "source": object_target,
                "target": object_target,
                "expected_source_geometry_revision": "x" * 64,
                "expected_target_geometry_revision": "y" * 64,
                "vertex_indices": [0],
                "max_distance": 1,
                "offset": 101,
            }
        )
    with pytest.raises(AgentError):
        RelaxVertices.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "x" * 64,
                "vertex_indices": [0],
                "factor": 0.5,
                "iterations": 9,
                "preserve_boundary": True,
            }
        )
    with pytest.raises(AgentError):
        ShrinkwrapAdd.parse(
            {
                "source": object_target,
                "target": object_target,
                "expected_stack_revision": "z" * 64,
                "name": "Wrap",
                "wrap_method": "PROJECT",
                "wrap_mode": "ON_SURFACE",
                "offset": 0,
            }
        )
