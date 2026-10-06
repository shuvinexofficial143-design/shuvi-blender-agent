"""Level 5 milestones 1-2: bounded Geometry Nodes inspection and typed node creation."""

import copy
from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

MAX_GEOMETRY_NODES = 64
MAX_GEOMETRY_LINKS = 128
MAX_INTERFACE_SOCKETS = 64
MAX_NODE_INPUTS = 32
MAX_NODE_OUTPUTS = 32
MAX_NESTED_GROUPS = 32
MAX_LOCATION = 10_000.0

NODE_TYPES = {
    "MESH_CUBE": "GeometryNodeMeshCube",
    "MESH_ICO_SPHERE": "GeometryNodeMeshIcoSphere",
    "JOIN_GEOMETRY": "GeometryNodeJoinGeometry",
    "TRANSFORM_GEOMETRY": "GeometryNodeTransform",
    "SET_POSITION": "GeometryNodeSetPosition",
    "INPUT_POSITION": "GeometryNodeInputPosition",
    "INPUT_NORMAL": "GeometryNodeInputNormal",
    "INPUT_INDEX": "GeometryNodeInputIndex",
    "REALIZE_INSTANCES": "GeometryNodeRealizeInstances",
    "INSTANCE_ON_POINTS": "GeometryNodeInstanceOnPoints",
}
NODE_TYPES_BY_ID = {value: key for key, value in NODE_TYPES.items()}

INPUT_RULES = {
    "MESH_CUBE": {
        "Size": ("VECTOR", 0.0, 10_000.0),
        "Vertices X": ("INT", 2, 256),
        "Vertices Y": ("INT", 2, 256),
        "Vertices Z": ("INT", 2, 256),
    },
    "MESH_ICO_SPHERE": {
        "Radius": ("FLOAT", 0.0, 10_000.0),
        "Subdivisions": ("INT", 1, 5),
    },
    "TRANSFORM_GEOMETRY": {
        "Translation": ("VECTOR", -10_000.0, 10_000.0),
        "Rotation": ("VECTOR", -1_000.0, 1_000.0),
        "Scale": ("VECTOR", -1_000.0, 1_000.0),
    },
    "SET_POSITION": {
        "Selection": ("BOOL", None, None),
        "Position": ("VECTOR", -10_000.0, 10_000.0),
        "Offset": ("VECTOR", -10_000.0, 10_000.0),
    },
    "INSTANCE_ON_POINTS": {
        "Selection": ("BOOL", None, None),
        "Pick Instance": ("BOOL", None, None),
        "Instance Index": ("INT", 0, 1_000_000),
        "Rotation": ("VECTOR", -1_000.0, 1_000.0),
        "Scale": ("VECTOR", -1_000.0, 1_000.0),
    },
}


def _node_type(value):
    value = string(value, "node_type", limit=40)
    if value not in NODE_TYPES:
        raise invalid("Unsupported Geometry Nodes node type")
    return value


def _location(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise invalid("location requires two numeric components")
    return tuple(number(item, "location", -MAX_LOCATION, MAX_LOCATION) for item in value)


def _raw_socket_value(value):
    if type(value) is bool:
        return value
    if type(value) is int:
        if value.bit_length() > 53:
            raise invalid("socket integer exceeds exact JSON range")
        return value
    if type(value) is float:
        return number(value, "socket value", -1_000_000_000.0, 1_000_000_000.0)
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return [number(item, "socket vector", -1_000_000_000.0, 1_000_000_000.0) for item in value]
    raise invalid("socket value must be boolean, bounded number, integer or three-number vector")


def _validated_input_value(node_type, socket_name, value):
    rule = INPUT_RULES.get(node_type, {}).get(socket_name)
    if rule is None:
        raise AgentError(
            ErrorCode.SAFETY_DENIED,
            "Socket is not allowlisted for typed default-value editing",
        )
    kind, low, high = rule
    if kind == "BOOL":
        if type(value) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Socket value must be boolean")
        return value
    if kind == "INT":
        try:
            return integer(value, "socket value", low, high)
        except AgentError:
            raise
    if kind == "FLOAT":
        return number(value, "socket value", low, high)
    if kind == "VECTOR":
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise AgentError(
                ErrorCode.INVALID_REQUEST,
                "Socket vector requires exactly three numeric components",
            )
        return [number(item, "socket vector", low, high) for item in value]
    raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported socket rule")


@dataclass(frozen=True)
class GeometryTreeInspect:
    group_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"group_name"})
        return cls(object_name(data["group_name"]))


@dataclass(frozen=True)
class GeometryGroupCreate:
    group_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"group_name"})
        return cls(object_name(data["group_name"]))


