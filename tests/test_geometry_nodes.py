import copy
from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeNode, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.geometry_nodes import (
    GeometryGroupCreate,
    GeometryLinkChange,
    GeometryNodeAdd,
    GeometryNodeOperations,
    GeometryNodeRemove,
    GeometryNodeSetInput,
    GeometryTreeInspect,
)
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry
from shuvi_blender_agent.tools import MAX_REGISTERED_TOOLS, ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    operations = GeometryNodeOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    return bpy, operations, registry


def create_group(registry, name="Procedural"):
    result = registry.dispatch(Request("geometry_nodes.group_create", {"group_name": name}))
    assert result.status == Status.VERIFIED
    return result.data["after"]


def inspect(registry, name="Procedural"):
    result = registry.dispatch(Request("geometry_nodes.tree_inspect", {"group_name": name}))
    assert result.status == Status.SUCCEEDED
    return result.data


def add_node(registry, node_type, node_name, group_name="Procedural", location=None):
    payload = {
        "group_name": group_name,
        "expected_group_revision": inspect(registry, group_name)["group_revision"],
        "node_type": node_type,
        "node_name": node_name,
    }
    if location is not None:
        payload["location"] = location
    return registry.dispatch(Request("geometry_nodes.node_add", payload))


def link_payload(
    registry,
    from_node_name,
    from_socket_identifier,
    to_node_name,
    to_socket_identifier,
    group_name="Procedural",
):
    return {
        "group_name": group_name,
        "expected_group_revision": inspect(registry, group_name)["group_revision"],
        "from_node_name": from_node_name,
        "from_socket_identifier": from_socket_identifier,
        "to_node_name": to_node_name,
        "to_socket_identifier": to_socket_identifier,
    }


def test_factory_stays_within_bounded_registry_cap():
    bpy = fake_bpy()
    registry = create_registry(bpy, SafetyPolicy(allow_mutations=True))
    assert len(registry.catalog()) == 188
    assert MAX_REGISTERED_TOOLS == 192
    assert len(registry.catalog()) < MAX_REGISTERED_TOOLS


def test_group_create_and_empty_tree_inspection_are_verified():
    bpy, operations, registry = setup()

    created = create_group(registry)
    assert created["group_name"] == "Procedural"
    assert created["tree_type"] == "GeometryNodeTree"
    assert created["node_count"] == 0
    assert created["link_count"] == 0
    assert created["interface"] == []
    assert len(created["group_revision"]) == 64

    result = inspect(registry)
    assert result == created


def test_group_create_rejects_duplicate_name_without_mutation():
    bpy, operations, registry = setup()
    before = create_group(registry)

    duplicate = registry.dispatch(
        Request("geometry_nodes.group_create", {"group_name": "Procedural"})
    )
    assert duplicate.status == Status.FAILED
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET
    assert inspect(registry)["group_revision"] == before["group_revision"]


def test_tree_inspect_reports_interface_sockets_and_nested_groups():
    bpy, operations, registry = setup()
    create_group(registry)
    group = bpy.data.node_groups.get("Procedural")
    group.interface.items_tree.extend(
        [
            NS(
                item_type="SOCKET",
                name="Geometry",
                identifier="Socket_0",
                in_out="INPUT",
                socket_type="NodeSocketGeometry",
            ),
            NS(
                item_type="SOCKET",
                name="Geometry",
                identifier="Socket_1",
                in_out="OUTPUT",
                socket_type="NodeSocketGeometry",
            ),
        ]
    )
    nested = bpy.data.node_groups.new("Nested", "GeometryNodeTree")
    node = FakeNode("GROUP", "Nested Group", "GeometryNodeGroup")
    node.node_tree = nested
    group.nodes.append(node)

    result = inspect(registry)
    assert result["interface"] == [
        {
            "name": "Geometry",
            "identifier": "Socket_0",
            "direction": "INPUT",
            "socket_type": "NodeSocketGeometry",
        },
        {
            "name": "Geometry",
            "identifier": "Socket_1",
            "direction": "OUTPUT",
            "socket_type": "NodeSocketGeometry",
        },
    ]
    assert result["nested_groups"] == ["Nested"]
    row = next(item for item in result["nodes"] if item["name"] == "Nested Group")
    assert row["managed_type"] is False
    assert row["nested_group"] == "Nested"


