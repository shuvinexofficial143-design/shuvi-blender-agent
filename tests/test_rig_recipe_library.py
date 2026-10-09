from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.rig_recipe_library import (
    COMPATIBILITY,
    LIBRARY_VERSION,
    MIN_BLENDER_VERSION,
    RECIPE_SPECS,
    RecipeAction,
)
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS

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
        )
        if constraint_type == "LIMIT_ROTATION":
            constraint.use_limit_x = False
            constraint.min_x = 0.0
            constraint.max_x = 0.0
            constraint.use_limit_y = False
            constraint.min_y = 0.0
            constraint.max_y = 0.0
            constraint.use_limit_z = False
            constraint.min_z = 0.0
            constraint.max_z = 0.0
        elif constraint_type == "IK":
            constraint.target = None
            constraint.subtarget = ""
            constraint.chain_count = 0
        else:
            raise RuntimeError("Unsupported fake constraint type")
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


def setup_recipe_rig():
    upper = bone("Upper", head=(0, 0, 0), tail=(0, 0, 1))
    middle = bone("Middle", parent=upper, head=(0, 0, 1), tail=(0, 0, 2))
    end = bone("End", parent=middle, head=(0, 0, 2), tail=(0, 0, 3))
    target = bone("IK.Target", head=(1, 0, 3), tail=(1, 0, 4), deform=False)
    obj = FakeObject("RecipeRig", "ARMATURE")
    obj.data = NS(
        name="RecipeRigData",
        users=0,
        library=None,
        bones=[upper, middle, end, target],
    )
    obj.pose = NS(
        bones=[
            pose_bone("Upper"),
            pose_bone("Middle"),
            pose_bone("End"),
            pose_bone("IK.Target"),
        ]
    )
    bpy = fake_bpy([obj])
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    object_id = next(
        item["object_id"]
        for item in registry.dispatch(Request("objects.list")).data["items"]
        if item["name"] == "RecipeRig"
    )
    rig = registry.dispatch(Request("rig.armature_inspect", {"object_id": object_id})).data
    return bpy, obj, registry, object_id, rig


def target_from_rig(rig):
    return {
        "object_id": rig["object_id"],
        "expected_name": rig["name"],
        "expected_revision": rig["object_revision"],
    }


def recipe_payload(rig, recipe_id, parameters):
    return {
        "recipe_id": recipe_id,
        "target": target_from_rig(rig),
        "expected_rig_revision": rig["rig_revision"],
        "parameters": parameters,
    }


def limit_parameters():
    return {
        "bone_name": "Upper",
        "constraint_name": "Recipe Limit",
        "influence": 0.75,
        "mute": False,
        "use_limit_x": True,
        "min_x": -0.5,
        "max_x": 0.5,
        "use_limit_y": False,
        "min_y": -0.25,
        "max_y": 0.25,
        "use_limit_z": True,
        "min_z": -1.0,
        "max_z": 1.0,
    }


def ik_parameters():
    return {
        "bone_name": "End",
        "constraint_name": "Recipe IK",
        "influence": 1.0,
        "mute": False,
        "target_bone_name": "IK.Target",
        "chain_count": 3,
    }


def ik_fk_parameters():
    return {
        "upper_bone": "Upper",
        "middle_bone": "Middle",
        "end_bone": "End",
        "target_bone": "IK.Target",
        "constraint_name": "Recipe IKFK",
        "initial_mode": "IK",
    }


def test_factory_registers_level6_m9_recipe_tools_at_raised_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 308
    assert MAX_REGISTERED_TOOLS == 308
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.recipe_catalog", "rig.recipe_preview", "rig.recipe_apply"} <= names


def test_recipe_catalog_is_deterministic_versioned_and_bounded():
    _, _, registry, _, _ = setup_recipe_rig()
    first = registry.dispatch(Request("rig.recipe_catalog", {}))
    second = registry.dispatch(Request("rig.recipe_catalog", {}))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    assert first.data["library_version"] == LIBRARY_VERSION == 1
    assert first.data["minimum_blender_version"] == MIN_BLENDER_VERSION == "4.2"
    assert first.data["compatibility"] == COMPATIBILITY
    assert first.data["recipe_count"] == len(RECIPE_SPECS) == 3
    assert [item["recipe_id"] for item in first.data["recipes"]] == sorted(RECIPE_SPECS)
    assert len(first.data["catalog_revision"]) == 64
    for descriptor in first.data["recipes"]:
        assert descriptor["recipe_version"] == 1
        assert descriptor["operations"] == ["preview", "apply"]
        assert descriptor["source_only"] is True
        assert descriptor["real_runtime_verified"] is False
        assert descriptor["parameter_schema"]


