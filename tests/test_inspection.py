from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.models import ObjectTarget, PageQuery, Transform
from shuvi_blender_agent.tools import ToolRegistry


def test_scene_summary_and_typed_listing():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    summary = inspector.summary()
    assert summary["object_count"] == 2
    assert summary["blender_version"] == [4, 2, 0]
    assert summary["render"]["resolution_x"] == 1920
    registry = ToolRegistry(inspector.tools())
    result = registry.dispatch(Request("objects.list", {"limit": 1}))
    assert result.data["total"] == 2
    assert result.data["next_offset"] == 1
    first = result.data["items"][0]
    assert first["name"] == "Cube"
    assert (
        registry.dispatch(Request("object.inspect", {"object_id": first["object_id"]})).data
        == first
    )
    assert bpy.data.filepath == ""


def test_identity_survives_rename_but_not_removal_or_other_session():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    obj = bpy.context.scene.objects[0]
    uid = inspector.identity(obj)
    obj.name = "Renamed"
    assert inspector.resolve(uid) is obj
    with pytest.raises(AgentError):
        BpyInspector(bpy).resolve(uid)
    bpy.context.scene.objects.remove(obj)
    bpy.context.scene.objects.append(FakeObject("Renamed"))
    with pytest.raises(AgentError) as error:
        inspector.resolve(uid)
    assert error.value.code == ErrorCode.NOT_FOUND


def test_stale_page_and_target_protection():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    first_page = inspector.page(PageQuery(limit=1))
    snapshot = first_page["items"][0]
    target = ObjectTarget(snapshot["object_id"], snapshot["name"], snapshot["revision"])
    assert inspector.target(target)[0].name == "Cube"
    bpy.context.scene.objects[0].location[0] = 10
    with pytest.raises(AgentError) as error:
        inspector.page(PageQuery(offset=1, expected_revision=first_page["revision"]))
    assert error.value.code == ErrorCode.STALE_STATE
    with pytest.raises(AgentError):
        inspector.target(target)


def test_filters_and_details_are_bounded():
    bpy = fake_bpy()
    obj = bpy.context.scene.objects[0]
    obj.modifiers = [
        NS(name=f"Mod{i}", type="BEVEL", show_viewport=True, show_render=True) for i in range(80)
    ]
    inspector = BpyInspector(bpy)
    page = inspector.page(PageQuery(name_prefix="C", object_type="MESH"))
    assert page["total"] == 1
    assert len(page["items"][0]["modifiers"]) == 64
    assert page["items"][0]["details_truncated"]


@pytest.mark.parametrize(
    "payload", [{"limit": 101}, {"offset": -1}, {"limit": True}, {"code": "x"}, {"name_prefix": []}]
)
def test_invalid_queries(payload):
    with pytest.raises(AgentError):
        PageQuery.parse(payload)


def test_transform_contract_and_scene_work_limit():
    with pytest.raises(AgentError):
        Transform.parse(
            {"location": [0, 0, float("inf")], "rotation_euler": [0, 0, 0], "scale": [1, 1, 1]}
        )
    bpy = fake_bpy([FakeObject("obj")] * 10001)
    with pytest.raises(AgentError):
        BpyInspector(bpy).summary()


def test_collection_pages_are_sorted_bounded_and_revision_protected():
    bpy = fake_bpy()
    for name in ("Z", "A", "M"):
        bpy.data.collections.new(name)
    inspector = BpyInspector(bpy)
    first = inspector.collection_page(PageQuery(limit=2))
    assert [item["name"] for item in first["items"]] == ["A", "Collection"]
    assert first["total"] == 4
    second = inspector.collection_page(
        PageQuery(offset=2, limit=2, expected_revision=first["revision"])
    )
    assert second["next_offset"] is None
    with pytest.raises(AgentError):
        inspector.collection_page(PageQuery(offset=2))
    # Replacing a relationship with the same count still invalidates the revision.
    collection = bpy.data.collections.get("A")
    collection.children.append(bpy.data.collections.get("Z"))
    revision_before = inspector.summary()["revision"]
    collection.children[0] = bpy.data.collections.get("M")
    with pytest.raises(AgentError) as error:
        inspector.collection_page(PageQuery(expected_revision=revision_before))
    assert error.value.code == ErrorCode.STALE_STATE


def test_scene_and_nested_metadata_work_limits_before_traversal():
    bpy = fake_bpy()
    bpy.data.collections = [NS(name="Unused")] * 10_001
    with pytest.raises(AgentError) as error:
        BpyInspector(bpy).summary()
    assert error.value.code == ErrorCode.SAFETY_DENIED
    bpy = fake_bpy()
    bpy.data.collections[0].children = [None] * 100_001
    with pytest.raises(AgentError) as error:
        BpyInspector(bpy).summary()
    assert error.value.code == ErrorCode.SAFETY_DENIED


def test_oversized_scene_strings_and_page_bytes_are_denied(monkeypatch):
    bpy = fake_bpy()
    bpy.context.scene.objects[0].asset_data = NS(description="x" * 1001)
    with pytest.raises(AgentError) as error:
        BpyInspector(bpy).page(PageQuery())
    assert error.value.code == ErrorCode.SAFETY_DENIED
    bpy.context.scene.objects[0].asset_data = None
    monkeypatch.setattr("shuvi_blender_agent.inspection.MAX_PAGE_BYTES", 10)
    with pytest.raises(AgentError) as error:
        BpyInspector(bpy).page(PageQuery())
    assert error.value.code == ErrorCode.SAFETY_DENIED


def test_summary_does_not_retain_all_object_snapshots():
    inspector = BpyInspector(fake_bpy([FakeObject(f"Object{i}") for i in range(200)]))
    snapshot = inspector.snapshot
    alive = peak = 0

    class CountedSnapshot(dict):
        def __init__(self, data):
            nonlocal alive, peak
            super().__init__(data)
            alive += 1
            peak = max(peak, alive)

        def __del__(self):
            nonlocal alive
            alive -= 1

    inspector.snapshot = lambda obj: CountedSnapshot(snapshot(obj))
    assert inspector.summary()["object_count"] == 200
    assert peak <= 2


def test_animation_readback_has_a_total_point_budget():
    obj = FakeObject("Animated")
    curves = [
        NS(
            data_path="location",
            array_index=i,
            keyframe_points=[NS(co=[float(k), 0.0], interpolation="LINEAR") for k in range(256)],
        )
        for i in range(64)
    ]
    obj.animation_data = NS(action=NS(name="Action", fcurves=curves))
    data = BpyInspector(fake_bpy([obj])).snapshot(obj)["animation"]
    assert sum(len(channel["points"]) for channel in data["channels"]) == 1024
    assert data["details_truncated"]


def test_foreign_identity_does_not_allocate_scene_identities():
    inspector = BpyInspector(fake_bpy())
    with pytest.raises(AgentError):
        inspector.resolve("foreign:object")
    assert not inspector._identities


def test_truncated_target_cannot_authorize_mutation():
    obj = FakeObject("Detailed")
    obj.modifiers = [
        NS(name=f"M{i}", type="OTHER", show_viewport=True, show_render=True) for i in range(65)
    ]
    inspector = BpyInspector(fake_bpy([obj]))
    snapshot = inspector.snapshot(obj)
    with pytest.raises(AgentError) as error:
        inspector.target(ObjectTarget.from_snapshot(snapshot))
    assert error.value.code == ErrorCode.SAFETY_DENIED
