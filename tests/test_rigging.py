from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.rigging import (
    ArmatureCreate,
    ArmatureInspect,
    BoneCreate,
    BoneHierarchyEdit,
    BoneSymmetryEdit,
    IKFKSetup,
    IKFKSwitch,
    MeshArmatureBinding,
    PoseBoneReset,
    PoseBoneTransform,
    PoseConstraintCreate,
    PoseConstraintRemove,
    RiggingOperations,
    VertexGroupRemove,
    VertexGroupWeightsSet,
)
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry

IDENTITY = [[float(row == col) for col in range(4)] for row in range(4)]


def bone(name, *, parent=None, head=(0, 0, 0), tail=(0, 0, 1), connect=False, deform=True):
    return NS(
        name=name,
        parent=parent,
        head_local=list(head),
        tail_local=list(tail),
        matrix_local=[row[:] for row in IDENTITY],
        use_connect=connect,
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


def pose_bone(name, *, location=(0, 0, 0), constraints=()):
    return NS(
        name=name,
        rotation_mode="XYZ",
        location=list(location),
        rotation_euler=[0.0, 0.0, 0.0],
        rotation_quaternion=[1.0, 0.0, 0.0, 0.0],
        scale=[1.0, 1.0, 1.0],
        constraints=FakePoseConstraints(constraints),
    )


def rig_fixture():
    root = bone("Root", head=(0, 0, 0), tail=(0, 0, 1), deform=False)
    spine = bone(
        "Spine",
        parent=root,
        head=(0, 0, 1),
        tail=(0, 0, 2),
        connect=True,
    )
    arm = bone(
        "Arm.L",
        parent=spine,
        head=(0, 0, 1.8),
        tail=(1, 0, 1.8),
    )
    obj = FakeObject("CharacterRig", "ARMATURE")
    obj.data = NS(
        name="CharacterRigData",
        users=0,
        library=None,
        bones=[spine, arm, root],
    )
    obj.pose = NS(
        bones=[
            pose_bone(
                "Spine",
                location=(0.1, 0.0, 0.0),
                constraints=[
                    NS(name="Limit Rotation", type="LIMIT_ROTATION", mute=False, influence=0.75)
                ],
            ),
            pose_bone("Root"),
            pose_bone("Arm.L"),
        ]
    )
    return obj


def setup():
    obj = rig_fixture()
    bpy = fake_bpy([obj])
    inspector = BpyInspector(bpy)
    operations = RiggingOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy())
    return obj, inspector, registry


def test_factory_registers_level6_armature_inspection_under_raised_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS
    item = next(entry for entry in registry.catalog() if entry["name"] == "rig.armature_inspect")
    assert item["classification"] == "read_only"
    assert item["verification_required"] is False
    assert item["payload_fields"] == ["object_id"]


def test_armature_inspection_is_deterministic_and_reports_hierarchy_pose_state():
    obj, inspector, registry = setup()
    payload = {"object_id": inspector.identity(obj)}

    first = registry.dispatch(Request("rig.armature_inspect", payload))
    second = registry.dispatch(Request("rig.armature_inspect", payload))

    assert first.status == Status.SUCCEEDED
    assert first.data == second.data
    data = first.data
    assert data["name"] == "CharacterRig"
    assert data["armature_name"] == "CharacterRigData"
    assert data["bone_count"] == 3
    assert data["pose_bone_count"] == 3
    assert data["root_bones"] == ["Root"]
    assert data["root_count"] == 1
    assert data["hierarchy_cycle"] is False
    assert [item["name"] for item in data["bones"]] == ["Arm.L", "Root", "Spine"]
    spine = next(item for item in data["bones"] if item["name"] == "Spine")
    assert spine["parent"] == "Root"
    assert spine["use_connect"] is True
    assert spine["use_deform"] is True
    pose = next(item for item in data["pose_bones"] if item["name"] == "Spine")
    assert pose["location"] == [0.1, 0.0, 0.0]
    assert pose["constraint_count"] == 1
    assert pose["constraints"] == [
        {
            "name": "Limit Rotation",
            "type": "LIMIT_ROTATION",
            "mute": False,
            "influence": 0.75,
            "use_limit_x": False,
            "min_x": 0.0,
            "max_x": 0.0,
            "use_limit_y": False,
            "min_y": 0.0,
            "max_y": 0.0,
            "use_limit_z": False,
            "min_z": 0.0,
            "max_z": 0.0,
        }
    ]
    assert data["pose_missing_bones"] == []
    assert data["pose_extra_bones"] == []
    assert data["source_only"] is True
    assert data["real_runtime_verified"] is False
    assert len(data["object_revision"]) == 64
    assert len(data["rig_revision"]) == 64


def test_armature_inspection_reports_pose_name_mismatch_without_mutation():
    obj, inspector, registry = setup()
    obj.pose.bones.pop()
    obj.pose.bones.append(pose_bone("ForeignPoseBone"))

    result = registry.dispatch(
        Request("rig.armature_inspect", {"object_id": inspector.identity(obj)})
    )

    assert result.status == Status.SUCCEEDED
    assert result.data["pose_missing_bones"] == ["Arm.L"]
    assert result.data["pose_extra_bones"] == ["ForeignPoseBone"]


def test_armature_inspection_rejects_non_armature_object():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(RiggingOperations(ObjectOperations(inspector)).tools())

    result = registry.dispatch(
        Request(
            "rig.armature_inspect",
            {"object_id": inspector.identity(bpy.context.scene.objects[0])},
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_armature_inspection_rejects_bone_count_above_bound():
    obj = FakeObject("HugeRig", "ARMATURE")
    obj.data = NS(
        name="HugeRigData",
        users=0,
        library=None,
        bones=[bone(f"Bone{i}") for i in range(257)],
    )
    obj.pose = NS(bones=[])
    bpy = fake_bpy([obj])
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(RiggingOperations(ObjectOperations(inspector)).tools())

    result = registry.dispatch(
        Request("rig.armature_inspect", {"object_id": inspector.identity(obj)})
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"object_id": ""},
        {"object_id": "x" * 129},
        {"object_id": "id", "unexpected": True},
    ],
)
def test_armature_inspection_contract_rejects_invalid_payload(payload):
    with pytest.raises(AgentError):
        ArmatureInspect.parse(payload)


def transform():
    return {
        "location": [0, 0, 0],
        "rotation_euler": [0, 0, 0],
        "scale": [1, 1, 1],
    }


def scene_revision(registry):
    return registry.dispatch(Request("scene.inspect")).data["revision"]


