"""Level 5 milestone 7: bounded procedural Geometry Nodes scatter systems."""

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

SCATTER_RECIPES = ("CUBE_SCATTER", "ICO_SPHERE_SCATTER")
MAX_PREFIX_BYTES = 24
MAX_SCATTER_INSTANCES = 2048


def _prefix(value):
    prefix = string(value, "prefix", limit=MAX_PREFIX_BYTES)
    if not prefix:
        raise invalid("prefix cannot be empty")
    if len(prefix.encode("utf-8")) > MAX_PREFIX_BYTES:
        raise invalid(f"prefix exceeds {MAX_PREFIX_BYTES} UTF-8 bytes")
    return prefix


def _vector3(value, name, low, high):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid(f"{name} requires exactly three numeric components")
    return [number(item, name, low, high) for item in value]


def _integer_vector3(value, name, low, high):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid(f"{name} requires exactly three integer components")
    return [integer(item, name, low, high) for item in value]


def _estimated_cube_surface_points(vertices):
    x, y, z = vertices
    interior = max(x - 2, 0) * max(y - 2, 0) * max(z - 2, 0)
    return x * y * z - interior


def _recipe(value):
    recipe = string(value, "recipe", limit=32)
    if recipe not in SCATTER_RECIPES:
        raise invalid("recipe must be CUBE_SCATTER or ICO_SPHERE_SCATTER")
    return recipe


def _parameters(recipe, value):
    if not isinstance(value, dict):
        raise invalid("parameters must be an object")
    common = {
        "point_size",
        "point_vertices",
        "rotation",
        "scale",
    }
    if recipe == "CUBE_SCATTER":
        fields(value, common | {"instance_size", "instance_vertices"})
    else:
        fields(value, common | {"instance_radius", "instance_subdivisions"})

    point_vertices = _integer_vector3(value["point_vertices"], "point_vertices", 2, 20)
    estimated = _estimated_cube_surface_points(point_vertices)
    if estimated > MAX_SCATTER_INSTANCES:
        raise invalid(
            f"estimated scatter instance count exceeds {MAX_SCATTER_INSTANCES}"
        )

    result = {
        "point_size": _vector3(value["point_size"], "point_size", 0.001, 1_000.0),
        "point_vertices": point_vertices,
        "rotation": _vector3(value["rotation"], "rotation", -6.283185307, 6.283185307),
        "scale": _vector3(value["scale"], "scale", 0.001, 100.0),
        "estimated_instance_count": estimated,
    }
    if recipe == "CUBE_SCATTER":
        result["instance_size"] = _vector3(
            value["instance_size"],
            "instance_size",
            0.001,
            1_000.0,
        )
        result["instance_vertices"] = integer(
            value["instance_vertices"],
            "instance_vertices",
            2,
            8,
        )
    else:
        result["instance_radius"] = number(
            value["instance_radius"],
            "instance_radius",
            0.001,
            1_000.0,
        )
        result["instance_subdivisions"] = integer(
            value["instance_subdivisions"],
            "instance_subdivisions",
            1,
            3,
        )
    return result


