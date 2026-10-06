"""Host-side allowlist of payload parsers and safety classes; no bpy import."""

from .animation import FrameRange, InsertKeyframe, SetFrame
from .appearance import CreateDevice, MaterialAssign
from .assets import AddModifier, CreateCollection, MarkAsset
from .collection_ops import (
    CollectionNameRequest,
    CollectionObjectChange,
    CreateChildCollection,
    MoveObject,
    RenameCollection,
)
from .hierarchy import ParentChange
from .mesh import CreateMesh, TranslateVertices
from .mesh_transform import MeshTransformAction
from .models import CreateObject, DuplicateObject, PageQuery, SetTransform
from .object_core import RenameObject, SetProperties
from .rendering import FileAction, RenderConfig
from .safety import SafetyClass
from .scene_state import CursorSet, SceneRename, SetPivot, SetUnits
from .selection import SelectionChange
from .shape_ops import CreateCurve, CreateText
from .transform import PatchTransform
from .validation import fields, string
from .visibility import SetVisibility


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
        "scene.rename": (mutation, SceneRename.parse),
        "scene.set_units": (mutation, SetUnits.parse),
        "cursor.inspect": (read, empty),
        "cursor.set": (mutation, CursorSet.parse),
        "mode.inspect": (read, empty),
        "shape.inspect": (read, object_id),
        "curve.create": (mutation, CreateCurve.parse),
        "text.create": (mutation, CreateText.parse),
        "pivot.inspect": (read, empty),
        "pivot.set": (mutation, SetPivot.parse),
        "objects.list": (read, PageQuery.parse),
        "collections.list": (read, PageQuery.parse),
        "object.inspect": (read, object_id),
        "object.rename": (mutation, RenameObject.parse),
        "object.set_properties": (mutation, SetProperties.parse),
        "object.set_visibility": (mutation, SetVisibility.parse),
        "object.patch_transform": (mutation, PatchTransform.parse),
        "selection.set": (mutation, SelectionChange.parse),
        "selection.inspect": (read, empty),
        "hierarchy.inspect": (read, object_id),
        "origin.inspect": (read, object_id),
        "hierarchy.set_parent": (mutation, ParentChange.parse),
        "collection.inspect": (read, CollectionNameRequest.parse),
        "collection.rename": (mutation, RenameCollection.parse),
        "collection.link_object": (mutation, CollectionObjectChange.parse),
        "collection.unlink_object": (mutation, CollectionObjectChange.parse),
        "collection.move_object": (mutation, MoveObject.parse),
        "collection.create_child": (mutation, CreateChildCollection.parse),
        "object.create": (mutation, CreateObject.parse),
        "object.set_transform": (mutation, SetTransform.parse),
        "object.duplicate": (mutation, DuplicateObject.parse),
        "object.duplicate_linked": (mutation, DuplicateObject.parse),
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
        "mesh.apply_object_transform": (mutation, MeshTransformAction.parse),
        "origin.to_centroid": (mutation, MeshTransformAction.parse),
    }