def install_armature_mode_ops(bpy):
    def mode_set(*, mode):
        active = bpy.context.view_layer.objects.active
        if active is None or active.type != "ARMATURE":
            return {"CANCELLED"}
        if mode == "EDIT":
            bpy.context.mode = "EDIT_ARMATURE"
        elif mode == "OBJECT":
            bpy.context.mode = "OBJECT"
        else:
            return {"CANCELLED"}
        return {"FINISHED"}

    bpy.ops = NS(object=NS(mode_set=mode_set))


def create_armature(registry, name="NewRig"):
    return registry.dispatch(
        Request(
            "rig.armature_create",
            {
                "name": name,
                "transform": transform(),
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )


def target_from_rig(rig):
    return {
        "object_id": rig["object_id"],
        "expected_name": rig["name"],
        "expected_revision": rig["object_revision"],
    }


def test_armature_create_is_verified_empty_local_rig():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))

    result = create_armature(registry)

    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["object"]["name"] == "NewRig"
    assert after["object"]["type"] == "ARMATURE"
    assert after["object"]["scene_member"] is True
    assert after["rig"]["armature_name"] == "NewRigArmature"
    assert after["rig"]["bone_count"] == 0
    assert after["rig"]["pose_bone_count"] == 0
    assert after["rig"]["linked_object"] is False
    assert after["rig"]["linked_armature_data"] is False
    assert bpy.data.objects.get("NewRig") is not None
    assert bpy.data.armatures.get("NewRigArmature") is not None


def test_bone_create_requires_fresh_rig_and_verifies_exact_created_bone():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    created = create_armature(registry)
    rig = created.data["after"]["rig"]
    obj = bpy.data.objects.get("NewRig")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    install_armature_mode_ops(bpy)
    rig = registry.dispatch(Request("rig.armature_inspect", {"object_id": rig["object_id"]})).data

    result = registry.dispatch(
        Request(
            "rig.bone_create",
            {
                "target": target_from_rig(rig),
                "expected_rig_revision": rig["rig_revision"],
                "name": "Root",
                "head": [0, 0, 0],
                "tail": [0, 0, 2],
                "use_deform": False,
            },
        )
    )

    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["bone_count"] == 1
    assert after["root_bones"] == ["Root"]
    root = after["bones"][0]
    assert root["name"] == "Root"
    assert root["parent"] is None
    assert root["head_local"] == [0.0, 0.0, 0.0]
    assert root["tail_local"] == [0.0, 0.0, 2.0]
    assert root["use_connect"] is False
    assert root["use_deform"] is False
    assert bpy.context.mode == "OBJECT"


def test_bone_create_rejects_stale_rig_revision_and_duplicate_name():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    created = create_armature(registry)
    rig = created.data["after"]["rig"]
    obj = bpy.data.objects.get("NewRig")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    install_armature_mode_ops(bpy)
    selected = registry.dispatch(
        Request("rig.armature_inspect", {"object_id": rig["object_id"]})
    ).data

    external = obj.data.edit_bones.new("External")
    external.head = [0, 0, 0]
    external.tail = [0, 1, 0]
    stale = registry.dispatch(
        Request(
            "rig.bone_create",
            {
                "target": target_from_rig(selected),
                "expected_rig_revision": selected["rig_revision"],
                "name": "Root",
                "head": [0, 0, 0],
                "tail": [0, 0, 1],
            },
        )
    )
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE

    current = registry.dispatch(
        Request("rig.armature_inspect", {"object_id": rig["object_id"]})
    ).data
    duplicate = registry.dispatch(
        Request(
            "rig.bone_create",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "name": "External",
                "head": [0, 0, 0],
                "tail": [0, 0, 1],
            },
        )
    )
    assert duplicate.status == Status.FAILED
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET


def test_bone_create_requires_target_selected_and_active():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    created = create_armature(registry)
    rig = created.data["after"]["rig"]
    install_armature_mode_ops(bpy)

    result = registry.dispatch(
        Request(
            "rig.bone_create",
            {
                "target": target_from_rig(rig),
                "expected_rig_revision": rig["rig_revision"],
                "name": "Root",
                "head": [0, 0, 0],
                "tail": [0, 0, 1],
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_bone_create_rolls_back_on_verification_failure(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    created = create_armature(registry)
    rig = created.data["after"]["rig"]
    obj = bpy.data.objects.get("NewRig")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    install_armature_mode_ops(bpy)
    rig = registry.dispatch(Request("rig.armature_inspect", {"object_id": rig["object_id"]})).data

    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.bone_create",
            {
                "target": target_from_rig(rig),
                "expected_rig_revision": rig["rig_revision"],
                "name": "RollbackBone",
                "head": [0, 0, 0],
                "tail": [1, 0, 0],
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert obj.data.bones == []
    assert bpy.context.mode == "OBJECT"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "Rig",
            "transform": transform(),
            "expected_scene_revision": "x" * 64,
            "extra": True,
        },
        {
            "name": "",
            "transform": transform(),
            "expected_scene_revision": "x" * 64,
        },
    ],
)
def test_armature_create_contract_rejects_invalid_payload(payload):
    with pytest.raises(AgentError):
        ArmatureCreate.parse(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "target": {
                "object_id": "id",
                "expected_name": "Rig",
                "expected_revision": "x" * 64,
            },
            "expected_rig_revision": "y" * 64,
            "name": "Bone",
            "head": [0, 0, 0],
            "tail": [0, 0, 0],
        },
        {
            "target": {
                "object_id": "id",
                "expected_name": "Rig",
                "expected_revision": "x" * 64,
            },
            "expected_rig_revision": "y" * 64,
            "name": "Bone",
            "head": [0, 0, 0],
            "tail": [0, 0, 1],
            "use_deform": "yes",
        },
    ],
)
def test_bone_create_contract_rejects_invalid_payload(payload):
    with pytest.raises(AgentError):
        BoneCreate.parse(payload)


def prepare_editable_rig():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    created = create_armature(registry)
    assert created.status == Status.VERIFIED
    obj = bpy.data.objects.get("NewRig")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    install_armature_mode_ops(bpy)
    object_id = created.data["after"]["rig"]["object_id"]
    return bpy, obj, registry, object_id


def add_rig_bone(registry, object_id, name, head, tail):
    current = registry.dispatch(Request("rig.armature_inspect", {"object_id": object_id})).data
    return registry.dispatch(
        Request(
            "rig.bone_create",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "name": name,
                "head": head,
                "tail": tail,
            },
        )
    )


def inspect_rig(registry, object_id):
    return registry.dispatch(Request("rig.armature_inspect", {"object_id": object_id})).data