@dataclass(frozen=True)
class ScatterPreview:
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
class ScatterApply:
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
        preview = ScatterPreview.parse(
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


ScatterClear = ScatterApply


class GeometryScatterOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.bpy = objects.bpy
        self.geometry = GeometryNodeOperations(objects)

    @staticmethod
    def _node_name(prefix, suffix):
        return object_name(f"{prefix}_{suffix}")

    def _plan(self, recipe, prefix, parameters):
        points = self._node_name(prefix, "Points")
        instance = self._node_name(prefix, "Instance")
        scatter = self._node_name(prefix, "Scatter")
        output = self._node_name(prefix, "Output")

        point_inputs = {
            "Size": parameters["point_size"],
            "Vertices X": parameters["point_vertices"][0],
            "Vertices Y": parameters["point_vertices"][1],
            "Vertices Z": parameters["point_vertices"][2],
        }
        if recipe == "CUBE_SCATTER":
            instance_type = "MESH_CUBE"
            instance_inputs = {
                "Size": parameters["instance_size"],
                "Vertices X": parameters["instance_vertices"],
                "Vertices Y": parameters["instance_vertices"],
                "Vertices Z": parameters["instance_vertices"],
            }
        else:
            instance_type = "MESH_ICO_SPHERE"
            instance_inputs = {
                "Radius": parameters["instance_radius"],
                "Subdivisions": parameters["instance_subdivisions"],
            }

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
            "nodes": [
                {
                    "name": points,
                    "node_type": "MESH_CUBE",
                    "location": [-700.0, 160.0],
                    "inputs": point_inputs,
                },
                {
                    "name": instance,
                    "node_type": instance_type,
                    "location": [-700.0, -180.0],
                    "inputs": instance_inputs,
                },
                {
                    "name": scatter,
                    "node_type": "INSTANCE_ON_POINTS",
                    "location": [-180.0, 60.0],
                    "inputs": {
                        "Selection": True,
                        "Pick Instance": False,
                        "Instance Index": 0,
                        "Rotation": parameters["rotation"],
                        "Scale": parameters["scale"],
                    },
                },
                {
                    "name": output,
                    "node_type": "GROUP_OUTPUT_INTERNAL",
                    "location": [300.0, 60.0],
                    "inputs": {},
                },
            ],
            "links": [
                {
                    "from_node": points,
                    "from_socket": "Mesh",
                    "to_node": scatter,
                    "to_socket": "Points",
                },
                {
                    "from_node": instance,
                    "from_socket": "Mesh",
                    "to_node": scatter,
                    "to_socket": "Instance",
                },
                {
                    "from_node": scatter,
                    "from_socket": "Instances",
                    "to_node": output,
                    "to_socket": "Geometry",
                },
            ],
            "scatter": {
                "estimated_instance_count": parameters["estimated_instance_count"],
                "maximum_instance_count": MAX_SCATTER_INSTANCES,
                "instances_realized": False,
                "external_asset_references": False,
                "collection_references": False,
            },
            "source_only": True,
            "real_runtime_verified": False,
        }
        plan["scatter_revision"] = revision(plan)
        return plan

    def preview(self, request: Request, action: ScatterPreview):
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
                    f"Scatter {direction.lower()} socket not found",
                )
            if len(matches) != 1:
                raise AgentError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    f"Scatter {direction.lower()} socket is ambiguous",
                )
            socket = matches[0]
        return socket

    @staticmethod
    def _set_default(node, socket_name, value):
        socket = GeometryScatterOperations._socket_by_name(
            node.inputs,
            socket_name,
            "input",
        )
        if not hasattr(socket, "default_value"):
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Scatter input has no default value",
            )
        socket.default_value = value

    @staticmethod
    def _empty_tree_required(snapshot):
        if snapshot["node_count"] or snapshot["link_count"] or snapshot["interface"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Scatter apply requires an empty Geometry Nodes group",
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
                "Scatter output interface cannot be identified exactly",
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
                    "inputs": {
                        name: values.get(name) for name in spec.get("inputs", {})
                    },
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

    def apply(self, request: Request, action: ScatterApply):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        self._empty_tree_required(before)
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot receive scatter systems",
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
                        "scatter": plan["scatter"],
                        "scatter_revision": plan["scatter_revision"],
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
                    "Scatter apply rollback could not be verified",
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
                    "Scatter graph differs from requested state",
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

    def clear(self, request: Request, action: ScatterClear):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot be cleared by scatter workflow",
            )
        plan = self._plan(action.recipe, action.prefix, action.parameters)
        match = self._verify_exact_plan(before, plan)
        if not match.matched:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry Nodes group does not exactly match the requested scatter workflow",
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
                        "cleared_scatter_revision": plan["scatter_revision"],
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
                    "Scatter clear rollback could not be verified",
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
                    "Scatter clear readback is not empty",
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
                "geometry_nodes.scatter_preview",
                SafetyClass.READ_ONLY,
                ScatterPreview.parse,
                self.preview,
            ),
            Tool(
                "geometry_nodes.scatter_apply",
                SafetyClass.MUTATION,
                ScatterApply.parse,
                self.apply,
            ),
            Tool(
                "geometry_nodes.scatter_clear",
                SafetyClass.MUTATION,
                ScatterClear.parse,
                self.clear,
            ),
        ]
