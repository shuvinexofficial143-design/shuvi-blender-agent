from types import SimpleNamespace as NS

from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.rig_acceptance import (
    Level6AcceptanceRequest,
    RigAcceptanceOperations,
)
from shuvi_blender_agent.rig_recipe_library import RigRecipeLibraryOperations
from shuvi_blender_agent.rigging import RiggingOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare

IDENTITY = [[float(row == col) for col in range(4)] for row in range(4)]


def bone(name, *, parent=None, head=(0, 0, 0), tail=(0, 0, 1), deform=True):
    return NS(
        name=name,
        parent=parent,
        head_local=list(head),
        tail_local=list(tail),
        matrix_local=[row[:] for row in IDENTITY],
        use_connect=False,
        use_deform=deform,
        inherit_scale="FULL",
    )


class FakePoseConstraints(list):
    def new(self, constraint_type):
        constraint = NS(
            name=constraint_type,
            type=constraint_type,
            mute=False,
            influence=1.0,
            target=None,
            subtarget="",
            chain_count=0,
        )
        self.append(constraint)
        return constraint


def pose_bone(name):
    return NS(
        name=name,
        rotation_mode="XYZ",
        location=[0.0, 0.0, 0.0],
        rotation_euler=[0.0, 0.0, 0.0],
        rotation_quaternion=[1.0, 0.0, 0.0, 0.0],
        scale=[1.0, 1.0, 1.0],
        constraints=FakePoseConstraints(),
    )


def target(snapshot):
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def rig_target(snapshot):
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["object_revision"],
    }


def object_state(registry, name):
    items = registry.dispatch(Request("objects.list", {"limit": 100})).data["items"]
    return next(item for item in items if item["name"] == name)


def inspect_rig(registry, object_id):
    result = registry.dispatch(Request("rig.armature_inspect", {"object_id": object_id}))
    assert result.status == Status.SUCCEEDED
    return result.data


def setup_acceptance_rig():
    upper = bone("Upper", head=(0, 0, 0), tail=(0, 0, 1))
    middle = bone("Middle", parent=upper, head=(0, 0, 1), tail=(0, 0, 2))
    end = bone("End", parent=middle, head=(0, 0, 2), tail=(0, 0, 3))
    control = bone("IK.Target", head=(1, 0, 3), tail=(1, 0, 4), deform=False)
    rig = FakeObject("AcceptanceRig", "ARMATURE")
    rig.data = NS(
        name="AcceptanceRigData",
        users=0,
        library=None,
        bones=[upper, middle, end, control],
    )
    rig.pose = NS(
        bones=[
            pose_bone("Upper"),
            pose_bone("Middle"),
            pose_bone("End"),
            pose_bone("IK.Target"),
        ]
    )
    mesh = FakeObject("Body", "MESH")
    bpy = fake_bpy([mesh, rig])
    mesh.data.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [],
        [(0, 1, 2), (0, 2, 3)],
    )
    mesh.data.update()
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    rigging = RiggingOperations(objects)
    recipes = RigRecipeLibraryOperations(objects)
    registry = ToolRegistry(
        [*objects.tools(), *rigging.tools(), *recipes.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    acceptance = RigAcceptanceOperations(objects)

    mesh_state = objects._readback(mesh)
    rig_state = rigging._snapshot(rig)
    bound = registry.dispatch(
        Request(
            "rig.mesh_armature_bind",
            {
                "mesh_target": target(mesh_state),
                "armature_target": rig_target(rig_state),
                "expected_rig_revision": rig_state["rig_revision"],
                "modifier_name": "Shuvi Armature",
            },
        )
    )
    assert bound.status == Status.VERIFIED

    mesh_state = objects._readback(mesh)
    rig_state = rigging._snapshot(rig)
    weights = registry.dispatch(
        Request(
            "rig.mesh_weights_inspect",
            {
                "mesh_object_id": mesh_state["object_id"],
                "armature_object_id": rig_state["object_id"],
            },
        )
    ).data
    weighted = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            {
                "mesh_target": target(mesh_state),
                "armature_target": rig_target(rig_state),
                "expected_rig_revision": rig_state["rig_revision"],
                "expected_weight_revision": weights["weight_revision"],
                "bone_name": "Upper",
                "weights": [
                    {"vertex_index": 0, "weight": 1.0},
                    {"vertex_index": 1, "weight": 0.75},
                    {"vertex_index": 2, "weight": 0.25},
                ],
            },
        )
    )
    assert weighted.status == Status.VERIFIED
    rig_state = rigging._snapshot(rig)
    return bpy, rig, mesh, registry, acceptance, rig_state, mesh_state


def acceptance_payload(rig_state, mesh_state):
    return {
        "mesh_object_id": mesh_state["object_id"],
        "recipe_id": "control.three_bone_ik_fk",
        "target": rig_target(rig_state),
        "expected_rig_revision": rig_state["rig_revision"],
        "parameters": {
            "upper_bone": "Upper",
            "middle_bone": "Middle",
            "end_bone": "End",
            "target_bone": "IK.Target",
            "constraint_name": "Acceptance IKFK",
            "initial_mode": "IK",
        },
    }


def evaluate(acceptance, payload):
    return acceptance.evaluate(Level6AcceptanceRequest.parse(payload))


def test_m10_reconciles_cap_without_new_public_tools():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS == 252
    names = {item["name"] for item in registry.catalog()}
    assert "rig.level6_acceptance" not in names
    assert "rig.workflow_preview" not in names


def test_level6_acceptance_passes_full_m1_m9_source_state():
    _, _, _, _, acceptance, rig_state, mesh_state = setup_acceptance_rig()
    data = evaluate(acceptance, acceptance_payload(rig_state, mesh_state))

    assert data["source_acceptance_status"] == "READY"
    assert data["check_count"] == 6
    assert all(item["status"] == "PASS" for item in data["checks"])
    assert data["source_level_complete_when_passed"] == 6
    assert data["source_scope"] == "LEVEL_6_SOURCE_AND_FAKE_BPY_ACCEPTANCE_ONLY"
    assert data["verified_recovery_required"] is True
    assert data["runtime_acceptance_required"] is True
    assert data["real_runtime_verified"] is False
    assert data["production_ready"] is False
    assert data["public_tool_added"] is False
    assert len(data["acceptance_revision"]) == 64


def test_level6_acceptance_fails_closed_on_stale_rig_state():
    _, rig, _, _, acceptance, rig_state, mesh_state = setup_acceptance_rig()
    payload = acceptance_payload(rig_state, mesh_state)
    rig.pose.bones[0].location = [0.25, 0.0, 0.0]

    try:
        evaluate(acceptance, payload)
    except Exception as exc:
        assert getattr(exc, "code", None) == ErrorCode.STALE_STATE
    else:
        raise AssertionError("stale rig acceptance must fail closed")


def test_failed_ik_fk_apply_recovers_then_acceptance_still_passes(monkeypatch):
    _, rig, _, registry, acceptance, rig_state, mesh_state = setup_acceptance_rig()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    payload = acceptance_payload(rig_state, mesh_state)
    recipe_payload = {key: value for key, value in payload.items() if key != "mesh_object_id"}
    result = registry.dispatch(Request("rig.recipe_apply", recipe_payload))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    delegate = result.data["delegate_result"]
    assert delegate["rolled_back"] is True
    assert delegate["recovery_verified"] is True
    end = next(item for item in rig.pose.bones if item.name == "End")
    assert len(end.constraints) == 0

    recovered = evaluate(acceptance, payload)
    assert recovered["source_acceptance_status"] == "READY"
    assert all(item["status"] == "PASS" for item in recovered["checks"])
