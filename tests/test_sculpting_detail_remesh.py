import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.modeling_hardsurface import HardSurfaceOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.sculpting_detail import (
    DetailPlan,
    SculptDetailOperations,
    SubdivisionLevels,
    SubdivisionSetup,
)
from shuvi_blender_agent.sculpting_remesh import (
    SculptRemeshPlanningOperations,
    SurfaceAnchors,
    SurfaceSnapshot,
    VoxelPlan,
    VoxelTarget,
)
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    hard = HardSurfaceOperations(objects)
    detail = SculptDetailOperations(objects)
    remesh = SculptRemeshPlanningOperations(objects)
    registry = ToolRegistry(
        [*hard.tools(), *detail.tools(), *remesh.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, hard, detail, remesh, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def stack(registry, inspector, obj):
    return registry.dispatch(
        Request("modifier.stack_inspect", {"object_id": inspector.identity(obj)})
    ).data


def cube_like(obj):
    obj.data.from_pydata(
        [
            [-1, -1, -1],
            [1, -1, -1],
            [1, 1, -1],
            [-1, 1, -1],
            [-1, -1, 1],
            [1, -1, 1],
            [1, 1, 1],
            [-1, 1, 1],
        ],
        [],
        [
            [0, 1, 2, 3],
            [4, 7, 6, 5],
            [0, 4, 5, 1],
            [1, 5, 6, 2],
            [2, 6, 7, 3],
            [4, 0, 3, 7],
        ],
    )


def test_detail_plan_estimates_bounded_subdivision_cost():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "sculpt.detail_plan",
            {
                "object_id": inspector.identity(obj),
                "viewport_level": 2,
                "render_level": 3,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["base_face_count"] == 6
    assert data["estimated_viewport_face_count"] == 96
    assert data["estimated_render_face_count"] == 384
    assert data["estimate_model"] == "BASE_FACES_X_4_POW_LEVEL"
    assert data["existing_subsurf_count"] == 0
    assert data["multires_runtime_required"] is True
    assert data["multires_source_status"] == "PLANNING_ONLY"


def test_subdivision_setup_adds_verified_subsurf_preview():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "sculpt.subdivision_setup",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "SculptDetail",
                "viewport_level": 2,
                "render_level": 3,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["count"] == 1
    assert after["items"][0]["type"] == "SUBSURF"
    assert after["items"][0]["settings"] == {"levels": 2, "render_levels": 3}
    assert after["sculpt_detail_mode"] == "SUBSURF_PREVIEW"
    assert after["estimated_viewport_face_count"] == 96
    assert after["multires_runtime_required"] is True


def test_subdivision_setup_requires_empty_stack():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)
    modifier = obj.modifiers.new("Existing", "BEVEL")
    modifier.width = 0.1
    modifier.segments = 2
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "sculpt.subdivision_setup",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "name": "SculptDetail",
                "viewport_level": 1,
                "render_level": 2,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.modifiers) == 1


def test_subdivision_level_control_updates_verified_stack():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)
    initial = stack(registry, inspector, obj)
    setup_result = registry.dispatch(
        Request(
            "sculpt.subdivision_setup",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": initial["stack_revision"],
                "name": "SculptDetail",
                "viewport_level": 1,
                "render_level": 1,
            },
        )
    )
    current = setup_result.data["after"]

    result = registry.dispatch(
        Request(
            "sculpt.subdivision_set_levels",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": current["stack_revision"],
                "name": "SculptDetail",
                "viewport_level": 3,
                "render_level": 2,
            },
        )
    )
    assert result.status == Status.VERIFIED
    item = result.data["after"]["items"][0]
    assert item["settings"] == {"levels": 3, "render_levels": 2}
    assert result.data["after"]["estimated_viewport_face_count"] == 384


