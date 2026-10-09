"""M7: real compositing nodes, green-screen chroma properties and safe ownership."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_keying import ChromaKeyOperations, KeyPreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, scene, clip, tree = setup()
    existing = tree.nodes.new("CompositorNodeComposite")
    existing.name = "ExistingComposite"
    background = tree.nodes.new("CompositorNodeImage")
    background.name = "ExistingBackground"
    reg = ToolRegistry(ChromaKeyOperations(bpy).tools(), SafetyPolicy())
    payload = {
        "scene_name": "Scene",
        "clip_name": "Footage",
        "key_color": [0, 1, 0],
        "clip_black": 0.04,
        "clip_white": 0.88,
        "despill_factor": 0.75,
    }
    return bpy, scene, clip, tree, reg, payload


def preview(reg, payload):
    return reg.dispatch(Request("compositor.key_preview", payload))


def apply(reg, payload, plan):
    return reg.dispatch(
        Request(
            "compositor.key_apply",
            payload
            | {
                "expected_key_revision": plan.data["key_revision"],
            },
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.key_release", {"expected_key_token": token}))


def test_m7_creates_native_clip_to_keying_and_owned_restore():
    _, _, clip, tree, reg, payload = prepare()
    before_nodes = {node.name for node in tree.nodes}
    plan = preview(reg, payload)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    out = apply(reg, payload, plan)
    assert out.status == Status.VERIFIED, out.error
    movie = tree.nodes.get("ShuviGreenClip")
    key = tree.nodes.get("ShuviGreenKey")
    assert movie.clip is clip and movie.bl_idname == "CompositorNodeMovieClip"
    assert key.bl_idname == "CompositorNodeKeying"
    assert key.inputs["Key Color"].default_value == (0.0, 1.0, 0.0, 1.0)
    assert key.despill_factor == 0.75
    assert len(tree.links) == 1
    assert tree.links[0].from_node is movie and tree.links[0].to_node is key
    done = release(reg, out.data["key_token"])
    assert done.status == Status.VERIFIED, done.error
    assert {node.name for node in tree.nodes} == before_nodes
    assert len(tree.links) == 0
    assert release(reg, out.data["key_token"]).error.code == ErrorCode.STALE_STATE


def test_m7_stale_graph_denies_apply():
    _, _, _, tree, reg, payload = prepare()
    plan = preview(reg, payload)
    tree.nodes.new("CompositorNodeImage").name = "ForeignNode"
    denied = apply(reg, payload, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviGreenKey") is None


def test_m7_foreign_changes_block_unsafe_release():
    _, _, _, tree, reg, payload = prepare()
    out = apply(reg, payload, preview(reg, payload))
    assert out.status == Status.VERIFIED
    tree.nodes.get("ShuviGreenKey").clip_black = 0.3
    assert release(reg, out.data["key_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviGreenClip") is not None


def test_m7_foreign_link_blocks_release():
    _, _, _, tree, reg, payload = prepare()
    out = apply(reg, payload, preview(reg, payload))
    key = tree.nodes.get("ShuviGreenKey")
    comp = tree.nodes.get("ExistingComposite")
    tree.links.new(key.outputs["Image"], comp.inputs["Image"])
    assert release(reg, out.data["key_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert len(tree.links) == 2


def test_m7_failure_rolls_back_owned_nodes_only():
    _, _, _, tree, reg, payload = prepare()
    before = {node.name for node in tree.nodes}
    plan = preview(reg, payload)
    tree.links.new = lambda *_: (_ for _ in ()).throw(RuntimeError("link failure"))
    result = apply(reg, payload, plan)
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert {node.name for node in tree.nodes} == before


def test_m7_no_implicit_compositor_creation_or_clip_loading():
    _, scene, clip, _, reg, payload = prepare()
    scene.use_nodes = False
    assert preview(reg, payload).error.code == ErrorCode.SAFETY_DENIED
    scene.use_nodes = True
    clip.library = object()
    assert preview(reg, payload).error.code == ErrorCode.SAFETY_DENIED


def test_m7_readonly_policy_and_host_registry():
    bpy, _, _, tree, _, payload = prepare()
    catalog = create_registry(bpy).catalog()
    assert len(catalog) == 302
    assert {"compositor.key_preview", "compositor.key_apply", "compositor.key_release"} <= {
        item["name"] for item in catalog
    }
    locked = ToolRegistry(ChromaKeyOperations(bpy).tools(), SafetyPolicy(allow_mutations=False))
    plan = preview(locked, payload)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, payload, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviGreenKey") is None


@pytest.mark.parametrize(
    "change",
    [
        {"clip_black": 0.9, "clip_white": 0.8},
        {"key_color": [0.1, 2, 0]},
        {"key_color": [0, 1]},
        {"despill_factor": float("nan")},
    ],
)
def test_m7_rejects_invalid_keying_params(change):
    _, _, _, _, _, payload = prepare()
    with pytest.raises(AgentError):
        KeyPreview.parse(payload | change)


def test_m7_extra_code_field_rejected():
    _, _, _, _, reg, payload = prepare()
    assert preview(reg, payload | {"exec": "import os"}).error.code == ErrorCode.INVALID_REQUEST
