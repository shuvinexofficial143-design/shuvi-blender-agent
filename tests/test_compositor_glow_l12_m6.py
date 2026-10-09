"""Level 12 M6 tests for real native Fog Glow/Bloom graph and strict undo."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_glow import GlowOperations, GlowPreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def fixture():
    bpy, _, _, tree = setup()
    tree.nodes.new("CompositorNodeImage").name = "Source"
    tree.nodes.new("CompositorNodeComposite").name = "Composite"
    reg = ToolRegistry(GlowOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "glare_type": "FOG_GLOW",
        "quality": "HIGH",
        "threshold": 1.4,
        "size": 7,
        "mix": 0.25,
    }
    return bpy, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.glow_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.glow_apply",
            args | {"expected_glow_revision": plan.data["glow_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.glow_release", {"expected_glow_token": token}))


def test_m6_native_glare_exact_settings_and_owned_release():
    _, tree, reg, args = fixture()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    node = tree.nodes.get("ShuviFogGlow")
    assert node.bl_idname == "CompositorNodeGlare"
    assert (node.glare_type, node.quality) == ("FOG_GLOW", "HIGH")
    assert (node.threshold, node.size, node.mix) == (1.4, 7, 0.25)
    assert len(tree.links) == 2
    assert any(x.from_node is node and x.to_node.name == "Composite" for x in tree.links)
    token = done.data["glow_token"]
    assert release(reg, token).status == Status.VERIFIED
    assert tree.nodes.get("ShuviFogGlow") is None
    assert len(tree.links) == 0
    assert release(reg, token).error.code == ErrorCode.STALE_STATE


def test_m6_bloom_mode_and_viewer_output():
    _, tree, reg, args = fixture()
    tree.nodes.new("CompositorNodeViewer").name = "Viewer"
    args.update(
        output_node="Viewer",
        glare_type="BLOOM",
        quality="MEDIUM",
        threshold=0.6,
        size=9,
        mix=-0.5,
    )
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    node = tree.nodes.get("ShuviFogGlow")
    assert (node.glare_type, node.quality, node.size, node.mix) == (
        "BLOOM",
        "MEDIUM",
        9,
        -0.5,
    )
    assert release(reg, result.data["glow_token"]).status == Status.VERIFIED


def test_m6_refuses_existing_output_link():
    _, tree, reg, args = fixture()
    tree.links.new(
        tree.nodes.get("Source").outputs["Image"],
        tree.nodes.get("Composite").inputs["Image"],
    )
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviFogGlow") is None
    assert len(tree.links) == 1


def test_m6_detects_stale_graph_before_any_mutation():
    _, tree, reg, args = fixture()
    old = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "Foreign"
    assert apply(reg, args, old).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviFogGlow") is None


def test_m6_refuses_release_after_foreign_glare_setting_changed():
    _, tree, reg, args = fixture()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    node = tree.nodes.get("ShuviFogGlow")
    node.threshold = 3.0
    assert release(reg, done.data["glow_token"]).error.code == ErrorCode.SAFETY_DENIED
    node.threshold = 1.4
    tree.nodes.new("CompositorNodeImage").name = "Outside"
    assert release(reg, done.data["glow_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert node in tree.nodes


def test_m6_atomic_rollback_when_second_link_fails():
    _, tree, reg, args = fixture()
    real = tree.links.new
    n = {"calls": 0}

    def injected(a, b):
        n["calls"] += 1
        if n["calls"] == 2:
            raise RuntimeError("deliberate failure")
        return real(a, b)

    tree.links.new = injected
    done = apply(reg, args, preview(reg, args))
    assert done.error.code == ErrorCode.EXECUTION_ERROR
    assert tree.nodes.get("ShuviFogGlow") is None
    assert tree.nodes.get("Source") is not None
    assert len(tree.links) == 0


def test_m6_registry_host_allowlist_and_readonly_gate():
    bpy, tree, _, args = fixture()
    catalog = {tool["name"] for tool in create_registry(bpy).catalog()}
    assert len(catalog) == 329
    assert {
        "compositor.glow_preview",
        "compositor.glow_apply",
        "compositor.glow_release",
    } <= catalog
    locked = ToolRegistry(GlowOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviFogGlow") is None


@pytest.mark.parametrize(
    "update",
    [
        {"threshold": -1},
        {"threshold": 11},
        {"threshold": float("nan")},
        {"threshold": True},
        {"size": 5},
        {"size": 10},
        {"size": 7.1},
        {"quality": "LOW"},
        {"glare_type": "GHOSTS"},
        {"mix": float("inf")},
        {"mix": 1.2},
        {"scene_name": ""},
        {"payload": "bpy.ops.render.render()"},
    ],
)
def test_m6_rejects_invalid_types_values_and_injected_code(update):
    with pytest.raises(AgentError):
        GlowPreview.parse(fixture()[-1] | update)