@pytest.mark.parametrize(
    "node_type",
    [
        "MESH_CUBE",
        "MESH_ICO_SPHERE",
        "JOIN_GEOMETRY",
        "TRANSFORM_GEOMETRY",
        "SET_POSITION",
        "INPUT_POSITION",
        "INPUT_NORMAL",
        "INPUT_INDEX",
        "REALIZE_INSTANCES",
        "INSTANCE_ON_POINTS",
    ],
)
def test_typed_node_allowlist_creates_each_supported_node(node_type):
    bpy, operations, registry = setup()
    create_group(registry)

    result = add_node(registry, node_type, f"Node_{node_type}")
    assert result.status == Status.VERIFIED
    row = result.data["node"]
    assert row["node_type"] == node_type
    assert row["managed_type"] is True
    assert row["bl_idname"]


def test_node_add_uses_deterministic_grid_and_accepts_bounded_override():
    bpy, operations, registry = setup()
    create_group(registry)

    first = add_node(registry, "MESH_CUBE", "Cube")
    assert first.data["node"]["location"] == [0.0, 0.0]

    second = add_node(registry, "INPUT_POSITION", "Position")
    assert second.data["node"]["location"] == [240.0, 0.0]

    third = add_node(
        registry,
        "TRANSFORM_GEOMETRY",
        "Transform",
        location=[120.0, -360.0],
    )
    assert third.data["node"]["location"] == [120.0, -360.0]


def test_node_add_rejects_stale_revision_and_name_collision():
    bpy, operations, registry = setup()
    create_group(registry)
    stale = inspect(registry)["group_revision"]
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED

    stale_result = registry.dispatch(
        Request(
            "geometry_nodes.node_add",
            {
                "group_name": "Procedural",
                "expected_group_revision": stale,
                "node_type": "INPUT_POSITION",
                "node_name": "Position",
            },
        )
    )
    assert stale_result.error.code == ErrorCode.STALE_STATE

    collision = add_node(registry, "INPUT_POSITION", "Cube")
    assert collision.error.code == ErrorCode.AMBIGUOUS_TARGET


def test_node_set_input_verifies_vector_and_integer_values():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED

    size = registry.dispatch(
        Request(
            "geometry_nodes.node_set_input",
            {
                "group_name": "Procedural",
                "expected_group_revision": inspect(registry)["group_revision"],
                "node_name": "Cube",
                "socket_name": "Size",
                "value": [2, 3, 4],
            },
        )
    )
    assert size.status == Status.VERIFIED

    vertices = registry.dispatch(
        Request(
            "geometry_nodes.node_set_input",
            {
                "group_name": "Procedural",
                "expected_group_revision": inspect(registry)["group_revision"],
                "node_name": "Cube",
                "socket_name": "Vertices X",
                "value": 8,
            },
        )
    )
    assert vertices.status == Status.VERIFIED
    row = next(item for item in vertices.data["after"]["nodes"] if item["name"] == "Cube")
    values = {item["name"]: item["default_value"] for item in row["inputs"]}
    assert values["Size"] == [2.0, 3.0, 4.0]
    assert values["Vertices X"] == 8


