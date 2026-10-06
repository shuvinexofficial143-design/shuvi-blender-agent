import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.character_body import (
    BodyRegionPlan,
    BodySymmetryAudit,
    CharacterBodyOperations,
    ExtremityGuide,
    LimbGuide,
)
from shuvi_blender_agent.character_sculpt_workflow import (
    CharacterSculptQA,
    CharacterSculptWorkflowOperations,
    RecoveryRestore,
    RecoverySnapshot,
    SculptRecipePreview,
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
    body = CharacterBodyOperations(objects)
    workflow = CharacterSculptWorkflowOperations(objects)
    registry = ToolRegistry(
        [*body.tools(), *workflow.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, meshes, body, workflow, registry


def cube_like(obj):
    obj.data.from_pydata(
        [
            [-1, -1, 0],
            [1, -1, 0],
            [1, 1, 0],
            [-1, 1, 0],
            [-1, -1, 2],
            [1, -1, 2],
            [1, 1, 2],
            [-1, 1, 2],
        ],
        [],
        [
            [0, 3, 2, 1],
            [4, 5, 6, 7],
            [0, 1, 5, 4],
            [1, 2, 6, 5],
            [2, 3, 7, 6],
            [3, 0, 4, 7],
        ],
    )


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def test_body_region_plan_returns_full_symmetric_region_set():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "character.body_region_plan",
            {
                "object_id": inspector.identity(obj),
                "preset": "ADULT_NEUTRAL",
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["mesh_height"] == pytest.approx(2)
    assert data["region_count"] == 17
    assert data["symmetry_axis"] == "LOCAL_X"
    assert data["purpose"] == "CHARACTER_SCULPT_REGION_PLANNING_ONLY"
    names = {item["name"] for item in data["regions"]}
    assert {"CHEST", "ABDOMEN", "PELVIS", "HAND_L", "HAND_R", "FOOT_L", "FOOT_R"} <= names


def test_limb_guides_are_side_aware_for_arm_and_leg():
    bpy, inspector, meshes, body, workflow, registry = setup()

    left_arm = registry.dispatch(
        Request(
            "character.limb_guide",
            {
                "preset": "HEROIC",
                "height": 2,
                "origin": [0, 0, 0],
                "side": "LEFT",
                "limb_kind": "ARM",
            },
        )
    ).data
    right_leg = registry.dispatch(
        Request(
            "character.limb_guide",
            {
                "preset": "HEROIC",
                "height": 2,
                "origin": [0, 0, 0],
                "side": "RIGHT",
                "limb_kind": "LEG",
            },
        )
    ).data

    assert left_arm["landmark_count"] == 4
    assert left_arm["landmarks"][0]["name"] == "SHOULDER"
    assert left_arm["landmarks"][0]["position"][0] < 0
    assert right_leg["landmark_count"] == 4
    assert right_leg["landmarks"][0]["name"] == "HIP"
    assert right_leg["landmarks"][0]["position"][0] > 0


def test_hand_and_foot_extremity_guides_have_expected_landmarks():
    bpy, inspector, meshes, body, workflow, registry = setup()

    hand = registry.dispatch(
        Request(
            "character.extremity_guide",
            {
                "kind": "HAND",
                "side": "RIGHT",
                "anchor": [1, 0, 1],
                "length": 0.2,
            },
        )
    ).data
    foot = registry.dispatch(
        Request(
            "character.extremity_guide",
            {
                "kind": "FOOT",
                "side": "LEFT",
                "anchor": [-0.3, 0, 0.1],
                "length": 0.3,
            },
        )
    ).data

    assert hand["landmark_count"] == 7
    assert {item["name"] for item in hand["landmarks"]} >= {"WRIST", "THUMB_TIP", "PINKY_TIP"}
    assert foot["landmark_count"] == 5
    assert {item["name"] for item in foot["landmarks"]} >= {"HEEL", "BIG_TOE", "LITTLE_TOE"}


def test_body_symmetry_audit_passes_symmetric_cube():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "character.body_symmetry_audit",
            {
                "object_id": inspector.identity(obj),
                "tolerance": 0.0001,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["symmetry_status"] == "PASS"
    assert data["paired_vertex_count"] == 8
    assert data["unmatched_positive_indices"] == []
    assert data["unmatched_negative_indices"] == []
    assert data["symmetry_candidate_checks"] > 0


def test_body_symmetry_audit_flags_asymmetric_mesh():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)
    obj.data.vertices[1].co = [1.4, -1, 0]
    obj.data.update()

    data = registry.dispatch(
        Request(
            "character.body_symmetry_audit",
            {
                "object_id": inspector.identity(obj),
                "tolerance": 0.01,
            },
        )
    ).data
    assert data["symmetry_status"] == "REVIEW"
    assert data["unmatched_positive_indices"]


def test_character_sculpt_qa_passes_closed_symmetric_mesh():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    result = registry.dispatch(
        Request(
            "character.sculpt_qa",
            {
                "object_id": inspector.identity(obj),
                "symmetry_tolerance": 0.0001,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["qa_status"] == "PASS"
    assert data["blockers"] == []
    assert data["advisories"] == []
    assert data["sculpt"]["sculpt_ready"] is True
    assert len(data["qa_revision"]) == 64


def test_character_sculpt_qa_reviews_asymmetry_without_false_blocker():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)
    obj.data.vertices[1].co = [1.3, -1, 0]
    obj.data.update()

    data = registry.dispatch(
        Request(
            "character.sculpt_qa",
            {
                "object_id": inspector.identity(obj),
                "symmetry_tolerance": 0.01,
            },
        )
    ).data
    assert data["qa_status"] == "REVIEW"
    assert "LOCAL_X_SYMMETRY_REVIEW" in data["advisories"]
    assert data["blockers"] == []


@pytest.mark.parametrize(
    ("recipe", "expected_count"),
    [
        ("BODY_PRIMARY_FORMS", 3),
        ("FACE_PRIMARY_FORMS", 4),
        ("HAND_FOOT_REFINEMENT", 4),
    ],
)
def test_sculpt_recipe_preview_is_allowlisted_and_nonexecuting(recipe, expected_count):
    bpy, inspector, meshes, body, workflow, registry = setup()
    result = registry.dispatch(
        Request(
            "character.sculpt_recipe_preview",
            {"recipe": recipe, "intensity": 0.8},
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["recipe"] == recipe
    assert data["step_count"] == expected_count
    assert data["execution_status"] == "PREVIEW_ONLY"
    assert data["automatic_execution"] is False
    assert data["requires_fresh_state_per_mutation"] is True
    assert len(data["recipe_revision"]) == 64


def test_recovery_snapshot_and_restore_round_trip_coordinates():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    snapshot = registry.dispatch(
        Request(
            "character.sculpt_recovery_snapshot",
            {
                "object_id": inspector.identity(obj),
                "vertex_indices": [0, 1],
            },
        )
    ).data
    assert snapshot["entry_count"] == 2
    original = snapshot["entries"]

    obj.data.vertices[0].co = [-0.5, -1, 0.4]
    obj.data.vertices[1].co = [0.5, -1, 0.4]
    obj.data.update()
    changed = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "character.sculpt_recovery_restore",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": changed["geometry_revision"],
                "expected_topology_revision": snapshot["topology_revision"],
                "entries": original,
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["vertices"][0] == pytest.approx([-1, -1, 0])
    assert after["vertices"][1] == pytest.approx([1, -1, 0])
    assert after["restored_vertex_indices"] == [0, 1]
    assert after["restored_vertex_count"] == 2


def test_recovery_restore_rejects_changed_topology():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)

    snapshot = registry.dispatch(
        Request(
            "character.sculpt_recovery_snapshot",
            {
                "object_id": inspector.identity(obj),
                "vertex_indices": [0],
            },
        )
    ).data
    obj.data.from_pydata(
        [[-1, -1, 0], [1, -1, 0], [0, 1, 0], [0, 0, 2]],
        [],
        [[0, 1, 2], [0, 3, 1], [1, 3, 2], [2, 3, 0]],
    )
    current = meshes.snapshot(obj)

    result = registry.dispatch(
        Request(
            "character.sculpt_recovery_restore",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": current["geometry_revision"],
                "expected_topology_revision": snapshot["topology_revision"],
                "entries": snapshot["entries"],
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE


def test_recovery_restore_verification_failure_rolls_back_current_coordinates():
    bpy, inspector, meshes, body, workflow, registry = setup()
    obj = bpy.data.objects.get("Cube")
    cube_like(obj)
    snapshot = registry.dispatch(
        Request(
            "character.sculpt_recovery_snapshot",
            {
                "object_id": inspector.identity(obj),
                "vertex_indices": [0],
            },
        )
    ).data

    obj.data.vertices[0].co = [-0.4, -1, 0.2]
    obj.data.update()
    current = meshes.snapshot(obj)
    current_position = list(current["vertices"][0])
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
            "character.sculpt_recovery_restore",
            {
                "target": target(inspector, obj),
                "expected_geometry_revision": current["geometry_revision"],
                "expected_topology_revision": snapshot["topology_revision"],
                "entries": snapshot["entries"],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert meshes.snapshot(obj)["vertices"][0] == pytest.approx(current_position)


def test_milestones8_and9_contract_validation():
    with pytest.raises(AgentError):
        BodyRegionPlan.parse({"object_id": "id", "preset": "UNKNOWN"})
    with pytest.raises(AgentError):
        LimbGuide.parse(
            {
                "preset": "ADULT_NEUTRAL",
                "height": 1.8,
                "origin": [0, 0, 0],
                "side": "CENTER",
                "limb_kind": "ARM",
            }
        )
    with pytest.raises(AgentError):
        ExtremityGuide.parse(
            {
                "kind": "HAND",
                "side": "LEFT",
                "anchor": [0, 0, 0],
                "length": 0,
            }
        )
    with pytest.raises(AgentError):
        BodySymmetryAudit.parse({"object_id": "id", "tolerance": 0})
    with pytest.raises(AgentError):
        CharacterSculptQA.parse({"object_id": "id", "symmetry_tolerance": 0})
    with pytest.raises(AgentError):
        SculptRecipePreview.parse({"recipe": "UNKNOWN", "intensity": 0.5})
    with pytest.raises(AgentError):
        RecoverySnapshot.parse({"object_id": "id", "vertex_indices": [1, 1]})
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        RecoveryRestore.parse(
            {
                "target": object_target,
                "expected_geometry_revision": "y" * 64,
                "expected_topology_revision": "z" * 64,
                "entries": [],
            }
        )
