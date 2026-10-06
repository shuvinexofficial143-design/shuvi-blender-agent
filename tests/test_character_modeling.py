import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.character_blockout import (
    BlockoutPlan,
    CharacterBlockoutOperations,
    LandmarkFit,
    ProportionGuide,
)
from shuvi_blender_agent.character_face import (
    CharacterFaceOperations,
    FaceFit,
    FaceGuide,
    FaceRegions,
    FaceSymmetryAudit,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.mesh import MeshOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    meshes = MeshOperations(objects)
    blockout = CharacterBlockoutOperations(objects)
    face = CharacterFaceOperations(objects)
    registry = ToolRegistry(
        [*blockout.tools(), *face.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, blockout, face, registry


def body_mesh(obj):
    obj.data.from_pydata(
        [
            [-0.8, 0, 0.0],
            [0.8, 0, 0.0],
            [-0.7, 0, 0.5],
            [0.7, 0, 0.5],
            [-1.0, 0, 1.0],
            [1.0, 0, 1.0],
            [-1.2, 0, 1.55],
            [1.2, 0, 1.55],
            [0.0, 0, 1.75],
            [0.0, 0, 2.0],
        ],
        [],
        [],
    )


def exact_face_mesh(obj, front_y=0.92):
    points = [
        [-1, -1, 0],
        [1, -1, 0],
        [-1, 1, 2],
        [1, 1, 2],
    ]
    template = {
        "BROW_L": (-0.40, 1.64),
        "BROW_R": (0.40, 1.64),
        "EYE_L": (-0.40, 1.40),
        "EYE_R": (0.40, 1.40),
        "NOSE_BRIDGE": (0.00, 1.26),
        "NOSE_TIP": (0.00, 1.02),
        "MOUTH_L": (-0.32, 0.68),
        "MOUTH_R": (0.32, 0.68),
        "PHILTRUM": (0.00, 0.80),
        "CHIN": (0.00, 0.24),
        "JAW_L": (-0.68, 0.40),
        "JAW_R": (0.68, 0.40),
        "EAR_L": (-0.94, 1.12),
        "EAR_R": (0.94, 1.12),
    }
    points.extend([[x, front_y, z] for x, z in template.values()])
    obj.data.from_pydata(points, [], [])


def test_proportion_guide_is_deterministic_and_scaled():
    bpy, inspector, meshes, blockout, face, registry = setup()
    result = registry.dispatch(
        Request(
            "character.proportion_guide",
            {
                "preset": "ADULT_NEUTRAL",
                "height": 1.8,
                "origin": [0, 0, 0],
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["head_units"] == pytest.approx(7.5)
    assert data["head_height"] == pytest.approx(0.24)
    assert data["height"] == pytest.approx(1.8)
    assert data["coordinate_convention"] == "LOCAL_X_LEFT_RIGHT_Y_DEPTH_Z_UP"
    assert data["guide_status"] == "REFERENCE_ONLY"
    assert data["centerline_landmarks"][0]["name"] == "HEAD_TOP"
    assert data["paired_landmarks"][0]["name"] == "SHOULDER_L"


def test_blockout_plan_has_symmetric_body_parts():
    bpy, inspector, meshes, blockout, face, registry = setup()
    result = registry.dispatch(
        Request(
            "character.blockout_plan",
            {
                "preset": "HEROIC",
                "height": 2.0,
                "origin": [1, 2, 3],
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["part_count"] == 11
    assert data["symmetry_axis"] == "LOCAL_X"
    assert data["execution_status"] == "PLANNING_ONLY"
    by_name = {item["name"]: item for item in data["parts"]}
    assert by_name["UPPER_ARM_L"]["center"][0] < 1
    assert by_name["UPPER_ARM_R"]["center"][0] > 1
    assert by_name["THIGH_L"]["dimensions"] == by_name["THIGH_R"]["dimensions"]


def test_landmark_fit_maps_guide_targets_to_mesh_candidates_without_mutation():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    body_mesh(obj)
    before = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "character.landmark_fit",
            {
                "object_id": inspector.identity(obj),
                "preset": "ADULT_NEUTRAL",
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["mesh_height"] == pytest.approx(2.0)
    assert data["landmark_count"] == 18
    assert data["fit_status"] == "CANDIDATE_MAPPING_ONLY"
    assert all(item["vertex_index"] >= 0 for item in data["fitted_landmarks"])
    assert meshes.snapshot(obj) == before


def test_face_guide_builds_expected_local_reference_points():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    exact_face_mesh(obj)

    result = registry.dispatch(
        Request(
            "character.face_guide",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "POSITIVE_Y",
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["width"] == pytest.approx(2)
    assert data["depth"] == pytest.approx(2)
    assert data["height"] == pytest.approx(2)
    assert data["surface_y"] == pytest.approx(0.92)
    assert data["landmark_count"] == 14
    assert data["guide_status"] == "REFERENCE_ONLY"
    by_name = {item["name"]: item for item in data["landmarks"]}
    assert by_name["NOSE_TIP"]["position"] == pytest.approx([0, 0.92, 1.02])
    assert by_name["EYE_L"]["position"][0] == pytest.approx(-0.4)
    assert by_name["EYE_R"]["position"][0] == pytest.approx(0.4)


def test_face_landmark_fit_accepts_exact_candidates():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    exact_face_mesh(obj)

    result = registry.dispatch(
        Request(
            "character.face_landmark_fit",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "POSITIVE_Y",
                "max_normalized_distance": 0.01,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["landmark_count"] == 14
    assert data["rejected_count"] == 0
    assert data["fit_status"] == "CANDIDATE_MAPPING_ONLY"
    assert all(item["normalized_distance"] == pytest.approx(0) for item in data["fitted_landmarks"])


def test_face_region_plan_returns_bounded_brush_regions():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    exact_face_mesh(obj)

    result = registry.dispatch(
        Request(
            "character.face_region_plan",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "POSITIVE_Y",
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["region_count"] == 6
    assert data["purpose"] == "SCULPT_BRUSH_PLANNING_ONLY"
    names = {item["name"] for item in data["regions"]}
    assert {"LEFT_EYE_SOCKET", "RIGHT_EYE_SOCKET", "NOSE", "MOUTH", "CHIN_JAW", "BROW"} == names
    assert all(item["radius"] > 0 for item in data["regions"])


def test_face_symmetry_audit_passes_exact_symmetric_candidates():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    exact_face_mesh(obj)

    result = registry.dispatch(
        Request(
            "character.face_symmetry_audit",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "POSITIVE_Y",
                "tolerance": 0.001,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["symmetry_status"] == "PASS"
    assert data["violation_count"] == 0
    assert all(item["within_tolerance"] for item in data["pair_results"])
    assert all(item["within_tolerance"] for item in data["centerline_results"])


def test_face_symmetry_audit_flags_asymmetric_candidate():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    exact_face_mesh(obj)
    obj.data.vertices[5].co = [0.8, 0.92, 1.4]
    obj.data.update()

    result = registry.dispatch(
        Request(
            "character.face_symmetry_audit",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "POSITIVE_Y",
                "tolerance": 0.05,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["symmetry_status"] == "REVIEW"
    assert result.data["violation_count"] > 0


def test_negative_y_face_guide_uses_opposite_surface():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    exact_face_mesh(obj, front_y=-0.92)

    result = registry.dispatch(
        Request(
            "character.face_guide",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "NEGATIVE_Y",
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["surface_y"] == pytest.approx(-0.92)


def test_character_helpers_reject_flat_or_wrong_type_geometry():
    bpy, inspector, meshes, blockout, face, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata([[0, 0, 0], [1, 0, 0]], [], [])

    result = registry.dispatch(
        Request(
            "character.face_guide",
            {
                "object_id": inspector.identity(obj),
                "front_direction": "POSITIVE_Y",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED

    sphere = bpy.data.objects.get("Sphere")
    sphere.type = "EMPTY"
    result = registry.dispatch(
        Request(
            "character.landmark_fit",
            {
                "object_id": inspector.identity(sphere),
                "preset": "ADULT_NEUTRAL",
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_milestones6_and7_contract_validation():
    with pytest.raises(AgentError):
        ProportionGuide.parse(
            {"preset": "UNKNOWN", "height": 1.8, "origin": [0, 0, 0]}
        )
    with pytest.raises(AgentError):
        BlockoutPlan.parse(
            {"preset": "HEROIC", "height": 0, "origin": [0, 0, 0]}
        )
    with pytest.raises(AgentError):
        LandmarkFit.parse({"object_id": "id", "preset": "UNKNOWN"})
    with pytest.raises(AgentError):
        FaceGuide.parse({"object_id": "id", "front_direction": "FRONT"})
    with pytest.raises(AgentError):
        FaceFit.parse(
            {
                "object_id": "id",
                "front_direction": "POSITIVE_Y",
                "max_normalized_distance": 0,
            }
        )
    with pytest.raises(AgentError):
        FaceSymmetryAudit.parse(
            {
                "object_id": "id",
                "front_direction": "POSITIVE_Y",
                "tolerance": 0,
            }
        )
    assert FaceRegions.parse(
        {"object_id": "id", "front_direction": "NEGATIVE_Y"}
    ).object_id == "id"