@pytest.mark.parametrize(
    ("recipe_id", "parameters", "operation"),
    [
        ("constraint.limit_rotation", limit_parameters(), "rig.pose_constraint_create"),
        ("constraint.same_armature_ik", ik_parameters(), "rig.pose_constraint_create"),
        ("control.three_bone_ik_fk", ik_fk_parameters(), "rig.ik_fk_setup"),
    ],
)
def test_recipe_preview_is_fresh_revision_gated_and_reports_delegate_plan(
    recipe_id, parameters, operation
):
    _, _, registry, _, rig = setup_recipe_rig()
    result = registry.dispatch(
        Request("rig.recipe_preview", recipe_payload(rig, recipe_id, parameters))
    )

    assert result.status == Status.SUCCEEDED
    assert result.data["recipe"]["recipe_id"] == recipe_id
    preview = result.data["preview"]
    assert preview["ready"] is True
    assert preview["blockers"] == []
    assert preview["plan"]["operation"] == operation
    assert preview["rig_revision"] == rig["rig_revision"]
    assert preview["source_only"] is True
    assert preview["real_runtime_verified"] is False


def test_recipe_preview_rejects_stale_rig_revision():
    _, obj, registry, _, rig = setup_recipe_rig()
    obj.pose.bones[0].location = [0.5, 0.0, 0.0]

    result = registry.dispatch(
        Request(
            "rig.recipe_preview",
            recipe_payload(rig, "constraint.limit_rotation", limit_parameters()),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE


@pytest.mark.parametrize(
    ("recipe_id", "parameters", "constraint_type"),
    [
        ("constraint.limit_rotation", limit_parameters(), "LIMIT_ROTATION"),
        ("constraint.same_armature_ik", ik_parameters(), "IK"),
    ],
)
def test_constraint_recipes_apply_through_verified_existing_mutation(
    recipe_id, parameters, constraint_type
):
    _, obj, registry, object_id, rig = setup_recipe_rig()
    result = registry.dispatch(
        Request("rig.recipe_apply", recipe_payload(rig, recipe_id, parameters))
    )

    assert result.status == Status.VERIFIED
    assert result.verification["matched"] is True
    delegate = result.data["delegate_result"]
    assert delegate["before"]["rig_revision"] == rig["rig_revision"]
    after = registry.dispatch(Request("rig.armature_inspect", {"object_id": object_id})).data
    owner = next(item for item in after["pose_bones"] if item["name"] == parameters["bone_name"])
    created = next(
        item for item in owner["constraints"] if item["name"] == parameters["constraint_name"]
    )
    assert created["type"] == constraint_type
    assert obj.select_get() is True


def test_ik_fk_recipe_apply_uses_managed_m8_setup_and_exact_readback():
    _, _, registry, _, rig = setup_recipe_rig()
    result = registry.dispatch(
        Request(
            "rig.recipe_apply",
            recipe_payload(rig, "control.three_bone_ik_fk", ik_fk_parameters()),
        )
    )

    assert result.status == Status.VERIFIED
    assert result.verification["matched"] is True
    delegate = result.data["delegate_result"]
    assert delegate["ik_fk"]["managed"] is True
    assert delegate["ik_fk"]["mode"] == "IK"
    assert delegate["ik_fk"]["constraint"]["chain_count"] == 3
    assert delegate["ik_fk"]["constraint"]["target_bone_name"] == "IK.Target"


def test_recipe_apply_propagates_verified_delegate_recovery(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    _, obj, registry, _, rig = setup_recipe_rig()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.recipe_apply",
            recipe_payload(rig, "control.three_bone_ik_fk", ik_fk_parameters()),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    delegate = result.data["delegate_result"]
    assert delegate["rolled_back"] is True
    assert delegate["recovery_verified"] is True
    end = next(item for item in obj.pose.bones if item.name == "End")
    assert len(end.constraints) == 0


@pytest.mark.parametrize(
    "payload",
    [
        {
            "recipe_id": "unknown.recipe",
            "target": {
                "object_id": "id",
                "expected_name": "Rig",
                "expected_revision": "x" * 64,
            },
            "expected_rig_revision": "y" * 64,
            "parameters": {},
        },
        {
            "recipe_id": "constraint.limit_rotation",
            "target": {
                "object_id": "id",
                "expected_name": "Rig",
                "expected_revision": "x" * 64,
            },
            "expected_rig_revision": "y" * 64,
            "parameters": [],
        },
        {
            "recipe_id": "constraint.same_armature_ik",
            "target": {
                "object_id": "id",
                "expected_name": "Rig",
                "expected_revision": "x" * 64,
            },
            "expected_rig_revision": "y" * 64,
            "parameters": {
                "bone_name": "End",
                "constraint_name": "Recipe IK",
                "influence": 1.0,
                "mute": False,
                "target_bone_name": "IK.Target",
                "chain_count": 3,
                "unrestricted_extra": True,
            },
        },
    ],
)
def test_recipe_contract_rejects_unknown_untyped_or_extra_payload(payload):
    with pytest.raises(AgentError):
        RecipeAction.parse(payload)
