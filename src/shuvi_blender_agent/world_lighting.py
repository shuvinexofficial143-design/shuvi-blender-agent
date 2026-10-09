"""Level 9 M5: owned, reversible Blender World nodes with loaded HDRI support."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, number, string
from .verification import compare

WORLD_OUTPUT = "SHUVI_WORLD_OUTPUT"
WORLD_BACKGROUND = "SHUVI_WORLD_BACKGROUND"
WORLD_ENVIRONMENT = "SHUVI_WORLD_ENVIRONMENT"


@dataclass(frozen=True)
class WorldPreview:
    name: str
    mode: str
    strength: float
    color: tuple[float, float, float] | None
    image_name: str | None

    @classmethod
    def parse(cls, data):
        fields(data, {"name", "mode", "strength"}, {"color", "image_name"})
        name = object_name(data["name"])
        if len(name) > 48:
            raise invalid("World name too long")
        mode = string(data["mode"], "mode", limit=12)
        if mode not in ("COLOR", "HDRI"):
            raise invalid("Expected COLOR or HDRI")
        strength = number(data["strength"], "strength", 0, 10)
        if mode == "COLOR":
            if "image_name" in data or "color" not in data:
                raise invalid("COLOR requires color and forbids image_name")
            rgb = data["color"]
            if not isinstance(rgb, list) or len(rgb) != 3:
                raise invalid("World color must contain three numeric channels")
            color = tuple(number(v, "world color", 0, 1) for v in rgb)
            return cls(name, mode, strength, color, None)
        if "color" in data or "image_name" not in data:
            raise invalid("HDRI requires an existing image_name and forbids color")
        return cls(name, mode, strength, None, string(data["image_name"], "image_name", limit=128))


@dataclass(frozen=True)
class WorldApply:
    preview: WorldPreview
    expected_world_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"name", "mode", "strength", "expected_world_revision"},
            {"color", "image_name"},
        )
        return cls(
            WorldPreview.parse({k: v for k, v in data.items() if k != "expected_world_revision"}),
            string(data["expected_world_revision"], "expected_world_revision", limit=64),
        )


@dataclass(frozen=True)
class WorldRelease:
    expected_world_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_world_token"})
        return cls(string(data["expected_world_token"], "expected_world_token", limit=64))


class WorldLightingOperations:
    """Never alters/deletes a foreign World; owns only a newly created World."""

    def __init__(self, objects: ObjectOperations):
        self.bpy = objects.bpy
        self.inspector = objects.inspector
        self._owned = {}

    @staticmethod
    def _pointer(obj):
        return int(obj.as_pointer()) if hasattr(obj, "as_pointer") else id(obj)

    def _is_world(self, world):
        return any(self._pointer(w) == self._pointer(world) for w in self.bpy.data.worlds)

    @staticmethod
    def _image_read(image):
        return {
            "name": str(image.name),
            "size": [int(v) for v in image.size],
            "has_data": bool(getattr(image, "has_data", False)),
            "source": str(getattr(image, "source", "")),
        }

    def _loaded_hdri(self, name):
        image = self.bpy.data.images.get(name)
        if image is None:
            raise AgentError(ErrorCode.NOT_FOUND, "HDRI image is not loaded in Blender")
        snap = self._image_read(image)
        width, height = snap["size"]
        if (
            not snap["has_data"]
            or snap["source"] not in ("FILE", "TILED")
            or not 32 <= height <= 16384
            or width != 2 * height
            or getattr(image, "library", None) is not None
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "HDRI must be a local, loaded 2:1 equirectangular image",
            )
        return image, snap

    def _plan(self, action: WorldPreview):
        scene = self.bpy.context.scene
        image, image_state = (self._loaded_hdri(action.image_name) if action.image_name else (None, None))
        before = scene.world
        blockers = []
        if self._owned:
            blockers.append("WORLD_ALREADY_MANAGED")
        if self.bpy.data.worlds.get(action.name) is not None:
            blockers.append("WORLD_NAME_COLLISION")
        if self.bpy.context.mode != "OBJECT":
            blockers.append("OBJECT_MODE_REQUIRED")
        if len(self.bpy.data.worlds) >= 256:
            blockers.append("WORLD_DATABLOCK_LIMIT")
        plan = {
            "name": action.name,
            "mode": action.mode,
            "strength": action.strength,
            "color": list(action.color) if action.color is not None else None,
            "image_name": action.image_name,
            "image_state": image_state,
            "image_pointer": self._pointer(image) if image else None,
            "original_world_name": before.name if before is not None else None,
            "original_world_pointer": self._pointer(before) if before else None,
            "scene_revision": self.inspector.summary()["revision"],
            "blockers": sorted(blockers),
            "ready": not blockers,
            "source_only": True,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["world_revision"] = revision(plan)
        return image, before, plan

    def preview(self, request: Request, action: WorldPreview):
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[2])

    def _read(self, world):
        if world.node_tree is None or not world.use_nodes:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "World nodes are not enabled")
        nodes = world.node_tree.nodes
        output = nodes.get(WORLD_OUTPUT)
        background = nodes.get(WORLD_BACKGROUND)
        environment = nodes.get(WORLD_ENVIRONMENT)
        if output is None or background is None:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Managed World nodes missing")
        links = sorted(
            (
                str(link.from_node.name),
                str(link.from_socket.name),
                str(link.to_node.name),
                str(link.to_socket.name),
            )
            for link in world.node_tree.links
        )
        return {
            "name": world.name,
            "node_count": len(nodes),
            "node_types": sorted((n.name, n.type) for n in nodes),
            "links": links,
            "strength": float(background.inputs["Strength"].default_value),
            "color": list(background.inputs["Color"].default_value),
            "image_name": environment.image.name if environment and environment.image else None,
            "image_pointer": (
                self._pointer(environment.image) if environment and environment.image else None
            ),
            "projection": environment.projection if environment else None,
        }

    @staticmethod
    def _expected(plan):
        types = [
            (WORLD_BACKGROUND, "BACKGROUND"),
            (WORLD_OUTPUT, "OUTPUT_WORLD"),
        ]
        links = [(WORLD_BACKGROUND, "Background", WORLD_OUTPUT, "Surface")]
        if plan["mode"] == "HDRI":
            types.append((WORLD_ENVIRONMENT, "TEX_ENVIRONMENT"))
            links.append((WORLD_ENVIRONMENT, "Color", WORLD_BACKGROUND, "Color"))
        return {
            "name": plan["name"],
            "node_count": len(types),
            "node_types": sorted(types),
            "links": sorted(links),
            "strength": plan["strength"],
            "color": [1.0, 1.0, 1.0, 1.0] if plan["mode"] == "HDRI" else plan["color"] + [1.0],
            "image_name": plan["image_name"],
            "image_pointer": plan["image_pointer"],
            "projection": "EQUIRECTANGULAR" if plan["mode"] == "HDRI" else None,
        }

    def _clean(self, new_world, original, scene_revision):
        scene = self.bpy.context.scene
        scene.world = original
        if new_world is not None and self._is_world(new_world):
            self.bpy.data.worlds.remove(new_world, do_unlink=True)
        self.bpy.context.view_layer.update()
        if (
            scene.world is not original
            or (new_world is not None and self._is_world(new_world))
            or self.inspector.summary()["revision"] != scene_revision
        ):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "World restoration unverified")

    def apply(self, request: Request, action: WorldApply):
        image, original, plan = self._plan(action.preview)
        if plan["world_revision"] != action.expected_world_revision:
            raise AgentError(ErrorCode.STALE_STATE, "World lighting changed since preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "World setup blocked")
        new_world = None
        try:
            new_world = self.bpy.data.worlds.new(plan["name"])
            new_world.use_nodes = True
            tree = new_world.node_tree
            for node in list(tree.nodes):
                tree.nodes.remove(node)
            output = tree.nodes.new("ShaderNodeOutputWorld")
            output.name = WORLD_OUTPUT
            background = tree.nodes.new("ShaderNodeBackground")
            background.name = WORLD_BACKGROUND
            background.inputs["Strength"].default_value = plan["strength"]
            if plan["mode"] == "COLOR":
                background.inputs["Color"].default_value = plan["color"] + [1.0]
            else:
                environment = tree.nodes.new("ShaderNodeTexEnvironment")
                environment.name = WORLD_ENVIRONMENT
                environment.image = image
                environment.projection = "EQUIRECTANGULAR"
                tree.links.new(environment.outputs["Color"], background.inputs["Color"])
            tree.links.new(background.outputs["Background"], output.inputs["Surface"])
            self.bpy.context.scene.world = new_world
            self.bpy.context.view_layer.update()
            expected = self._expected(plan)
            checked = compare(expected, self._read(new_world))
            if checked.matched and self.bpy.context.scene.world is new_world:
                token = revision({
                    "scene": plan["scene_revision"],
                    "new_world": self._pointer(new_world),
                    "original": plan["original_world_pointer"],
                    "expected": expected,
                })
                self._owned[token] = {
                    "new": new_world,
                    "before": original,
                    "scene_revision": plan["scene_revision"],
                    "expected": expected,
                    "image": image,
                }
                return Result(
                    request.request_id, request.command_id, Status.VERIFIED,
                    {"world_token": token, "mode": plan["mode"], "source_only": True, "render_verified": False},
                    verification=checked.to_dict(),
                )
        except Exception as exc:
            try:
                self._clean(new_world, original, plan["scene_revision"])
            except Exception as recovery_exc:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "World rollback not verified") from recovery_exc
            raise AgentError(ErrorCode.EXECUTION_ERROR, "World setup interrupted; original world restored") from exc
        self._clean(new_world, original, plan["scene_revision"])
        return Result(
            request.request_id, request.command_id, Status.FAILED,
            {"rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "World node graph readback mismatch"),
            checked.to_dict(),
        )

    def release(self, request: Request, action: WorldRelease):
        owned = self._owned.get(action.expected_world_token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown/foreign World ownership token")
        current = owned["new"]
        before = owned["before"]
        if (
            not self._is_world(current)
            or self.bpy.context.scene.world is not current
            or (before is not None and not self._is_world(before))
            or self.inspector.summary()["revision"] != owned["scene_revision"]
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "World/scene changed since setup")
        try:
            checked = compare(owned["expected"], self._read(current))
        except (AttributeError, KeyError, AgentError) as exc:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed World graph was edited") from exc
        if not checked.matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed World graph was modified")
        if owned["image"] is not None:
            same_image = self.bpy.data.images.get(owned["image"].name) is owned["image"]
            if not same_image or not self._image_read(owned["image"])["has_data"]:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Managed HDRI was replaced/unloaded")
        # Only the same-session newly created world is removed.
        self._clean(current, before, owned["scene_revision"])
        del self._owned[action.expected_world_token]
        return Result(
            request.request_id, request.command_id, Status.VERIFIED,
            {"restored_original_world": True, "removed_owned_world": True},
            verification=compare({"restored": True}, {"restored": True}).to_dict(),
        )

    def tools(self):
        return [
            Tool("lighting.world_preview", SafetyClass.READ_ONLY, WorldPreview.parse, self.preview),
            Tool("lighting.world_apply", SafetyClass.MUTATION, WorldApply.parse, self.apply),
            Tool("lighting.world_release", SafetyClass.MUTATION, WorldRelease.parse, self.release),
        ]