def test_factory_registers_level6_m3_tools_under_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.bone_hierarchy_edit", "rig.bone_symmetry_edit"} <= names


def test_bone_hierarchy_edit_parents_connects_and_renames_with_exact_readback():
    bpy, obj, registry, object_id = prepare_editable_rig()
    assert add_rig_bone(registry, object_id, "Root", [0, 0, 0], [0, 0, 2]).status == Status.VERIFIED
    assert (
        add_rig_bone(registry, object_id, "Child", [1, 0, 0], [1, 0, 1]).status == Status.VERIFIED
    )
    before = inspect_rig(registry, object_id)

    result = registry.dispatch(
        Request(
            "rig.bone_hierarchy_edit",
            {
                "target": target_from_rig(before),
                "expected_rig_revision": before["rig_revision"],
                "bone_name": "Child",
                "new_name": "Spine",
                "parent_name": "Root",
                "use_connect": True,
            },
        )
    )

    assert result.status == Status.VERIFIED
    after = result.data["after"]
    spine = next(item for item in after["bones"] if item["name"] == "Spine")
    assert spine["parent"] == "Root"
    assert spine["use_connect"] is True
    assert spine["head_local"] == [0.0, 0.0, 2.0]
    assert spine["tail_local"] == [1.0, 0.0, 1.0]
    assert after["hierarchy_cycle"] is False
    assert bpy.context.mode == "OBJECT"


def test_bone_hierarchy_edit_rejects_cycle_and_duplicate_rename():
    bpy, obj, registry, object_id = prepare_editable_rig()
    assert add_rig_bone(registry, object_id, "Root", [0, 0, 0], [0, 0, 2]).status == Status.VERIFIED
    assert (
        add_rig_bone(registry, object_id, "Child", [0, 0, 2], [0, 0, 3]).status == Status.VERIFIED
    )
    current = inspect_rig(registry, object_id)
    parented = registry.dispatch(
        Request(
            "rig.bone_hierarchy_edit",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Child",
                "new_name": "Child",
                "parent_name": "Root",
                "use_connect": True,
            },
        )
    )
    assert parented.status == Status.VERIFIED

    current = inspect_rig(registry, object_id)
    cycle = registry.dispatch(
        Request(
            "rig.bone_hierarchy_edit",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Root",
                "new_name": "Root",
                "parent_name": "Child",
                "use_connect": False,
            },
        )
    )
    assert cycle.status == Status.FAILED
    assert cycle.error.code == ErrorCode.SAFETY_DENIED

    duplicate = registry.dispatch(
        Request(
            "rig.bone_hierarchy_edit",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Root",
                "new_name": "Child",
                "parent_name": None,
                "use_connect": False,
            },
        )
    )
    assert duplicate.status == Status.FAILED
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET


def test_bone_hierarchy_edit_verification_failure_restores_original_rig(
    monkeypatch,
):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = prepare_editable_rig()
    assert add_rig_bone(registry, object_id, "Root", [0, 0, 0], [0, 0, 2]).status == Status.VERIFIED
    assert (
        add_rig_bone(registry, object_id, "Child", [1, 0, 0], [1, 0, 1]).status == Status.VERIFIED
    )
    before = inspect_rig(registry, object_id)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.bone_hierarchy_edit",
            {
                "target": target_from_rig(before),
                "expected_rig_revision": before["rig_revision"],
                "bone_name": "Child",
                "new_name": "Spine",
                "parent_name": "Root",
                "use_connect": True,
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect_rig(registry, object_id)["rig_revision"] == before["rig_revision"]


def test_bone_symmetry_edit_mirrors_left_coordinates_across_local_x():
    bpy, obj, registry, object_id = prepare_editable_rig()
    assert (
        add_rig_bone(registry, object_id, "Arm.L", [1, 0, 0], [2, 0, 0]).status == Status.VERIFIED
    )
    assert (
        add_rig_bone(registry, object_id, "Arm.R", [-1, 0, 0], [-2, 0, 0]).status == Status.VERIFIED
    )
    before = inspect_rig(registry, object_id)

    result = registry.dispatch(
        Request(
            "rig.bone_symmetry_edit",
            {
                "target": target_from_rig(before),
                "expected_rig_revision": before["rig_revision"],
                "left_name": "Arm.L",
                "right_name": "Arm.R",
                "left_head": [1.5, 2, 3],
                "left_tail": [2.5, 2, 4],
            },
        )
    )

    assert result.status == Status.VERIFIED
    after = result.data["after"]
    left = next(item for item in after["bones"] if item["name"] == "Arm.L")
    right = next(item for item in after["bones"] if item["name"] == "Arm.R")
    assert left["head_local"] == [1.5, 2.0, 3.0]
    assert left["tail_local"] == [2.5, 2.0, 4.0]
    assert right["head_local"] == [-1.5, 2.0, 3.0]
    assert right["tail_local"] == [-2.5, 2.0, 4.0]
    assert bpy.context.mode == "OBJECT"


def test_bone_symmetry_edit_verification_failure_restores_both_bones(
    monkeypatch,
):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = prepare_editable_rig()
    assert (
        add_rig_bone(registry, object_id, "Arm.L", [1, 0, 0], [2, 0, 0]).status == Status.VERIFIED
    )
    assert (
        add_rig_bone(registry, object_id, "Arm.R", [-1, 0, 0], [-2, 0, 0]).status == Status.VERIFIED
    )
    before = inspect_rig(registry, object_id)

    monkeypatch.setattr(
        "shuvi_blender_agent.rigging.compare",
        lambda expected, actual: real_compare({"forced": 1}, {"forced": 2}),
    )
    result = registry.dispatch(
        Request(
            "rig.bone_symmetry_edit",
            {
                "target": target_from_rig(before),
                "expected_rig_revision": before["rig_revision"],
                "left_name": "Arm.L",
                "right_name": "Arm.R",
                "left_head": [3, 0, 0],
                "left_tail": [4, 0, 0],
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect_rig(registry, object_id)["rig_revision"] == before["rig_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            BoneHierarchyEdit.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Bone",
                "new_name": "Bone",
                "parent_name": None,
                "use_connect": True,
            },
        ),
        (
            BoneSymmetryEdit.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "left_name": "ArmLeft",
                "right_name": "ArmRight",
                "left_head": [1, 0, 0],
                "left_tail": [2, 0, 0],
            },
        ),
    ],
)
def test_level6_m3_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)


def setup_pose_rig():
    obj = rig_fixture()
    bpy = fake_bpy([obj])
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    objects = registry.dispatch(Request("objects.list")).data["items"]
    object_id = next(item["object_id"] for item in objects if item["name"] == "CharacterRig")
    return bpy, obj, registry, object_id


