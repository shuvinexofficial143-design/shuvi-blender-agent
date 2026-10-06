"""Level 4 milestones 9-10: advanced texture planning, QA, recovery and acceptance."""

from dataclasses import dataclass
from math import floor

from .appearance import color
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .material_nodes import (
    BUMP_NODE,
    CHANNELS,
    MANAGED_PREFIX,
    NORMAL_NODE,
    PRINCIPLED_INPUTS,
    MaterialNodeOperations,
)
from .material_slots import MaterialSlotOperations
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .uv import UVOperations
from .validation import fields, integer, invalid, number, string
from .verification import compare

MAX_UDIM_TILES = 256
MAX_RECOVERY_NODES = 9
MAX_RECOVERY_LINKS = 16
MAX_TEXTURE_SIZE = 32768

_ALLOWED_MANAGED_TYPES = {
    NORMAL_NODE: "NORMAL_MAP",
    BUMP_NODE: "BUMP",
    **{f"{MANAGED_PREFIX}TEX_{channel}": "TEX_IMAGE" for channel in CHANNELS},
}


def _material(value):
    return object_name(value)


def _layer(value):
    return string(value, "uv_layer_name", limit=63)


def _channels(value):
    if not isinstance(value, list) or not 1 <= len(value) <= len(CHANNELS):
        raise invalid("channels requires 1..7 channel names")
    parsed = tuple(string(item, "channel", limit=24) for item in value)
    if len(set(parsed)) != len(parsed) or any(item not in CHANNELS for item in parsed):
        raise invalid("channels must be unique supported PBR channels")
    return parsed


@dataclass(frozen=True)
class ImageInspect:
    image_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"image_name"})
        return cls(string(data["image_name"], "image_name", limit=128))


@dataclass(frozen=True)
class MaterialOnly:
    material_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"material_name"})
        return cls(_material(data["material_name"]))


@dataclass(frozen=True)
class UDIMPlan:
    object_id: str
    uv_layer_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "uv_layer_name"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _layer(data["uv_layer_name"]),
        )


@dataclass(frozen=True)
class BakePrep:
    object_id: str
    material_name: str
    uv_layer_name: str
    channels: tuple[str, ...]
    texture_size: int

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"object_id", "material_name", "uv_layer_name", "channels", "texture_size"},
        )
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _material(data["material_name"]),
            _layer(data["uv_layer_name"]),
            _channels(data["channels"]),
            integer(data["texture_size"], "texture_size", 16, MAX_TEXTURE_SIZE),
        )


@dataclass(frozen=True)
class AssetScope:
    object_id: str
    material_name: str
    uv_layer_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "material_name", "uv_layer_name"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _material(data["material_name"]),
            _layer(data["uv_layer_name"]),
        )


def _recovery_principled(data):
    fields(data, set(PRINCIPLED_INPUTS))
    return {
        "base_color": list(color(data["base_color"], 4)),
        "metallic": number(data["metallic"], "metallic", 0, 1),
        "roughness": number(data["roughness"], "roughness", 0, 1),
        "transmission": number(data["transmission"], "transmission", 0, 1),
        "emission_color": list(color(data["emission_color"], 4)),
        "emission_strength": number(data["emission_strength"], "emission_strength", 0, 1000),
        "alpha": number(data["alpha"], "alpha", 0, 1),
    }


def _optional_number(value, name, low, high):
    if value is None:
        return None
    return number(value, name, low, high)


def _recovery_state(data):
    fields(data, {"principled", "auxiliary", "textures"})
    auxiliary = fields(
        data["auxiliary"],
        {"normal_strength", "height_strength", "height_distance"},
    )
    textures = fields(data["textures"], set(CHANNELS))
    parsed_textures = {}
    for channel, image_name in textures.items():
        parsed_textures[channel] = (
            None if image_name is None else string(image_name, "image_name", limit=128)
        )
    return {
        "principled": _recovery_principled(data["principled"]),
        "auxiliary": {
            "normal_strength": _optional_number(
                auxiliary["normal_strength"], "normal_strength", 0, 10
            ),
            "height_strength": _optional_number(
                auxiliary["height_strength"], "height_strength", 0, 10
            ),
            "height_distance": _optional_number(
                auxiliary["height_distance"], "height_distance", 0, 100
            ),
        },
        "textures": parsed_textures,
    }


