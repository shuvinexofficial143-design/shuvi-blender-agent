"""Level12 M2 native lens distortion, chromatic dispersion and ownership tests."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_grade import ColorGradeOperations
from shuvi_blender_agent.compositor_lens import LensDistortionOperations, LensPreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, scene, _, tree = setup()
    source = tree.nodes.new("CompositorNodeImage")
    source.name = "Source"
    target = tree.nodes.new("CompositorNodeComposite")
    target.name = "Composite"
    reg = ToolRegistry(LensDistortionOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "distortion": -0.15,
        "dispersion": 0.08,
        "use_fit": True,
        "use_jitter": False,
    }
    return bpy, scene, tree, reg, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.lens_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.lens_apply",
            args | {"expected_lens_revision": plan.data["lens_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.lens_release", {"expected_lens_token": token}))


def test_m2_native_lens_distortion_and_dispersion_and_owned_restore():
    _, _, tree, reg, args = prepare()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    lens = tree.nodes.get("ShuviLensDistortion")
    assert lens.bl_idname == "CompositorNodeLensdist"
    assert lens.inputs["Distort"].default_value == -0.15
    assert lens.inputs["Dispersion"].default_value == 0.08
    assert lens.use_fit is True and lens.use_jitter is False
    assert lens.use_projector is False
    assert len(tree.links) == 2
    assert any(link.from_node is lens and link.to_node.name == "Composite" for link in tree.links)
    assert release(reg, done.data["lens_token"]).status == Status.VERIFIED
    assert tree.nodes.get("ShuviLensDistortion") is None
    assert len(tree.links) == 0
    assert release(reg, done.data["lens_token"]).error.code == ErrorCode.STALE_STATE


def test_m2_lens_from_existing_grade_node_to_separate_viewer():
    bpy, _, tree, reg, args = prepare()
    viewer = tree.nodes.new("CompositorNodeViewer")
    viewer.name = "Viewer"
    grade_reg = ToolRegistry(ColorGradeOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    grade_args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "brightness": 8,
        "contrast": 4,
        "use_premultiply": False,
    }
    grade_plan = grade_reg.dispatch(Request("compositor.grade_preview", grade_args))
    grade_done = grade_reg.dispatch(
        Request(
            "compositor.grade_apply",
            grade_args | {"expected_grade_revision": grade_plan.data["grade_revision"]},
        )
    )
    assert grade_done.status == Status.VERIFIED
    args["source_node"] = "ShuviColorGrade"
    args["output_node"] = "Viewer"
    lens_done = apply(reg, args, preview(reg, args))
    assert lens_done.status == Status.VERIFIED
    assert len(tree.links) == 4
    assert (
        grade_reg.dispatch(
            Request(
                "compositor.grade_release",
                {"expected_grade_token": grade_done.data["grade_token"]},
            )
        ).error.code
        == ErrorCode.SAFETY_DENIED
    )
    assert release(reg, lens_done.data["lens_token"]).status == Status.VERIFIED
    assert (
        grade_reg.dispatch(
            Request(
                "compositor.grade_release",
                {"expected_grade_token": grade_done.data["grade_token"]},
            )
        ).status
        == Status.VERIFIED
    )


def test_m2_prelinked_target_rejected_without_foreign_rewire():
    _, _, tree, reg, args = prepare()
    source = tree.nodes.get("Source")
    target = tree.nodes.get("Composite")
    tree.links.new(source.outputs["Image"], target.inputs["Image"])
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert len(tree.links) == 1
    assert tree.nodes.get("ShuviLensDistortion") is None


def test_m2_stale_preview_denies_apply():
    _, _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "Foreign"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviLensDistortion") is None


def test_m2_external_distortion_change_denies_release():
    _, _, tree, reg, args = prepare()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    node = tree.nodes.get("ShuviLensDistortion")
    node.inputs["Distort"].default_value = 0.2
    assert release(reg, done.data["lens_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert node in tree.nodes


def test_m2_partial_failure_rolls_back_owned_lens_only():
    _, _, tree, reg, args = prepare()
    real = tree.links.new
    count = {"n": 0}

    def fail_second(src, dst):
        count["n"] += 1
        if count["n"] == 2:
            raise RuntimeError("injected link failure")
        return real(src, dst)

    tree.links.new = fail_second
    out = apply(reg, args, preview(reg, args))
    assert out.error.code == ErrorCode.EXECUTION_ERROR
    assert len(tree.links) == 0
    assert tree.nodes.get("ShuviLensDistortion") is None
    assert tree.nodes.get("Source") is not None


def test_m2_one_use_nonce_changes_after_release_and_recreate():
    _, _, _, reg, args = prepare()
    first = apply(reg, args, preview(reg, args))
    assert first.status == Status.VERIFIED
    assert release(reg, first.data["lens_token"]).status == Status.VERIFIED
    second = apply(reg, args, preview(reg, args))
    assert second.status == Status.VERIFIED
    assert first.data["lens_token"] != second.data["lens_token"]


def test_m2_registry_tool_allowlist_and_readonly_policy():
    bpy, _, tree, _, args = prepare()
    names = {entry["name"] for entry in create_registry(bpy).catalog()}
    assert len(names) == 329
    assert {
        "compositor.lens_preview",
        "compositor.lens_apply",
        "compositor.lens_release",
    } <= names
    locked = ToolRegistry(LensDistortionOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    assert tree.nodes.get("ShuviLensDistortion") is None


@pytest.mark.parametrize(
    "change",
    [
        {"distortion": -0.51},
        {"distortion": 0.51},
        {"distortion": float("nan")},
        {"dispersion": 0.3},
        {"dispersion": float("inf")},
        {"use_fit": 1},
        {"use_jitter": "yes"},
        {"source_node": ""},
        {"script": "bpy.ops.render.render()"},
    ],
)
def test_m2_strict_typed_validation(change):
    with pytest.raises(AgentError):
        LensPreview.parse(prepare()[-1] | change)
