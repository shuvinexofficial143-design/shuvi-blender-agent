"""M8: real Alpha Over compositor connectivity, rollback and one-use release."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_alpha_over import AlphaCompositeOperations, BlendPreview
from shuvi_blender_agent.compositor_keying import ChromaKeyOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, _, _, tree = setup()
    comp = tree.nodes.new("CompositorNodeComposite")
    comp.name = "Composite"
    bg = tree.nodes.new("CompositorNodeImage")
    bg.name = "Background"
    key_reg = ToolRegistry(ChromaKeyOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    key_params = {
        "scene_name": "Scene",
        "clip_name": "Footage",
        "key_color": [0, 1, 0],
        "clip_black": 0.05,
        "clip_white": 0.9,
        "despill_factor": 0.75,
    }
    plan = key_reg.dispatch(Request("compositor.key_preview", key_params))
    keyed = key_reg.dispatch(
        Request(
            "compositor.key_apply",
            key_params
            | {
                "expected_key_revision": plan.data["key_revision"],
            },
        )
    )
    assert keyed.status == Status.VERIFIED, keyed.error
    reg = ToolRegistry(AlphaCompositeOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    payload = {
        "scene_name": "Scene",
        "foreground_node": "ShuviGreenKey",
        "background_node": "Background",
        "composite_node": "Composite",
        "opacity": 0.85,
        "use_premultiply": True,
    }
    return bpy, tree, key_reg, keyed.data["key_token"], reg, payload


def preview(reg, params):
    return reg.dispatch(Request("compositor.blend_preview", params))


def apply(reg, params, plan):
    return reg.dispatch(
        Request(
            "compositor.blend_apply",
            params | {"expected_blend_revision": plan.data["blend_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.blend_release", {"expected_blend_token": token}))


def test_m8_connect_background_keying_to_final_composite_and_restore():
    _, tree, key_reg, key_token, reg, params = prepare()
    original = len(tree.links)
    plan = preview(reg, params)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["mutation_performed"] is False
    done = apply(reg, params, plan)
    assert done.status == Status.VERIFIED, done.error
    alpha = tree.nodes.get("ShuviAlphaOver")
    assert alpha.bl_idname == "CompositorNodeAlphaOver"
    assert alpha.inputs[0].default_value == 0.85
    assert alpha.use_premultiply is True
    assert len(tree.links) == original + 3
    assert any(
        link.to_node is tree.nodes.get("Composite") and link.from_node is alpha
        for link in tree.links
    )
    gone = release(reg, done.data["blend_token"])
    assert gone.status == Status.VERIFIED, gone.error
    assert tree.nodes.get("ShuviAlphaOver") is None
    assert len(tree.links) == original
    assert release(reg, done.data["blend_token"]).error.code == ErrorCode.STALE_STATE
    assert (
        key_reg.dispatch(
            Request("compositor.key_release", {"expected_key_token": key_token})
        ).status
        == Status.VERIFIED
    )


def test_m8_existing_composite_input_refuses_destructive_rewire():
    _, tree, _, _, reg, params = prepare()
    extra = tree.nodes.new("CompositorNodeImage")
    extra.name = "Outside"
    tree.links.new(extra.outputs["Image"], tree.nodes.get("Composite").inputs["Image"])
    denied = preview(reg, params)
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviAlphaOver") is None


def test_m8_stale_preview_denies_apply():
    _, tree, _, _, reg, params = prepare()
    planned = preview(reg, params)
    tree.nodes.new("CompositorNodeImage").name = "AddedAfterPreview"
    denied = apply(reg, params, planned)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviAlphaOver") is None


def test_m8_external_graph_changes_block_owned_release():
    _, tree, _, _, reg, params = prepare()
    applied = apply(reg, params, preview(reg, params))
    assert applied.status == Status.VERIFIED
    tree.nodes.new("CompositorNodeImage").name = "ForeignNode"
    denied = release(reg, applied.data["blend_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviAlphaOver") is not None


def test_m8_external_opacity_change_blocks_unsafe_release():
    _, tree, _, _, reg, params = prepare()
    applied = apply(reg, params, preview(reg, params))
    assert applied.status == Status.VERIFIED
    tree.nodes.get("ShuviAlphaOver").inputs[0].default_value = 0.4
    denied = release(reg, applied.data["blend_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m8_partial_link_failure_rolls_back_without_touching_key():
    _, tree, _, _, reg, params = prepare()
    before = len(tree.links)
    plan = preview(reg, params)
    original = tree.links.new
    count = {"n": 0}

    def failed_link(output, input_socket):
        count["n"] += 1
        if count["n"] == 2:
            raise RuntimeError("Injected compositor failure")
        return original(output, input_socket)

    tree.links.new = failed_link
    denied = apply(reg, params, plan)
    assert denied.error.code == ErrorCode.EXECUTION_ERROR
    assert tree.nodes.get("ShuviAlphaOver") is None
    assert tree.nodes.get("ShuviGreenKey") is not None
    assert len(tree.links) == before


def test_m8_rejects_non_native_foreground():
    _, _, _, _, reg, params = prepare()
    params["foreground_node"] = "Background"
    params["background_node"] = "ShuviGreenKey"
    assert preview(reg, params).error.code == ErrorCode.SAFETY_DENIED


def test_m8_readonly_host_and_registry():
    bpy, tree, _, _, _, params = prepare()
    catalog = create_registry(bpy).catalog()
    assert len(catalog) == 317
    assert {"compositor.blend_preview", "compositor.blend_apply", "compositor.blend_release"} <= {
        x["name"] for x in catalog
    }
    locked = ToolRegistry(
        AlphaCompositeOperations(bpy).tools(), SafetyPolicy(allow_mutations=False)
    )
    plan = preview(locked, params)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, params, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviAlphaOver") is None


@pytest.mark.parametrize(
    "data",
    [
        {"opacity": -1},
        {"opacity": float("nan")},
        {"use_premultiply": 1},
        {"foreground_node": ""},
    ],
)
def test_m8_invalid_payload_is_rejected(data):
    _, _, _, _, _, params = prepare()
    with pytest.raises(AgentError):
        BlendPreview.parse(params | data)


def test_m8_arbitrary_script_field_denied():
    _, _, _, _, reg, params = prepare()
    denied = preview(reg, params | {"exec": "bpy.ops.render.render()"})
    assert denied.error.code == ErrorCode.INVALID_REQUEST
