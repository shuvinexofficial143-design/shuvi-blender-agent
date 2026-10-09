"""M5: source-only World node graph / HDRI image lifecycle acceptance."""

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.world_lighting import WorldApply, WorldLightingOperations, WorldPreview


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    ops = WorldLightingOperations(ObjectOperations(inspector))
    registry = ToolRegistry(ops.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, registry


def args(mode="COLOR"):
    common = {"name": "SHUVI_ENV", "mode": mode, "strength": 0.8}
    return common | (
        {"color": [0.2, 0.4, 0.8]} if mode == "COLOR" else {"image_name": "LoadedHDRI"}
    )


def imported_hdri(bpy):
    img = bpy.data.images.new("LoadedHDRI", width=2048, height=1024)
    img.source = "FILE"
    img.has_data = True
    return img


def preview(reg, data):
    result = reg.dispatch(Request("lighting.world_preview", data))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(reg, data, plan):
    return reg.dispatch(
        Request("lighting.world_apply", data | {"expected_world_revision": plan["world_revision"]})
    )


def release(reg, token):
    return reg.dispatch(
        Request("lighting.world_release", {"expected_world_token": token})
    )


@pytest.mark.parametrize("mode", ["COLOR", "HDRI"])
def test_m5_plan_apply_node_graph_and_owned_release_restores_foreign_world(mode):
    bpy, inspector, reg = setup()
    before_world = bpy.data.worlds.new("ForeignWorld")
    bpy.context.scene.world = before_world
    before_revision = inspector.summary()["revision"]
    image = imported_hdri(bpy) if mode == "HDRI" else None
    data = args(mode)
    plan = preview(reg, data)
    assert plan["ready"], plan["blockers"]
    assert not plan["mutation_performed"]
    assert bpy.context.scene.world is before_world
    done = apply(reg, data, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.verification["matched"] is True
    world = bpy.context.scene.world
    assert world is not before_world
    assert world.use_nodes
    assert world.node_tree.nodes.get("SHUVI_WORLD_BACKGROUND") is not None
    assert world.node_tree.nodes.get("SHUVI_WORLD_OUTPUT") is not None
    if image:
        assert world.node_tree.nodes.get("SHUVI_WORLD_ENVIRONMENT").image is image
    released = release(reg, done.data["world_token"])
    assert released.status == Status.VERIFIED, released.error
    assert bpy.context.scene.world is before_world
    assert bpy.data.worlds == [before_world]
    assert inspector.summary()["revision"] == before_revision


def test_m5_can_create_and_remove_world_without_existing_world():
    bpy, _, reg = setup()
    data = args()
    outcome = apply(reg, data, preview(reg, data))
    assert outcome.status == Status.VERIFIED, outcome.error
    assert bpy.context.scene.world is not None
    assert release(reg, outcome.data["world_token"]).status == Status.VERIFIED
    assert bpy.context.scene.world is None
    assert not bpy.data.worlds


def test_m5_world_preview_stale_after_scene_or_world_change():
    bpy, _, reg = setup()
    data = args()
    planned = preview(reg, data)
    bpy.context.scene.world = bpy.data.worlds.new("OtherWorld")
    denied = apply(reg, data, planned)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert bpy.data.worlds.get("SHUVI_ENV") is None


def test_m5_changed_hdri_identity_blocks_stale_apply():
    bpy, _, reg = setup()
    old = imported_hdri(bpy)
    data = args("HDRI")
    planned = preview(reg, data)
    bpy.data.images.remove(old)
    imported_hdri(bpy)
    denied = apply(reg, data, planned)
    assert denied.error.code == ErrorCode.STALE_STATE


def test_m5_invalid_hdri_or_generated_image_denied():
    bpy, _, reg = setup()
    image = bpy.data.images.new("LoadedHDRI", 100, 100)
    with pytest.raises(AgentError):
        WorldPreview.parse(args("HDRI") | {"color": [1, 1, 1]})
    denied = reg.dispatch(Request("lighting.world_preview", args("HDRI")))
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    image.source = "FILE"
    image.has_data = True
    denied = reg.dispatch(Request("lighting.world_preview", args("HDRI")))
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m5_corrupted_world_strength_readback_rolls_back_without_foreign_edits():
    bpy, inspector, reg = setup()
    foreign = bpy.data.worlds.new("EarlierWorld")
    bpy.context.scene.world = foreign
    before = inspector.summary()["revision"]
    data = args()
    planned = preview(reg, data)

    def corrupt():
        owned = bpy.data.worlds.get("SHUVI_ENV")
        if owned is not None:
            background = owned.node_tree.nodes.get("SHUVI_WORLD_BACKGROUND")
            background.inputs["Strength"].default_value = 999

    bpy.context.view_layer.update = corrupt
    outcome = apply(reg, data, planned)
    assert outcome.status == Status.FAILED
    assert outcome.error.code == ErrorCode.VERIFICATION_FAILED
    assert bpy.context.scene.world is foreign
    assert bpy.data.worlds == [foreign]
    assert inspector.summary()["revision"] == before


def test_m5_exception_during_node_creation_restores_original_world():
    bpy, _, reg = setup()
    data = args()
    planned = preview(reg, data)
    original = bpy.data.worlds.new
    def fail(name):
        raise RuntimeError("New World failure")
    bpy.data.worlds.new = fail
    outcome = apply(reg, data, planned)
    assert outcome.error.code == ErrorCode.EXECUTION_ERROR
    assert not bpy.data.worlds
    bpy.data.worlds.new = original


def test_m5_changed_managed_world_or_foreign_session_token_refuses_release():
    bpy, _, reg = setup()
    data = args()
    done = apply(reg, data, preview(reg, data))
    assert done.status == Status.VERIFIED
    other = WorldLightingOperations(ObjectOperations(BpyInspector(bpy)))
    alternate = ToolRegistry(other.tools(), SafetyPolicy(allow_mutations=True))
    assert release(alternate, done.data["world_token"]).error.code == ErrorCode.STALE_STATE
    world = bpy.context.scene.world
    world.node_tree.nodes.get("SHUVI_WORLD_BACKGROUND").inputs["Strength"].default_value = 0.1
    assert release(reg, done.data["world_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert bpy.context.scene.world is world


@pytest.mark.parametrize("field,value", [
    ("strength", 15), ("strength", True), ("mode", "SKY"),
    ("color", [1, 2]), ("image_name", "../../etc/passwd"),
])
def test_m5_rejects_invalid_payload_or_unloaded_hdri(field, value):
    bpy, _, reg = setup()
    data = args("HDRI") if field == "image_name" else args()
    data[field] = value
    result = reg.dispatch(Request("lighting.world_preview", data))
    assert result.status == Status.FAILED


def test_m5_permission_gate_and_strict_world_parsers():
    bpy, _, _ = setup()
    denied = ToolRegistry(
        WorldLightingOperations(ObjectOperations(BpyInspector(bpy))).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    data = args()
    planned = preview(denied, data)
    assert apply(denied, data, planned).status == Status.FAILED
    assert not bpy.data.worlds
    with pytest.raises(AgentError):
        WorldApply.parse(data)
    with pytest.raises(AgentError):
        WorldPreview.parse(data | {"python": "import os"})
