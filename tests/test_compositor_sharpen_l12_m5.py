"""Level 12 M5 native image sharpen filter, rollback and graph guards."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_sharpen import SharpenPreview, SharpenFilterOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, _, _, tree = setup()
    tree.nodes.new("CompositorNodeImage").name = "Source"
    tree.nodes.new("CompositorNodeComposite").name = "Composite"
    reg = ToolRegistry(SharpenFilterOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "filter_type": "SHARPEN_DIAMOND",
        "strength": 0.65,
    }
    return bpy, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.sharpen_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.sharpen_apply",
            args
            | {
                "expected_sharpen_revision": plan.data["sharpen_revision"],
            },
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.sharpen_release", {"expected_sharpen_token": token}))


def test_m5_native_sharpen_strength_native_links_and_undo():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    node = tree.nodes.get("ShuviSharpenFilter")
    assert node.bl_idname == "CompositorNodeFilter"
    assert node.filter_type == "SHARPEN_DIAMOND"
    assert node.inputs["Fac"].default_value == 0.65
    assert len(tree.links) == 2
    assert any(x.from_node is node and x.to_node.name == "Composite" for x in tree.links)
    token = done.data["sharpen_token"]
    assert release(reg, token).status == Status.VERIFIED
    assert len(tree.links) == 0
    assert tree.nodes.get("ShuviSharpenFilter") is None
    assert release(reg, token).error.code == ErrorCode.STALE_STATE


def test_m5_box_sharpen_and_viewer_target():
    _, tree, reg, args = prepare()
    tree.nodes.new("CompositorNodeViewer").name = "Viewer"
    args["output_node"] = "Viewer"
    args["filter_type"] = "SHARPEN"
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    assert tree.nodes.get("ShuviSharpenFilter").filter_type == "SHARPEN"
    assert release(reg, result.data["sharpen_token"]).status == Status.VERIFIED


def test_m5_existing_output_link_not_overwritten():
    _, tree, reg, args = prepare()
    tree.links.new(
        tree.nodes.get("Source").outputs["Image"], tree.nodes.get("Composite").inputs["Image"]
    )
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviSharpenFilter") is None
    assert len(tree.links) == 1


def test_m5_stale_preview_rejected():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "Foreign"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviSharpenFilter") is None


def test_m5_external_parameter_change_denies_release():
    _, tree, reg, args = prepare()
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    node = tree.nodes.get("ShuviSharpenFilter")
    node.inputs["Fac"].default_value = 0.15
    assert release(reg, result.data["sharpen_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert node in tree.nodes


def test_m5_injected_second_link_failure_reverts_owned_node():
    _, tree, reg, args = prepare()
    original = tree.links.new
    calls = {"count": 0}

    def fail_second(a, b):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected link failure")
        return original(a, b)

    tree.links.new = fail_second
    result = apply(reg, args, preview(reg, args))
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert tree.nodes.get("ShuviSharpenFilter") is None
    assert tree.nodes.get("Source") is not None
    assert len(tree.links) == 0


def test_m5_catalog_and_readonly_gate():
    bpy, tree, _, args = prepare()
    names = {x["name"] for x in create_registry(bpy).catalog()}
    assert len(names) == 326
    assert {
        "compositor.sharpen_preview",
        "compositor.sharpen_apply",
        "compositor.sharpen_release",
    } <= names
    locked = ToolRegistry(SharpenFilterOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviSharpenFilter") is None


@pytest.mark.parametrize(
    "update",
    [
        {"strength": -0.1},
        {"strength": 1.1},
        {"strength": True},
        {"strength": float("nan")},
        {"filter_type": "SOFTEN"},
        {"filter_type": "INVALID"},
        {"source_node": ""},
        {"exec": "bpy.ops.render.render()"},
    ],
)
def test_m5_strict_parser_rejects_invalid_and_arbitrary_code(update):
    with pytest.raises(AgentError):
        SharpenPreview.parse(prepare()[-1] | update)
