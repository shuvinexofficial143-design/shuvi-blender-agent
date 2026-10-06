"""Level 4 milestones 7-8: bounded Principled shader and PBR texture graph tools."""

from dataclasses import dataclass

from .appearance import color
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, number, string
from .verification import compare

MAX_SHADER_NODES = 32
MAX_SHADER_LINKS = 64
MANAGED_PREFIX = "SHUVI_"
NORMAL_NODE = "SHUVI_NORMAL_MAP"
BUMP_NODE = "SHUVI_BUMP"

PRINCIPLED_INPUTS = {
    "base_color": "Base Color",
    "metallic": "Metallic",
    "roughness": "Roughness",
    "transmission": "Transmission Weight",
    "emission_color": "Emission Color",
    "emission_strength": "Emission Strength",
    "alpha": "Alpha",
}

CHANNELS = {
    "BASE_COLOR": ("Base Color", "Color", "sRGB"),
    "ROUGHNESS": ("Roughness", "Color", "Non-Color"),
    "METALLIC": ("Metallic", "Color", "Non-Color"),
    "NORMAL": (None, "Color", "Non-Color"),
    "HEIGHT": (None, "Color", "Non-Color"),
    "AO": (None, "Color", "Non-Color"),
    "ALPHA": ("Alpha", "Alpha", "Non-Color"),
}


def _channel(value):
    value = string(value, "channel", limit=24)
    if value not in CHANNELS:
        raise invalid("Unsupported PBR texture channel")
    return value


def _settings(data):
    values = fields(
        data,
        set(),
        {
            "base_color",
            "metallic",
            "roughness",
            "transmission",
            "emission_color",
            "emission_strength",
            "alpha",
            "normal_strength",
            "height_strength",
            "height_distance",
        },
    )
    if not values:
        raise invalid("Principled settings patch cannot be empty")
    parsed = {}
    if "base_color" in values:
        parsed["base_color"] = list(color(values["base_color"], 4))
    if "metallic" in values:
        parsed["metallic"] = number(values["metallic"], "metallic", 0, 1)
    if "roughness" in values:
        parsed["roughness"] = number(values["roughness"], "roughness", 0, 1)
    if "transmission" in values:
        parsed["transmission"] = number(values["transmission"], "transmission", 0, 1)
    if "emission_color" in values:
        parsed["emission_color"] = list(color(values["emission_color"], 4))
    if "emission_strength" in values:
        parsed["emission_strength"] = number(
            values["emission_strength"], "emission_strength", 0, 1000
        )
    if "alpha" in values:
        parsed["alpha"] = number(values["alpha"], "alpha", 0, 1)
    if "normal_strength" in values:
        parsed["normal_strength"] = number(values["normal_strength"], "normal_strength", 0, 10)
    if "height_strength" in values:
        parsed["height_strength"] = number(values["height_strength"], "height_strength", 0, 10)
    if "height_distance" in values:
        parsed["height_distance"] = number(values["height_distance"], "height_distance", 0, 100)
    return parsed


@dataclass(frozen=True)
class ShaderInspect:
    material_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"material_name"})
        return cls(object_name(data["material_name"]))


@dataclass(frozen=True)
class PrincipledSet:
    material_name: str
    expected_shader_revision: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"material_name", "expected_shader_revision", "settings"})
        return cls(
            object_name(data["material_name"]),
            string(data["expected_shader_revision"], "expected_shader_revision", limit=64),
            _settings(data["settings"]),
        )


@dataclass(frozen=True)
class PBRTextureAssign:
    material_name: str
    expected_shader_revision: str
    channel: str
    image_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"material_name", "expected_shader_revision", "channel", "image_name"})
        return cls(
            object_name(data["material_name"]),
            string(data["expected_shader_revision"], "expected_shader_revision", limit=64),
            _channel(data["channel"]),
            string(data["image_name"], "image_name", limit=128),
        )


@dataclass(frozen=True)
class PBRTextureClear:
    material_name: str
    expected_shader_revision: str
    channel: str

    @classmethod
    def parse(cls, data):
        fields(data, {"material_name", "expected_shader_revision", "channel"})
        return cls(
            object_name(data["material_name"]),
            string(data["expected_shader_revision"], "expected_shader_revision", limit=64),
            _channel(data["channel"]),
        )


class MaterialNodeOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.bpy = objects.bpy

    def _material(self, name):
        material = self.bpy.data.materials.get(name)
        if material is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Material not found")
        if getattr(material, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local material datablock required")
        if not bool(material.use_nodes) or material.node_tree is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Node-enabled material required")
        if len(material.node_tree.nodes) > MAX_SHADER_NODES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shader node work limit exceeded")
        if len(material.node_tree.links) > MAX_SHADER_LINKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shader link work limit exceeded")
        return material

    @staticmethod
    def _principled(material):
        nodes = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
        if len(nodes) != 1:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Exactly one Principled BSDF is required")
        return nodes[0]

    @staticmethod
    def _socket(table, name):
        try:
            return table[name]
        except (KeyError, TypeError) as exc:
            raise AgentError(
                ErrorCode.UNSUPPORTED_OPERATION,
                f"Required shader socket is unavailable: {name}",
            ) from exc

    @staticmethod
    def _value(value):
        if isinstance(value, (int, float, bool, str)) or value is None:
            return value
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _node_name(channel):
        return f"{MANAGED_PREFIX}TEX_{channel}"

    @staticmethod
    def _link_key(link):
        return [
            str(link.from_node.name),
            str(link.from_socket.name),
            str(link.to_node.name),
            str(link.to_socket.name),
        ]

    def _snapshot(self, material):
        shader = self._principled(material)
        tree = material.node_tree
        node_rows = []
        managed = {}
        for node in tree.nodes:
            image = getattr(node, "image", None)
            row = {
                "name": str(node.name),
                "type": str(node.type),
                "image": str(image.name) if image is not None else None,
            }
            node_rows.append(row)
            if str(node.name).startswith(MANAGED_PREFIX):
                managed[str(node.name)] = row

        principled = {}
        for key, socket_name in PRINCIPLED_INPUTS.items():
            socket = self._socket(shader.inputs, socket_name)
            principled[key] = self._value(socket.default_value)

        normal = tree.nodes.get(NORMAL_NODE)
        bump = tree.nodes.get(BUMP_NODE)
        auxiliary = {
            "normal_strength": (
                float(self._socket(normal.inputs, "Strength").default_value) if normal else None
            ),
            "height_strength": (
                float(self._socket(bump.inputs, "Strength").default_value) if bump else None
            ),
            "height_distance": (
                float(self._socket(bump.inputs, "Distance").default_value) if bump else None
            ),
        }
        links = sorted(self._link_key(link) for link in tree.links)
        textures = {}
        for channel, (_, _, expected_space) in CHANNELS.items():
            node = tree.nodes.get(self._node_name(channel))
            image = getattr(node, "image", None) if node is not None else None
            image_name = str(image.name) if image is not None else None
            colorspace = (
                str(image.colorspace_settings.name)
                if image is not None and getattr(image, "colorspace_settings", None) is not None
                else None
            )
            textures[channel] = {
                "node_present": node is not None,
                "image_name": image_name,
                "colorspace": colorspace,
                "expected_colorspace": expected_space,
                "wired": any(link.from_node is node for link in tree.links)
                if node is not None
                else False,
            }

        base = {
            "material_name": str(material.name),
            "node_count": len(tree.nodes),
            "link_count": len(tree.links),
            "nodes": sorted(node_rows, key=lambda item: (item["name"], item["type"])),
            "links": links,
            "principled": principled,
            "auxiliary": auxiliary,
            "textures": textures,
        }
        base["shader_revision"] = revision(base)
        return base

    @staticmethod
    def _links_into(tree, socket):
        return [link for link in tree.links if link.to_socket is socket]

    @staticmethod
    def _is_managed(node):
        return str(node.name).startswith(MANAGED_PREFIX)

    def _clear_input_links(self, tree, socket):
        links = self._links_into(tree, socket)
        unmanaged = [link for link in links if not self._is_managed(link.from_node)]
        if unmanaged:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Refusing to replace an unmanaged shader link",
            )
        for link in links:
            tree.links.remove(link)

    def _ensure_node(self, tree, name, node_type):
        node = tree.nodes.get(name)
        if node is not None:
            if node.type != node_type:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Managed node name has unexpected type")
            return node, False
        if len(tree.nodes) >= MAX_SHADER_NODES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shader node work limit reached")
        idname = {
            "TEX_IMAGE": "ShaderNodeTexImage",
            "NORMAL_MAP": "ShaderNodeNormalMap",
            "BUMP": "ShaderNodeBump",
        }[node_type]
        node = tree.nodes.new(idname)
        node.name = name
        node.label = name
        return node, True

    def _ensure_link(self, tree, from_socket, to_socket):
        self._clear_input_links(tree, to_socket)
        if len(tree.links) >= MAX_SHADER_LINKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shader link work limit reached")
        tree.links.new(from_socket, to_socket)

    def _rewire_normal_chain(self, material):
        tree = material.node_tree
        shader = self._principled(material)
        normal = tree.nodes.get(NORMAL_NODE)
        bump = tree.nodes.get(BUMP_NODE)
        target = self._socket(shader.inputs, "Normal")
        self._clear_input_links(tree, target)
        if bump is not None:
            if normal is not None:
                self._ensure_link(
                    tree,
                    self._socket(normal.outputs, "Normal"),
                    self._socket(bump.inputs, "Normal"),
                )
            self._ensure_link(
                tree,
                self._socket(bump.outputs, "Normal"),
                target,
            )
        elif normal is not None:
            self._ensure_link(
                tree,
                self._socket(normal.outputs, "Normal"),
                target,
            )

    def _capture(self, material):
        tree = material.node_tree
        shader = self._principled(material)
        direct = {
            name: self._value(self._socket(shader.inputs, socket_name).default_value)
            for name, socket_name in PRINCIPLED_INPUTS.items()
        }
        managed_nodes = []
        for node in tree.nodes:
            if not self._is_managed(node):
                continue
            image = getattr(node, "image", None)
            managed_nodes.append(
                {
                    "name": str(node.name),
                    "type": str(node.type),
                    "image": str(image.name) if image is not None else None,
                    "inputs": {
                        str(socket.name): self._value(socket.default_value)
                        for socket in node.inputs
                    },
                }
            )
        managed_names = {row["name"] for row in managed_nodes}
        managed_links = [
            self._link_key(link)
            for link in tree.links
            if str(link.from_node.name) in managed_names or str(link.to_node.name) in managed_names
        ]
        return {
            "direct": direct,
            "managed_nodes": managed_nodes,
            "managed_links": managed_links,
        }

    def _restore(self, material, state):
        tree = material.node_tree
        shader = self._principled(material)
        for node in list(tree.nodes):
            if self._is_managed(node):
                tree.nodes.remove(node)
        for key, socket_name in PRINCIPLED_INPUTS.items():
            self._socket(shader.inputs, socket_name).default_value = state["direct"][key]

        by_name = {str(node.name): node for node in tree.nodes}
        for row in state["managed_nodes"]:
            node, _ = self._ensure_node(tree, row["name"], row["type"])
            image_name = row["image"]
            if image_name is not None:
                image = self.bpy.data.images.get(image_name)
                if image is None:
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Recovery image is missing")
                node.image = image
            for socket_name, value in row["inputs"].items():
                socket = node.inputs.get(socket_name)
                if socket is not None:
                    socket.default_value = value
            by_name[row["name"]] = node

        for from_node, from_socket, to_node, to_socket in state["managed_links"]:
            source_node = by_name.get(from_node)
            target_node = by_name.get(to_node)
            if source_node is None or target_node is None:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Recovery node is missing")
            source = source_node.outputs.get(from_socket)
            target = target_node.inputs.get(to_socket)
            if source is None or target is None:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Recovery socket is missing")
            tree.links.new(source, target)

    def inspect(self, request: Request, action: ShaderInspect):
        material = self._material(action.material_name)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._snapshot(material),
        )

    def principled_set(self, request: Request, action: PrincipledSet):
        material = self._material(action.material_name)
        before = self._snapshot(material)
        require_revision(action.expected_shader_revision, before["shader_revision"])
        restore = self._capture(material)
        shader = self._principled(material)
        tree = material.node_tree

        try:
            for key, value in action.settings.items():
                if key in PRINCIPLED_INPUTS:
                    self._socket(shader.inputs, PRINCIPLED_INPUTS[key]).default_value = value

            if "normal_strength" in action.settings:
                normal, _ = self._ensure_node(tree, NORMAL_NODE, "NORMAL_MAP")
                self._socket(normal.inputs, "Strength").default_value = action.settings[
                    "normal_strength"
                ]
                self._rewire_normal_chain(material)

            if "height_strength" in action.settings or "height_distance" in action.settings:
                bump, _ = self._ensure_node(tree, BUMP_NODE, "BUMP")
                if "height_strength" in action.settings:
                    self._socket(bump.inputs, "Strength").default_value = action.settings[
                        "height_strength"
                    ]
                if "height_distance" in action.settings:
                    self._socket(bump.inputs, "Distance").default_value = action.settings[
                        "height_distance"
                    ]
                self._rewire_normal_chain(material)

            self.bpy.context.view_layer.update()
            after = self._snapshot(material)
            expected = {"material_name": action.material_name}
            actual = {"material_name": after["material_name"]}
            for key, value in action.settings.items():
                if key in PRINCIPLED_INPUTS:
                    expected[key] = value
                    actual[key] = after["principled"][key]
                else:
                    expected[key] = value
                    actual[key] = after["auxiliary"][key]
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after},
                    verification=verification.to_dict(),
                )

            self._restore(material, restore)
            self.bpy.context.view_layer.update()
            restored = self._snapshot(material)
            recovery = compare(
                {"shader_revision": before["shader_revision"]},
                {"shader_revision": restored["shader_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Principled shader recovery could not be verified",
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
                    "Principled shader readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            self._restore(material, restore)
            self.bpy.context.view_layer.update()
            raise

    def _texture_verification(self, snapshot, channel):
        return snapshot["textures"][channel]

    def pbr_assign(self, request: Request, action: PBRTextureAssign):
        material = self._material(action.material_name)
        before = self._snapshot(material)
        require_revision(action.expected_shader_revision, before["shader_revision"])
        image = self.bpy.data.images.get(action.image_name)
        if image is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Image datablock not found")
        if getattr(image, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local image datablock required")
        _, output_name, expected_space = CHANNELS[action.channel]
        actual_space = str(image.colorspace_settings.name)
        if actual_space != expected_space:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                f"{action.channel} requires {expected_space} color space",
            )

        restore = self._capture(material)
        tree = material.node_tree
        shader = self._principled(material)
        try:
            node, _ = self._ensure_node(
                tree,
                self._node_name(action.channel),
                "TEX_IMAGE",
            )
            node.image = image
            source = self._socket(node.outputs, output_name)
            target_name = CHANNELS[action.channel][0]

            if action.channel == "NORMAL":
                normal, _ = self._ensure_node(tree, NORMAL_NODE, "NORMAL_MAP")
                self._ensure_link(tree, source, self._socket(normal.inputs, "Color"))
                self._rewire_normal_chain(material)
            elif action.channel == "HEIGHT":
                bump, _ = self._ensure_node(tree, BUMP_NODE, "BUMP")
                self._ensure_link(tree, source, self._socket(bump.inputs, "Height"))
                self._rewire_normal_chain(material)
            elif target_name is not None:
                self._ensure_link(tree, source, self._socket(shader.inputs, target_name))

            self.bpy.context.view_layer.update()
            after = self._snapshot(material)
            expected = {
                "node_present": True,
                "image_name": action.image_name,
                "colorspace": expected_space,
                "expected_colorspace": expected_space,
                "wired": action.channel != "AO",
            }
            actual = self._texture_verification(after, action.channel)
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "channel": action.channel,
                        "ao_auxiliary_only": action.channel == "AO",
                    },
                    verification=verification.to_dict(),
                )

            self._restore(material, restore)
            self.bpy.context.view_layer.update()
            restored = self._snapshot(material)
            recovery = compare(
                {"shader_revision": before["shader_revision"]},
                {"shader_revision": restored["shader_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "PBR texture recovery could not be verified",
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
                    "PBR texture readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            self._restore(material, restore)
            self.bpy.context.view_layer.update()
            raise

    def pbr_clear(self, request: Request, action: PBRTextureClear):
        material = self._material(action.material_name)
        before = self._snapshot(material)
        require_revision(action.expected_shader_revision, before["shader_revision"])
        tree = material.node_tree
        node = tree.nodes.get(self._node_name(action.channel))
        if node is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Managed PBR texture channel is not assigned")
        restore = self._capture(material)

        try:
            tree.nodes.remove(node)
            if action.channel in {"NORMAL", "HEIGHT"}:
                self._rewire_normal_chain(material)
            self.bpy.context.view_layer.update()
            after = self._snapshot(material)
            expected = {"node_present": False, "image_name": None, "wired": False}
            row = self._texture_verification(after, action.channel)
            actual = {
                "node_present": row["node_present"],
                "image_name": row["image_name"],
                "wired": row["wired"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after, "channel": action.channel},
                    verification=verification.to_dict(),
                )

            self._restore(material, restore)
            self.bpy.context.view_layer.update()
            restored = self._snapshot(material)
            recovery = compare(
                {"shader_revision": before["shader_revision"]},
                {"shader_revision": restored["shader_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "PBR texture clear recovery could not be verified",
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
                    "PBR texture clear readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            self._restore(material, restore)
            self.bpy.context.view_layer.update()
            raise

    def tools(self):
        return [
            Tool(
                "material.shader_inspect",
                SafetyClass.READ_ONLY,
                ShaderInspect.parse,
                self.inspect,
            ),
            Tool(
                "material.principled_set",
                SafetyClass.MUTATION,
                PrincipledSet.parse,
                self.principled_set,
            ),
            Tool(
                "material.pbr_texture_assign",
                SafetyClass.MUTATION,
                PBRTextureAssign.parse,
                self.pbr_assign,
            ),
            Tool(
                "material.pbr_texture_clear",
                SafetyClass.MUTATION,
                PBRTextureClear.parse,
                self.pbr_clear,
            ),
        ]
