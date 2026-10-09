"""Level12 M1 tests for real compositor BrightContrast node and safety boundaries."""

import pytest
from compositor_fakes import setup

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.compositor_grade import ColorGradeOperations, GradePreview
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import ToolRegistry


def prepare():
    bpy, scene, clip, tree = setup()
    source = tree.nodes.new("CompositorNodeImage")
    source.name = "Source"
    sink = tree.nodes.new("CompositorNodeComposite")
    sink.name = "Composite"
    registry = ToolRegistry(ColorGradeOperations(bpy).tools(), SafetyPolicy(allow_mutations=True))
    args = {
        "scene_name": "Scene",
        "source_node": "Source",
        "output_node": "Composite",
        "brightness": 12.5,
        "contrast": -8.5,
        "use_premultiply": True,
    }
    return bpy, scene, clip, tree, registry, args


def preview(reg, args):
    return reg.dispatch(Request("compositor.grade_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "compositor.grade_apply",
            args | {"expected_grade_revision": plan.data["grade_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("compositor.grade_release", {"expected_grade_token": token}))


def test_m1_native_grade_changes_rna_and_output_and_restores():
    _, _, _, tree, reg, args = prepare()
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["mutation_performed"] is False
    result = apply(reg, args, plan)
    assert result.status == Status.VERIFIED, result.error
    grade = tree.nodes.get("ShuviColorGrade")
    assert grade.bl_idname == "CompositorNodeBrightContrast"
    assert grade.inputs["Bright"].default_value == 12.5
    assert grade.inputs["Contrast"].default_value == -8.5
    assert grade.use_premultiply is True
    assert len(tree.links) == 2
    assert any(link.to_node is grade for link in tree.links)
    assert any(link.from_node is grade and link.to_node.name == "Composite" for link in tree.links)
    token = result.data["grade_token"]
    assert release(reg, token).status == Status.VERIFIED
    assert tree.nodes.get("ShuviColorGrade") is None
    assert len(tree.links) == 0
    assert release(reg, token).error.code == ErrorCode.STALE_STATE


def test_m1_repeat_after_release_uses_new_token():
    _, _, _, _, reg, args = prepare()
    first = apply(reg, args, preview(reg, args))
    assert first.status == Status.VERIFIED
    assert release(reg, first.data["grade_token"]).status == Status.VERIFIED
    second = apply(reg, args, preview(reg, args))
    assert second.status == Status.VERIFIED
    assert first.data["grade_token"] != second.data["grade_token"]


def test_m1_existing_link_is_never_rewired():
    _, _, _, tree, reg, args = prepare()
    other = tree.nodes.new("CompositorNodeImage")
    other.name = "Other"
    tree.links.new(other.outputs["Image"], tree.nodes.get("Composite").inputs["Image"])
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert tree.nodes.get("ShuviColorGrade") is None
    assert len(tree.links) == 1


def test_m1_stale_graph_denied_before_node_creation():
    _, _, _, tree, reg, args = prepare()
    plan = preview(reg, args)
    tree.nodes.new("CompositorNodeImage").name = "Outside"
    assert apply(reg, args, plan).error.code == ErrorCode.STALE_STATE
    assert tree.nodes.get("ShuviColorGrade") is None


def test_m1_foreign_property_and_link_changes_prevent_release():
    _, _, _, tree, reg, args = prepare()
    result = apply(reg, args, preview(reg, args))
    assert result.status == Status.VERIFIED
    node = tree.nodes.get("ShuviColorGrade")
    node.inputs["Bright"].default_value = 24
    assert release(reg, result.data["grade_token"]).error.code == ErrorCode.SAFETY_DENIED
    node.inputs["Bright"].default_value = 12.5
    tree.nodes.new("CompositorNodeImage").name = "Outside"
    assert release(reg, result.data["grade_token"]).error.code == ErrorCode.SAFETY_DENIED
    assert node in tree.nodes


def test_m1_partial_link_failure_rolls_back_owned_node():
    _, _, _, tree, reg, args = prepare()
    original = tree.links.new
    calls = {"count": 0}

    def fail_second(a, b):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("forced link failure")
        return original(a, b)

    tree.links.new = fail_second
    result = apply(reg, args, preview(reg, args))
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert tree.nodes.get("ShuviColorGrade") is None
    assert len(tree.links) == 0
    assert tree.nodes.get("Source") is not None


def test_m1_source_type_and_scene_guards():
    _, scene, _, tree, reg, args = prepare()
    scene.use_nodes = False
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    scene.use_nodes = True
    args["source_node"] = "Composite"
    args["output_node"] = "Source"
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    tree.nodes.new("CompositorNodeImage").name = "ShuviColorGrade"
    args["source_node"] = "Source"
    args["output_node"] = "Composite"
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED


def test_m1_viewer_sink_and_read_only_policy():
    bpy, _, _, tree, _, args = prepare()
    viewer = tree.nodes.new("CompositorNodeViewer")
    viewer.name = "Viewer"
    args["output_node"] = "Viewer"
    locked = ToolRegistry(ColorGradeOperations(bpy).tools(), SafetyPolicy())
    plan = preview(locked, args)
    assert plan.status == Status.SUCCEEDED
    assert apply(locked, args, plan).status == Status.FAILED
    names = {tool["name"] for tool in create_registry(bpy).catalog()}
    assert len(names) == 320
    assert {
        "compositor.grade_preview",
        "compositor.grade_apply",
        "compositor.grade_release",
    } <= names


@pytest.mark.parametrize(
    "change",
    [
        {"brightness": float("nan")},
        {"brightness": -101},
        {"contrast": 101},
        {"brightness": True},
        {"use_premultiply": 1},
        {"source_node": ""},
        {"code": "bpy.ops.render.render()"},
    ],
)
def test_m1_rejects_untrusted_values(change):
    with pytest.raises(AgentError):
        GradePreview.parse(prepare()[-1] | change)