@dataclass(frozen=True)
class RecoveryRestore:
    material_name: str
    expected_shader_revision: str
    recovery_revision: str
    state: dict

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "material_name",
                "expected_shader_revision",
                "recovery_revision",
                "state",
            },
        )
        state = _recovery_state(data["state"])
        supplied = string(data["recovery_revision"], "recovery_revision", limit=64)
        if supplied != revision(state):
            raise invalid("recovery_revision does not match recovery state")
        return cls(
            _material(data["material_name"]),
            string(data["expected_shader_revision"], "expected_shader_revision", limit=64),
            supplied,
            state,
        )


class TextureWorkflowOperations(MaterialNodeOperations):
    def __init__(self, objects: ObjectOperations):
        super().__init__(objects)
        self.inspector = objects.inspector
        self.uv = UVOperations(objects)
        self.slots = MaterialSlotOperations(objects)

    def _image(self, name):
        image = self.bpy.data.images.get(name)
        if image is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Image datablock not found")
        if getattr(image, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local image datablock required")
        return image

    @staticmethod
    def _image_size(image):
        size = list(getattr(image, "size", []) or [])
        if len(size) < 2:
            return [0, 0]
        return [int(size[0]), int(size[1])]

    def _image_summary(self, image):
        tiles = getattr(image, "tiles", None)
        tile_numbers = []
        if tiles is not None:
            for item in list(tiles)[:MAX_UDIM_TILES]:
                number_value = getattr(item, "number", None)
                if isinstance(number_value, int):
                    tile_numbers.append(number_value)
        source = str(getattr(image, "source", "GENERATED"))
        summary = {
            "image_name": str(image.name),
            "size": self._image_size(image),
            "colorspace": str(image.colorspace_settings.name),
            "source": source,
            "is_tiled": source == "TILED",
            "tile_numbers": sorted(set(tile_numbers)),
            "packed": getattr(image, "packed_file", None) is not None,
            "has_filepath": bool(str(getattr(image, "filepath", ""))),
        }
        summary["image_revision"] = revision(summary)
        return summary

    def image_inspect(self, request: Request, action: ImageInspect):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._image_summary(self._image(action.image_name)),
        )

    def _uv_layer(self, obj, layer_name):
        mesh, _, _, _ = self.uv._mesh(obj)
        layer = None
        getter = getattr(mesh.uv_layers, "get", None)
        if callable(getter):
            layer = getter(layer_name)
        if layer is None:
            layer = next((item for item in mesh.uv_layers if str(item.name) == layer_name), None)
        if layer is None:
            raise AgentError(ErrorCode.NOT_FOUND, "UV layer not found")
        loop_count = sum(len(face.vertices) for face in mesh.polygons)
        return mesh, layer, self.uv._layer_face_uvs(mesh, layer, loop_count)

    @staticmethod
    def _tile_axis(low, high, maximum):
        if low < 0 or high < 0:
            return None
        epsilon = 1e-9
        lower = floor(low + epsilon)
        upper = floor(high - epsilon) if high - low > epsilon else floor(high + epsilon)
        if lower != upper or not 0 <= lower <= maximum:
            return None
        return lower

    def _udim_data(self, obj, layer_name):
        _, _, face_uvs = self._uv_layer(obj, layer_name)
        face_tiles = []
        split_faces = []
        invalid_faces = []
        tiles = set()
        for face_index, uvs in enumerate(face_uvs):
            minimum = [min(float(uv[axis]) for uv in uvs) for axis in range(2)]
            maximum = [max(float(uv[axis]) for uv in uvs) for axis in range(2)]
            tile_u = self._tile_axis(minimum[0], maximum[0], 9)
            tile_v = self._tile_axis(minimum[1], maximum[1], 99)
            tile = None
            if tile_u is None or tile_v is None:
                if any(value < 0 for value in minimum) or maximum[0] > 10 or maximum[1] > 100:
                    invalid_faces.append(face_index)
                else:
                    split_faces.append(face_index)
            else:
                tile = 1001 + tile_u + 10 * tile_v
                tiles.add(tile)
            face_tiles.append({"face_index": face_index, "tile": tile})
        if len(tiles) > MAX_UDIM_TILES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "UDIM tile work limit exceeded")
        return {
            "tiles": sorted(tiles),
            "face_tiles": face_tiles,
            "split_face_indices": split_faces,
            "invalid_face_indices": invalid_faces,
        }

    def udim_plan(self, request: Request, action: UDIMPlan):
        obj = self.inspector.resolve(action.object_id)
        uv_snapshot = self.uv.snapshot(obj)
        data = self._udim_data(obj, action.uv_layer_name)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "object_id": uv_snapshot["object_id"],
                "geometry_revision": uv_snapshot["geometry_revision"],
                "uv_revision": uv_snapshot["uv_revision"],
                "uv_layer_name": action.uv_layer_name,
                "tile_count": len(data["tiles"]),
                **data,
                "execution_status": "UDIM_SOURCE_PLAN_ONLY",
                "runtime_udim_verified": False,
            },
        )

    @staticmethod
    def _link_exists(tree, from_node, from_socket, to_node, to_socket):
        return any(
            link.from_node is from_node
            and str(link.from_socket.name) == from_socket
            and link.to_node is to_node
            and str(link.to_socket.name) == to_socket
            for link in tree.links
        )

    def _channel_qa_data(self, material):
        snapshot = self._snapshot(material)
        tree = material.node_tree
        shader = self._principled(material)
        checks = []
        blockers = []
        advisories = []
        present_count = 0

        for channel, (target_name, output_name, expected_space) in CHANNELS.items():
            node = tree.nodes.get(self._node_name(channel))
            if node is None:
                checks.append(
                    {
                        "channel": channel,
                        "status": "ABSENT",
                        "image_name": None,
                        "colorspace": None,
                    }
                )
                continue
            present_count += 1
            image = getattr(node, "image", None)
            problems = []
            if image is None:
                problems.append("MISSING_IMAGE")
            else:
                known = self.bpy.data.images.get(str(image.name))
                if known is not image:
                    problems.append("MISSING_IMAGE_DATABLOCK")
                if str(image.colorspace_settings.name) != expected_space:
                    problems.append("COLORSPACE_MISMATCH")

            wired = False
            if channel == "NORMAL":
                helper = tree.nodes.get(NORMAL_NODE)
                wired = (
                    helper is not None
                    and self._link_exists(tree, node, output_name, helper, "Color")
                )
            elif channel == "HEIGHT":
                helper = tree.nodes.get(BUMP_NODE)
                wired = (
                    helper is not None
                    and self._link_exists(tree, node, output_name, helper, "Height")
                )
            elif channel == "AO":
                wired = not any(link.from_node is node for link in tree.links)
                if not wired:
                    problems.append("AO_UNEXPECTED_OUTGOING_LINK")
            else:
                wired = self._link_exists(tree, node, output_name, shader, target_name)

            if channel != "AO" and not wired:
                problems.append("BROKEN_CHANNEL_LINK")
            status = "PASS" if not problems else "BLOCKED"
            if problems:
                blockers.extend(f"{channel}:{problem}" for problem in problems)
            checks.append(
                {
                    "channel": channel,
                    "status": status,
                    "image_name": str(image.name) if image is not None else None,
                    "colorspace": (
                        str(image.colorspace_settings.name) if image is not None else None
                    ),
                    "expected_colorspace": expected_space,
                    "wiring_ok": wired,
                    "problems": problems,
                }
            )

        normal = tree.nodes.get(NORMAL_NODE)
        bump = tree.nodes.get(BUMP_NODE)
        shader_normal_ok = True
        if bump is not None:
            shader_normal_ok = self._link_exists(tree, bump, "Normal", shader, "Normal")
            if normal is not None:
                normal_to_bump = self._link_exists(tree, normal, "Normal", bump, "Normal")
                if not normal_to_bump:
                    blockers.append("NORMAL_CHAIN:BROKEN_NORMAL_TO_BUMP")
        elif normal is not None:
            shader_normal_ok = self._link_exists(tree, normal, "Normal", shader, "Normal")
        if not shader_normal_ok:
            blockers.append("NORMAL_CHAIN:BROKEN_SHADER_NORMAL_LINK")

        if present_count == 0:
            advisories.append("NO_MANAGED_PBR_TEXTURES")
        return {
            "material_name": str(material.name),
            "shader_revision": snapshot["shader_revision"],
            "managed_texture_count": present_count,
            "checks": checks,
            "blockers": sorted(set(blockers)),
            "advisories": advisories,
            "status": "BLOCKED" if blockers else ("REVIEW" if advisories else "PASS"),
        }

    def channel_qa(self, request: Request, action: MaterialOnly):
        material = self._material(action.material_name)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._channel_qa_data(material),
        )

    def _consistency_data(self, material):
        qa = self._channel_qa_data(material)
        tree = material.node_tree
        dimensions = {}
        channel_images = {}
        invalid_sizes = []
        for channel in CHANNELS:
            node = tree.nodes.get(self._node_name(channel))
            image = getattr(node, "image", None) if node is not None else None
            if image is None:
                continue
            size = self._image_size(image)
            channel_images[channel] = str(image.name)
            dimensions[channel] = size
            if size[0] <= 0 or size[1] <= 0:
                invalid_sizes.append(channel)

        valid_sizes = {tuple(size) for size in dimensions.values() if min(size) > 0}
        resolution_mismatch = len(valid_sizes) > 1
        reused = {}
        for channel, image_name in channel_images.items():
            reused.setdefault(image_name, []).append(channel)
        reused = {
            image_name: channels
            for image_name, channels in reused.items()
            if len(channels) > 1
        }
        blockers = list(qa["blockers"])
        blockers.extend(f"{channel}:INVALID_IMAGE_SIZE" for channel in invalid_sizes)
        advisories = list(qa["advisories"])
        if resolution_mismatch:
            advisories.append("MIXED_TEXTURE_RESOLUTIONS")
        if reused:
            advisories.append("IMAGE_REUSED_ACROSS_CHANNELS")
        return {
            "material_name": str(material.name),
            "shader_revision": qa["shader_revision"],
            "channel_images": channel_images,
            "dimensions": dimensions,
            "resolution_mismatch": resolution_mismatch,
            "reused_images": reused,
            "blockers": sorted(set(blockers)),
            "advisories": sorted(set(advisories)),
            "status": "BLOCKED" if blockers else ("REVIEW" if advisories else "PASS"),
        }

    def consistency_qa(self, request: Request, action: MaterialOnly):
        material = self._material(action.material_name)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._consistency_data(material),
        )

    def _uv_layer_summary(self, obj, layer_name):
        snapshot = self.uv.snapshot(obj)
        layer = next((item for item in snapshot["layers"] if item["name"] == layer_name), None)
        if layer is None:
            raise AgentError(ErrorCode.NOT_FOUND, "UV layer not found")
        return snapshot, layer

    def _bake_data(self, action: BakePrep):
        obj = self.inspector.resolve(action.object_id)
        uv_snapshot, layer = self._uv_layer_summary(obj, action.uv_layer_name)
        material = self._material(action.material_name)
        channel_qa = self._channel_qa_data(material)
        slots = self.slots._snapshot(obj)
        blockers = []
        advisories = []

        if action.material_name not in slots["slot_names"]:
            blockers.append("MATERIAL_NOT_ASSIGNED_TO_OBJECT")
        if layer["degenerate_uv_face_indices"]:
            blockers.append("DEGENERATE_UV_FACES")
        if layer["overlap_face_pairs"]:
            blockers.append("OVERLAPPING_UV_FACES")
        if channel_qa["status"] == "BLOCKED":
            blockers.append("MATERIAL_CHANNEL_QA_BLOCKED")
        for channel in action.channels:
            row = next(item for item in channel_qa["checks"] if item["channel"] == channel)
            if row["status"] == "ABSENT":
                advisories.append(f"{channel}:NO_EXISTING_TARGET_TEXTURE")

        udim = self._udim_data(obj, action.uv_layer_name)
        if udim["split_face_indices"]:
            blockers.append("UV_FACE_SPANS_MULTIPLE_UDIM_TILES")
        if udim["invalid_face_indices"]:
            blockers.append("UV_OUTSIDE_SUPPORTED_UDIM_RANGE")
        return {
            "object_id": uv_snapshot["object_id"],
            "material_name": action.material_name,
            "uv_layer_name": action.uv_layer_name,
            "texture_size": action.texture_size,
            "channels": list(action.channels),
            "geometry_revision": uv_snapshot["geometry_revision"],
            "uv_revision": uv_snapshot["uv_revision"],
            "shader_revision": channel_qa["shader_revision"],
            "udim_tiles": udim["tiles"],
            "blockers": sorted(set(blockers)),
            "advisories": sorted(set(advisories)),
            "status": "BLOCKED" if blockers else ("REVIEW" if advisories else "READY"),
            "execution_status": "BAKE_PREP_SOURCE_ONLY",
            "runtime_bake_executed": False,
        }

    def bake_prep(self, request: Request, action: BakePrep):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._bake_data(action),
        )

    def recovery_snapshot(self, request: Request, action: MaterialOnly):
        material = self._material(action.material_name)
        snapshot = self._snapshot(material)
        state = {
            "principled": snapshot["principled"],
            "auxiliary": snapshot["auxiliary"],
            "textures": {
                channel: snapshot["textures"][channel]["image_name"] for channel in CHANNELS
            },
        }
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "material_name": action.material_name,
                "shader_revision": snapshot["shader_revision"],
                "state": state,
                "recovery_revision": revision(state),
                "scope": "SHUVI_MANAGED_LEVEL4_MATERIAL_STATE_ONLY",
            },
        )

    def _restore_state(self, material, state):
        tree = material.node_tree
        shader = self._principled(material)
        for node in list(tree.nodes):
            if self._is_managed(node):
                tree.nodes.remove(node)

        for key, socket_name in PRINCIPLED_INPUTS.items():
            self._socket(shader.inputs, socket_name).default_value = state["principled"][key]

        auxiliary = state["auxiliary"]
        if auxiliary["normal_strength"] is not None:
            normal, _ = self._ensure_node(tree, NORMAL_NODE, "NORMAL_MAP")
            self._socket(normal.inputs, "Strength").default_value = auxiliary["normal_strength"]
        if (
            auxiliary["height_strength"] is not None
            or auxiliary["height_distance"] is not None
        ):
            bump, _ = self._ensure_node(tree, BUMP_NODE, "BUMP")
            if auxiliary["height_strength"] is not None:
                self._socket(bump.inputs, "Strength").default_value = auxiliary["height_strength"]
            if auxiliary["height_distance"] is not None:
                self._socket(bump.inputs, "Distance").default_value = auxiliary["height_distance"]

        for channel, image_name in state["textures"].items():
            if image_name is None:
                continue
            image = self._image(image_name)
            _, output_name, expected_space = CHANNELS[channel]
            if str(image.colorspace_settings.name) != expected_space:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    f"Recovery image for {channel} has wrong colorspace",
                )
            node, _ = self._ensure_node(tree, self._node_name(channel), "TEX_IMAGE")
            node.image = image
            source = self._socket(node.outputs, output_name)
            target_name = CHANNELS[channel][0]
            if channel == "NORMAL":
                normal, _ = self._ensure_node(tree, NORMAL_NODE, "NORMAL_MAP")
                self._ensure_link(tree, source, self._socket(normal.inputs, "Color"))
            elif channel == "HEIGHT":
                bump, _ = self._ensure_node(tree, BUMP_NODE, "BUMP")
                self._ensure_link(tree, source, self._socket(bump.inputs, "Height"))
            elif channel == "AO":
                continue
            else:
                self._ensure_link(tree, source, self._socket(shader.inputs, target_name))
        self._rewire_normal_chain(material)

    def recovery_restore(self, request: Request, action: RecoveryRestore):
        material = self._material(action.material_name)
        before = self._snapshot(material)
        require_revision(action.expected_shader_revision, before["shader_revision"])
        fallback = {
            "principled": before["principled"],
            "auxiliary": before["auxiliary"],
            "textures": {
                channel: before["textures"][channel]["image_name"] for channel in CHANNELS
            },
        }
        try:
            self._restore_state(material, action.state)
            self.bpy.context.view_layer.update()
            after = self._snapshot(material)
            expected_state_revision = action.recovery_revision
            actual_state = {
                "principled": after["principled"],
                "auxiliary": after["auxiliary"],
                "textures": {
                    channel: after["textures"][channel]["image_name"] for channel in CHANNELS
                },
            }
            expected = {"recovery_revision": expected_state_revision}
            actual = {"recovery_revision": revision(actual_state)}
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": after,
                        "restored_recovery_revision": action.recovery_revision,
                    },
                    verification=verification.to_dict(),
                )

            self._restore_state(material, fallback)
            self.bpy.context.view_layer.update()
            rolled = self._snapshot(material)
            recovery = compare(
                {"shader_revision": before["shader_revision"]},
                {"shader_revision": rolled["shader_revision"]},
            )
            if not recovery.matched:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Texture recovery restore rollback could not be verified",
                )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "restored": rolled,
                    "rolled_back": True,
                    "recovery_verified": True,
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Recovery state readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            self._restore_state(material, fallback)
            self.bpy.context.view_layer.update()
            raise

    def _asset_qa_data(self, action: AssetScope):
        obj = self.inspector.resolve(action.object_id)
        uv_snapshot, layer = self._uv_layer_summary(obj, action.uv_layer_name)
        material = self._material(action.material_name)
        slots = self.slots._snapshot(obj)
        channel = self._channel_qa_data(material)
        consistency = self._consistency_data(material)
        udim = self._udim_data(obj, action.uv_layer_name)

        checks = [
            {
                "name": "uv_layer",
                "status": "PASS",
                "detail": action.uv_layer_name,
            },
            {
                "name": "uv_degenerate",
                "status": "BLOCKED" if layer["degenerate_uv_face_indices"] else "PASS",
                "detail": layer["degenerate_uv_face_indices"],
            },
            {
                "name": "uv_overlap",
                "status": "BLOCKED" if layer["overlap_face_pairs"] else "PASS",
                "detail": layer["overlap_face_pairs"],
            },
            {
                "name": "udim_faces",
                "status": (
                    "BLOCKED"
                    if udim["split_face_indices"] or udim["invalid_face_indices"]
                    else "PASS"
                ),
                "detail": {
                    "tiles": udim["tiles"],
                    "split_faces": udim["split_face_indices"],
                    "invalid_faces": udim["invalid_face_indices"],
                },
            },
            {
                "name": "material_assignment",
                "status": "PASS" if action.material_name in slots["slot_names"] else "BLOCKED",
                "detail": slots["slot_names"],
            },
            {
                "name": "channel_graph",
                "status": channel["status"],
                "detail": channel["blockers"],
            },
            {
                "name": "texture_consistency",
                "status": consistency["status"],
                "detail": {
                    "blockers": consistency["blockers"],
                    "advisories": consistency["advisories"],
                },
            },
            {
                "name": "managed_texture_present",
                "status": "PASS" if channel["managed_texture_count"] > 0 else "REVIEW",
                "detail": channel["managed_texture_count"],
            },
        ]
        blockers = [item["name"] for item in checks if item["status"] == "BLOCKED"]
        reviews = [item["name"] for item in checks if item["status"] == "REVIEW"]
        return {
            "object_id": uv_snapshot["object_id"],
            "material_name": action.material_name,
            "uv_layer_name": action.uv_layer_name,
            "geometry_revision": uv_snapshot["geometry_revision"],
            "uv_revision": uv_snapshot["uv_revision"],
            "shader_revision": channel["shader_revision"],
            "checks": checks,
            "blockers": blockers,
            "reviews": reviews,
            "status": "BLOCKED" if blockers else ("REVIEW" if reviews else "PASS"),
            "real_runtime_verified": False,
            "production_ready": False,
        }

    def asset_qa(self, request: Request, action: AssetScope):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._asset_qa_data(action),
        )

    def workflow_preview(self, request: Request, action: AssetScope):
        qa = self._asset_qa_data(action)
        stages = [
            "UV diagnostics",
            "seam and unwrap review",
            "UV island pack review",
            "texel-density review",
            "material slot assignment",
            "Principled shader review",
            "PBR channel QA",
            "UDIM and consistency QA",
            "bake preparation",
            "Level 4 source acceptance",
        ]
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                **qa,
                "stages": [
                    {"index": index + 1, "name": name} for index, name in enumerate(stages)
                ],
                "recommended_recovery_before_mutation": True,
                "auto_mutates": False,
                "workflow_scope": "LEVEL_4_SOURCE_PREVIEW_ONLY",
            },
        )

    def level4_acceptance(self, request: Request, action: AssetScope):
        qa = self._asset_qa_data(action)
        checks = {item["name"]: item["status"] for item in qa["checks"]}
        required = (
            "uv_layer",
            "uv_degenerate",
            "uv_overlap",
            "udim_faces",
            "material_assignment",
            "channel_graph",
            "texture_consistency",
            "managed_texture_present",
        )
        blockers = [name for name in required if checks[name] == "BLOCKED"]
        reviews = [name for name in required if checks[name] == "REVIEW"]
        status = "BLOCKED" if blockers else ("REVIEW" if reviews else "PASS")
        acceptance = {
            "checks": [{"name": name, "status": checks[name]} for name in required],
            "blockers": blockers,
            "advisories": reviews,
            "source_acceptance_status": status,
            "scope": "LEVEL_4_SOURCE_AND_FAKE_ADAPTER_ACCEPTANCE_ONLY",
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
            "production_ready": False,
        }
        acceptance["acceptance_revision"] = revision(acceptance)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            acceptance,
        )

    def tools(self):
        return [
            Tool(
                "texture.image_inspect",
                SafetyClass.READ_ONLY,
                ImageInspect.parse,
                self.image_inspect,
            ),
            Tool("texture.udim_plan", SafetyClass.READ_ONLY, UDIMPlan.parse, self.udim_plan),
            Tool("texture.channel_qa", SafetyClass.READ_ONLY, MaterialOnly.parse, self.channel_qa),
            Tool("texture.bake_prep", SafetyClass.READ_ONLY, BakePrep.parse, self.bake_prep),
            Tool(
                "texture.consistency_qa",
                SafetyClass.READ_ONLY,
                MaterialOnly.parse,
                self.consistency_qa,
            ),
            Tool(
                "texture.recovery_snapshot",
                SafetyClass.READ_ONLY,
                MaterialOnly.parse,
                self.recovery_snapshot,
            ),
            Tool(
                "texture.recovery_restore",
                SafetyClass.MUTATION,
                RecoveryRestore.parse,
                self.recovery_restore,
            ),
            Tool("texture.asset_qa", SafetyClass.READ_ONLY, AssetScope.parse, self.asset_qa),
            Tool(
                "texture.workflow_preview",
                SafetyClass.READ_ONLY,
                AssetScope.parse,
                self.workflow_preview,
            ),
            Tool(
                "texture.level4_acceptance",
                SafetyClass.READ_ONLY,
                AssetScope.parse,
                self.level4_acceptance,
            ),
        ]