def test_detail_plan_rejects_excessive_estimated_faces():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    vertices = []
    faces = []
    for index in range(4096):
        base = len(vertices)
        vertices.extend(
            [
                [index * 2.0, 0, 0],
                [index * 2.0 + 1, 0, 0],
                [index * 2.0 + 1, 1, 0],
                [index * 2.0, 1, 0],
            ]
        )
        faces.append([base, base + 1, base + 2, base + 3])
    obj.data.from_pydata(vertices, [], faces)

    result = registry.dispatch(
        Request(
            "sculpt.detail_plan",
            {
                "object_id": inspector.identity(obj),
                "viewport_level": 3,
                "render_level": 3,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_voxel_plan_reports_grid_and_planning_only_boundary():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "sculpt.voxel_plan",
            {"object_id": inspector.identity(obj), "voxel_size": 0.5},
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["bounds_min"] == [-1, -1, -1]
    assert data["bounds_max"] == [1, 1, 1]
    assert data["extents"] == [2, 2, 2]
    assert data["grid_dimensions"] == [6, 6, 6]
    assert data["estimated_cell_count"] == 216
    assert data["runtime_remesh_required"] is True
    assert data["execution_status"] == "PLANNING_ONLY"


def test_voxel_target_density_derives_recommended_size():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "sculpt.voxel_target_density",
            {"object_id": inspector.identity(obj), "longest_axis_voxels": 20},
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["longest_axis_extent"] == pytest.approx(2)
    assert result.data["recommended_voxel_size"] == pytest.approx(0.1)
    assert result.data["grid_dimensions"] == [22, 22, 22]


def test_surface_snapshot_captures_preservation_baseline():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request("sculpt.surface_snapshot", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["centroid"] == pytest.approx([0, 0, 0])
    assert data["surface_area"] == pytest.approx(24)
    assert data["average_edge_length"] == pytest.approx(2)
    assert data["vertex_count"] == 8
    assert data["face_count"] == 6
    assert data["geometry_revision"] == meshes.snapshot(obj)["geometry_revision"]


def test_surface_anchor_plan_is_deterministic_and_bounded():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    first = registry.dispatch(
        Request(
            "sculpt.surface_anchor_plan",
            {"object_id": inspector.identity(obj), "max_anchors": 6},
        )
    ).data
    second = registry.dispatch(
        Request(
            "sculpt.surface_anchor_plan",
            {"object_id": inspector.identity(obj), "max_anchors": 6},
        )
    ).data
    assert first == second
    assert first["anchor_count"] == 6
    assert len({item["vertex_index"] for item in first["anchors"]}) == 6
    assert first["purpose"] == "POST_REMESH_SURFACE_COMPARISON"
    assert all(len(item["normal"]) == 3 for item in first["anchors"])


def test_voxel_plan_rejects_excessive_resolution():
    bpy, inspector, meshes, hard, detail, remesh, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "sculpt.voxel_plan",
            {"object_id": inspector.identity(obj), "voxel_size": 0.001},
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_milestones4_and5_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        DetailPlan.parse({"object_id": "id", "viewport_level": 4, "render_level": 1})
    with pytest.raises(AgentError):
        SubdivisionSetup.parse(
            {
                "target": object_target,
                "expected_stack_revision": "y" * 64,
                "name": "Detail",
                "viewport_level": -1,
                "render_level": 1,
            }
        )
    with pytest.raises(AgentError):
        SubdivisionLevels.parse(
            {
                "target": object_target,
                "expected_stack_revision": "y" * 64,
                "name": "Detail",
                "viewport_level": 1,
                "render_level": 5,
            }
        )
    with pytest.raises(AgentError):
        VoxelPlan.parse({"object_id": "id", "voxel_size": 0})
    with pytest.raises(AgentError):
        VoxelTarget.parse({"object_id": "id", "longest_axis_voxels": 7})
    with pytest.raises(AgentError):
        SurfaceAnchors.parse({"object_id": "id", "max_anchors": 33})
    assert SurfaceSnapshot.parse({"object_id": "id"}).object_id == "id"
