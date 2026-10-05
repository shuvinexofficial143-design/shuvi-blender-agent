import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.assets import AddModifier, AssetOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(
        AssetOperations(ObjectOperations(inspector)).tools(), SafetyPolicy(allow_mutations=True)
    )
    snap = inspector.snapshot(bpy.context.scene.objects[0])
    target = {
        "object_id": snap["object_id"],
        "expected_name": snap["name"],
        "expected_revision": snap["revision"],
    }
    return bpy, inspector, registry, target


@pytest.mark.parametrize(
    "kind,settings",
    [
        ("BEVEL", {"width": 0.1, "segments": 2}),
        ("SUBSURF", {"levels": 1, "render_levels": 2}),
        ("SOLIDIFY", {"thickness": 0.2}),
    ],
)
def test_verified_modifier(kind, settings):
    bpy, _, registry, target = setup()
    result = registry.dispatch(
        Request(
            "modifier.add", {"target": target, "name": "Mod", "kind": kind, "settings": settings}
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["added_modifier"]["settings"] == settings
    assert bpy.context.scene.objects[0].modifiers.get("Mod") is not None


def test_modifier_bounds_and_readback_failure():
    bpy, _, registry, target = setup()
    bad = {
        "target": target,
        "name": "Mod",
        "kind": "SUBSURF",
        "settings": {"levels": 6, "render_levels": 6},
    }
    with pytest.raises(AgentError):
        AddModifier.parse(bad)
    bpy.context.view_layer.update = lambda: setattr(
        bpy.context.scene.objects[0].modifiers[0], "width", 0
    )
    result = registry.dispatch(
        Request(
            "modifier.add",
            {
                "target": target,
                "name": "Mod",
                "kind": "BEVEL",
                "settings": {"width": 0.1, "segments": 2},
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert not bpy.context.scene.objects[0].modifiers


def test_additive_collection_keeps_existing_membership():
    bpy, inspector, registry, target = setup()
    result = registry.dispatch(
        Request(
            "collection.create",
            {
                "name": "Assets",
                "target": target,
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    obj = bpy.context.scene.objects[0]
    assert {item.name for item in obj.users_collection} == {"Collection", "Assets"}
    assert bpy.context.scene.collection.children.get("Assets") is not None
    assert bpy.data.collections.get("Assets").objects.get(obj.name) is obj


def test_empty_collection_and_collision():
    _, inspector, registry, _ = setup()
    payload = {
        "name": "Assets",
        "target": None,
        "expected_scene_revision": inspector.summary()["revision"],
    }
    assert registry.dispatch(Request("collection.create", payload)).status == Status.VERIFIED
    payload["expected_scene_revision"] = inspector.summary()["revision"]
    assert (
        registry.dispatch(Request("collection.create", payload)).error.code
        == ErrorCode.AMBIGUOUS_TARGET
    )


def test_asset_mark_readback_and_no_replacement():
    bpy, inspector, registry, target = setup()
    result = registry.dispatch(
        Request("asset.mark", {"target": target, "description": "Reusable cube"})
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["asset"] == {"marked": True, "description": "Reusable cube"}
    fresh = inspector.snapshot(bpy.context.scene.objects[0])
    target["expected_revision"] = fresh["revision"]
    assert (
        registry.dispatch(
            Request("asset.mark", {"target": target, "description": "other"})
        ).error.code
        == ErrorCode.AMBIGUOUS_TARGET
    )


def test_existing_modifier_stack_is_denied_before_adding():
    bpy, inspector, registry, target = setup()
    obj = bpy.context.scene.objects[0]
    obj.modifiers.new("Existing", "SUBSURF")
    target["expected_revision"] = inspector.snapshot(obj)["revision"]
    result = registry.dispatch(
        Request(
            "modifier.add",
            {
                "target": target,
                "name": "Next",
                "kind": "SUBSURF",
                "settings": {"levels": 2, "render_levels": 2},
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert len(obj.modifiers) == 1


def test_large_mesh_modifier_is_denied_before_evaluation():
    bpy, _, registry, target = setup()
    obj = bpy.context.scene.objects[0]
    obj.data.vertices = [None] * 4097
    result = registry.dispatch(
        Request(
            "modifier.add",
            {
                "target": target,
                "name": "Next",
                "kind": "BEVEL",
                "settings": {"width": 1, "segments": 8},
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert not obj.modifiers


def test_collection_creation_does_not_exceed_object_relationship_bounds():
    bpy, inspector, registry, target = setup()
    obj = bpy.context.scene.objects[0]
    for i in range(63):
        obj.users_collection.append(bpy.data.collections.new(f"Group{i}"))
    target["expected_revision"] = inspector.snapshot(obj)["revision"]
    result = registry.dispatch(
        Request(
            "collection.create",
            {
                "name": "Next",
                "target": target,
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert bpy.data.collections.get("Next") is None