def test_node_set_input_rejects_unallowlisted_socket_and_bad_typed_value():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED

    unsupported = registry.dispatch(
        Request(
            "geometry_nodes.node_set_input",
            {
                "group_name": "Procedural",
                "expected_group_revision": inspect(registry)["group_revision"],
                "node_name": "Cube",
                "socket_name": "Mesh",
                "value": 1,
            },
        )
    )
    assert unsupported.error.code in (ErrorCode.NOT_FOUND, ErrorCode.SAFETY_DENIED)

    bad_range = registry.dispatch(
        Request(
            "geometry_nodes.node_set_input",
            {
                "group_name": "Procedural",
                "expected_group_revision": inspect(registry)["group_revision"],
                "node_name": "Cube",
                "socket_name": "Vertices X",
                "value": 1,
            },
        )
    )
    assert bad_range.error.code == ErrorCode.INVALID_REQUEST


def test_node_set_input_rejects_stale_revision():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    stale = inspect(registry)["group_revision"]
    assert add_node(registry, "INPUT_POSITION", "Position").status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.node_set_input",
            {
                "group_name": "Procedural",
                "expected_group_revision": stale,
                "node_name": "Cube",
                "socket_name": "Size",
                "value": [2, 2, 2],
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE


def test_node_remove_verifies_absence_and_preserves_other_nodes():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "INPUT_POSITION", "Position").status == Status.VERIFIED
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.node_remove",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "node_name": "Cube",
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["node_count"] == 1
    assert {item["name"] for item in after["nodes"]} == {"Position"}


def test_node_remove_supports_preexisting_link_with_typed_recovery_available():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED
    group = bpy.data.node_groups.get("Procedural")
    cube = group.nodes.get("Cube")
    transform = group.nodes.get("Transform")
    group.links.new(cube.outputs["Mesh"], transform.inputs["Geometry"])
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.node_remove",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "node_name": "Cube",
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["node_count"] == before["node_count"] - 1
    assert result.data["after"]["link_count"] == 0


def test_node_remove_verification_failure_recreates_original_node():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert (
        registry.dispatch(
            Request(
                "geometry_nodes.node_set_input",
                {
                    "group_name": "Procedural",
                    "expected_group_revision": inspect(registry)["group_revision"],
                    "node_name": "Cube",
                    "socket_name": "Size",
                    "value": [2, 3, 4],
                },
            )
        ).status
        == Status.VERIFIED
    )
    before = inspect(registry)
    original = operations._snapshot
    calls = {"count": 0}

    def corrupt_second(group):
        calls["count"] += 1
        snapshot = original(group)
        if calls["count"] == 2:
            snapshot = copy.deepcopy(snapshot)
            snapshot["node_count"] += 1
        return snapshot

    operations._snapshot = corrupt_second
    result = registry.dispatch(
        Request(
            "geometry_nodes.node_remove",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "node_name": "Cube",
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert (
        original(bpy.data.node_groups.get("Procedural"))["group_revision"]
        == before["group_revision"]
    )


def test_node_set_input_verification_failure_restores_previous_value():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    before = inspect(registry)
    original = operations._snapshot
    calls = {"count": 0}

    def corrupt_second(group):
        calls["count"] += 1
        snapshot = original(group)
        if calls["count"] == 2:
            snapshot = copy.deepcopy(snapshot)
            row = next(item for item in snapshot["nodes"] if item["name"] == "Cube")
            socket = next(item for item in row["inputs"] if item["name"] == "Size")
            socket["default_value"] = [999.0, 999.0, 999.0]
        return snapshot

    operations._snapshot = corrupt_second
    result = registry.dispatch(
        Request(
            "geometry_nodes.node_set_input",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "node_name": "Cube",
                "socket_name": "Size",
                "value": [2, 3, 4],
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert (
        original(bpy.data.node_groups.get("Procedural"))["group_revision"]
        == before["group_revision"]
    )


def test_link_add_and_remove_use_explicit_socket_identifiers():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED

    added = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
        )
    )
    assert added.status == Status.VERIFIED
    assert added.data["after"]["link_count"] == 1
    row = added.data["link"]
    assert row["from_node"] == "Cube"
    assert row["from_socket"] == "Mesh"
    assert row["from_socket_identifier"] == "Mesh"
    assert row["from_socket_type"] == "GEOMETRY"
    assert row["to_node"] == "Transform"
    assert row["to_socket_identifier"] == "Geometry"
    assert row["to_socket_type"] == "GEOMETRY"

    removed = registry.dispatch(
        Request(
            "geometry_nodes.link_remove",
            link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
        )
    )
    assert removed.status == Status.VERIFIED
    assert removed.data["after"]["link_count"] == 0


def test_link_add_rejects_incompatible_socket_types():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "INPUT_INDEX", "Index").status == Status.VERIFIED
    assert add_node(registry, "SET_POSITION", "Set Position").status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Index", "Index", "Set Position", "Offset"),
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["link_count"] == 0


def test_link_add_refuses_occupied_single_input_and_exact_duplicate():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "MESH_ICO_SPHERE", "Sphere").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED

    first = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
        )
    )
    assert first.status == Status.VERIFIED

    duplicate = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
        )
    )
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET

    occupied = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Sphere", "Mesh", "Transform", "Geometry"),
        )
    )
    assert occupied.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["link_count"] == 1


