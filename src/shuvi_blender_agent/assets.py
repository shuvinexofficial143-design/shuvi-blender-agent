"""Conservative modifiers, additive collections and local asset metadata."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string


def modifier_settings(kind: str, settings: dict) -> dict:
    if kind == "BEVEL":
        fields(settings, {"width", "segments"})
        return {
            "width": number(settings["width"], "width", 0, 100),
            "segments": integer(settings["segments"], "segments", 1, 8),
        }
    if kind == "SUBSURF":
        fields(settings, {"levels", "render_levels"})
        return {key: integer(settings[key], key, 0, 2) for key in settings}
    if kind == "SOLIDIFY":
        fields(settings, {"thickness"})
        return {"thickness": number(settings["thickness"], "thickness", -100, 100)}
    raise invalid("Unsupported modifier type")


@dataclass(frozen=True)
class AddModifier:
    target: ObjectTarget
    name: str
    kind: str
    settings: dict

    @classmethod
    def parse(cls, data: dict) -> "AddModifier":
        fields(data, {"target", "name", "kind", "settings"})
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["name"]),
            data["kind"],
            modifier_settings(data["kind"], data["settings"]),
        )


@dataclass(frozen=True)
class CreateCollection:
    name: str
    expected_scene_revision: str
    target: ObjectTarget | None

    @classmethod
    def parse(cls, data: dict) -> "CreateCollection":
        fields(data, {"name", "expected_scene_revision", "target"})
        return cls(
            object_name(data["name"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
            ObjectTarget.parse(data["target"]) if data["target"] is not None else None,
        )


@dataclass(frozen=True)
class MarkAsset:
    target: ObjectTarget
    description: str

    @classmethod
    def parse(cls, data: dict) -> "MarkAsset":
        fields(data, {"target", "description"})
        description = data["description"]
        if not isinstance(description, str) or len(description) > 1000 or "\x00" in description:
            raise invalid("Asset description must be a string of at most 1000 characters")
        return cls(ObjectTarget.parse(data["target"]), description)


class AssetOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def add_modifier(self, request: Request, action: AddModifier) -> Result:
        obj, before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.type != "MESH" or len(obj.modifiers) >= 64:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Editable mesh with fewer than 64 modifiers required"
            )
        if obj.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already exists")
        if action.kind == "SUBSURF" and len(obj.data.vertices) > 10_000:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subdivision input exceeds mesh work limit")
        modifier = obj.modifiers.new(action.name, action.kind)
        try:
            # Keys come solely from the explicit typed parser above, never user bpy paths.
            for key, value in action.settings.items():
                setattr(modifier, key, value)
            self.bpy.context.view_layer.update()
            after = self.inspector.snapshot(obj)
            after["added_modifier"] = {
                "name": modifier.name,
                "type": modifier.type,
                "settings": {key: getattr(modifier, key) for key in action.settings},
            }
            expected = {
                "added_modifier": {
                    "name": action.name,
                    "type": action.kind,
                    "settings": action.settings,
                }
            }
            result = self.objects._result(request, before, after, expected)
            if result.status == Status.FAILED:
                obj.modifiers.remove(modifier)
                result.data["rolled_back"] = obj.modifiers.get(action.name) is None
            return result
        except Exception:
            if obj.modifiers.get(action.name) == modifier:
                obj.modifiers.remove(modifier)
            raise

    def create_collection(self, request: Request, action: CreateCollection) -> Result:
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        if self.bpy.data.collections.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Collection name already exists")
        root = self.bpy.context.scene.collection
        if len(root.children) >= 64:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Root collection work limit reached")
        obj = None
        before = None
        if action.target is not None:
            obj, before = self.inspector.target(action.target)
            self.objects._editable(obj)
        collection = self.bpy.data.collections.new(action.name)
        try:
            root.children.link(collection)
            if obj is not None:
                collection.objects.link(obj)
            after = {
                "name": collection.name,
                "root_linked": root.children.get(collection.name) == collection,
                "object_id": self.inspector.identity(obj) if obj else None,
                "object_linked": collection.objects.get(obj.name) == obj if obj else None,
            }
            expected = {
                "name": action.name,
                "root_linked": True,
                "object_id": self.inspector.identity(obj) if obj else None,
                "object_linked": True if obj else None,
            }
            result = self.objects._result(request, before, after, expected)
            if result.status == Status.FAILED:
                self.bpy.data.collections.remove(collection)
                result.data["rolled_back"] = self.bpy.data.collections.get(action.name) is None
            return result
        except Exception:
            if self.bpy.data.collections.get(action.name) == collection:
                self.bpy.data.collections.remove(collection)
            raise

    def mark_asset(self, request: Request, action: MarkAsset) -> Result:
        obj, before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.asset_data is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Object is already an asset")
        obj.asset_mark()
        obj.asset_data.description = action.description
        after = self.inspector.snapshot(obj)
        return self.objects._result(
            request, before, after, {"asset": {"marked": True, "description": action.description}}
        )

    def tools(self) -> list[Tool]:
        return [
            Tool("modifier.add", SafetyClass.MUTATION, AddModifier.parse, self.add_modifier),
            Tool(
                "collection.create",
                SafetyClass.MUTATION,
                CreateCollection.parse,
                self.create_collection,
            ),
            Tool("asset.mark", SafetyClass.MUTATION, MarkAsset.parse, self.mark_asset),
        ]
