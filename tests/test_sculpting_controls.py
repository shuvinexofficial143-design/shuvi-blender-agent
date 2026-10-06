import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.sculpting_controls import (
    ControlledDisplace,
    ControlledGrab,
    RegionPreview,
    SculptControlOperations,
)
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    controls = SculptControlOperations(objects)
    registry = ToolRegistry(controls.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, meshes, controls, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def symmetric_quad(obj):
    obj.data.from_pydata(
        [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
        [],
        [[0, 1, 2, 3]],
    )


def common_region():
    return {
        "center": [1, 0, 0],
        "radius": 2.0,
        "falloff": "LINEAR",
        "axis": "X",
        "side": "POSITIVE",
        "symmetry": True,
        "plane_epsilon": 0.000001,
        "require_symmetry_pairs": True,
        "mask": [],
    }


def test_region_preview_reports_side_sources_and_mirror_pairs():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)

    result = registry.dispatch(
        Request(
            "sculpt.region_preview",
            {"object_id": inspector.identity(obj)} | common_region(),
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["source_vertex_indices"] == [1, 2]
    assert data["changed_vertex_indices"] == [0, 1, 2, 3]
    assert [entry["partner_index"] for entry in data["entries"]] == [0, 3]
    assert data["missing_symmetry_source_indices"] == []
    assert data["source_vertex_count"] == 2
    assert data["changed_vertex_count"] == 4
    assert data["symmetry_candidate_checks"] > 0


def test_region_mask_uses_stronger_weight_across_symmetry_pair():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)
    payload = common_region()
    payload["mask"] = [
        {"vertex_index": 1, "weight": 0.25},
        {"vertex_index": 0, "weight": 0.75},
    ]

    data = registry.dispatch(
        Request(
            "sculpt.region_preview",
            {"object_id": inspector.identity(obj)} | payload,
        )
    ).data
    entry = next(item for item in data["entries"] if item["source_index"] == 1)
    assert entry["mask_weight"] == pytest.approx(0.25)
    assert entry["partner_mask_weight"] == pytest.approx(0.75)
    assert entry["effective_mask_weight"] == pytest.approx(0.75)
    assert entry["final_weight"] == pytest.approx(entry["radial_weight"] * 0.25)


def test_fully_masked_source_is_removed_from_positive_influence():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)
    payload = common_region()
    payload["mask"] = [{"vertex_index": 1, "weight": 1.0}]

    data = registry.dispatch(
        Request(
            "sculpt.region_preview",
            {"object_id": inspector.identity(obj)} | payload,
        )
    ).data
    assert data["source_vertex_indices"] == [2]
    assert data["changed_vertex_indices"] == [2, 3]


def test_controlled_displace_mirrors_normal_deformation_across_x():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_displace_controlled",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "strength": 0.5,
            }
            | common_region(),
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_indices"] == [0, 1, 2, 3]
    assert after["source_vertex_indices"] == [1, 2]
    for left, right in ((0, 1), (3, 2)):
        assert after["vertices"][left][0] == pytest.approx(-after["vertices"][right][0])
        assert after["vertices"][left][1] == pytest.approx(after["vertices"][right][1])
        assert after["vertices"][left][2] == pytest.approx(after["vertices"][right][2])
        assert after["vertices"][right][2] > 0


def test_controlled_grab_mirrors_axis_component():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "sculpt.brush_grab_controlled",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "delta": [0.5, 0.25, 0],
            }
            | common_region(),
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    for left, right in ((0, 1), (3, 2)):
        assert after["vertices"][left][0] < before["vertices"][left][0]
        assert after["vertices"][right][0] > before["vertices"][right][0]
        assert after["vertices"][left][1] - before["vertices"][left][1] == pytest.approx(
            after["vertices"][right][1] - before["vertices"][right][1]
        )


def test_side_filter_without_symmetry_changes_only_positive_side():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)
    before = meshes.snapshot(obj)
    region = common_region() | {
        "symmetry": False,
        "require_symmetry_pairs": False,
    }

    result = registry.dispatch(
        Request(
            "sculpt.brush_grab_controlled",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "delta": [0, 0, 1],
            }
            | region,
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["affected_vertex_indices"] == [1, 2]
    assert after["vertices"][0] == before["vertices"][0]
    assert after["vertices"][3] == before["vertices"][3]
    assert after["vertices"][1][2] > 0
    assert after["vertices"][2][2] > 0


def test_plane_vertex_is_self_paired_and_kept_on_symmetry_plane():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [-1, 0, 0], [0, 1, 0]],
        [],
        [[0, 1, 3], [0, 3, 2]],
    )
    before = meshes.snapshot(obj)
    region = common_region() | {
        "center": [0, 0, 0],
        "radius": 2,
    }

    preview = registry.dispatch(
        Request(
            "sculpt.region_preview",
            {"object_id": inspector.identity(obj)} | region,
        )
    ).data
    plane_entry = next(item for item in preview["entries"] if item["source_index"] == 0)
    assert plane_entry["partner_index"] == 0
    assert plane_entry["on_symmetry_plane"] is True

    result = registry.dispatch(
        Request(
            "sculpt.brush_grab_controlled",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "delta": [0.5, 0, 1],
            }
            | region,
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["vertices"][0][0] == pytest.approx(0)
    assert result.data["after"]["vertices"][0][2] > 0


def test_require_pairs_fails_closed_on_asymmetric_mesh():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[1, 0, 0], [2, 0, 0], [1, 1, 0]],
        [],
        [[0, 1, 2]],
    )

    result = registry.dispatch(
        Request(
            "sculpt.region_preview",
            {"object_id": inspector.identity(obj)} | common_region(),
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_controlled_region_total_changed_vertex_cap_counts_mirrors():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    size = 23
    vertices = [[x - 11, y - 11, 0] for y in range(size) for x in range(size)]
    faces = []
    for y in range(size - 1):
        for x in range(size - 1):
            a = y * size + x
            faces.append([a, a + 1, a + size + 1, a + size])
    obj.data.from_pydata(vertices, [], faces)

    region = common_region() | {
        "center": [0, 0, 0],
        "radius": 100,
        "plane_epsilon": 0.000001,
    }
    result = registry.dispatch(
        Request(
            "sculpt.region_preview",
            {"object_id": inspector.identity(obj)} | region,
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_controlled_grab_verification_failure_rolls_back_both_sides():
    bpy, inspector, meshes, controls, registry = setup()
    obj = bpy.data.objects.get("Cube")
    symmetric_quad(obj)
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
            "sculpt.brush_grab_controlled",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": before["geometry_revision"],
                "delta": [0.5, 0, 0],
            }
            | common_region(),
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(obj)["vertices"] == before["vertices"]


def test_milestone3_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    base = common_region()

    with pytest.raises(AgentError):
        RegionPreview.parse({"object_id": "id"} | base | {"axis": "NONE"})
    with pytest.raises(AgentError):
        RegionPreview.parse(
            {"object_id": "id"} | base | {"symmetry": False, "require_symmetry_pairs": True}
        )
    with pytest.raises(AgentError):
        RegionPreview.parse(
            {"object_id": "id"}
            | base
            | {
                "mask": [
                    {"vertex_index": 1, "weight": 0.5},
                    {"vertex_index": 1, "weight": 0.25},
                ]
            }
        )
    with pytest.raises(AgentError):
        ControlledDisplace.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "y" * 64,
                "strength": 0,
            }
            | base
        )
    with pytest.raises(AgentError):
        ControlledGrab.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "y" * 64,
                "delta": [0, 0, 0],
            }
            | base
        )