@dataclass(frozen=True)
class GeometryNodeAdd:
    group_name: str
    expected_group_revision: str
    node_type: str
    node_name: str
    location: tuple | None

    @classmethod
    def parse(cls, data):
        values = fields(
            data,
            {"group_name", "expected_group_revision", "node_type", "node_name"},
            {"location"},
        )
        return cls(
            object_name(values["group_name"]),
            string(values["expected_group_revision"], "expected_group_revision", limit=64),
            _node_type(values["node_type"]),
            object_name(values["node_name"]),
            _location(values["location"]) if "location" in values else None,
        )


@dataclass(frozen=True)
class GeometryNodeRemove:
    group_name: str
    expected_group_revision: str
    node_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"group_name", "expected_group_revision", "node_name"})
        return cls(
            object_name(data["group_name"]),
            string(data["expected_group_revision"], "expected_group_revision", limit=64),
            object_name(data["node_name"]),
        )


@dataclass(frozen=True)
class GeometryNodeSetInput:
    group_name: str
    expected_group_revision: str
    node_name: str
    socket_name: str
    value: object

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "group_name",
                "expected_group_revision",
                "node_name",
                "socket_name",
                "value",
            },
        )
        return cls(
            object_name(data["group_name"]),
            string(data["expected_group_revision"], "expected_group_revision", limit=64),
            object_name(data["node_name"]),
            string(data["socket_name"], "socket_name", limit=63),
            _raw_socket_value(data["value"]),
        )


class GeometryNodeOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.bpy = objects.bpy

    def _group(self, name):
        table = getattr(self.bpy.data, "node_groups", None)
        if table is None:
            raise AgentError(
                ErrorCode.UNSUPPORTED_OPERATION,
                "Geometry Nodes datablocks are unavailable",
            )
        group = table.get(name)
        if group is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Geometry Nodes group not found")
        if getattr(group, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local Geometry Nodes group required")
        if str(getattr(group, "bl_idname", "")) != "GeometryNodeTree":
            raise AgentError(ErrorCode.SAFETY_DENIED, "GeometryNodeTree group required")
        if len(group.nodes) > MAX_GEOMETRY_NODES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Geometry node work limit exceeded")
        if len(group.links) > MAX_GEOMETRY_LINKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Geometry link work limit exceeded")
        return group

    @staticmethod
    def _socket_value(socket):
        if not hasattr(socket, "default_value"):
            return None
        value = socket.default_value
        if value is None or type(value) in (bool, str):
            return value
        if type(value) is int:
            return value if value.bit_length() <= 53 else None
        if type(value) is float:
            return float(value)
        try:
            items = list(value)
        except (TypeError, ValueError):
            return None
        if not 1 <= len(items) <= 4:
            return None
        if not all(type(item) in (int, float, bool) for item in items):
            return None
        return [float(item) if type(item) is not bool else item for item in items]

    @staticmethod
    def _node_idname(node):
        return str(getattr(node, "bl_idname", ""))

    @classmethod
    def _node_alias(cls, node):
        return NODE_TYPES_BY_ID.get(cls._node_idname(node))

    @staticmethod
    def _socket_linked(group, socket):
        return any(
            link.from_socket is socket or link.to_socket is socket
            for link in group.links
        )

    def _socket_rows(self, group, node, table, direction):
        sockets = list(table)
        limit = MAX_NODE_INPUTS if direction == "INPUT" else MAX_NODE_OUTPUTS
        if len(sockets) > limit:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Node socket work limit exceeded")
        return [
            {
                "name": str(socket.name),
                "identifier": str(getattr(socket, "identifier", socket.name)),
                "socket_type": str(getattr(socket, "type", "UNKNOWN")),
                "direction": direction,
                "linked": self._socket_linked(group, socket),
                "multi_input": bool(getattr(socket, "is_multi_input", False)),
                "default_value": self._socket_value(socket),
            }
            for socket in sockets
        ]

    def _interface_rows(self, group):
        interface = getattr(group, "interface", None)
        items = list(getattr(interface, "items_tree", ())) if interface is not None else []
        sockets = [item for item in items if str(getattr(item, "item_type", "SOCKET")) == "SOCKET"]
        if len(sockets) > MAX_INTERFACE_SOCKETS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Node interface work limit exceeded")
        return [
            {
                "name": str(getattr(item, "name", "")),
                "identifier": str(getattr(item, "identifier", getattr(item, "name", ""))),
                "direction": str(getattr(item, "in_out", "UNKNOWN")),
                "socket_type": str(getattr(item, "socket_type", "UNKNOWN")),
            }
            for item in sockets
        ]

    def _node_row(self, group, node):
        location = list(getattr(node, "location", (0.0, 0.0)))
        if len(location) != 2:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Node location readback is invalid")
        nested = getattr(node, "node_tree", None)
        return {
            "name": str(node.name),
            "label": str(getattr(node, "label", "")),
            "node_type": self._node_alias(node),
            "bl_idname": self._node_idname(node),
            "managed_type": self._node_alias(node) is not None,
            "location": [float(location[0]), float(location[1])],
            "inputs": self._socket_rows(group, node, node.inputs, "INPUT"),
            "outputs": self._socket_rows(group, node, node.outputs, "OUTPUT"),
            "nested_group": str(nested.name) if nested is not None else None,
        }

    def _snapshot(self, group):
        nodes = [self._node_row(group, node) for node in group.nodes]
        links = []
        for link in group.links:
            links.append(
                {
                    "from_node": str(link.from_node.name),
                    "from_socket": str(link.from_socket.name),
                    "to_node": str(link.to_node.name),
                    "to_socket": str(link.to_socket.name),
                }
            )
        nested_groups = sorted(
            {
                row["nested_group"]
                for row in nodes
                if row["nested_group"] is not None
            }
        )
        if len(nested_groups) > MAX_NESTED_GROUPS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Nested node-group work limit exceeded")
        base = {
            "group_name": str(group.name),
            "tree_type": str(getattr(group, "bl_idname", "")),
            "node_count": len(nodes),
            "link_count": len(links),
            "interface": self._interface_rows(group),
            "nodes": sorted(nodes, key=lambda item: item["name"]),
            "links": sorted(
                links,
                key=lambda item: (
                    item["from_node"],
                    item["from_socket"],
                    item["to_node"],
                    item["to_socket"],
                ),
            ),
            "nested_groups": nested_groups,
        }
        base["group_revision"] = revision(base)
        return base

    @staticmethod
    def _find_node(snapshot, name):
        return next((item for item in snapshot["nodes"] if item["name"] == name), None)

    @staticmethod
    def _input_socket(node, name):
        getter = getattr(node.inputs, "get", None)
        socket = getter(name) if callable(getter) else None
        if socket is None:
            try:
                socket = node.inputs[name]
            except (KeyError, TypeError, IndexError):
                socket = None
        if socket is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Geometry node input socket not found")
        return socket

    @staticmethod
    def _default_location(index):
        return [float((index % 4) * 240), float(-((index // 4) * 180))]

    def inspect(self, request: Request, action: GeometryTreeInspect):
        snapshot = self._snapshot(self._group(action.group_name))
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, snapshot)

    def group_create(self, request: Request, action: GeometryGroupCreate):
        table = getattr(self.bpy.data, "node_groups", None)
        if table is None:
            raise AgentError(
                ErrorCode.UNSUPPORTED_OPERATION,
                "Geometry Nodes datablocks are unavailable",
            )
        if table.get(action.group_name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Geometry Nodes group name already exists")
        group = None
        try:
            group = table.new(action.group_name, "GeometryNodeTree")
            after = self._snapshot(group)
            expected = {
                "group_name": action.group_name,
                "tree_type": "GeometryNodeTree",
                "node_count": 0,
                "link_count": 0,
            }
            actual = {key: after[key] for key in expected}
            verification = compare(expected, actual)
            if not verification.matched:
                table.remove(group)
                group = None
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.FAILED,
                    {"after": after, "rolled_back": True},
                    AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "Geometry Nodes group creation readback differs from requested state",
                    ),
                    verification.to_dict(),
                )
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"after": after},
                verification=verification.to_dict(),
            )
        except Exception:
            if group is not None and table.get(action.group_name) is group:
                table.remove(group)
            raise

    def node_add(self, request: Request, action: GeometryNodeAdd):
        group = self._group(action.group_name)
        before = self._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        if group.nodes.get(action.node_name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Geometry node name already exists")
        if len(group.nodes) >= MAX_GEOMETRY_NODES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Geometry node work limit reached")

        node = None
        try:
            node = group.nodes.new(NODE_TYPES[action.node_type])
            node.name = action.node_name
            node.label = action.node_name
            node.location = list(
                action.location
                if action.location is not None
                else self._default_location(before["node_count"])
            )
            after = self._snapshot(group)
            row = self._find_node(after, action.node_name)
            expected = {
                "node_name": action.node_name,
                "node_type": action.node_type,
                "location": list(node.location),
                "node_count": before["node_count"] + 1,
            }
            actual = {
                "node_name": row["name"] if row else None,
                "node_type": row["node_type"] if row else None,
                "location": row["location"] if row else None,
                "node_count": after["node_count"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after, "node": row},
                    verification=verification.to_dict(),
                )

            group.nodes.remove(node)
            node = None
            restored = self._snapshot(group)
            recovery = compare(
                {"group_revision": before["group_revision"]},
                {"group_revision": restored["group_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Geometry node add rollback could not be verified",
                )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "restored": restored,
                    "rolled_back": True,
                    "recovery_verified": True,
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Geometry node add readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if node is not None and group.nodes.get(action.node_name) is node:
                group.nodes.remove(node)
            raise

    def _capture_node(self, group, node):
        alias = self._node_alias(node)
        if alias is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Only allowlisted Geometry nodes can mutate")
        if any(link.from_node is node or link.to_node is node for link in group.links):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Linked Geometry nodes cannot be removed before typed link recovery is available",
            )
        values = {}
        for socket in node.inputs:
            if hasattr(socket, "default_value"):
                values[str(socket.name)] = copy.deepcopy(socket.default_value)
        location = list(node.location)
        return {
            "node_type": alias,
            "name": str(node.name),
            "label": str(getattr(node, "label", "")),
            "location": [float(location[0]), float(location[1])],
            "inputs": values,
        }

    def _recreate_node(self, group, state):
        node = group.nodes.new(NODE_TYPES[state["node_type"]])
        node.name = state["name"]
        node.label = state["label"]
        node.location = list(state["location"])
        for socket_name, value in state["inputs"].items():
            socket = self._input_socket(node, socket_name)
            if hasattr(socket, "default_value"):
                socket.default_value = copy.deepcopy(value)
        return node

    def node_remove(self, request: Request, action: GeometryNodeRemove):
        group = self._group(action.group_name)
        before = self._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        node = group.nodes.get(action.node_name)
        if node is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Geometry node not found")
        state = self._capture_node(group, node)

        group.nodes.remove(node)
        after = self._snapshot(group)
        expected = {
            "node_absent": True,
            "node_count": before["node_count"] - 1,
        }
        actual = {
            "node_absent": self._find_node(after, action.node_name) is None,
            "node_count": after["node_count"],
        }
        verification = compare(expected, actual)
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"before": before, "after": after},
                verification=verification.to_dict(),
            )

        self._recreate_node(group, state)
        restored = self._snapshot(group)
        recovery = compare(
            {"group_revision": before["group_revision"]},
            {"group_revision": restored["group_revision"]},
        )
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Geometry node remove rollback could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Geometry node removal readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def node_set_input(self, request: Request, action: GeometryNodeSetInput):
        group = self._group(action.group_name)
        before = self._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        node = group.nodes.get(action.node_name)
        if node is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Geometry node not found")
        alias = self._node_alias(node)
        if alias is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Only allowlisted Geometry nodes can mutate")
        socket = self._input_socket(node, action.socket_name)
        if self._socket_linked(group, socket):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Refusing to overwrite a linked Geometry node input",
            )
        value = _validated_input_value(alias, action.socket_name, action.value)
        if not hasattr(socket, "default_value"):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry node input has no editable default value",
            )
        previous = copy.deepcopy(socket.default_value)
        socket.default_value = copy.deepcopy(value)

        after = self._snapshot(group)
        row = self._find_node(after, action.node_name)
        socket_row = (
            next(
                (item for item in row["inputs"] if item["name"] == action.socket_name),
                None,
            )
            if row is not None
            else None
        )
        expected = {
            "node_name": action.node_name,
            "socket_name": action.socket_name,
            "default_value": value,
        }
        actual = {
            "node_name": row["name"] if row else None,
            "socket_name": socket_row["name"] if socket_row else None,
            "default_value": socket_row["default_value"] if socket_row else None,
        }
        verification = compare(expected, actual)
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"before": before, "after": after},
                verification=verification.to_dict(),
            )

        socket.default_value = previous
        restored = self._snapshot(group)
        recovery = compare(
            {"group_revision": before["group_revision"]},
            {"group_revision": restored["group_revision"]},
        )
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Geometry node input rollback could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Geometry node input readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "geometry_nodes.tree_inspect",
                SafetyClass.READ_ONLY,
                GeometryTreeInspect.parse,
                self.inspect,
            ),
            Tool(
                "geometry_nodes.group_create",
                SafetyClass.MUTATION,
                GeometryGroupCreate.parse,
                self.group_create,
            ),
            Tool(
                "geometry_nodes.node_add",
                SafetyClass.MUTATION,
                GeometryNodeAdd.parse,
                self.node_add,
            ),
            Tool(
                "geometry_nodes.node_remove",
                SafetyClass.MUTATION,
                GeometryNodeRemove.parse,
                self.node_remove,
            ),
            Tool(
                "geometry_nodes.node_set_input",
                SafetyClass.MUTATION,
                GeometryNodeSetInput.parse,
                self.node_set_input,
            ),
        ]