def test_link_add_allows_multiple_links_into_multi_input_socket():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "MESH_ICO_SPHERE", "Sphere").status == Status.VERIFIED
    assert add_node(registry, "JOIN_GEOMETRY", "Join").status == Status.VERIFIED

    first = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Cube", "Mesh", "Join", "Geometry"),
        )
    )
    second = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(registry, "Sphere", "Mesh", "Join", "Geometry"),
        )
    )
    assert first.status == Status.VERIFIED
    assert second.status == Status.VERIFIED
    assert inspect(registry)["link_count"] == 2


def test_link_add_rejects_dependency_cycle():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform A").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform B").status == Status.VERIFIED

    first = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(
                registry,
                "Transform A",
                "Geometry",
                "Transform B",
                "Geometry",
            ),
        )
    )
    assert first.status == Status.VERIFIED

    cycle = registry.dispatch(
        Request(
            "geometry_nodes.link_add",
            link_payload(
                registry,
                "Transform B",
                "Geometry",
                "Transform A",
                "Geometry",
            ),
        )
    )
    assert cycle.error.code == ErrorCode.SAFETY_DENIED
    assert inspect(registry)["link_count"] == 1


def test_link_mutations_reject_stale_revision():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED
    stale = inspect(registry)["group_revision"]
    assert add_node(registry, "INPUT_POSITION", "Position").status == Status.VERIFIED

    payload = {
        "group_name": "Procedural",
        "expected_group_revision": stale,
        "from_node_name": "Cube",
        "from_socket_identifier": "Mesh",
        "to_node_name": "Transform",
        "to_socket_identifier": "Geometry",
    }
    result = registry.dispatch(Request("geometry_nodes.link_add", payload))
    assert result.error.code == ErrorCode.STALE_STATE


def test_link_add_verification_failure_rolls_back_exactly():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED
    original = operations._snapshot
    calls = {"count": 0}

    def corrupt_second(group):
        calls["count"] += 1
        snapshot = original(group)
        if calls["count"] == 2:
            snapshot = copy.deepcopy(snapshot)
            snapshot["link_count"] += 1
        return snapshot

    before = inspect(registry)
    operations._snapshot = corrupt_second
    payload = {
        "group_name": "Procedural",
        "expected_group_revision": before["group_revision"],
        "from_node_name": "Cube",
        "from_socket_identifier": "Mesh",
        "to_node_name": "Transform",
        "to_socket_identifier": "Geometry",
    }
    result = registry.dispatch(Request("geometry_nodes.link_add", payload))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert original(bpy.data.node_groups.get("Procedural"))["link_count"] == 0
    assert (
        original(bpy.data.node_groups.get("Procedural"))["group_revision"]
        == before["group_revision"]
    )


