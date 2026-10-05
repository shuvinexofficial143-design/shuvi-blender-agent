"""Host-side allowlist of payload parsers and safety classes; no bpy import."""

from .animation import FrameRange, InsertKeyframe, SetFrame
from .appearance import CreateDevice, MaterialAssign
from .assets import AddModifier, CreateCollection, MarkAsset
from .mesh import CreateMesh, TranslateVertices
from .models import CreateObject, DuplicateObject, PageQuery, SetTransform
from .rendering import FileAction, RenderConfig
from .safety import SafetyClass
from .validation import fields, string


def empty(data):
    return fields(data, set())


def object_id(data):
    fields(data, {"object_id"})
    return string(data["object_id"], "object_id", limit=128)


def builtin_contracts() -> dict:
    read, mutation = SafetyClass.READ_ONLY, SafetyClass.MUTATION
    return {
        "system.ping": (read, empty),
        "system.capabilities": (read, empty),
        "scene.inspect": (read, empty),
        "objects.list": (read, PageQuery.parse),
        "collections.list": (read, PageQuery.parse),
        "object.inspect": (read, object_id),
        "object.create": (mutation, CreateObject.parse),
        "object.set_transform": (mutation, SetTransform.parse),
        "object.duplicate": (mutation, DuplicateObject.parse),
        "material.create_assign": (mutation, MaterialAssign.parse),
        "device.create": (mutation, CreateDevice.parse),
        "modifier.add": (mutation, AddModifier.parse),
        "collection.create": (mutation, CreateCollection.parse),
        "asset.mark": (mutation, MarkAsset.parse),
        "animation.set_range": (mutation, FrameRange.parse),
        "animation.set_frame": (mutation, SetFrame.parse),
        "animation.insert_keyframe": (mutation, InsertKeyframe.parse),
        "render.configure": (mutation, RenderConfig.parse),
        "render.execute": (SafetyClass.RENDER, FileAction.parse_png),
        "file.checkpoint": (SafetyClass.FILE_WRITE, FileAction.parse_blend),
        "mesh.inspect": (read, object_id),
        "mesh.create": (mutation, CreateMesh.parse),
        "mesh.translate_vertices": (mutation, TranslateVertices.parse),
    }