def pose_payload(rig, bone_name="Root", rotation_mode="XYZ", rotation=(0.1, 0.2, 0.3)):
    return {
        "target": target_from_rig(rig),
        "expected_rig_revision": rig["rig_revision"],
        "bone_name": bone_name,
        "location": [1.0, 2.0, 3.0],
        "rotation_mode": rotation_mode,
        "rotation": list(rotation),
        "scale": [1.2, 0.8, 1.1],
    }


def test_factory_registers_level6_m4_pose_tools_under_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.pose_bone_transform", "rig.pose_bone_reset"} <= names


def test_pose_bone_transform_sets_xyz_channels_with_exact_readback():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)

    result = registry.dispatch(Request("rig.pose_bone_transform", pose_payload(before)))

    assert result.status == Status.VERIFIED
    after = result.data["after"]
    root = next(item for item in after["pose_bones"] if item["name"] == "Root")
    assert root["rotation_mode"] == "XYZ"
    assert root["location"] == [1.0, 2.0, 3.0]
    assert root["rotation_euler"] == [0.1, 0.2, 0.3]
    assert root["scale"] == [1.2, 0.8, 1.1]
    assert bpy.context.mode == "OBJECT"


def test_pose_bone_transform_normalizes_quaternion_and_verifies_it():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    payload = pose_payload(
        before,
        rotation_mode="QUATERNION",
        rotation=(0.5, 0.5, 0.0, 0.0),
    )

    result = registry.dispatch(Request("rig.pose_bone_transform", payload))

    assert result.status == Status.VERIFIED
    root = next(item for item in result.data["after"]["pose_bones"] if item["name"] == "Root")
    assert root["rotation_mode"] == "QUATERNION"
    assert root["rotation_quaternion"] == pytest.approx([2**-0.5, 2**-0.5, 0.0, 0.0])


def test_pose_bone_reset_restores_identity_channels():
    bpy, obj, registry, object_id = setup_pose_rig()
    root = next(item for item in obj.pose.bones if item.name == "Root")
    root.location = [4.0, 5.0, 6.0]
    root.rotation_mode = "XYZ"
    root.rotation_euler = [0.4, 0.5, 0.6]
    root.scale = [2.0, 3.0, 4.0]
    before = inspect_rig(registry, object_id)

    result = registry.dispatch(
        Request(
            "rig.pose_bone_reset",
            {
                "target": target_from_rig(before),
                "expected_rig_revision": before["rig_revision"],
                "bone_name": "Root",
            },
        )
    )

    assert result.status == Status.VERIFIED
    root_after = next(item for item in result.data["after"]["pose_bones"] if item["name"] == "Root")
    assert root_after["rotation_mode"] == "QUATERNION"
    assert root_after["location"] == [0.0, 0.0, 0.0]
    assert root_after["rotation_euler"] == [0.0, 0.0, 0.0]
    assert root_after["rotation_quaternion"] == [1.0, 0.0, 0.0, 0.0]
    assert root_after["scale"] == [1.0, 1.0, 1.0]


def test_pose_bone_transform_rejects_stale_rig_revision_and_missing_bone():
    bpy, obj, registry, object_id = setup_pose_rig()
    stale = inspect_rig(registry, object_id)
    root = next(item for item in obj.pose.bones if item.name == "Root")
    root.location = [0.25, 0.0, 0.0]

    stale_result = registry.dispatch(Request("rig.pose_bone_transform", pose_payload(stale)))
    assert stale_result.status == Status.FAILED
    assert stale_result.error.code == ErrorCode.STALE_STATE

    current = inspect_rig(registry, object_id)
    missing = registry.dispatch(
        Request(
            "rig.pose_bone_reset",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Missing",
            },
        )
    )
    assert missing.status == Status.FAILED
    assert missing.error.code == ErrorCode.NOT_FOUND


def test_pose_bone_transform_verification_failure_restores_pose(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(Request("rig.pose_bone_transform", pose_payload(before)))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect_rig(registry, object_id)["rig_revision"] == before["rig_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            PoseBoneTransform.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Root",
                "location": [0, 0, 0],
                "rotation_mode": "AXIS_ANGLE",
                "rotation": [0, 0, 0],
                "scale": [1, 1, 1],
            },
        ),
        (
            PoseBoneTransform.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Root",
                "location": [0, 0, 0],
                "rotation_mode": [],
                "rotation": [0, 0, 0],
                "scale": [1, 1, 1],
            },
        ),
        (
            PoseBoneTransform.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Root",
                "location": [0, 0, 0],
                "rotation_mode": "QUATERNION",
                "rotation": [0, 0, 0, 0],
                "scale": [1, 1, 1],
            },
        ),
        (
            PoseBoneTransform.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Root",
                "location": [0, 0, 0],
                "rotation_mode": "XYZ",
                "rotation": [0, 0, 0],
                "scale": [0, 1, 1],
            },
        ),
        (
            PoseBoneReset.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "",
            },
        ),
    ],
)
def test_level6_m4_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)


def limit_constraint_payload(rig, bone_name="Arm.L", constraint_name="Shuvi Limit"):
    return {
        "target": target_from_rig(rig),
        "expected_rig_revision": rig["rig_revision"],
        "bone_name": bone_name,
        "constraint_name": constraint_name,
        "constraint_type": "LIMIT_ROTATION",
        "influence": 0.8,
        "mute": False,
        "use_limit_x": True,
        "min_x": -0.5,
        "max_x": 0.5,
        "use_limit_y": True,
        "min_y": -0.25,
        "max_y": 0.25,
        "use_limit_z": False,
        "min_z": -0.1,
        "max_z": 0.1,
    }


def ik_constraint_payload(rig, bone_name="Arm.L", target_bone_name="Root"):
    return {
        "target": target_from_rig(rig),
        "expected_rig_revision": rig["rig_revision"],
        "bone_name": bone_name,
        "constraint_name": "Shuvi IK",
        "constraint_type": "IK",
        "influence": 1.0,
        "mute": False,
        "target_bone_name": target_bone_name,
        "chain_count": 2,
    }


def test_factory_registers_level6_m5_constraint_tools_at_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.pose_constraint_create", "rig.pose_constraint_remove"} <= names


