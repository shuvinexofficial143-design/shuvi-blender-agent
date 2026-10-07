from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.rigging import ArmatureInspect, RiggingOperations
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
    assert len(registry.catalog()) == 184
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
