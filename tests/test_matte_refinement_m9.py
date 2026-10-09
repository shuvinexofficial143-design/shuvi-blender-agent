"""Level 11 M9 native edge/matte refinement source-level acceptance."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_keying import ChromaKeyOperations
from shuvi_blender_agent.compositor_matte import MattePreview, MatteRefinementOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, _, _, tree = setup()
    reg_key = ToolRegistry(ChromaKeyOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    key = {
        "scene_name": "Scene",
        "clip_name": "Footage",
        "key_color": [0, 1, 0],
        "clip_black": 0.05,
        "clip_white": 0.95,
        "despill_factor": 0.7,
    }
    plan = reg_key.dispatch(Request("compositor.key_preview", key))
    applied = reg_key.dispatch(
        Request("compositor.key_apply", key | {"expected_key_revision": plan.data["key_revision"]})
    )
    assert applied.status == Status.VERIFIED, applied.error
    reg = ToolRegistry(MatteRefinementOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {"scene_name": "Scene", "key_node": "ShuviGreenKey", "distance": -2}
    return bpy, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.matte_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.matte_apply",
            args | {"expected_matte_revision": plan.data["matte_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(
        Request("compositor.matte_release", {"expected_matte_token": token})
    )


def test_m9_native_nodes_exact_links_and_guarded_restore():
    _, tree, reg, args = prepare()
    before = len(tree.links)
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    matte = tree.nodes.get("ShuviMatteRefine")
    alpha = tree.nodes.get("ShuviMatteOutput")
    assert matte.bl_idname == "CompositorNodeDilateErode"
    assert matte.mode == "STEP" and matte.distance == -2
    assert alpha.mode == "REPLACE_ALPHA"
    assert len(tree.links) == before + 3
    assert any(link.from_node is matte and link.to_node is alpha for link in tree.links)
    assert release(reg, done.data["matte_token"]).status == Status.VERIFIED
    assert tree.nodes.get("ShuviMatteOutput") is None
    assert tree.nodes.get("ShuviMatteRefine") is None
    assert len(tree.links) == before
    assert release(reg, done.data["matte_token"]).error.code == ErrorCode.STALE_STATE


def test_m9_stale_graph_does_not_mutate():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "Foreign"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviMatteRefine") is None


def test_m9_external_link_or_property_change_blocks_release():
    _, tree, reg, args = prepare()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    tree.nodes.get("ShuviMatteRefine").distance = 3
    assert release(reg, done.data["matte_token"]).error.code == ErrorCode.SAFETY_DENIED
    tree.nodes.get("ShuviMatteRefine").distance = -2
    tree.nodes.new("CompositorNodeImage").name = "Foreign"
    assert release(reg, done.data["matte_token"]).error.code == ErrorCode.SAFETY_DENIED


def test_m9_injected_link_failure_removes_only_own_nodes():
    _, tree, reg, args = prepare()
    before = len(tree.links)
    real = tree.links.new
    calls = {"count": 0}

    def fail_second(source, sink):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected link failure")
        return real(source, sink)

    tree.links.new = fail_second
    out = apply(reg, args, preview(reg, args))
    assert out.error.code == ErrorCode.EXECUTION_ERROR
    assert len(tree.links) == before
    assert tree.nodes.get("ShuviGreenKey") is not None
    assert tree.nodes.get("ShuviMatteRefine") is None


def test_m9_readonly_policy_and_catalog():
    bpy, tree, _, args = prepare()
    assert len(create_registry(bpy).catalog()) == 308
    locked = ToolRegistry(MatteRefinementOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviMatteRefine") is None


@pytest.mark.parametrize(
    "change",
    [
        {"distance": -9},
        {"distance": 9},
        {"distance": True},
        {"distance": 0.5},
        {"distance": float("nan")},
        {"key_node": ""},
        {"exec": "import os"},
    ],
)
def test_m9_parser_rejects_invalid_or_code_payload(change):
    args = {"scene_name": "Scene", "key_node": "ShuviGreenKey", "distance": -2}
    with pytest.raises(AgentError):
        MattePreview.parse(args | change)


def test_m9_no_implicit_scene_or_key_creation():
    _, tree, reg, args = prepare()
    args["key_node"] = "Unknown"
    assert preview(reg, args).error.code == ErrorCode.NOT_FOUND
    args["key_node"] = "ShuviGreenKey"
    tree.nodes.get("ShuviGreenKey").bl_idname = "CompositorNodeImage"
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
