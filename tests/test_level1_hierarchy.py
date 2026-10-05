from fake_bpy import fake_bpy
from test_operations import target

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry


def setup():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    return bpy, registry


def scene_revision(registry):
    return registry.dispatch(Request("scene.inspect")).data["revision"]


def snapshots(registry):
    page = registry.dispatch(Request("objects.list")).data["items"]
    return {item["name"]: item for item in page}


def create_collection(registry, name):
    result = registry.dispatch(
        Request(
            "collection.create",
            {
                "name": name,
                "target": None,
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED


def test_parent_unparent_keep_world_and_cycle_rejection():
    bpy, registry = setup()
    items = snapshots(registry)
    world = [row[:] for row in bpy.data.objects.get("Cube").matrix_world]
    result = registry.dispatch(
        Request(
            "hierarchy.set_parent",
            {
                "child": target(items["Cube"]),
                "parent": target(items["Sphere"]),
                "keep_world": True,
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["parent_id"] == items["Sphere"]["object_id"]
    assert result.data["after"]["matrix_world"] == world

    parent_state = registry.dispatch(
        Request("hierarchy.inspect", {"object_id": items["Sphere"]["object_id"]})
    )
    assert parent_state.status == Status.SUCCEEDED
    assert items["Cube"]["object_id"] in parent_state.data["child_ids"]

    fresh = snapshots(registry)
    cycle = registry.dispatch(
        Request(
            "hierarchy.set_parent",
            {
                "child": target(fresh["Sphere"]),
                "parent": target(fresh["Cube"]),
                "keep_world": True,
            },
        )
    )
    assert cycle.error.code == ErrorCode.SAFETY_DENIED

    fresh = snapshots(registry)
    result = registry.dispatch(
        Request(
            "hierarchy.set_parent",
            {"child": target(fresh["Cube"]), "parent": None, "keep_world": True},
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["parent_id"] is None


def test_collection_move_preserves_scene_membership_and_orphan_guard():
    bpy, registry = setup()
    create_collection(registry, "Assets")
    item = snapshots(registry)["Cube"]
    result = registry.dispatch(
        Request(
            "collection.move_object",
            {
                "source": "Collection",
                "destination": "Assets",
                "target": target(item),
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    obj = bpy.data.objects.get("Cube")
    assert [collection.name for collection in obj.users_collection] == ["Assets"]

    item = snapshots(registry)["Cube"]
    denied = registry.dispatch(
        Request(
            "collection.unlink_object",
            {
                "collection": "Assets",
                "target": target(item),
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert [collection.name for collection in obj.users_collection] == ["Assets"]


def test_collection_link_unlink_readback():
    bpy, registry = setup()
    create_collection(registry, "Extra")
    item = snapshots(registry)["Cube"]
    result = registry.dispatch(
        Request(
            "collection.link_object",
            {
                "collection": "Extra",
                "target": target(item),
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["collection_count"] == 2

    item = snapshots(registry)["Cube"]
    result = registry.dispatch(
        Request(
            "collection.unlink_object",
            {
                "collection": "Extra",
                "target": target(item),
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["collection_count"] == 1
    assert bpy.data.collections.get("Extra") not in bpy.data.objects.get("Cube").users_collection


def test_child_collection_inspection_and_rename():
    _, registry = setup()
    create_collection(registry, "Parent")
    result = registry.dispatch(
        Request(
            "collection.create_child",
            {
                "name": "Child",
                "parent": "Parent",
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED

    inspected = registry.dispatch(Request("collection.inspect", {"name": "Child"}))
    assert inspected.status == Status.SUCCEEDED
    assert inspected.data["parent_names"] == ["Parent"]

    result = registry.dispatch(
        Request(
            "collection.rename",
            {
                "name": "Child",
                "new_name": "Child2",
                "expected_scene_revision": scene_revision(registry),
            },
        )
    )
    assert result.status == Status.VERIFIED
    inspected = registry.dispatch(Request("collection.inspect", {"name": "Child2"}))
    assert inspected.status == Status.SUCCEEDED


def test_collection_mutations_reject_stale_scene_revision():
    _, registry = setup()
    create_collection(registry, "Extra")
    item = snapshots(registry)["Cube"]
    stale_revision = scene_revision(registry)
    registry.dispatch(
        Request(
            "object.rename",
            {"target": target(item), "name": "CubeRenamed"},
        )
    )
    fresh = snapshots(registry)["CubeRenamed"]
    result = registry.dispatch(
        Request(
            "collection.link_object",
            {
                "collection": "Extra",
                "target": target(fresh),
                "expected_scene_revision": stale_revision,
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE


def test_origin_inspection_reports_local_and_world_locations():
    bpy, registry = setup()
    obj = bpy.data.objects.get("Cube")
    obj.location = [1.0, 2.0, 3.0]
    obj.matrix_world[0][3] = 4.0
    obj.matrix_world[1][3] = 5.0
    obj.matrix_world[2][3] = 6.0
    item = snapshots(registry)["Cube"]
    result = registry.dispatch(Request("origin.inspect", {"object_id": item["object_id"]}))
    assert result.status == Status.SUCCEEDED
    assert result.data["local_location"] == [1.0, 2.0, 3.0]
    assert result.data["world_location"] == [4.0, 5.0, 6.0]
