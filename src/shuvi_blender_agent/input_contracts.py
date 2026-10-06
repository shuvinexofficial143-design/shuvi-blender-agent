"""Host-side allowlist of payload parsers and safety classes; no bpy import."""

from .animation import FrameRange, InsertKeyframe, SetFrame
from .appearance import CreateDevice, MaterialAssign, UpdateDevice
from .assets import AddModifier, CreateCollection, MarkAsset
from .collection_ops import (
    CollectionNameRequest,
    CollectionObjectChange,
    CreateChildCollection,
    MoveObject,
    RenameCollection,
)
from .destructive import DeleteObject
from .hierarchy import ParentChange
from .mesh import CreateMesh, TranslateVertices
from .mesh_transform import MeshTransformAction
from .mode_ops import ModeChange
from .modeling import ExtrudeFace
from .modeling_edit import DissolveEdge, MergeVertices, TransformElements
from .modeling_hardsurface import BooleanAdd, ModifierMove, ModifierUpdate, StackAdd
from .modeling_modifier_workflows import RecipeApply, RecipePreview, StackCompose
from .modeling_qa import QAInspect, WorkflowApply, WorkflowPreview
from .modeling_region import BevelBoundaryEdge, ExtrudeRegion, InsetFace
from .modeling_repair import CleanupFaces, MergeByDistance, RemoveLooseVertices, RepairInspect
from .modeling_retopology import (
    ProjectionInspect,
    ProjectVertices,
    RelaxVertices,
    ShrinkwrapAdd,
)
from .modeling_shading import OrientFaces, SetFaceSmoothing
from .modeling_topology import (
    BridgeBoundaryLoops,
    FillBoundaryLoop,
    LoopCutQuadStrip,
    SubdivideEdge,
)
from .models import CreateObject, DuplicateObject, PageQuery, SetTransform
from .object_core import RenameObject, SetProperties
from .rendering import FileAction, RenderConfig
from .safety import SafetyClass
from .scene_state import CursorSet, SceneRename, SetPivot, SetUnits
from .sculpting import SculptBrush, SculptSmooth
from .sculpting_brushes import SculptCrease, SculptFlatten, SculptGrab, SculptNormalizedBrush
from .sculpting_controls import ControlledDisplace, ControlledGrab, RegionPreview
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
        "mode.set": (mutation, ModeChange.parse),
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
        "object.delete": (SafetyClass.DESTRUCTIVE, DeleteObject.parse),
        "material.create_assign": (mutation, MaterialAssign.parse),
        "device.create": (mutation, CreateDevice.parse),
        "device.update": (mutation, UpdateDevice.parse),
        "modifier.add": (mutation, AddModifier.parse),
        "modifier.stack_inspect": (read, object_id),
        "modifier.stack_add": (mutation, StackAdd.parse),
        "modifier.boolean_add": (mutation, BooleanAdd.parse),
        "modifier.update": (mutation, ModifierUpdate.parse),
        "modifier.move": (mutation, ModifierMove.parse),
        "modifier.stack_diagnose": (read, object_id),
        "modifier.stack_compose": (mutation, StackCompose.parse),
        "modifier.recipe_preview": (read, RecipePreview.parse),
        "modifier.recipe_apply": (mutation, RecipeApply.parse),
        "modeling.qa_inspect": (read, QAInspect.parse),
        "modeling.workflow_preview": (read, WorkflowPreview.parse),
        "modeling.workflow_apply": (mutation, WorkflowApply.parse),
        "sculpt.inspect": (read, object_id),
        "sculpt.brush_displace": (mutation, SculptBrush.parse),
        "sculpt.brush_smooth": (mutation, SculptSmooth.parse),
        "sculpt.brush_inflate": (mutation, SculptNormalizedBrush.parse),
        "sculpt.brush_flatten": (mutation, SculptFlatten.parse),
        "sculpt.brush_pinch": (mutation, SculptNormalizedBrush.parse),
        "sculpt.brush_grab": (mutation, SculptGrab.parse),
        "sculpt.brush_crease": (mutation, SculptCrease.parse),
        "sculpt.region_preview": (read, RegionPreview.parse),
        "sculpt.brush_displace_controlled": (mutation, ControlledDisplace.parse),
        "sculpt.brush_grab_controlled": (mutation, ControlledGrab.parse),
        "collection.create": (mutation, CreateCollection.parse),
        "asset.mark": (mutation, MarkAsset.parse),
        "animation.set_range": (mutation, FrameRange.parse),
        "animation.set_frame": (mutation, SetFrame.parse),
        "animation.insert_keyframe": (mutation, InsertKeyframe.parse),
        "render.configure": (mutation, RenderConfig.parse),
        "render.execute": (SafetyClass.RENDER, FileAction.parse_png),
        "file.checkpoint": (SafetyClass.FILE_WRITE, FileAction.parse_blend),
        "file.open_checkpoint": (SafetyClass.DESTRUCTIVE, FileAction.parse_blend),
        "mesh.inspect": (read, object_id),
        "mesh.topology_inspect": (read, object_id),
        "mesh.create": (mutation, CreateMesh.parse),
        "mesh.translate_vertices": (mutation, TranslateVertices.parse),
        "mesh.extrude_face": (mutation, ExtrudeFace.parse),
        "mesh.transform_elements": (mutation, TransformElements.parse),
        "mesh.merge_vertices": (mutation, MergeVertices.parse),
        "mesh.dissolve_edge": (mutation, DissolveEdge.parse),
        "mesh.extrude_region": (mutation, ExtrudeRegion.parse),
        "mesh.inset_face": (mutation, InsetFace.parse),
        "mesh.bevel_boundary_edge": (mutation, BevelBoundaryEdge.parse),
        "mesh.subdivide_edge": (mutation, SubdivideEdge.parse),
        "mesh.loop_cut_quad_strip": (mutation, LoopCutQuadStrip.parse),
        "mesh.bridge_boundary_loops": (mutation, BridgeBoundaryLoops.parse),
        "mesh.fill_boundary_loop": (mutation, FillBoundaryLoop.parse),
        "mesh.shading_inspect": (read, object_id),
        "mesh.set_face_smoothing": (mutation, SetFaceSmoothing.parse),
        "mesh.orient_faces_consistently": (mutation, OrientFaces.parse),
        "mesh.repair_inspect": (read, RepairInspect.parse),
        "mesh.merge_by_distance": (mutation, MergeByDistance.parse),
        "mesh.cleanup_faces": (mutation, CleanupFaces.parse),
        "mesh.remove_loose_vertices": (mutation, RemoveLooseVertices.parse),
        "mesh.retopology_inspect": (read, object_id),
        "mesh.retopology_projection_inspect": (read, ProjectionInspect.parse),
        "mesh.retopology_project": (mutation, ProjectVertices.parse),
        "mesh.retopology_relax": (mutation, RelaxVertices.parse),
        "modifier.shrinkwrap_add": (mutation, ShrinkwrapAdd.parse),
        "mesh.apply_object_transform": (mutation, MeshTransformAction.parse),
        "origin.to_centroid": (mutation, MeshTransformAction.parse),
    }