def test_pose_constraint_create_limit_rotation_with_exact_readback():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)

    result = registry.dispatch(
        Request("rig.pose_constraint_create", limit_constraint_payload(before))
    )

    assert result.status == Status.VERIFIED
    arm = next(item for item in result.data["after"]["pose_bones"] if item["name"] == "Arm.L")
    constraint = next(item for item in arm["constraints"] if item["name"] == "Shuvi Limit")
    assert constraint["type"] == "LIMIT_ROTATION"
    assert constraint["influence"] == 0.8
    assert constraint["use_limit_x"] is True
    assert constraint["min_x"] == -0.5
    assert constraint["max_y"] == 0.25
    assert (
        result.data["after"]["total_pose_constraint_count"]
        == before["total_pose_constraint_count"] + 1
    )
    assert bpy.context.mode == "OBJECT"


def test_pose_constraint_create_ik_uses_same_armature_explicit_target_bone():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)

    result = registry.dispatch(Request("rig.pose_constraint_create", ik_constraint_payload(before)))

    assert result.status == Status.VERIFIED
    arm = next(item for item in result.data["after"]["pose_bones"] if item["name"] == "Arm.L")
    constraint = next(item for item in arm["constraints"] if item["name"] == "Shuvi IK")
    assert constraint["type"] == "IK"
    assert constraint["target_object_name"] == "CharacterRig"
    assert constraint["target_bone_name"] == "Root"
    assert constraint["chain_count"] == 2


def test_pose_constraint_create_rejects_duplicate_name_and_self_ik_target():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    created = registry.dispatch(
        Request("rig.pose_constraint_create", limit_constraint_payload(before))
    )
    assert created.status == Status.VERIFIED

    current = inspect_rig(registry, object_id)
    duplicate = registry.dispatch(
        Request("rig.pose_constraint_create", limit_constraint_payload(current))
    )
    assert duplicate.status == Status.FAILED
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET

    current = inspect_rig(registry, object_id)
    self_ik = registry.dispatch(
        Request(
            "rig.pose_constraint_create",
            ik_constraint_payload(current, bone_name="Arm.L", target_bone_name="Arm.L"),
        )
    )
    assert self_ik.status == Status.FAILED
    assert self_ik.error.code == ErrorCode.SAFETY_DENIED


def test_pose_constraint_remove_verifies_absence_and_counts():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    created = registry.dispatch(
        Request("rig.pose_constraint_create", ik_constraint_payload(before))
    )
    assert created.status == Status.VERIFIED
    current = inspect_rig(registry, object_id)

    result = registry.dispatch(
        Request(
            "rig.pose_constraint_remove",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Arm.L",
                "constraint_name": "Shuvi IK",
                "expected_constraint_type": "IK",
            },
        )
    )

    assert result.status == Status.VERIFIED
    arm = next(item for item in result.data["after"]["pose_bones"] if item["name"] == "Arm.L")
    assert not any(item["name"] == "Shuvi IK" for item in arm["constraints"])
    assert (
        result.data["after"]["total_pose_constraint_count"]
        == current["total_pose_constraint_count"] - 1
    )


def test_pose_constraint_remove_rejects_nonfinal_constraint_for_exact_recovery():
    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    first = registry.dispatch(
        Request("rig.pose_constraint_create", limit_constraint_payload(before))
    )
    assert first.status == Status.VERIFIED

    current = inspect_rig(registry, object_id)
    second = registry.dispatch(
        Request("rig.pose_constraint_create", ik_constraint_payload(current))
    )
    assert second.status == Status.VERIFIED

    current = inspect_rig(registry, object_id)
    result = registry.dispatch(
        Request(
            "rig.pose_constraint_remove",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Arm.L",
                "constraint_name": "Shuvi Limit",
                "expected_constraint_type": "LIMIT_ROTATION",
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert inspect_rig(registry, object_id)["rig_revision"] == current["rig_revision"]


def test_pose_constraint_create_verification_failure_removes_created_constraint(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request("rig.pose_constraint_create", limit_constraint_payload(before))
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect_rig(registry, object_id)["rig_revision"] == before["rig_revision"]


def test_pose_constraint_remove_verification_failure_recreates_constraint(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = setup_pose_rig()
    before = inspect_rig(registry, object_id)
    created = registry.dispatch(
        Request("rig.pose_constraint_create", limit_constraint_payload(before))
    )
    assert created.status == Status.VERIFIED
    current = inspect_rig(registry, object_id)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.pose_constraint_remove",
            {
                "target": target_from_rig(current),
                "expected_rig_revision": current["rig_revision"],
                "bone_name": "Arm.L",
                "constraint_name": "Shuvi Limit",
                "expected_constraint_type": "LIMIT_ROTATION",
            },
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert inspect_rig(registry, object_id)["rig_revision"] == current["rig_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            PoseConstraintCreate.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Arm.L",
                "constraint_name": "IK",
                "constraint_type": "IK",
                "influence": 1.0,
                "mute": False,
                "target_bone_name": "Root",
                "chain_count": 0,
            },
        ),
        (
            PoseConstraintCreate.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Arm.L",
                "constraint_name": "Limit",
                "constraint_type": "LIMIT_ROTATION",
                "influence": 1.0,
                "mute": False,
                "use_limit_x": True,
                "min_x": 2.0,
                "max_x": 1.0,
                "use_limit_y": False,
                "min_y": 0.0,
                "max_y": 0.0,
                "use_limit_z": False,
                "min_z": 0.0,
                "max_z": 0.0,
            },
        ),
        (
            PoseConstraintRemove.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                "bone_name": "Arm.L",
                "constraint_name": "Whatever",
                "expected_constraint_type": "COPY_LOCATION",
            },
        ),
    ],
)
def test_level6_m5_constraint_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)


def object_state(registry, name):
    items = registry.dispatch(Request("objects.list", {"limit": 100})).data["items"]
    return next(item for item in items if item["name"] == name)


def target_from_object(snapshot):
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def setup_binding_rig():
    mesh = FakeObject("Body", "MESH")
    rig = rig_fixture()
    bpy = fake_bpy([mesh, rig])
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    mesh_state = object_state(registry, "Body")
    rig_state = object_state(registry, "CharacterRig")
    rig_detail = inspect_rig(registry, rig_state["object_id"])
    return bpy, mesh, rig, registry, mesh_state, rig_detail


def binding_payload(mesh_state, rig_state, modifier_name="Shuvi Armature"):
    return {
        "mesh_target": target_from_object(mesh_state),
        "armature_target": target_from_rig(rig_state),
        "expected_rig_revision": rig_state["rig_revision"],
        "modifier_name": modifier_name,
    }


def test_factory_registers_level6_m6_binding_tools_below_raised_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.mesh_armature_bind", "rig.mesh_armature_unbind"} <= names


