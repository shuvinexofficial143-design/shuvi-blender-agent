"""Level 12 M4 native fixed-radius Gaussian blur graph and guard tests."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_blur import BlurPreview, GaussianBlurOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, _, _, tree = setup()
    tree.nodes.new("CompositorNodeImage").name = "Source"
    tree.nodes.new("CompositorNodeComposite").name = "Composite"
    reg = ToolRegistry(GaussianBlurOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "radius_x": 9,
        "radius_y": 4,
        "filter_type": "FAST_GAUSS",
        "use_extended_bounds": True,
    }
    return bpy, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.blur_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.blur_apply",
            args
            | {
                "expected_blur_revision": plan.data["blur_revision"],
            },
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.blur_release", {"expected_blur_token": token}))


def test_m4_native_node_radii_filter_links_and_release():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    node = tree.nodes.get("ShuviGaussianBlur")
    assert node.bl_idname == "CompositorNodeBlur"
    assert node.filter_type == "FAST_GAUSS"
    assert (node.size_x, node.size_y) == (9, 4)
    assert node.use_extended_bounds is True
    assert node.use_relative is False
    assert node.use_variable_size is False
    assert len(tree.links) == 2
    assert any(x.from_node is node and x.to_node.name == "Composite" for x in tree.links)
    token = done.data["blur_token"]
    assert release(reg, token).status == Status.VERIFIED
    assert len(tree.links) == 0
    assert tree.nodes.get("ShuviGaussianBlur") is None
    assert release(reg, token).error.code == ErrorCode.STALE_STATE


def test_m4_gauss_and_viewer_target():
    _, tree, reg, args = prepare()
    tree.nodes.new("CompositorNodeViewer").name = "Viewer"
    args["output_node"] = "Viewer"
    args["filter_type"] = "GAUSS"
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    assert tree.nodes.get("ShuviGaussianBlur").filter_type == "GAUSS"
    assert release(reg, result.data["blur_token"]).status == Status.VERIFIED


def test_m4_existing_output_link_not_overwritten():
    _, tree, reg, args = prepare()
    tree.links.new(
        tree.nodes.get("Source").outputs["Image"], tree.nodes.get("Composite").inputs["Image"]
    )
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviGaussianBlur") is None
    assert len(tree.links) == 1


def test_m4_stale_preview_rejected():
    _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "Foreign"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviGaussianBlur") is None


def test_m4_external_parameter_change_denies_release():
    _, tree, reg, args = prepare()
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    node = tree.nodes.get("ShuviGaussianBlur")
    node.size_x = 22
    assert release(reg, result.data["blur_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert node in tree.nodes


def test_m4_injected_second_link_failure_reverts_owned_node():
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
    assert tree.nodes.get("ShuviGaussianBlur") is None
    assert tree.nodes.get("Source") is not None
    assert len(tree.links) == 0


def test_m4_catalog_and_readonly_gate():
    bpy, tree, _, args = prepare()
    names = {x["name"] for x in create_registry(bpy).catalog()}
    assert len(names) == 329
    assert {"compositor.blur_preview", "compositor.blur_apply", "compositor.blur_release"} <= names
    locked = ToolRegistry(GaussianBlurOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviGaussianBlur") is None


@pytest.mark.parametrize(
    "update",
    [
        {"radius_x": 0},
        {"radius_y": 65},
        {"radius_y": True},
        {"radius_x": 1.5},
        {"filter_type": "INVALID"},
        {"filter_type": ""},
        {"use_extended_bounds": 1},
        {"output_node": ""},
        {"exec": "bpy.ops.render.render()"},
    ],
)
def test_m4_strict_parser_rejects_invalid_and_arbitrary_code(update):
    with pytest.raises(AgentError):
        BlurPreview.parse(prepare()[-1] | update)
