"""Level 12 M3 native Hue/Saturation/Value compositor contract tests."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_hsv import HSVColorOperations, HuePreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, _, _, tree = setup()
    tree.nodes.new("CompositorNodeImage").name = "Source"
    tree.nodes.new("CompositorNodeComposite").name = "Composite"
    reg = ToolRegistry(HSVColorOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "hue": 0.65,
        "saturation": 1.25,
        "value": 0.8,
        "factor": 0.75,
    }
    return bpy, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.hsv_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.hsv_apply",
            args | {"expected_hue_revision": plan.data["hue_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.hsv_release", {"expected_hue_token": token}))


def test_hsv_native_sockets_exact_links_and_release():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    result = apply(reg, args, plan)
    assert result.status == Status.VERIFIED, result.error
    node = tree.nodes.get("ShuviHSVAdjust")
    assert node.bl_idname == "CompositorNodeHueSat"
    assert [node.inputs[k].default_value for k in ("Hue", "Saturation", "Value", "Fac")] == [
        0.65,
        1.25,
        0.8,
        0.75,
    ]
    assert len(tree.links) == 2
    assert any(x.from_node is node and x.to_node.name == "Composite" for x in tree.links)
    assert release(reg, result.data["hue_token"]).status == Status.VERIFIED
    assert len(tree.links) == 0
    assert tree.nodes.get("ShuviHSVAdjust") is None
    assert release(reg, result.data["hue_token"]).error.code == ErrorCode.STALE_STATE


def test_hsv_existing_connected_output_not_rewired():
    _, tree, reg, args = prepare()
    source = tree.nodes.get("Source")
    tree.links.new(source.outputs["Image"], tree.nodes.get("Composite").inputs["Image"])
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert len(tree.links) == 1


def test_hsv_stale_graph_blocks_apply():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "External"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviHSVAdjust") is None


def test_hsv_settings_and_external_nodes_protected_on_release():
    _, tree, reg, args = prepare()
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    node = tree.nodes.get("ShuviHSVAdjust")
    node.inputs["Saturation"].default_value = 0.4
    assert release(reg, result.data["hue_token"]).error.code == ErrorCode.SAFETY_DENIED
    node.inputs["Saturation"].default_value = 1.25
    tree.nodes.new("CompositorNodeImage").name = "Unrelated"
    assert release(reg, result.data["hue_token"]).error.code == ErrorCode.SAFETY_DENIED


def test_hsv_partial_link_failure_rolls_back_owned_node_only():
    _, tree, reg, args = prepare()
    original = tree.links.new
    n = {"i": 0}

    def injected(a, b):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("injected")
        return original(a, b)

    tree.links.new = injected
    result = apply(reg, args, preview(reg, args))
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert len(tree.links) == 0
    assert tree.nodes.get("ShuviHSVAdjust") is None
    assert tree.nodes.get("Source") is not None


def test_hsv_registry_and_policy():
    bpy, tree, _, args = prepare()
    catalog = {x["name"] for x in create_registry(bpy).catalog()}
    assert len(catalog) == 323
    assert {"compositor.hsv_preview", "compositor.hsv_apply", "compositor.hsv_release"} <= catalog
    locked = ToolRegistry(HSVColorOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviHSVAdjust") is None


@pytest.mark.parametrize(
    "update",
    [
        {"hue": -0.1},
        {"hue": 1.1},
        {"hue": float("nan")},
        {"saturation": 2.1},
        {"value": -0.1},
        {"factor": float("inf")},
        {"factor": True},
        {"source_node": ""},
        {"python": "exec()"},
    ],
)
def test_hsv_parser_rejects_invalid_values(update):
    with pytest.raises(AgentError):
        HuePreview.parse(prepare()[-1] | update)
