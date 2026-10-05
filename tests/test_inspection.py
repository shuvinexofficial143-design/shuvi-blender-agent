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
