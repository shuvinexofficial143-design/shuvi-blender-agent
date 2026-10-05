import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.verification import compare


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(ObjectOperations(inspector).tools(), SafetyPolicy(allow_mutations=True))
    return bpy, inspector, registry


def test_primitive_geometry_mismatch_is_cleaned_up():
    bpy, inspector, registry = setup()
    scene_revision = inspector.summary()["revision"]

    def corrupt():
        bpy.data.objects.get("New").data.vertices[0].co = [99, 99, 99]

    bpy.context.view_layer.update = corrupt
    result = registry.dispatch(
        Request(
            "object.create",
            {
                "name": "New",
                "kind": "CUBE",
                "transform": transform(),
                "expected_scene_revision": scene_revision,
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"]
    assert bpy.data.objects.get("New") is None
    assert len(bpy.data.meshes) == 2


def test_duplicate_geometry_mismatch_is_cleaned_up():
    bpy, inspector, registry = setup()
    original = bpy.context.scene.objects[0]
    original.data.from_pydata([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [], [[0, 1, 2]])
    before = inspector.snapshot(original)

    def corrupt():
        bpy.data.objects.get("Copy").data.vertices[0].co = [9, 9, 9]

    bpy.context.view_layer.update = corrupt
    result = registry.dispatch(
        Request(
            "object.duplicate",
            {
                "target": target(before),
                "name": "Copy",
                "transform": transform(),
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert bpy.data.objects.get("Copy") is None
    assert original.data.vertices[0].co == [0, 0, 0]


def test_oversized_mesh_duplicate_is_denied_before_copy():
    bpy, inspector, registry = setup()
    original = bpy.context.scene.objects[0]
    original.data.vertices = [None] * 4097
    result = registry.dispatch(
        Request(
            "object.duplicate",
            {
                "target": target(inspector.snapshot(original)),
                "name": "Copy",
                "transform": transform(),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert bpy.data.objects.get("Copy") is None


def transform():
    return {"location": [1.5, -2, 3], "rotation_euler": [0.1, 0.2, 0.3], "scale": [1, 2, -1]}


def target(snapshot):
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def test_transform_exact_readback_and_no_stale_retry():
    bpy, inspector, registry = setup()
    before = inspector.snapshot(bpy.context.scene.objects[0])
    req = Request("object.set_transform", {"target": target(before), "transform": transform()})
    result = registry.dispatch(req)
    assert result.status == Status.VERIFIED
    assert result.verification["matched"]
    assert result.data["before"] == before
    assert result.data["after"]["transform"]["location"] == [1.5, -2, 3]
    assert registry.dispatch(req).error.code == ErrorCode.STALE_STATE


@pytest.mark.parametrize("kind,vertices,faces", [("CUBE", 8, 6), ("PLANE", 4, 1), ("EMPTY", 0, 0)])
def test_create_direct_data_geometry_and_readback(kind, vertices, faces):
    bpy, inspector, registry = setup()
    result = registry.dispatch(
        Request(
            "object.create",
            {
                "name": "New",
                "kind": kind,
                "transform": transform(),
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["name"] == "New"
    obj = bpy.data.objects.get("New")
    assert obj in bpy.context.scene.objects
    if vertices:
        assert len(obj.data.vertices) == vertices
        assert len(obj.data.faces) == faces
    else:
        assert obj.data is None


def test_name_collision_and_stale_scene_never_create():
    bpy, inspector, registry = setup()
    payload = {
        "name": "Cube",
        "kind": "CUBE",
        "transform": transform(),
        "expected_scene_revision": inspector.summary()["revision"],
    }
    assert (
        registry.dispatch(Request("object.create", payload)).error.code
        == ErrorCode.AMBIGUOUS_TARGET
    )
    payload["name"] = "New"
    bpy.context.scene.objects[0].location[0] = 999
    assert registry.dispatch(Request("object.create", payload)).error.code == ErrorCode.STALE_STATE
    assert bpy.data.objects.get("New") is None


def test_default_policy_denies_mutation():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(ObjectOperations(inspector).tools())
    before = inspector.snapshot(bpy.context.scene.objects[0])
    result = registry.dispatch(
        Request("object.set_transform", {"target": target(before), "transform": transform()})
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert bpy.context.scene.objects[0].location == [0, 0, 0]


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("library", object()),
        ("constraints", [object()]),
        ("animation_data", object()),
        ("is_editable", False),
    ],
)
def test_unsafe_transform_targets_denied(attribute, value):
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    before = inspector.snapshot(obj)
    if attribute == "animation_data":
        # A real animation_data has an action field; include that in the readback fingerprint.
        from types import SimpleNamespace

        value = SimpleNamespace(action=None)
    setattr(obj, attribute, value)
    before = inspector.snapshot(obj)
    result = registry.dispatch(
        Request("object.set_transform", {"target": target(before), "transform": transform()})
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED


def test_mismatched_mutation_readback_is_failure():
    bpy, inspector, registry = setup()
    obj = bpy.context.scene.objects[0]
    before = inspector.snapshot(obj)
    bpy.context.view_layer.update = lambda: setattr(obj, "location", [0, 0, 0])
    result = registry.dispatch(
        Request("object.set_transform", {"target": target(before), "transform": transform()})
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert not result.verification["matched"]
    assert "$.transform.location[0]" in result.verification["differences"]


def test_create_verification_failure_removes_only_created_data():
    bpy, inspector, registry = setup()

    def interfere():
        bpy.data.objects.get("New").location = [0, 0, 0]

    bpy.context.view_layer.update = interfere
    original_mesh_count = len(bpy.data.meshes)
    result = registry.dispatch(
        Request(
            "object.create",
            {
                "name": "New",
                "kind": "CUBE",
                "transform": transform(),
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"]
    assert bpy.data.objects.get("New") is None
    assert len(bpy.data.meshes) == original_mesh_count
    assert bpy.data.objects.get("Cube") is not None


def test_duplicate_has_distinct_identity_and_mesh():
    bpy, inspector, registry = setup()
    original = bpy.context.scene.objects[0]
    snapshot = inspector.snapshot(original)
    result = registry.dispatch(
        Request(
            "object.duplicate",
            {
                "target": target(snapshot),
                "name": "Duplicate",
                "transform": transform(),
            },
        )
    )
    assert result.status == Status.VERIFIED
    duplicate = bpy.data.objects.get("Duplicate")
    assert duplicate.data is not original.data
    assert result.data["after"]["object_id"] != snapshot["object_id"]
    assert list(original.location) == [0, 0, 0]


def test_verification_accounts_for_floats_but_rejects_wrong_types():
    assert compare({"value": [0.1]}, {"value": [0.10000000149]}).matched
    assert not compare({"value": 1}, {"value": True}).matched
    assert not compare({"value": [1, 2]}, {"value": [1]}).matched
    assert not compare({"value": 1}, {"value": 2}).matched


def test_linked_duplicate_shares_mesh_but_not_object_identity():
    bpy, inspector, registry = setup()
    original = bpy.context.scene.objects[0]
    snapshot = inspector.snapshot(original)
    result = registry.dispatch(
        Request(
            "object.duplicate_linked",
            {
                "target": target(snapshot),
                "name": "LinkedCopy",
                "transform": transform(),
            },
        )
    )
    assert result.status == Status.VERIFIED
    duplicate = bpy.data.objects.get("LinkedCopy")
    assert duplicate is not original
    assert duplicate.data is original.data
    assert result.data["after"]["mesh_shared"] is True
    assert result.data["after"]["object_id"] != snapshot["object_id"]


def test_linked_duplicate_rejects_non_mesh_and_modifier_stack():
    bpy, inspector, registry = setup()
    empty = bpy.data.objects.new("Empty", None)
    bpy.context.scene.collection.objects.link(empty)
    empty_snapshot = inspector.snapshot(empty)
    result = registry.dispatch(
        Request(
            "object.duplicate_linked",
            {
                "target": target(empty_snapshot),
                "name": "BadLinked",
                "transform": transform(),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED

    mesh = bpy.data.objects.get("Cube")
    mesh.modifiers.new("Existing", "SUBSURF")
    mesh_snapshot = inspector.snapshot(mesh)
    result = registry.dispatch(
        Request(
            "object.duplicate_linked",
            {
                "target": target(mesh_snapshot),
                "name": "BadMeshLinked",
                "transform": transform(),
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
