"""Level 5 milestone 5: bounded procedural Geometry Nodes primitive recipes."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .geometry_nodes import GeometryNodeOperations, NODE_TYPES
from .inspection import revision
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

RECIPES = ("CUBE", "ICO_SPHERE", "TWIN_CUBE")
MAX_PREFIX_BYTES = 24


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


def _parameters(recipe, value):
    if not isinstance(value, dict):
        raise invalid("parameters must be an object")
    if recipe == "CUBE":
        fields(value, {"size", "vertices"})
        vertices = integer(value["vertices"], "vertices", 2, 64)
        return {
            "size": _vector3(value["size"], "size", 0.001, 1_000.0),
            "vertices": vertices,
        }
    if recipe == "ICO_SPHERE":
        fields(value, {"radius", "subdivisions"})
        return {
            "radius": number(value["radius"], "radius", 0.001, 1_000.0),
            "subdivisions": integer(value["subdivisions"], "subdivisions", 1, 5),
        }
    if recipe == "TWIN_CUBE":
        fields(value, {"size", "vertices", "offset"})
        vertices = integer(value["vertices"], "vertices", 2, 64)
        return {
            "size": _vector3(value["size"], "size", 0.001, 1_000.0),
            "vertices": vertices,
            "offset": _vector3(value["offset"], "offset", -1_000.0, 1_000.0),
        }
    raise invalid("Unsupported procedural primitive recipe")


@dataclass(frozen=True)
class PrimitivePreview:
    recipe: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"recipe", "prefix", "parameters"})
        recipe = data["recipe"]
        if not isinstance(recipe, str) or recipe not in RECIPES:
            raise invalid("recipe must be CUBE, ICO_SPHERE or TWIN_CUBE")
        return cls(recipe, _prefix(data["prefix"]), _parameters(recipe, data["parameters"]))


@dataclass(frozen=True)
class PrimitiveApply:
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
        preview = PrimitivePreview.parse(
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


PrimitiveClear = PrimitiveApply


class ProceduralPrimitiveOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.bpy = objects.bpy
        self.geometry = GeometryNodeOperations(objects)

    @staticmethod
    def _node_name(prefix, suffix):
        return object_name(f"{prefix}_{suffix}")

    def _plan(self, recipe, prefix, parameters):
        output_name = self._node_name(prefix, "Output")
        if recipe == "CUBE":
            cube = self._node_name(prefix, "Cube")
            nodes = [
                {
                    "name": cube,
                    "node_type": "MESH_CUBE",
                    "location": [-240.0, 0.0],
                    "inputs": {
                        "Size": parameters["size"],
                        "Vertices X": parameters["vertices"],
                        "Vertices Y": parameters["vertices"],
                        "Vertices Z": parameters["vertices"],
                    },
                },
                {
                    "name": output_name,
                    "node_type": "GROUP_OUTPUT_INTERNAL",
                    "location": [240.0, 0.0],
                    "inputs": {},
                },
            ]
            links = [
                {
                    "from_node": cube,
                    "from_socket": "Mesh",
                    "to_node": output_name,
                    "to_socket": "Geometry",
                }
            ]
        elif recipe == "ICO_SPHERE":
            sphere = self._node_name(prefix, "IcoSphere")
            nodes = [
                {
                    "name": sphere,
                    "node_type": "MESH_ICO_SPHERE",
                    "location": [-240.0, 0.0],
                    "inputs": {
                        "Radius": parameters["radius"],
                        "Subdivisions": parameters["subdivisions"],
                    },
                },
                {
                    "name": output_name,
                    "node_type": "GROUP_OUTPUT_INTERNAL",
                    "location": [240.0, 0.0],
                    "inputs": {},
                },
            ]
            links = [
                {
                    "from_node": sphere,
                    "from_socket": "Mesh",
                    "to_node": output_name,
                    "to_socket": "Geometry",
                }
            ]
        else:
            cube_a = self._node_name(prefix, "CubeA")
            cube_b = self._node_name(prefix, "CubeB")
            transform = self._node_name(prefix, "TransformB")
            join = self._node_name(prefix, "Join")
            cube_inputs = {
                "Size": parameters["size"],
                "Vertices X": parameters["vertices"],
                "Vertices Y": parameters["vertices"],
                "Vertices Z": parameters["vertices"],
            }
            nodes = [
                {
                    "name": cube_a,
                    "node_type": "MESH_CUBE",
                    "location": [-600.0, 140.0],
                    "inputs": cube_inputs,
                },
                {
                    "name": cube_b,
                    "node_type": "MESH_CUBE",
                    "location": [-600.0, -140.0],
                    "inputs": cube_inputs,
                },
                {
                    "name": transform,
                    "node_type": "TRANSFORM_GEOMETRY",
                    "location": [-300.0, -140.0],
                    "inputs": {
                        "Translation": parameters["offset"],
                        "Rotation": [0.0, 0.0, 0.0],
                        "Scale": [1.0, 1.0, 1.0],
                    },
                },
                {
                    "name": join,
                    "node_type": "JOIN_GEOMETRY",
                    "location": [0.0, 0.0],
                    "inputs": {},
                },
                {
                    "name": output_name,
                    "node_type": "GROUP_OUTPUT_INTERNAL",
                    "location": [300.0, 0.0],
                    "inputs": {},
                },
            ]
            links = [
                {
                    "from_node": cube_a,
                    "from_socket": "Mesh",
                    "to_node": join,
                    "to_socket": "Geometry",
                },
                {
                    "from_node": cube_b,
                    "from_socket": "Mesh",
                    "to_node": transform,
                    "to_socket": "Geometry",
                },
                {
                    "from_node": transform,
                    "from_socket": "Geometry",
                    "to_node": join,
                    "to_socket": "Geometry",
                },
                {
                    "from_node": join,
                    "from_socket": "Geometry",
                    "to_node": output_name,
                    "to_socket": "Geometry",
                },
            ]

        base = {
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
            "output": {
                "node_name": output_name,
                "socket_name": "Geometry",
            },
            "source_only": True,
            "real_runtime_verified": False,
        }
        base["primitive_revision"] = revision(base)
        return base

    def preview(self, request: Request, action: PrimitivePreview):
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
                    f"Procedural recipe {direction.lower()} socket not found",
                )
            if len(matches) != 1:
                raise AgentError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    f"Procedural recipe {direction.lower()} socket is ambiguous",
                )
            socket = matches[0]
        return socket

    @staticmethod
    def _set_default(node, socket_name, value):
        socket = ProceduralPrimitiveOperations._socket_by_name(
            node.inputs,
            socket_name,
            "input",
        )
        if not hasattr(socket, "default_value"):
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Procedural recipe input has no default value",
            )
        socket.default_value = value

    @staticmethod
    def _empty_tree_required(snapshot):
        if snapshot["node_count"] or snapshot["link_count"] or snapshot["interface"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Procedural primitive apply requires an empty Geometry Nodes group",
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

    def _cleanup_recipe(self, group, plan):
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
                "Procedural output interface cannot be identified exactly",
            )
        self._remove_interface_socket(group, matching[0])

    @staticmethod
    def _snapshot_signature(snapshot):
        return {
            "interface": [
                {
                    "name": item["name"],
                    "direction": item["direction"],
                    "socket_type": item["socket_type"],
                }
                for item in snapshot["interface"]
            ],
            "nodes": [
                {
                    "name": item["name"],
                    "node_type": item["node_type"]
                    if item["bl_idname"] != "NodeGroupOutput"
                    else "GROUP_OUTPUT_INTERNAL",
                    "location": item["location"],
                    "inputs": {
                        socket["name"]: socket["default_value"]
                        for socket in item["inputs"]
                        if socket["default_value"] is not None
                    },
                }
                for item in snapshot["nodes"]
            ],
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
        expected = self._plan_signature(plan)
        actual = self._snapshot_signature(snapshot)
        verification = compare(expected, actual)
        return verification

    def apply(self, request: Request, action: PrimitiveApply):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        self._empty_tree_required(before)
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot receive procedural primitives",
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
                        "primitive_revision": plan["primitive_revision"],
                        "recipe": action.recipe,
                        "prefix": action.prefix,
                    },
                    verification=verification.to_dict(),
                )

            self._cleanup_recipe(group, plan)
            restored = self.geometry._snapshot(group)
            recovery = compare(
                {"group_revision": before["group_revision"]},
                {"group_revision": restored["group_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Procedural primitive apply rollback could not be verified",
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
                    "Procedural primitive graph differs from requested recipe",
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

    def clear(self, request: Request, action: PrimitiveClear):
        group = self.geometry._group(action.group_name)
        before = self.geometry._snapshot(group)
        require_revision(action.expected_group_revision, before["group_revision"])
        if int(getattr(group, "users", 0)) > 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Shared Geometry Nodes groups cannot be cleared procedurally",
            )
        plan = self._plan(action.recipe, action.prefix, action.parameters)
        match = self._verify_exact_plan(before, plan)
        if not match.matched:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry Nodes group does not exactly match the requested procedural recipe",
            )

        try:
            self._cleanup_recipe(group, plan)
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
                        "cleared_primitive_revision": plan["primitive_revision"],
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
                    "Procedural primitive clear rollback could not be verified",
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
                    "Procedural primitive clear readback is not empty",
                ),
                verification.to_dict(),
            )
        except Exception:
            current = self.geometry._snapshot(group)
            if current["node_count"] == 0 and current["link_count"] == 0 and not current["interface"]:
                self._build(group, plan)
            raise

    def tools(self):
        return [
            Tool(
                "geometry_nodes.primitive_preview",
                SafetyClass.READ_ONLY,
                PrimitivePreview.parse,
                self.preview,
            ),
            Tool(
                "geometry_nodes.primitive_apply",
                SafetyClass.MUTATION,
                PrimitiveApply.parse,
                self.apply,
            ),
            Tool(
                "geometry_nodes.primitive_clear",
                SafetyClass.MUTATION,
                PrimitiveClear.parse,
                self.clear,
            ),
        ]