def test_mesh_armature_bind_adds_exact_managed_modifier_without_parenting():
    bpy, mesh, rig, registry, mesh_state, rig_state = setup_binding_rig()

    result = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(mesh_state, rig_state))
    )

    assert result.status == Status.VERIFIED
    after = result.data["after"]["mesh"]
    assert after["parent_id"] is None
    assert after["modifier_count"] == 1
    modifier = after["modifiers"][0]
    assert modifier == {
        "name": "Shuvi Armature",
        "type": "ARMATURE",
        "show_viewport": True,
        "show_render": True,
        "settings": {
            "target_name": "CharacterRig",
            "use_vertex_groups": True,
            "use_bone_envelopes": False,
        },
    }
    assert mesh.modifiers[0].object is rig
    assert result.data["after"]["armature"]["rig_revision"] == rig_state["rig_revision"]
    assert bpy.context.mode == "OBJECT"


def test_mesh_armature_unbind_removes_exact_managed_modifier():
    bpy, mesh, rig, registry, mesh_state, rig_state = setup_binding_rig()
    bound = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(mesh_state, rig_state))
    )
    assert bound.status == Status.VERIFIED

    current_mesh = object_state(registry, "Body")
    current_rig = inspect_rig(registry, rig_state["object_id"])
    result = registry.dispatch(
        Request(
            "rig.mesh_armature_unbind",
            binding_payload(current_mesh, current_rig),
        )
    )

    assert result.status == Status.VERIFIED
    after = result.data["after"]["mesh"]
    assert after["modifier_count"] == 0
    assert after["parent_id"] is None
    assert len(mesh.modifiers) == 0
    assert result.data["after"]["armature"]["rig_revision"] == current_rig["rig_revision"]


def test_mesh_armature_bind_rejects_stale_rig_revision_not_visible_to_object_target():
    bpy, mesh, rig, registry, mesh_state, rig_state = setup_binding_rig()
    root = next(item for item in rig.pose.bones if item.name == "Root")
    root.location = [0.25, 0.0, 0.0]

    result = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(mesh_state, rig_state))
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.STALE_STATE
    assert len(mesh.modifiers) == 0


def test_mesh_armature_bind_rejects_existing_modifier_and_vertex_groups():
    bpy, mesh, rig, registry, mesh_state, rig_state = setup_binding_rig()
    mesh.modifiers.new("Existing", "BEVEL")
    fresh_mesh = object_state(registry, "Body")
    result = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(fresh_mesh, rig_state))
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED

    mesh.modifiers.clear()
    mesh.vertex_groups = [NS(name="Root")]
    fresh_mesh = object_state(registry, "Body")
    fresh_rig = inspect_rig(registry, rig_state["object_id"])
    result = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(fresh_mesh, fresh_rig))
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_mesh_armature_bind_verification_failure_removes_created_modifier(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, mesh, rig, registry, mesh_state, rig_state = setup_binding_rig()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(mesh_state, rig_state))
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert len(mesh.modifiers) == 0
    assert object_state(registry, "Body")["revision"] == mesh_state["revision"]


def test_mesh_armature_unbind_verification_failure_restores_modifier(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, mesh, rig, registry, mesh_state, rig_state = setup_binding_rig()
    bound = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(mesh_state, rig_state))
    )
    assert bound.status == Status.VERIFIED
    current_mesh = object_state(registry, "Body")
    current_rig = inspect_rig(registry, rig_state["object_id"])
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.mesh_armature_unbind",
            binding_payload(current_mesh, current_rig),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert len(mesh.modifiers) == 1
    assert mesh.modifiers[0].type == "ARMATURE"
    assert mesh.modifiers[0].object is rig
    assert object_state(registry, "Body")["revision"] == current_mesh["revision"]


def test_mesh_armature_binding_contract_rejects_invalid_modifier_name():
    payload = {
        "mesh_target": {
            "object_id": "mesh",
            "expected_name": "Body",
            "expected_revision": "x" * 64,
        },
        "armature_target": {
            "object_id": "rig",
            "expected_name": "Rig",
            "expected_revision": "y" * 64,
        },
        "expected_rig_revision": "z" * 64,
        "modifier_name": "",
    }
    with pytest.raises(AgentError):
        MeshArmatureBinding.parse(payload)


def inspect_weights(registry, mesh_state, rig_state):
    result = registry.dispatch(
        Request(
            "rig.mesh_weights_inspect",
            {
                "mesh_object_id": mesh_state["object_id"],
                "armature_object_id": rig_state["object_id"],
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    return result.data


def setup_weight_rig():
    bpy, mesh, rig, registry, _, rig_state = setup_binding_rig()
    mesh.data.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [],
        [(0, 1, 2), (0, 2, 3)],
    )
    mesh.data.update()
    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    bound = registry.dispatch(
        Request("rig.mesh_armature_bind", binding_payload(mesh_state, rig_state))
    )
    assert bound.status == Status.VERIFIED
    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    return bpy, mesh, rig, registry, mesh_state, rig_state, weights


def weight_set_payload(mesh_state, rig_state, weights_state, bone_name="Spine", weights=None):
    if weights is None:
        weights = [
            {"vertex_index": 0, "weight": 1.0},
            {"vertex_index": 1, "weight": 0.75},
            {"vertex_index": 2, "weight": 0.25},
        ]
    return {
        "mesh_target": target_from_object(mesh_state),
        "armature_target": target_from_rig(rig_state),
        "expected_rig_revision": rig_state["rig_revision"],
        "expected_weight_revision": weights_state["weight_revision"],
        "bone_name": bone_name,
        "weights": weights,
    }


def weight_remove_payload(mesh_state, rig_state, weights_state, bone_name="Spine"):
    return {
        "mesh_target": target_from_object(mesh_state),
        "armature_target": target_from_rig(rig_state),
        "expected_rig_revision": rig_state["rig_revision"],
        "expected_weight_revision": weights_state["weight_revision"],
        "bone_name": bone_name,
    }


def test_factory_registers_level6_m7_weight_tools_under_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    assert len(registry.catalog()) == MAX_REGISTERED_TOOLS
    names = {item["name"] for item in registry.catalog()}
    assert {
        "rig.mesh_weights_inspect",
        "rig.vertex_group_weights_set",
        "rig.vertex_group_remove",
    } <= names


def test_mesh_weights_inspect_reports_empty_bound_weight_state():
    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()

    assert weights["mesh_object_id"] == mesh_state["object_id"]
    assert weights["armature_object_id"] == rig_state["object_id"]
    assert weights["modifier_name"] == "Shuvi Armature"
    assert weights["vertex_count"] == 4
    assert weights["group_count"] == 0
    assert weights["assignment_count"] == 0
    assert weights["groups"] == []
    assert weights["unmatched_group_names"] == []
    assert weights["nondeform_group_names"] == []
    assert len(weights["weight_revision"]) == 64
    assert weights["rig_revision"] == rig_state["rig_revision"]
    assert weights["source_only"] is True
    assert weights["real_runtime_verified"] is False


def test_vertex_group_weights_set_creates_bone_matched_group_with_exact_weights():
    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()

    result = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights),
        )
    )

    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["group_count"] == 1
    assert after["assignment_count"] == 3
    assert after["groups"] == [
        {
            "name": "Spine",
            "index": 0,
            "weights": [
                {"vertex_index": 0, "weight": 1.0},
                {"vertex_index": 1, "weight": 0.75},
                {"vertex_index": 2, "weight": 0.25},
            ],
        }
    ]
    assert after["rig_revision"] == rig_state["rig_revision"]
    assert bpy.context.mode == "OBJECT"


