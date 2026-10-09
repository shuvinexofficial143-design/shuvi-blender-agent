"""Level 11 M10 integrated five-node compositor shot regression tests."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_shot import GreenScreenShotOperations, ShotPreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, scene, clip, tree = setup()
    bg = tree.nodes.new("CompositorNodeImage")
    bg.name = "Background"
    output = tree.nodes.new("CompositorNodeComposite")
    output.name = "Composite"
    reg = ToolRegistry(GreenScreenShotOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "clip_name": "Footage",
        "background_node": "Background",
        "composite_node": "Composite",
        "key_color": [0, 1, 0],
        "clip_black": 0.04,
        "clip_white": 0.91,
        "despill_factor": 0.7,
        "matte_distance": -3,
        "opacity": 0.85,
        "use_premultiply": True,
    }
    return bpy, scene, clip, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.shot_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.shot_apply",
            args | {"expected_shot_revision": plan.data["shot_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.shot_release", {"expected_shot_token": token}))


def test_m10_integrated_native_graph_exact_readback_and_release():
    _, _, clip, tree, reg, args = prepare()
    before = {node.name for node in tree.nodes}
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    assert done.data["nodes_created"] == 5
    assert done.data["links_created"] == 7
    assert len(tree.links) == 7
    movie = tree.nodes.get("ShuviGreenClip")
    key = tree.nodes.get("ShuviGreenKey")
    matte = tree.nodes.get("ShuviMatteRefine")
    setter = tree.nodes.get("ShuviMatteOutput")
    blend = tree.nodes.get("ShuviAlphaOver")
    assert movie.clip is clip
    assert key.clip_black == 0.04 and key.clip_white == 0.91
    assert matte.mode == "STEP" and matte.distance == -3
    assert setter.mode == "REPLACE_ALPHA"
    assert blend.inputs[0].default_value == 0.85
    assert blend.use_premultiply is True
    assert any(
        link.from_node is blend and link.to_node is tree.nodes.get("Composite")
        for link in tree.links
    )
    assert release(reg, done.data["shot_token"]).status == Status.VERIFIED
    assert {node.name for node in tree.nodes} == before
    assert len(tree.links) == 0
    assert release(reg, done.data["shot_token"]).error.code == ErrorCode.STALE_STATE


def test_m10_repeated_apply_after_release_has_fresh_owner_token():
    _, _, _, _, reg, args = prepare()
    first = apply(reg, args, preview(reg, args))
    assert first.status == Status.VERIFIED
    assert release(reg, first.data["shot_token"]).status == Status.VERIFIED
    second = apply(reg, args, preview(reg, args))
    assert second.status == Status.VERIFIED
    assert first.data["shot_token"] != second.data["shot_token"]
    assert release(reg, first.data["shot_token"]).error.code == ErrorCode.STALE_STATE
    assert release(reg, second.data["shot_token"]).status == Status.VERIFIED


def test_m10_foreign_composite_connection_denied_without_rewire():
    _, _, _, tree, reg, args = prepare()
    foreign = tree.nodes.new("CompositorNodeImage")
    foreign.name = "Outside"
    tree.links.new(foreign.outputs["Image"], tree.nodes.get("Composite").inputs["Image"])
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert len(tree.links) == 1
    assert tree.nodes.get("ShuviGreenClip") is None


def test_m10_preview_stale_on_foreign_graph_change():
    _, _, _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "External"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviGreenClip") is None


def test_m10_foreign_change_prevents_destructive_release():
    _, _, _, tree, reg, args = prepare()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    tree.nodes.get("ShuviGreenKey").despill_factor = 0.3
    denied = release(reg, done.data["shot_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert len(tree.links) == 7


def test_m10_partial_link_failure_rolls_back_only_five_new_nodes():
    _, _, _, tree, reg, args = prepare()
    original = tree.links.new
    n = {"count": 0}

    def break_link(source, target):
        n["count"] += 1
        if n["count"] == 5:
            raise RuntimeError("injected")
        return original(source, target)

    tree.links.new = break_link
    denied = apply(reg, args, preview(reg, args))
    assert denied.error.code == ErrorCode.EXECUTION_ERROR
    assert set(node.name for node in tree.nodes) == {"Background", "Composite"}
    assert len(tree.links) == 0


def test_m10_native_source_requirement_and_reserved_node_guard():
    _, scene, clip, tree, reg, args = prepare()
    scene.use_nodes = False
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    scene.use_nodes = True
    clip.library = object()
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    clip.library = None
    tree.nodes.new("CompositorNodeImage").name = "ShuviGreenClip"
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED


def test_m10_registry_and_policy_gate():
    bpy, _, _, tree, _, args = prepare()
    names = {entry["name"] for entry in create_registry(bpy).catalog()}
    assert len(names) == 317
    assert {"compositor.shot_preview", "compositor.shot_apply", "compositor.shot_release"} <= names
    locked = ToolRegistry(GreenScreenShotOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviGreenClip") is None


@pytest.mark.parametrize(
    "changes",
    [
        {"matte_distance": -9},
        {"matte_distance": 9},
        {"matte_distance": 0.25},
        {"matte_distance": True},
        {"opacity": float("nan")},
        {"use_premultiply": 1},
        {"clip_black": 0.9, "clip_white": 0.2},
        {"key_color": [0, 1]},
        {"key_color": [0, float("inf"), 0]},
        {"background_node": ""},
        {"python": "bpy.ops.render.render()"},
    ],
)
def test_m10_strict_parser_denies_invalid_and_arbitrary_execution(changes):
    args = prepare()[-1]
    with pytest.raises(AgentError):
        ShotPreview.parse(args | changes)
