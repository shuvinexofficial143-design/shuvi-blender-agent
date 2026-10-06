import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.material_slots import (
    MaterialFaceAssign,
    MaterialSlotDuplicate,
    MaterialSlotLink,
    MaterialSlotOperations,
    MaterialSlotReassign,
    MaterialSlotRemove,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    operations = MaterialSlotOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, operations, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def mesh_two_faces(obj):
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2], [0, 2, 3]],
    )


def material_state(inspector, operations, obj):
    snap = operations._snapshot(obj)
    return target(inspector, obj), snap


def link_payload(inspector, operations, obj, material_name):
    obj_target, snap = material_state(inspector, operations, obj)
    return {
        "target": obj_target,
        "expected_material_revision": snap["material_revision"],
        "material_name": material_name,
    }


def test_material_slots_inspect_reports_slots_and_face_users():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    first = bpy.data.materials.new("First")
    second = bpy.data.materials.new("Second")
    obj.data.materials.append(first)
    obj.data.materials.append(second)
    obj.data.polygons[1].material_index = 1

    result = registry.dispatch(
        Request("material.slots_inspect", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["slot_names"] == ["First", "Second"]
    assert result.data["slot_face_users"] == [1, 1]
    assert result.data["face_material_indices"] == [0, 1]
    assert len(result.data["material_revision"]) == 64


def test_material_slot_link_and_reassign_are_verified():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    first = bpy.data.materials.new("First")
    second = bpy.data.materials.new("Second")

    linked = registry.dispatch(
        Request("material.slot_link", link_payload(inspector, operations, obj, "First"))
    )
    assert linked.status == Status.VERIFIED
    assert linked.data["after"]["slot_names"] == ["First"]
    assert first.users == 1

    _, snap = material_state(inspector, operations, obj)
    reassigned = registry.dispatch(
        Request(
            "material.slot_reassign",
            {
                "target": target(inspector, obj),
                "expected_material_revision": snap["material_revision"],
                "slot_index": 0,
                "material_name": "Second",
            },
        )
    )
    assert reassigned.status == Status.VERIFIED
    assert reassigned.data["after"]["slot_names"] == ["Second"]
    assert first.users == 0
    assert second.users == 1


def test_material_slot_duplicate_creates_independent_material():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    source = bpy.data.materials.new("Source")
    source.use_nodes = True
    source.node_tree.nodes[0].inputs["Metallic"].default_value = 0.75
    obj.data.materials.append(source)
    _, snap = material_state(inspector, operations, obj)

    result = registry.dispatch(
        Request(
            "material.slot_duplicate",
            {
                "target": target(inspector, obj),
                "expected_material_revision": snap["material_revision"],
                "source_slot_index": 0,
                "new_material_name": "SourceCopy",
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["slot_names"] == ["Source", "SourceCopy"]
    duplicate = bpy.data.materials.get("SourceCopy")
    assert duplicate is not source
    assert duplicate.node_tree.nodes[0].inputs["Metallic"].default_value == 0.75


def test_material_face_assign_is_verified_and_bounded():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    obj.data.materials.append(bpy.data.materials.new("First"))
    obj.data.materials.append(bpy.data.materials.new("Second"))
    _, snap = material_state(inspector, operations, obj)

    result = registry.dispatch(
        Request(
            "material.face_assign",
            {
                "target": target(inspector, obj),
                "expected_material_revision": snap["material_revision"],
                "slot_index": 1,
                "face_indices": [1],
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["face_material_indices"] == [0, 1]
    assert obj.data.polygons[1].material_index == 1


def test_material_slot_remove_allows_only_unused_final_slot():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    first = bpy.data.materials.new("First")
    second = bpy.data.materials.new("Second")
    obj.data.materials.append(first)
    obj.data.materials.append(second)
    _, snap = material_state(inspector, operations, obj)

    result = registry.dispatch(
        Request(
            "material.slot_remove",
            {
                "target": target(inspector, obj),
                "expected_material_revision": snap["material_revision"],
                "slot_index": 1,
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["slot_names"] == ["First"]

    obj.data.materials.append(second)
    obj.data.polygons[0].material_index = 1
    _, snap = material_state(inspector, operations, obj)
    denied = registry.dispatch(
        Request(
            "material.slot_remove",
            {
                "target": target(inspector, obj),
                "expected_material_revision": snap["material_revision"],
                "slot_index": 1,
            },
        )
    )
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_material_mutation_rejects_stale_material_revision():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    bpy.data.materials.new("First")
    payload = link_payload(inspector, operations, obj, "First")
    obj.data.polygons[0].material_index = 7

    result = registry.dispatch(Request("material.slot_link", payload))
    assert result.error.code == ErrorCode.STALE_STATE


def test_material_face_assignment_failure_restores_previous_indices():
    bpy, inspector, operations, registry = setup()
    obj = bpy.data.objects.get("Cube")
    mesh_two_faces(obj)
    obj.data.materials.append(bpy.data.materials.new("First"))
    obj.data.materials.append(bpy.data.materials.new("Second"))
    _, snap = material_state(inspector, operations, obj)
    original_update = obj.data.update
    calls = {"count": 0}

    def corrupt_first_update():
        calls["count"] += 1
        if calls["count"] == 1:
            obj.data.polygons[1].material_index = 0
        original_update()

    obj.data.update = corrupt_first_update
    result = registry.dispatch(
        Request(
            "material.face_assign",
            {
                "target": target(inspector, obj),
                "expected_material_revision": snap["material_revision"],
                "slot_index": 1,
                "face_indices": [1],
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert [polygon.material_index for polygon in obj.data.polygons] == [0, 0]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            MaterialSlotLink.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_material_revision": "y" * 64,
                "material_name": "",
            },
        ),
        (
            MaterialSlotReassign.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_material_revision": "y" * 64,
                "slot_index": 64,
                "material_name": "Mat",
            },
        ),
        (
            MaterialSlotDuplicate.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_material_revision": "y" * 64,
                "source_slot_index": 0,
                "new_material_name": "",
            },
        ),
        (
            MaterialSlotRemove.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_material_revision": "y" * 64,
                "slot_index": -1,
            },
        ),
        (
            MaterialFaceAssign.parse,
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "expected_material_revision": "y" * 64,
                "slot_index": 0,
                "face_indices": [0, 0],
            },
        ),
    ],
)
def test_material_slot_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
