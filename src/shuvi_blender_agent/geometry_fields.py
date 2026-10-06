"""Level 5 milestone 6: bounded Geometry Nodes attribute and field workflows."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .geometry_nodes import NODE_TYPES, GeometryNodeOperations
from .inspection import revision
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

WORKFLOWS = {
    "INDEX_ATTRIBUTE": {
        "field_node_type": "INPUT_INDEX",
        "field_output": "Index",
        "data_type": "INT",
    },
    "POSITION_ATTRIBUTE": {
        "field_node_type": "INPUT_POSITION",
        "field_output": "Position",
        "data_type": "FLOAT_VECTOR",
    },
    "NORMAL_ATTRIBUTE": {
        "field_node_type": "INPUT_NORMAL",
        "field_output": "Normal",
        "data_type": "FLOAT_VECTOR",
    },
}
MAX_PREFIX_BYTES = 24
MAX_ATTRIBUTE_BYTES = 48


def _prefix(value):
    prefix = string(value, "prefix", limit=MAX_PREFIX_BYTES)
    if not prefix:
        raise invalid("prefix cannot be empty")
    if len(prefix.encode("utf-8")) > MAX_PREFIX_BYTES:
        raise invalid(f"prefix exceeds {MAX_PREFIX_BYTES} UTF-8 bytes")
    return prefix


def _attribute_name(value):
    name = string(value, "attribute_name", limit=MAX_ATTRIBUTE_BYTES)
    if not name.startswith("shuvi_"):
        raise invalid("attribute_name must start with shuvi_")
    if len(name.encode("utf-8")) > MAX_ATTRIBUTE_BYTES:
        raise invalid(f"attribute_name exceeds {MAX_ATTRIBUTE_BYTES} UTF-8 bytes")
    if not all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in name):
        raise invalid("attribute_name must contain only ASCII letters, digits or underscore")
    if len(name) <= len("shuvi_"):
        raise invalid("attribute_name requires a suffix after shuvi_")
    return name


def _vector3(value, name, low, high):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid(f"{name} requires exactly three numeric components")
    return [number(item, name, low, high) for item in value]


def _parameters(value):
    if not isinstance(value, dict):
        raise invalid("parameters must be an object")
    fields(value, {"size", "vertices", "attribute_name"})
    return {
        "size": _vector3(value["size"], "size", 0.001, 1_000.0),
        "vertices": integer(value["vertices"], "vertices", 2, 64),
        "attribute_name": _attribute_name(value["attribute_name"]),
    }


def _workflow(value):
    workflow = string(value, "workflow", limit=32)
    if workflow not in WORKFLOWS:
        raise invalid(
            "workflow must be INDEX_ATTRIBUTE, POSITION_ATTRIBUTE or NORMAL_ATTRIBUTE"
        )
    return workflow


@dataclass(frozen=True)
class FieldWorkflowPreview:
    workflow: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"workflow", "prefix", "parameters"})
        return cls(
            _workflow(data["workflow"]),
            _prefix(data["prefix"]),
            _parameters(data["parameters"]),
        )


@dataclass(frozen=True)
class FieldWorkflowApply:
    group_name: str
    expected_group_revision: str
    workflow: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "group_name",
                "expected_group_revision",
                "workflow",
                "prefix",
                "parameters",
            },
        )
        preview = FieldWorkflowPreview.parse(
            {
                "workflow": data["workflow"],
                "prefix": data["prefix"],
                "parameters": data["parameters"],
            }
        )
        return cls(
            object_name(data["group_name"]),
            string(data["expected_group_revision"], "expected_group_revision", limit=64),
            preview.workflow,
            preview.prefix,
            preview.parameters,
        )


FieldWorkflowClear = FieldWorkflowApply


class GeometryFieldOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.bpy = objects.bpy
        self.geometry = GeometryNodeOperations(objects)

    @staticmethod
    def _node_name(prefix, suffix):
        return object_name(f"{prefix}_{suffix}")

    def _plan(self, workflow, prefix, parameters):
        definition = WORKFLOWS[workflow]
        cube = self._node_name(prefix, "Cube")
        field = self._node_name(prefix, "Field")
        store = self._node_name(prefix, "StoreAttribute")
        output = self._node_name(prefix, "Output")
        plan = {
            "workflow": workflow,
            "prefix": prefix,
            "parameters": parameters,
            "interface": [
                {
                    "name": "Geometry",
                    "direction": "OUTPUT",
                    "socket_type": "NodeSocketGeometry",
                }
            ],
            "nodes": [
                {
                    "name": cube,
                    "node_type": "MESH_CUBE",
                    "location": [-600.0, 100.0],
                    "inputs": {
                        "Size": parameters["size"],
                        "Vertices X": parameters["vertices"],
                        "Vertices Y": parameters["vertices"],
                        "Vertices Z": parameters["vertices"],
                    },
                },
                {
                    "name": field,
                    "node_type": definition["field_node_type"],
                    "location": [-600.0, -180.0],
                    "inputs": {},
                },
                {
                    "name": store,
                    "node_type": "STORE_NAMED_ATTRIBUTE_INTERNAL",
                    "location": [-180.0, 80.0],
                    "inputs": {
                        "Selection": True,
                        "Name": parameters["attribute_name"],
                    },
                    "field_settings": {
                        "data_type": definition["data_type"],
                        "domain": "POINT",
                    },
                },
                {
                    "name": output,
                    "node_type": "GROUP_OUTPUT_INTERNAL",
                    "location": [240.0, 80.0],
                    "inputs": {},
                },
            ],
            "links": [
                {
                    "from_node": cube,
                    "from_socket": "Mesh",
                    "to_node": store,
                    "to_socket": "Geometry",
                },
                {
                    "from_node": field,
                    "from_socket": definition["field_output"],
                    "to_node": store,
                    "to_socket": "Value",
                },
                {
                    "from_node": store,
                    "from_socket": "Geometry",
                    "to_node": output,
                    "to_socket": "Geometry",
                },
            ],
            "attribute": {
                "name": parameters["attribute_name"],
                "domain": "POINT",
                "data_type": definition["data_type"],
                "field_source": definition["field_output"],
            },
            "source_only": True,
            "real_runtime_verified": False,
        }
        plan["field_workflow_revision"] = revision(plan)
        return plan

    def preview(self, request: Request, action: FieldWorkflowPreview):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._plan(action.workflow, action.prefix, action.parameters),
        )

    @staticmethod
    def _socket_by_name(table, name, direction):
        getter = getattr(table, "get", None)
        socket = getter(name) if callable(getter) else None
        if socket is None:
            matches = [item for item in table if str(item.name) == name]
            if not matches:
                raise AgentError(
                    ErrorCode.NOT_FOUND,
                    f"Field workflow {direction.lower()} socket not found",
                )
            if len(matches) != 1:
                raise AgentError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    f"Field workflow {direction.lower()} socket is ambiguous",
                )
            socket = matches[0]
        return socket

    @staticmethod
    def _set_default(node, socket_name, value):
        socket = GeometryFieldOperations._socket_by_name(node.inputs, socket_name, "input")
        if not hasattr(socket, "default_value"):
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Field workflow input has no default value",
            )
        socket.default_value = value

    @staticmethod
    def _empty_tree_required(snapshot):
        if snapshot["node_count"] or snapshot["link_count"] or snapshot["interface"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Field workflow apply requires an empty Geometry Nodes group",
            )

    def _create_output_interface(self, group):
        interface = getattr(group, "interface", None)
        if interface is None or not hasattr(interface, "new_socket"):
            raise AgentError(
                ErrorCode.UNSUPPORTED_OPERATION,
                "Geometry Nodes interface API is unavailable",
            )
        return interface.new_socket(
            name="Geometry",
            in_out="OUTPUT",
            socket_type="NodeSocketGeometry",
        )

    @staticmethod
    def _remove_interface_socket(group, socket):
        interface = getattr(group, "interface", None)
        if interface is None or not hasattr(interface, "remove"):
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Geometry Nodes interface cleanup is unavailable",
            )
        interface.remove(socket)

    def _build(self, group, plan):
        output_socket = self._create_output_interface(group)
        created = {}
        try:
            for spec in plan["nodes"]:
                kind = spec["node_type"]
                if kind == "GROUP_OUTPUT_INTERNAL":
                    node = group.nodes.new("NodeGroupOutput")
                elif kind == "STORE_NAMED_ATTRIBUTE_INTERNAL":
                    node = group.nodes.new("GeometryNodeStoreNamedAttribute")
                    node.data_type = spec["field_settings"]["data_type"]
                    node.domain = spec["field_settings"]["domain"]
                else:
                    node = group.nodes.new(NODE_TYPES[kind])
                node.name = spec["name"]
                node.label = spec["name"]
                node.location = list(spec["location"])
                for socket_name, value in spec["inputs"].items():
                    self._set_default(node, socket_name, value)
                created[spec["name"]] = node

            for link in plan["links"]:
                source = created[link["from_node"]]
                target = created[link["to_node"]]
                output = self._socket_by_name(
                    source.outputs,
                    link["from_socket"],
                    "output",
                )
                input_socket = self._socket_by_name(
                    target.inputs,
                    link["to_socket"],
                    "input",
                )
                group.links.new(output, input_socket)
            return output_socket, created
        except Exception:
            for node in list(created.values())[::-1]:
                if node in group.nodes:
                    group.nodes.remove(node)
            if output_socket in getattr(group.interface, "items_tree", ()):
                self._remove_interface_socket(group, output_socket)
            raise

    def _cleanup(self, group, plan):
        names = {item["name"] for item in plan["nodes"]}
        for node in list(group.nodes):
            if str(node.name) in names:
                group.nodes.remove(node)
        items = list(getattr(group.interface, "items_tree", ()))
        matching = [
            item
            for item in items
            if str(getattr(item, "item_type", "SOCKET")) == "SOCKET"
            and str(getattr(item, "name", "")) == "Geometry"
            and str(getattr(item, "in_out", "")) == "OUTPUT"
            and str(getattr(item, "socket_type", "")) == "NodeSocketGeometry"
        ]
        if len(matching) != 1:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Field workflow output interface cannot be identified exactly",
            )
        self._remove_interface_socket(group, matching[0])

    @staticmethod
    def _actual_node_type(row):
        if row["bl_idname"] == "NodeGroupOutput":
            return "GROUP_OUTPUT_INTERNAL"
        if row["bl_idname"] == "GeometryNodeStoreNamedAttribute":
            return "STORE_NAMED_ATTRIBUTE_INTERNAL"
        return row["node_type"]

    def _snapshot_signature(self, snapshot, plan):
        expected_by_name = {item["name"]: item for item in plan["nodes"]}
        rows = []
        for row in snapshot["nodes"]:
            spec = expected_by_name.get(row["name"], {"inputs": {}})
            values = {item["name"]: item["default_value"] for item in row["inputs"]}
            compact = {
                "name": row["name"],
                "node_type": self._actual_node_type(row),
                "location": row["location"],
                "inputs": {
                    name: values.get(name)
                    for name in spec.get("inputs", {})
                },
            }
            if row["bl_idname"] == "GeometryNodeStoreNamedAttribute":
                compact["field_settings"] = row.get("field_settings")
            rows.append(compact)
        return {
            "interface": [
                {
                    "name": item["name"],
                    "direction": item["direction"],
                    "socket_type": item["socket_type"],
                }
                for item in snapshot["interface"]
            ],
            "nodes": sorted(rows, key=lambda item: item["name"]),
            "links": [
                {
                    "from_node": item["from_node"],
                    "from_socket": item["from_socket"],
                    "to_node": item["to_node"],
                    "to_socket": item["to_socket"],
                }
                for item in snapshot["links"]
            ],
        }

    @staticmethod
    def _plan_signature(plan):
        return {
            "interface": plan["interface"],
            "nodes": sorted(plan["nodes"], key=lambda item: item["name"]),
            "links": sorted(
                plan["links"],
                key=lambda item: (
                    item["from_node"],
                    item["from_socket"],
                    item["to_node"],
                    item["to_socket"],
                ),
            ),
        }

    def _verify_exact_plan(self, snapshot, plan):
        actual = self._snapshot_signature(snapshot, plan)
        actual["links"] = sorted(
            actual["links"],
            key=lambda item: (
                item["from_node"],
                item["from_socket"],
                item["to_node"],
                item["to_socket"],
            ),
        )
        return compare(self._plan_signature(plan), actual)

    def apply(self, request: Request, action: FieldWorkflowApply):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        self._empty_tree_required(before)
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot receive field workflows",
            )

        plan = self._plan(action.workflow, action.prefix, action.parameters)
        output_socket = None
        created = None
        try:
            output_socket, created = self._build(group, plan)
            after = self.geometry._snapshot(group)
            verification = self._verify_exact_plan(after, plan)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "workflow": action.workflow,
                        "attribute": plan["attribute"],
                        "field_workflow_revision": plan["field_workflow_revision"],
                    },
                    verification=verification.to_dict(),
                )

            self._cleanup(group, plan)
            restored = self.geometry._snapshot(group)
            recovery = compare(
                {"group_revision": before["group_revision"]},
                {"group_revision": restored["group_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Field workflow apply rollback could not be verified",
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
                    "Field workflow graph differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if created:
                for node in list(created.values())[::-1]:
                    if node in group.nodes:
                        group.nodes.remove(node)
            if output_socket is not None and output_socket in getattr(
                group.interface,
                "items_tree",
                (),
            ):
                self._remove_interface_socket(group, output_socket)
            raise

    def clear(self, request: Request, action: FieldWorkflowClear):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot be cleared by field workflow",
            )
        plan = self._plan(action.workflow, action.prefix, action.parameters)
        match = self._verify_exact_plan(before, plan)
        if not match.matched:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry Nodes group does not exactly match the requested field workflow",
            )

        try:
            self._cleanup(group, plan)
            after = self.geometry._snapshot(group)
            expected = {"node_count": 0, "link_count": 0, "interface": []}
            actual = {
                "node_count": after["node_count"],
                "link_count": after["link_count"],
                "interface": after["interface"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "cleared_field_workflow_revision": plan[
                            "field_workflow_revision"
                        ],
                    },
                    verification=verification.to_dict(),
                )

            self._build(group, plan)
            restored = self.geometry._snapshot(group)
            recovery = compare(
                {"group_revision": before["group_revision"]},
                {"group_revision": restored["group_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Field workflow clear rollback could not be verified",
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
                    "Field workflow clear readback is not empty",
                ),
                verification.to_dict(),
            )
        except Exception:
            current = self.geometry._snapshot(group)
            if (
                current["node_count"] == 0
                and current["link_count"] == 0
                and not current["interface"]
            ):
                self._build(group, plan)
            raise

    def tools(self):
        return [
            Tool(
                "geometry_nodes.field_preview",
                SafetyClass.READ_ONLY,
                FieldWorkflowPreview.parse,
                self.preview,
            ),
            Tool(
                "geometry_nodes.field_apply",
                SafetyClass.MUTATION,
                FieldWorkflowApply.parse,
                self.apply,
            ),
            Tool(
                "geometry_nodes.field_clear",
                SafetyClass.MUTATION,
                FieldWorkflowClear.parse,
                self.clear,
            ),
        ]