def test_vertex_group_weights_set_replaces_entire_existing_group_map():
    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()
    created = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights),
        )
    )
    assert created.status == Status.VERIFIED

    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    result = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(
                mesh_state,
                rig_state,
                weights,
                weights=[
                    {"vertex_index": 1, "weight": 0.5},
                    {"vertex_index": 3, "weight": 1.0},
                ],
            ),
        )
    )

    assert result.status == Status.VERIFIED
    group = result.data["after"]["groups"][0]
    assert group["weights"] == [
        {"vertex_index": 1, "weight": 0.5},
        {"vertex_index": 3, "weight": 1.0},
    ]
    assert result.data["after"]["assignment_count"] == 2


def test_vertex_group_weights_set_rejects_stale_weight_revision_and_missing_bone():
    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()
    external = mesh.vertex_groups.new(name="Spine")
    external.add([0], 1.0, "REPLACE")

    stale = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights),
        )
    )
    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE

    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    missing = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights, bone_name="Missing"),
        )
    )
    assert missing.status == Status.FAILED
    assert missing.error.code == ErrorCode.NOT_FOUND


def test_vertex_group_remove_removes_final_group_and_all_memberships():
    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()
    created = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights),
        )
    )
    assert created.status == Status.VERIFIED

    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    result = registry.dispatch(
        Request(
            "rig.vertex_group_remove",
            weight_remove_payload(mesh_state, rig_state, weights),
        )
    )

    assert result.status == Status.VERIFIED
    assert result.data["after"]["group_count"] == 0
    assert result.data["after"]["assignment_count"] == 0
    assert result.data["after"]["groups"] == []
    assert len(mesh.vertex_groups) == 0


