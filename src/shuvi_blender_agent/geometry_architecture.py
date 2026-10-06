"""Level 5 milestone 8: bounded procedural architecture/environment recipes."""

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

ARCHITECTURE_RECIPES = ("MODULAR_WALL", "BLOCK_GRID")
MAX_PREFIX_BYTES = 24
MAX_ARCHITECTURE_MODULES = 24
MAX_WALL_MODULES = 16


def _prefix(value):
    prefix = string(value, "prefix", limit=MAX_PREFIX_BYTES)
    if not prefix:
        raise invalid("prefix cannot be empty")
    if len(prefix.encode("utf-8")) > MAX_PREFIX_BYTES:
        raise invalid(f"prefix exceeds {MAX_PREFIX_BYTES} UTF-8 bytes")
    return prefix


def _recipe(value):
    recipe = string(value, "recipe", limit=32)
    if recipe not in ARCHITECTURE_RECIPES:
        raise invalid("recipe must be MODULAR_WALL or BLOCK_GRID")
    return recipe


def _vector3(value, name, low, high):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid(f"{name} requires exactly three numeric components")
    return [number(item, name, low, high) for item in value]


def _parameters(recipe, value):
    if not isinstance(value, dict):
        raise invalid("parameters must be an object")

    if recipe == "MODULAR_WALL":
        fields(value, {"module_size", "count", "gap", "base_offset"})
        return {
            "module_size": _vector3(
                value["module_size"],
                "module_size",
                0.001,
                1_000.0,
            ),
            "count": integer(value["count"], "count", 1, MAX_WALL_MODULES),
            "gap": number(value["gap"], "gap", 0.0, 1_000.0),
            "base_offset": _vector3(
                value["base_offset"],
                "base_offset",
                -1_000.0,
                1_000.0,
            ),
        }

    fields(
        value,
        {
            "block_size",
            "count_x",
            "count_y",
            "gap_x",
            "gap_y",
            "base_offset",
        },
    )
    count_x = integer(value["count_x"], "count_x", 1, 6)
    count_y = integer(value["count_y"], "count_y", 1, 6)
    module_count = count_x * count_y
    if module_count > MAX_ARCHITECTURE_MODULES:
        raise invalid(f"architecture module count exceeds {MAX_ARCHITECTURE_MODULES}")
    return {
        "block_size": _vector3(
            value["block_size"],
            "block_size",
            0.001,
            1_000.0,
        ),
        "count_x": count_x,
        "count_y": count_y,
        "gap_x": number(value["gap_x"], "gap_x", 0.0, 1_000.0),
        "gap_y": number(value["gap_y"], "gap_y", 0.0, 1_000.0),
        "base_offset": _vector3(
            value["base_offset"],
            "base_offset",
            -1_000.0,
            1_000.0,
        ),
    }


@dataclass(frozen=True)
class ArchitecturePreview:
    recipe: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"recipe", "prefix", "parameters"})
        recipe = _recipe(data["recipe"])
        return cls(
            recipe,
            _prefix(data["prefix"]),
            _parameters(recipe, data["parameters"]),
        )


@dataclass(frozen=True)
class ArchitectureApply:
    group_name: str
    expected_group_revision: str
    recipe: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "group_name",
                "expected_group_revision",
                "recipe",
                "prefix",
                "parameters",
            },
        )
        preview = ArchitecturePreview.parse(
            {
                "recipe": data["recipe"],
                "prefix": data["prefix"],
                "parameters": data["parameters"],
            }
        )
        return cls(
            object_name(data["group_name"]),
            string(data["expected_group_revision"], "expected_group_revision", limit=64),
            preview.recipe,
            preview.prefix,
            preview.parameters,
        )


ArchitectureClear = ArchitectureApply


class GeometryArchitectureOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.bpy = objects.bpy
        self.geometry = GeometryNodeOperations(objects)

    @staticmethod
    def _node_name(prefix, suffix):
        return object_name(f"{prefix}_{suffix}")

    @staticmethod
    def _module_specs(recipe, parameters):
        modules = []
        base = parameters["base_offset"]
        if recipe == "MODULAR_WALL":
            size = parameters["module_size"]
            pitch_x = size[0] + parameters["gap"]
            for index in range(parameters["count"]):
                modules.append(
                    {
                        "index": index,
                        "size": size,
                        "translation": [
                            base[0] + index * pitch_x,
                            base[1],
                            base[2],
                        ],
                    }
                )
            return modules

        size = parameters["block_size"]
        pitch_x = size[0] + parameters["gap_x"]
        pitch_y = size[1] + parameters["gap_y"]
        index = 0
        for y_index in range(parameters["count_y"]):
            for x_index in range(parameters["count_x"]):
                modules.append(
                    {
                        "index": index,
                        "size": size,
                        "translation": [
                            base[0] + x_index * pitch_x,
                            base[1] + y_index * pitch_y,
                            base[2],
                        ],
                    }
                )
                index += 1
        return modules

    def _plan(self, recipe, prefix, parameters):
        modules = self._module_specs(recipe, parameters)
        if len(modules) > MAX_ARCHITECTURE_MODULES:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Architecture module count exceeds source work limit",
            )

        join_name = self._node_name(prefix, "Join")
        output_name = self._node_name(prefix, "Output")
        nodes = []
        links = []

        for module in modules:
            ordinal = module["index"] + 1
            cube_name = self._node_name(prefix, f"Module{ordinal:02d}_Cube")
            transform_name = self._node_name(prefix, f"Module{ordinal:02d}_Transform")
            graph_y = float((module["index"] - (len(modules) - 1) / 2) * 110.0)
            nodes.extend(
                [
                    {
                        "name": cube_name,
                        "node_type": "MESH_CUBE",
                        "location": [-720.0, graph_y],
                        "inputs": {
                            "Size": module["size"],
                            "Vertices X": 2,
                            "Vertices Y": 2,
                            "Vertices Z": 2,
                        },
                    },
                    {
                        "name": transform_name,
                        "node_type": "TRANSFORM_GEOMETRY",
                        "location": [-360.0, graph_y],
                        "inputs": {
                            "Translation": module["translation"],
                            "Rotation": [0.0, 0.0, 0.0],
                            "Scale": [1.0, 1.0, 1.0],
                        },
                    },
                ]
            )
            links.extend(
                [
                    {
                        "from_node": cube_name,
                        "from_socket": "Mesh",
                        "to_node": transform_name,
                        "to_socket": "Geometry",
                    },
                    {
                        "from_node": transform_name,
                        "from_socket": "Geometry",
                        "to_node": join_name,
                        "to_socket": "Geometry",
                    },
                ]
            )

        nodes.extend(
            [
                {
                    "name": join_name,
                    "node_type": "JOIN_GEOMETRY",
                    "location": [40.0, 0.0],
                    "inputs": {},
                },
                {
                    "name": output_name,
                    "node_type": "GROUP_OUTPUT_INTERNAL",
                    "location": [420.0, 0.0],
                    "inputs": {},
                },
            ]
        )
        links.append(
            {
                "from_node": join_name,
                "from_socket": "Geometry",
                "to_node": output_name,
                "to_socket": "Geometry",
            }
        )

        plan = {
            "recipe": recipe,
            "prefix": prefix,
            "parameters": parameters,
            "interface": [
                {
                    "name": "Geometry",
                    "direction": "OUTPUT",
                    "socket_type": "NodeSocketGeometry",
                }
            ],
            "nodes": nodes,
            "links": links,
            "architecture": {
                "module_count": len(modules),
                "maximum_module_count": MAX_ARCHITECTURE_MODULES,
                "generated_node_count": len(nodes),
                "external_asset_references": False,
                "collection_references": False,
                "material_references": False,
            },
            "source_only": True,
            "real_runtime_verified": False,
        }
        plan["architecture_revision"] = revision(plan)
        return plan

    def preview(self, request: Request, action: ArchitecturePreview):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._plan(action.recipe, action.prefix, action.parameters),
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
                    f"Architecture {direction.lower()} socket not found",
                )
            if len(matches) != 1:
                raise AgentError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    f"Architecture {direction.lower()} socket is ambiguous",
                )
            socket = matches[0]
        return socket

    @staticmethod
    def _set_default(node, socket_name, value):
        socket = GeometryArchitectureOperations._socket_by_name(
            node.inputs,
            socket_name,
            "input",
        )
        if not hasattr(socket, "default_value"):
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Architecture input has no default value",
            )
        socket.default_value = value

    @staticmethod
    def _empty_tree_required(snapshot):
        if snapshot["node_count"] or snapshot["link_count"] or snapshot["interface"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Architecture apply requires an empty Geometry Nodes group",
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
                if spec["node_type"] == "GROUP_OUTPUT_INTERNAL":
                    node = group.nodes.new("NodeGroupOutput")
                else:
                    node = group.nodes.new(NODE_TYPES[spec["node_type"]])
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
                "Architecture output interface cannot be identified exactly",
            )
        self._remove_interface_socket(group, matching[0])

    @staticmethod
    def _actual_node_type(row):
        if row["bl_idname"] == "NodeGroupOutput":
            return "GROUP_OUTPUT_INTERNAL"
        return row["node_type"]

    def _snapshot_signature(self, snapshot, plan):
        expected_by_name = {item["name"]: item for item in plan["nodes"]}
        rows = []
        for row in snapshot["nodes"]:
            spec = expected_by_name.get(row["name"], {"inputs": {}})
            values = {item["name"]: item["default_value"] for item in row["inputs"]}
            rows.append(
                {
                    "name": row["name"],
                    "node_type": self._actual_node_type(row),
                    "location": row["location"],
                    "inputs": {name: values.get(name) for name in spec.get("inputs", {})},
                }
            )
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
            "links": sorted(
                [
                    {
                        "from_node": item["from_node"],
                        "from_socket": item["from_socket"],
                        "to_node": item["to_node"],
                        "to_socket": item["to_socket"],
                    }
                    for item in snapshot["links"]
                ],
                key=lambda item: (
                    item["from_node"],
                    item["from_socket"],
                    item["to_node"],
                    item["to_socket"],
                ),
            ),
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
        return compare(
            self._plan_signature(plan),
            self._snapshot_signature(snapshot, plan),
        )

    def apply(self, request: Request, action: ArchitectureApply):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        self._empty_tree_required(before)
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot receive architecture recipes",
            )

        plan = self._plan(action.recipe, action.prefix, action.parameters)
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
                        "recipe": action.recipe,
                        "architecture": plan["architecture"],
                        "architecture_revision": plan["architecture_revision"],
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
                    "Architecture apply rollback could not be verified",
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
                    "Architecture graph differs from requested state",
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

    def clear(self, request: Request, action: ArchitectureClear):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot be cleared by architecture recipe",
            )
        plan = self._plan(action.recipe, action.prefix, action.parameters)
        match = self._verify_exact_plan(before, plan)
        if not match.matched:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry Nodes group does not exactly match the architecture recipe",
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
                        "cleared_architecture_revision": plan["architecture_revision"],
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
                    "Architecture clear rollback could not be verified",
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
                    "Architecture clear readback is not empty",
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
                "geometry_nodes.architecture_preview",
                SafetyClass.READ_ONLY,
                ArchitecturePreview.parse,
                self.preview,
            ),
            Tool(
                "geometry_nodes.architecture_apply",
                SafetyClass.MUTATION,
                ArchitectureApply.parse,
                self.apply,
            ),
            Tool(
                "geometry_nodes.architecture_clear",
                SafetyClass.MUTATION,
                ArchitectureClear.parse,
                self.clear,
            ),
        ]
