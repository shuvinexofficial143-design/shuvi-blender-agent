import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.appearance import AppearanceOperations, CreateDevice, MaterialAssign
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    tools = AppearanceOperations(ObjectOperations(inspector)).tools()
    return bpy, inspector, ToolRegistry(tools, SafetyPolicy(allow_mutations=True))


def device_payload(inspector, kind):
    return {
        "name": "Device",
        "kind": kind,
        "expected_scene_revision": inspector.summary()["revision"],
        "transform": {"location": [1, 2, 3], "rotation_euler": [0, 0, 0], "scale": [1, 1, 1]},
        "settings": {"lens": 35, "clip_start": 0.1, "clip_end": 500, "make_active": True}
        if kind == "CAMERA"
        else {"energy": 250, "color": [0.5, 0.7, 1]},
    }


@pytest.mark.parametrize("kind", ["CAMERA", "POINT", "SUN", "SPOT", "AREA"])
def test_device_creation_verified(kind):
    bpy, inspector, registry = setup()
    result = registry.dispatch(Request("device.create", device_payload(inspector, kind)))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["scene_member"]
    obj = bpy.data.objects.get("Device")
    if kind == "CAMERA":
        assert bpy.context.scene.camera is obj
        assert result.data["after"]["camera"]["lens"] == 35
    else:
        assert result.data["after"]["light"]["energy"] == 250


def material_payload(inspector, obj):
    before = inspector.snapshot(obj)
    return {
        "target": {
            "object_id": before["object_id"],
            "expected_name": before["name"],
            "expected_revision": before["revision"],
        },
        "name": "Copper",
        "base_color": [0.9, 0.4, 0.2, 1],
        "metallic": 0.9,
        "roughness": 0.3,
    }


def test_material_assignment_and_shader_readback():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    payload = material_payload(inspector, obj)
    result = registry.dispatch(Request("material.create_assign", payload))
    assert result.status == Status.VERIFIED
    assert obj.material_slots[0].material.name == "Copper"
    assert result.data["after"]["assigned_material"]["metallic"] == 0.9
    fresh = material_payload(inspector, obj)
    assert (
        registry.dispatch(Request("material.create_assign", fresh)).error.code
        == ErrorCode.AMBIGUOUS_TARGET
    )


def test_material_cannot_modify_shared_mesh():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    obj.data.users = 2
    result = registry.dispatch(Request("material.create_assign", material_payload(inspector, obj)))
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert not bpy.data.materials


def test_material_mismatch_cleanup():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]

    def corrupt():
        material = bpy.data.materials.get("Copper")
        material.node_tree.nodes[0].inputs["Metallic"].default_value = 0

    bpy.context.view_layer.update = corrupt
    result = registry.dispatch(Request("material.create_assign", material_payload(inspector, obj)))
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"]
    assert not obj.material_slots
    assert not bpy.data.materials


def test_camera_failure_restores_previous_camera():
    bpy, inspector, registry = setup()

    def corrupt():
        bpy.data.objects.get("Device").data.lens = 1

    bpy.context.view_layer.update = corrupt
    result = registry.dispatch(Request("device.create", device_payload(inspector, "CAMERA")))
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert bpy.context.scene.camera is None
    assert bpy.data.objects.get("Device") is None
    assert not bpy.data.cameras


def test_invalid_device_and_material_bounds():
    _, inspector, _ = setup()
    payload = device_payload(inspector, "CAMERA")
    payload["settings"]["make_active"] = "yes"
    with pytest.raises(AgentError):
        CreateDevice.parse(payload)
    payload["settings"]["make_active"] = False
    payload["settings"]["clip_end"] = 0.01
    with pytest.raises(AgentError):
        CreateDevice.parse(payload)
    bpy = fake_bpy()
    payload = material_payload(BpyInspector(bpy), bpy.context.scene.objects[0])
    payload["roughness"] = 1.1
    with pytest.raises(AgentError):
        MaterialAssign.parse(payload)