def test_link_remove_verification_failure_restores_link():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED
    assert (
        registry.dispatch(
            Request(
                "geometry_nodes.link_add",
                link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
            )
        ).status
        == Status.VERIFIED
    )
    before = inspect(registry)
    original = operations._snapshot
    calls = {"count": 0}

    def corrupt_second(group):
        calls["count"] += 1
        snapshot = original(group)
        if calls["count"] == 2:
            snapshot = copy.deepcopy(snapshot)
            snapshot["link_count"] += 1
        return snapshot

    operations._snapshot = corrupt_second
    payload = {
        "group_name": "Procedural",
        "expected_group_revision": before["group_revision"],
        "from_node_name": "Cube",
        "from_socket_identifier": "Mesh",
        "to_node_name": "Transform",
        "to_socket_identifier": "Geometry",
    }
    result = registry.dispatch(Request("geometry_nodes.link_remove", payload))
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = original(bpy.data.node_groups.get("Procedural"))
    assert restored["link_count"] == 1
    assert restored["group_revision"] == before["group_revision"]


def test_linked_node_remove_now_captures_and_removes_incident_links():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED
    assert (
        registry.dispatch(
            Request(
                "geometry_nodes.link_add",
                link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
            )
        ).status
        == Status.VERIFIED
    )
    before = inspect(registry)

    result = registry.dispatch(
        Request(
            "geometry_nodes.node_remove",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "node_name": "Cube",
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["node_count"] == 1
    assert result.data["after"]["link_count"] == 0


def test_linked_node_remove_failure_restores_node_and_links():
    bpy, operations, registry = setup()
    create_group(registry)
    assert add_node(registry, "MESH_CUBE", "Cube").status == Status.VERIFIED
    assert add_node(registry, "TRANSFORM_GEOMETRY", "Transform").status == Status.VERIFIED
    assert (
        registry.dispatch(
            Request(
                "geometry_nodes.link_add",
                link_payload(registry, "Cube", "Mesh", "Transform", "Geometry"),
            )
        ).status
        == Status.VERIFIED
    )
    before = inspect(registry)
    original = operations._snapshot
    calls = {"count": 0}

    def corrupt_second(group):
        calls["count"] += 1
        snapshot = original(group)
        if calls["count"] == 2:
            snapshot = copy.deepcopy(snapshot)
            snapshot["node_count"] += 1
        return snapshot

    operations._snapshot = corrupt_second
    result = registry.dispatch(
        Request(
            "geometry_nodes.node_remove",
            {
                "group_name": "Procedural",
                "expected_group_revision": before["group_revision"],
                "node_name": "Cube",
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = original(bpy.data.node_groups.get("Procedural"))
    assert restored["node_count"] == before["node_count"]
    assert restored["link_count"] == before["link_count"]
    assert restored["group_revision"] == before["group_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (GeometryTreeInspect.parse, {"group_name": ""}),
        (GeometryGroupCreate.parse, {"group_name": ""}),
        (
            GeometryNodeAdd.parse,
            {
                "group_name": "Group",
                "expected_group_revision": "x" * 64,
                "node_type": "UNSAFE_SCRIPT_NODE",
                "node_name": "Node",
            },
        ),
        (
            GeometryNodeAdd.parse,
            {
                "group_name": "Group",
                "expected_group_revision": "x" * 64,
                "node_type": "MESH_CUBE",
                "node_name": "Node",
                "location": [0],
            },
        ),
        (
            GeometryNodeRemove.parse,
            {
                "group_name": "Group",
                "expected_group_revision": "x" * 64,
                "node_name": "",
            },
        ),
        (
            GeometryNodeSetInput.parse,
            {
                "group_name": "Group",
                "expected_group_revision": "x" * 64,
                "node_name": "Node",
                "socket_name": "Size",
                "value": [1, 2],
            },
        ),
        (
            GeometryLinkChange.parse,
            {
                "group_name": "Group",
                "expected_group_revision": "x" * 64,
                "from_node_name": "Source",
                "from_socket_identifier": "",
                "to_node_name": "Target",
                "to_socket_identifier": "Geometry",
            },
        ),
    ],
)
def test_geometry_node_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