def test_vertex_group_remove_rejects_nonfinal_group_for_exact_recovery():
    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()
    first = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights, bone_name="Spine"),
        )
    )
    assert first.status == Status.VERIFIED

    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    second = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(
                mesh_state,
                rig_state,
                weights,
                bone_name="Arm.L",
                weights=[{"vertex_index": 3, "weight": 1.0}],
            ),
        )
    )
    assert second.status == Status.VERIFIED

    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    result = registry.dispatch(
        Request(
            "rig.vertex_group_remove",
            weight_remove_payload(mesh_state, rig_state, weights, bone_name="Spine"),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert (
        inspect_weights(registry, mesh_state, rig_state)["weight_revision"]
        == weights["weight_revision"]
    )


def test_vertex_group_weights_set_verification_failure_restores_weights(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    recovered = inspect_weights(registry, mesh_state, rig_state)
    assert recovered["weight_revision"] == weights["weight_revision"]
    assert recovered["groups"] == []


def test_vertex_group_remove_verification_failure_recreates_group(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, mesh, rig, registry, mesh_state, rig_state, weights = setup_weight_rig()
    created = registry.dispatch(
        Request(
            "rig.vertex_group_weights_set",
            weight_set_payload(mesh_state, rig_state, weights),
        )
    )
    assert created.status == Status.VERIFIED

    mesh_state = object_state(registry, "Body")
    rig_state = inspect_rig(registry, rig_state["object_id"])
    weights = inspect_weights(registry, mesh_state, rig_state)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(
        Request(
            "rig.vertex_group_remove",
            weight_remove_payload(mesh_state, rig_state, weights),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    recovered = inspect_weights(registry, mesh_state, rig_state)
    assert recovered["weight_revision"] == weights["weight_revision"]
    assert recovered["groups"] == weights["groups"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            VertexGroupWeightsSet.parse,
            {
                "mesh_target": {
                    "object_id": "mesh",
                    "expected_name": "Body",
                    "expected_revision": "x" * 64,
                },
                "armature_target": {
                    "object_id": "rig",
                    "expected_name": "Rig",
                    "expected_revision": "y" * 64,
                },
                "expected_rig_revision": "z" * 64,
                "expected_weight_revision": "w" * 64,
                "bone_name": "Root",
                "weights": [{"vertex_index": 0, "weight": 0.0}],
            },
        ),
        (
            VertexGroupWeightsSet.parse,
            {
                "mesh_target": {
                    "object_id": "mesh",
                    "expected_name": "Body",
                    "expected_revision": "x" * 64,
                },
                "armature_target": {
                    "object_id": "rig",
                    "expected_name": "Rig",
                    "expected_revision": "y" * 64,
                },
                "expected_rig_revision": "z" * 64,
                "expected_weight_revision": "w" * 64,
                "bone_name": "Root",
                "weights": [
                    {"vertex_index": 0, "weight": 1.0},
                    {"vertex_index": 0, "weight": 0.5},
                ],
            },
        ),
        (
            VertexGroupRemove.parse,
            {
                "mesh_target": {
                    "object_id": "mesh",
                    "expected_name": "Body",
                    "expected_revision": "x" * 64,
                },
                "armature_target": {
                    "object_id": "rig",
                    "expected_name": "Rig",
                    "expected_revision": "y" * 64,
                },
                "expected_rig_revision": "z" * 64,
                "expected_weight_revision": "w" * 64,
                "bone_name": "",
            },
        ),
    ],
)
def test_level6_m7_weight_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)


def ik_fk_rig_fixture():
    upper = bone("Upper", head=(0, 0, 0), tail=(0, 0, 1), deform=True)
    middle = bone("Middle", parent=upper, head=(0, 0, 1), tail=(0, 0, 2), deform=True)
    end = bone("End", parent=middle, head=(0, 0, 2), tail=(0, 0, 3), deform=True)
    target = bone("IK.Target", head=(1, 0, 3), tail=(1, 0, 4), deform=False)
    obj = FakeObject("IKFKRig", "ARMATURE")
    obj.data = NS(
        name="IKFKRigData",
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
    return obj


def setup_ik_fk_rig():
    obj = ik_fk_rig_fixture()
    bpy = fake_bpy([obj])
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    object_id = object_state(registry, "IKFKRig")["object_id"]
    rig = inspect_rig(registry, object_id)
    return bpy, obj, registry, object_id, rig


def ik_fk_chain_fields():
    return {
        "upper_bone": "Upper",
        "middle_bone": "Middle",
        "end_bone": "End",
        "target_bone": "IK.Target",
        "constraint_name": "Shuvi IKFK",
    }


def ik_fk_setup_payload(rig, mode="IK"):
    return {
        "target": target_from_rig(rig),
        "expected_rig_revision": rig["rig_revision"],
        **ik_fk_chain_fields(),
        "initial_mode": mode,
    }


def ik_fk_switch_payload(rig, mode):
    return {
        "target": target_from_rig(rig),
        "expected_rig_revision": rig["rig_revision"],
        **ik_fk_chain_fields(),
        "mode": mode,
    }


def test_factory_registers_level6_m8_ik_fk_tools_at_cap():
    registry = create_registry(fake_bpy(), SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 229
    assert MAX_REGISTERED_TOOLS == 229
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.ik_fk_preview", "rig.ik_fk_setup", "rig.ik_fk_switch"} <= names


def test_ik_fk_preview_validates_chain_before_setup():
    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    result = registry.dispatch(
        Request(
            "rig.ik_fk_preview",
            {"object_id": object_id, **ik_fk_chain_fields()},
        )
    )

    assert result.status == Status.SUCCEEDED
    assert result.data["managed"] is False
    assert result.data["mode"] is None
    assert result.data["constraint"] is None
    assert result.data["rig_revision"] == rig["rig_revision"]
    assert result.data["source_only"] is True
    assert result.data["real_runtime_verified"] is False


def test_ik_fk_setup_creates_managed_ik_constraint_in_ik_mode():
    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    result = registry.dispatch(Request("rig.ik_fk_setup", ik_fk_setup_payload(rig, "IK")))

    assert result.status == Status.VERIFIED
    state = result.data["ik_fk"]
    assert state["managed"] is True
    assert state["mode"] == "IK"
    assert state["constraint"] == {
        "name": "Shuvi IKFK",
        "type": "IK",
        "mute": False,
        "influence": 1.0,
        "target_object_name": "IKFKRig",
        "target_bone_name": "IK.Target",
        "chain_count": 3,
    }
    assert bpy.context.mode == "OBJECT"


def test_ik_fk_setup_can_start_in_fk_mode_with_muted_ik():
    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    result = registry.dispatch(Request("rig.ik_fk_setup", ik_fk_setup_payload(rig, "FK")))

    assert result.status == Status.VERIFIED
    assert result.data["ik_fk"]["managed"] is True
    assert result.data["ik_fk"]["mode"] == "FK"
    end = next(item for item in obj.pose.bones if item.name == "End")
    assert end.constraints[0].mute is True


def test_ik_fk_switch_toggles_only_managed_constraint_mute():
    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    setup_result = registry.dispatch(Request("rig.ik_fk_setup", ik_fk_setup_payload(rig, "IK")))
    assert setup_result.status == Status.VERIFIED

    current = inspect_rig(registry, object_id)
    to_fk = registry.dispatch(Request("rig.ik_fk_switch", ik_fk_switch_payload(current, "FK")))
    assert to_fk.status == Status.VERIFIED
    assert to_fk.data["ik_fk"]["mode"] == "FK"

    current = inspect_rig(registry, object_id)
    to_ik = registry.dispatch(Request("rig.ik_fk_switch", ik_fk_switch_payload(current, "IK")))
    assert to_ik.status == Status.VERIFIED
    assert to_ik.data["ik_fk"]["mode"] == "IK"


def test_ik_fk_setup_rejects_invalid_chain_and_deforming_target():
    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    payload = ik_fk_setup_payload(rig)
    payload["middle_bone"] = "End"
    payload["end_bone"] = "Middle"
    bad_chain = registry.dispatch(Request("rig.ik_fk_setup", payload))
    assert bad_chain.status == Status.FAILED
    assert bad_chain.error.code == ErrorCode.SAFETY_DENIED

    target = next(item for item in obj.data.bones if item.name == "IK.Target")
    target.use_deform = True
    current = inspect_rig(registry, object_id)
    bad_target = registry.dispatch(Request("rig.ik_fk_setup", ik_fk_setup_payload(current)))
    assert bad_target.status == Status.FAILED
    assert bad_target.error.code == ErrorCode.SAFETY_DENIED


def test_ik_fk_switch_rejects_unmanaged_constraint():
    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    end = next(item for item in obj.pose.bones if item.name == "End")
    constraint = end.constraints.new("IK")
    constraint.name = "Shuvi IKFK"
    constraint.target = obj
    constraint.subtarget = "IK.Target"
    constraint.chain_count = 2
    constraint.influence = 1.0

    current = inspect_rig(registry, object_id)
    result = registry.dispatch(Request("rig.ik_fk_switch", ik_fk_switch_payload(current, "FK")))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_ik_fk_setup_verification_failure_rolls_back(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(Request("rig.ik_fk_setup", ik_fk_setup_payload(rig)))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    end = next(item for item in obj.pose.bones if item.name == "End")
    assert len(end.constraints) == 0
    assert inspect_rig(registry, object_id)["rig_revision"] == rig["rig_revision"]


def test_ik_fk_switch_verification_failure_restores_mode(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id, rig = setup_ik_fk_rig()
    setup_result = registry.dispatch(Request("rig.ik_fk_setup", ik_fk_setup_payload(rig, "IK")))
    assert setup_result.status == Status.VERIFIED
    current = inspect_rig(registry, object_id)
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.rigging.compare", fail_once)
    result = registry.dispatch(Request("rig.ik_fk_switch", ik_fk_switch_payload(current, "FK")))

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    end = next(item for item in obj.pose.bones if item.name == "End")
    constraint = next(item for item in end.constraints if item.name == "Shuvi IKFK")
    assert constraint.mute is False


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            IKFKSetup.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                **ik_fk_chain_fields(),
                "initial_mode": "BLEND",
            },
        ),
        (
            IKFKSwitch.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Rig",
                    "expected_revision": "x" * 64,
                },
                "expected_rig_revision": "y" * 64,
                **ik_fk_chain_fields(),
                "mode": 1,
            },
        ),
    ],
)
def test_level6_m8_contracts_reject_invalid_modes(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
