import pytest
from fake_bpy import NS, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.modeling_hardsurface import HardSurfaceOperations
from shuvi_blender_agent.modeling_modifier_workflows import (
    ModelingModifierWorkflowOperations,
    RecipeApply,
    RecipePreview,
    StackCompose,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    hard_surface = HardSurfaceOperations(objects)
    workflows = ModelingModifierWorkflowOperations(objects)
    registry = ToolRegistry(
        [*hard_surface.tools(), *workflows.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, hard_surface, workflows, registry


def target(inspector, obj):
    snap = inspector.snapshot(obj)
    return {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }


def stack(registry, inspector, obj):
    return registry.dispatch(
        Request("modifier.stack_inspect", {"object_id": inspector.identity(obj)})
    ).data


def test_stack_diagnose_empty_stack_is_clean():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    result = registry.dispatch(
        Request("modifier.stack_diagnose", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["count"] == 0
    assert data["type_counts"] == {}
    assert data["warnings"] == []
    assert data["complexity_score"] == 0
    assert len(data["diagnostic_revision"]) == 64


def test_stack_diagnose_reports_order_visibility_reference_and_unknown_warnings():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")

    sub = obj.modifiers.new("Sub", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 2
    sub.show_viewport = False

    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = 0.1
    bevel.segments = 2
    bevel.show_render = False

    boolean = obj.modifiers.new("BrokenBoolean", "BOOLEAN")
    boolean.operation = "DIFFERENCE"
    boolean.solver = "EXACT"
    boolean.object = None

    unknown = NS(
        name="Mystery",
        type="MIRROR",
        show_viewport=True,
        show_render=True,
    )
    obj.modifiers.append(unknown)

    result = registry.dispatch(
        Request("modifier.stack_diagnose", {"object_id": inspector.identity(obj)})
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["type_counts"] == {
        "BEVEL": 1,
        "BOOLEAN": 1,
        "MIRROR": 1,
        "SUBSURF": 1,
    }
    assert data["unsupported_modifier_indices"] == [3]
    assert data["disabled_viewport_indices"] == [0]
    assert data["disabled_render_indices"] == [1]
    assert data["missing_reference_indices"] == [2]
    assert data["subsurf_before_bevel_pairs"] == [[0, 1]]
    assert data["reference_modifier_count"] == 1
    assert data["complexity_score"] == 6
    assert data["warnings"] == [
        "UNSUPPORTED_MODIFIER_TYPES",
        "MISSING_OBJECT_REFERENCES",
        "SUBSURF_BEFORE_BEVEL",
        "VIEWPORT_DISABLED_ENTRIES",
        "RENDER_DISABLED_ENTRIES",
    ]


def test_stack_compose_appends_multiple_typed_modifiers_transactionally():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.stack_compose",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "entries": [
                    {
                        "name": "Shell",
                        "kind": "SOLIDIFY",
                        "settings": {"thickness": 0.08},
                    },
                    {
                        "name": "Edge",
                        "kind": "BEVEL",
                        "settings": {"width": 0.02, "segments": 3},
                    },
                    {
                        "name": "Smooth",
                        "kind": "SUBSURF",
                        "settings": {"levels": 1, "render_levels": 2},
                    },
                ],
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["composed_modifier_names"] == ["Shell", "Edge", "Smooth"]
    assert after["composed_modifier_count"] == 3
    assert [item["type"] for item in after["items"]] == [
        "SOLIDIFY",
        "BEVEL",
        "SUBSURF",
    ]


def test_stack_compose_rejects_existing_name_before_mutation():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    existing = obj.modifiers.new("Edge", "BEVEL")
    existing.width = 0.1
    existing.segments = 2
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.stack_compose",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "entries": [
                    {
                        "name": "Edge",
                        "kind": "BEVEL",
                        "settings": {"width": 0.2, "segments": 4},
                    }
                ],
            },
        )
    )
    assert result.error.code == ErrorCode.AMBIGUOUS_TARGET
    assert len(obj.modifiers) == 1
    assert existing.width == 0.1


def test_stack_compose_rejects_stale_revision():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    stale = stack(registry, inspector, obj)
    modifier = obj.modifiers.new("Existing", "BEVEL")
    modifier.width = 0.1
    modifier.segments = 2

    result = registry.dispatch(
        Request(
            "modifier.stack_compose",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": stale["stack_revision"],
                "entries": [
                    {
                        "name": "Solid",
                        "kind": "SOLIDIFY",
                        "settings": {"thickness": 0.1},
                    }
                ],
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert obj.modifiers.get("Solid") is None


def test_stack_compose_verification_failure_removes_all_created_entries():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    before = stack(registry, inspector, obj)
    calls = {"count": 0}

    def corrupt_once():
        calls["count"] += 1
        if calls["count"] == 1:
            modifier = obj.modifiers.get("Edge")
            if modifier is not None:
                modifier.width = 99

    bpy.context.view_layer.update = corrupt_once
    result = registry.dispatch(
        Request(
            "modifier.stack_compose",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "entries": [
                    {
                        "name": "Shell",
                        "kind": "SOLIDIFY",
                        "settings": {"thickness": 0.1},
                    },
                    {
                        "name": "Edge",
                        "kind": "BEVEL",
                        "settings": {"width": 0.02, "segments": 2},
                    },
                ],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert len(obj.modifiers) == 0


@pytest.mark.parametrize(
    "recipe,parameters,expected_types",
    [
        (
            "PANEL_SHELL",
            {"thickness": 0.08, "width": 0.02, "segments": 3},
            ["SOLIDIFY", "BEVEL"],
        ),
        (
            "SUBDIV_BEVEL",
            {"width": 0.02, "segments": 3, "levels": 1, "render_levels": 2},
            ["BEVEL", "SUBSURF"],
        ),
        (
            "HARD_SURFACE_TRIPLE",
            {
                "thickness": 0.08,
                "width": 0.02,
                "segments": 3,
                "levels": 1,
                "render_levels": 2,
            },
            ["SOLIDIFY", "BEVEL", "SUBSURF"],
        ),
    ],
)
def test_recipe_preview_is_deterministic(recipe, parameters, expected_types):
    bpy, inspector, hard_surface, workflows, registry = setup()
    result = registry.dispatch(
        Request(
            "modifier.recipe_preview",
            {
                "recipe": recipe,
                "prefix": "Hero",
                "parameters": parameters,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    data = result.data
    assert data["recipe"] == recipe
    assert data["entry_count"] == len(expected_types)
    assert [entry["kind"] for entry in data["entries"]] == expected_types
    assert all(entry["name"].startswith("Hero_") for entry in data["entries"])
    assert len(data["recipe_revision"]) == 64


def test_recipe_apply_builds_verified_preset_stack():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.recipe_apply",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "recipe": "HARD_SURFACE_TRIPLE",
                "prefix": "Body",
                "parameters": {
                    "thickness": 0.1,
                    "width": 0.03,
                    "segments": 4,
                    "levels": 1,
                    "render_levels": 2,
                },
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["recipe"] == "HARD_SURFACE_TRIPLE"
    assert after["recipe_prefix"] == "Body"
    assert after["recipe_modifier_names"] == [
        "Body_Solidify",
        "Body_Bevel",
        "Body_Subsurf",
    ]
    assert [item["type"] for item in after["items"]] == [
        "SOLIDIFY",
        "BEVEL",
        "SUBSURF",
    ]


def test_recipe_apply_collision_is_atomic():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    existing = obj.modifiers.new("Panel_Bevel", "BEVEL")
    existing.width = 0.5
    existing.segments = 2
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.recipe_apply",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "recipe": "PANEL_SHELL",
                "prefix": "Panel",
                "parameters": {"thickness": 0.1, "width": 0.02, "segments": 3},
            },
        )
    )
    assert result.error.code == ErrorCode.AMBIGUOUS_TARGET
    assert [modifier.name for modifier in obj.modifiers] == ["Panel_Bevel"]


def test_recipe_apply_respects_global_stack_limit():
    bpy, inspector, hard_surface, workflows, registry = setup()
    obj = bpy.data.objects.get("Cube")
    for index in range(15):
        modifier = obj.modifiers.new(f"Base{index}", "BEVEL")
        modifier.width = 0.01
        modifier.segments = 1
    before = stack(registry, inspector, obj)

    result = registry.dispatch(
        Request(
            "modifier.recipe_apply",
            {
                "target": target(inspector, obj),
                "expected_stack_revision": before["stack_revision"],
                "recipe": "PANEL_SHELL",
                "prefix": "Panel",
                "parameters": {"thickness": 0.1, "width": 0.02, "segments": 3},
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.modifiers) == 15


def test_milestone9_contract_validation():
    object_target = {
        "object_id": "id",
        "expected_name": "Cube",
        "expected_revision": "x" * 64,
    }
    with pytest.raises(AgentError):
        StackCompose.parse(
            {
                "target": object_target,
                "expected_stack_revision": "y" * 64,
                "entries": [],
            }
        )
    with pytest.raises(AgentError):
        StackCompose.parse(
            {
                "target": object_target,
                "expected_stack_revision": "y" * 64,
                "entries": [
                    {
                        "name": "A",
                        "kind": "BOOLEAN",
                        "settings": {"width": 1, "segments": 2},
                    }
                ],
            }
        )
    with pytest.raises(AgentError):
        RecipePreview.parse(
            {
                "recipe": "UNKNOWN",
                "prefix": "Test",
                "parameters": {},
            }
        )
    with pytest.raises(AgentError):
        RecipeApply.parse(
            {
                "target": object_target,
                "expected_stack_revision": "y" * 64,
                "recipe": "PANEL_SHELL",
                "prefix": "",
                "parameters": {"thickness": 0.1, "width": 0.02, "segments": 2},
            }
        )
