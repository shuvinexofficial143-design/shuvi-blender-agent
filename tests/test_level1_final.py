from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy
from test_operations import target

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.destructive import DeleteObject
from shuvi_blender_agent.files import OutputWorkspace
from shuvi_blender_agent.mode_ops import ModeChange
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry


def scene_revision(registry):
    return registry.dispatch(Request("scene.inspect")).data["revision"]


def first_snapshot(registry):
    return registry.dispatch(Request("objects.list")).data["items"][0]


def test_mode_set_mesh_edit_and_return_to_object():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    obj = bpy.data.objects.get("Cube")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    def mode_set(*, mode):
        bpy.context.mode = {
            "OBJECT": "OBJECT",
            "EDIT": "EDIT_MESH",
            "SCULPT": "SCULPT",
            "VERTEX_PAINT": "PAINT_VERTEX",
            "WEIGHT_PAINT": "PAINT_WEIGHT",
            "TEXTURE_PAINT": "PAINT_TEXTURE",
        }[mode]
        return {"FINISHED"}

    bpy.ops = NS(object=NS(mode_set=mode_set))
    active_id = registry.dispatch(Request("selection.inspect")).data["active_object_id"]
    before = registry.dispatch(Request("object.inspect", {"object_id": active_id})).data
    result = registry.dispatch(
        Request(
            "mode.set",
            {
                "target": target(before),
                "mode": "EDIT",
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["mode"] == "EDIT_MESH"

    edited = registry.dispatch(Request("object.inspect", {"object_id": before["object_id"]})).data
    result = registry.dispatch(
        Request(
            "mode.set",
            {
                "target": target(edited),
                "mode": "OBJECT",
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["mode"] == "OBJECT"


def test_mode_set_requires_active_selected_target_and_valid_type_mode():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    snap = first_snapshot(registry)
    bpy.ops = NS(object=NS(mode_set=lambda **kwargs: {"FINISHED"}))

    result = registry.dispatch(
        Request(
            "mode.set",
            {
                "target": target(snap),
                "mode": "SCULPT",
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED

    obj = bpy.data.objects.get("Cube")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    snap = registry.dispatch(Request("object.inspect", {"object_id": snap["object_id"]})).data
    payload = {
        "target": target(snap),
        "mode": "POSE",
        "expected_scene_revision": scene_revision(registry),
    }
    assert registry.dispatch(Request("mode.set", payload)).error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize("mode", ["", "EDIT_MESH", "RANDOM", 1])
def test_invalid_mode_contract(mode):
    with pytest.raises(AgentError):
        ModeChange.parse(
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                },
                "mode": mode,
                "expected_scene_revision": "x" * 64,
            }
        )


def test_object_delete_is_destructive_verified_and_policy_gated():
    bpy = fake_bpy()
    denied = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    snap = first_snapshot(denied)
    payload = {
        "target": target(snap),
        "expected_scene_revision": scene_revision(denied),
    }
    assert denied.dispatch(Request("object.delete", payload)).error.code == ErrorCode.SAFETY_DENIED

    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True, allow_destructive=True))
    snap = first_snapshot(registry)
    payload = {
        "target": target(snap),
        "expected_scene_revision": scene_revision(registry),
    }
    result = registry.dispatch(Request("object.delete", payload))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["present"] is False
    assert result.data["after"]["scene_member"] is False
    assert bpy.data.objects.get(snap["name"]) is None


def test_object_delete_rejects_parent_with_children():
    bpy = fake_bpy()
    bpy.data.objects.get("Sphere").parent = bpy.data.objects.get("Cube")
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True, allow_destructive=True))
    cube = next(
        item
        for item in registry.dispatch(Request("objects.list")).data["items"]
        if item["name"] == "Cube"
    )
    result = registry.dispatch(
        Request(
            "object.delete",
            {
                "target": target(cube),
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert bpy.data.objects.get("Cube") is not None


def test_delete_contract_requires_scene_revision():
    with pytest.raises(AgentError):
        DeleteObject.parse(
            {
                "target": {
                    "object_id": "id",
                    "expected_name": "Cube",
                    "expected_revision": "x" * 64,
                }
            }
        )


def test_open_checkpoint_is_confined_destructive_and_resets_session(tmp_path):
    bpy = fake_bpy()
    checkpoint = tmp_path / "safe.blend"
    checkpoint.write_bytes(b"BLENDER-v402" + b"payload")
    old_file = bpy.data.filepath
    calls = []

    def open_mainfile(**kwargs):
        calls.append(kwargs)
        bpy.data.filepath = kwargs["filepath"]
        bpy.context.mode = "OBJECT"
        return {"FINISHED"}

    bpy.ops = NS(wm=NS(open_mainfile=open_mainfile))
    registry = create_registry(
        bpy,
        SafetyPolicy(allow_mutations=True, allow_destructive=True),
        OutputWorkspace(tmp_path),
    )
    before = registry.dispatch(Request("scene.inspect")).data
    result = registry.dispatch(
        Request(
            "file.open_checkpoint",
            {
                "name": "safe.blend",
                "expected_scene_revision": before["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["file"] == str(checkpoint.resolve())
    assert result.data["after"]["previous_session_id"] == before["session_id"]
    assert result.data["after"]["session_id"] != before["session_id"]
    assert calls == [
        {
            "filepath": str(checkpoint.resolve()),
            "load_ui": False,
            "use_scripts": False,
        }
    ]
    assert old_file == ""


def test_open_checkpoint_requires_workspace_and_fresh_scene(tmp_path):
    bpy = fake_bpy()
    bpy.ops = NS(wm=NS(open_mainfile=lambda **kwargs: {"FINISHED"}))
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True, allow_destructive=True))
    result = registry.dispatch(
        Request(
            "file.open_checkpoint",
            {
                "name": "safe.blend",
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED

    checkpoint = tmp_path / "safe.blend"
    checkpoint.write_bytes(b"BLENDER-v402" + b"payload")
    calls = []
    bpy = fake_bpy()
    bpy.ops = NS(wm=NS(open_mainfile=lambda **kwargs: calls.append(kwargs) or {"FINISHED"}))
    registry = create_registry(
        bpy,
        SafetyPolicy(allow_mutations=True, allow_destructive=True),
        OutputWorkspace(tmp_path),
    )
    stale = scene_revision(registry)
    bpy.context.scene.name = "Changed"
    result = registry.dispatch(
        Request(
            "file.open_checkpoint",
            {"name": "safe.blend", "expected_scene_revision": stale},
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert not calls


def test_open_checkpoint_rejects_missing_or_invalid_file(tmp_path):
    bpy = fake_bpy()
    bpy.ops = NS(wm=NS(open_mainfile=lambda **kwargs: {"FINISHED"}))
    registry = create_registry(
        bpy,
        SafetyPolicy(allow_mutations=True, allow_destructive=True),
        OutputWorkspace(tmp_path),
    )
    payload = {
        "name": "missing.blend",
        "expected_scene_revision": scene_revision(registry),
    }
    result = registry.dispatch(Request("file.open_checkpoint", payload))
    assert result.error.code in (ErrorCode.EXECUTION_ERROR, ErrorCode.VERIFICATION_FAILED)
