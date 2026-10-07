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
    RiggingOperations,
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


def pose_bone(name, *, location=(0, 0, 0), constraints=()):
    return NS(
        name=name,
        rotation_mode="XYZ",
        location=list(location),
        rotation_euler=[0.0, 0.0, 0.0],
        rotation_quaternion=[1.0, 0.0, 0.0, 0.0],
        scale=[1.0, 1.0, 1.0],
        constraints=list(constraints),
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
    assert len(registry.catalog()) == 188
    assert MAX_REGISTERED_TOOLS == 192
    assert len(registry.catalog()) < MAX_REGISTERED_TOOLS
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
    current = registry.dispatch(
        Request("rig.armature_inspect", {"object_id": object_id})
    ).data
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
    assert len(registry.catalog()) == 188
    assert MAX_REGISTERED_TOOLS == 192
    names = {item["name"] for item in registry.catalog()}
    assert {"rig.bone_hierarchy_edit", "rig.bone_symmetry_edit"} <= names


def test_bone_hierarchy_edit_parents_connects_and_renames_with_exact_readback():
    bpy, obj, registry, object_id = prepare_editable_rig()
    assert add_rig_bone(registry, object_id, "Root", [0, 0, 0], [0, 0, 2]).status == Status.VERIFIED
    assert add_rig_bone(registry, object_id, "Child", [1, 0, 0], [1, 0, 1]).status == Status.VERIFIED
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
    assert add_rig_bone(registry, object_id, "Child", [0, 0, 2], [0, 0, 3]).status == Status.VERIFIED
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


def test_bone_hierarchy_edit_verification_failure_restores_original_rig(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = prepare_editable_rig()
    assert add_rig_bone(registry, object_id, "Root", [0, 0, 0], [0, 0, 2]).status == Status.VERIFIED
    assert add_rig_bone(registry, object_id, "Child", [1, 0, 0], [1, 0, 1]).status == Status.VERIFIED
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
    assert add_rig_bone(registry, object_id, "Arm.L", [1, 0, 0], [2, 0, 0]).status == Status.VERIFIED
    assert add_rig_bone(registry, object_id, "Arm.R", [-1, 0, 0], [-2, 0, 0]).status == Status.VERIFIED
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


def test_bone_symmetry_edit_verification_failure_restores_both_bones(monkeypatch):
    from shuvi_blender_agent.verification import compare as real_compare

    bpy, obj, registry, object_id = prepare_editable_rig()
    assert add_rig_bone(registry, object_id, "Arm.L", [1, 0, 0], [2, 0, 0]).status == Status.VERIFIED
    assert add_rig_bone(registry, object_id, "Arm.R", [-1, 0, 0], [-2, 0, 0]).status == Status.VERIFIED
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
