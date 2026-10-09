"""Host-side allowlist of payload parsers and safety classes; no bpy import."""

from .animation import AnimationInspect, FrameRange, InsertKeyframe, SetFrame
from .animation_acceptance import (
    AnimationQAInspect,
    AnimationRecoveryCapture,
    AnimationRecoveryRestore,
    Level7Acceptance,
)
from .animation_camera import CameraAnimationInspect, CameraOpticsKeyframeInsert
from .animation_controls import ControlInspect, ControlKeyframeInsert
from .animation_keyframes import EditKeyframe, RemoveKeyframe, ReplaceKeyframe
from .animation_nla import NLAInspect, NLAStripCreate
from .animation_pose import PoseBoneAnimationInspect, PoseBoneKeyframeInsert
from .animation_recipe_library import (
    AnimationRecipeApply,
    AnimationRecipeCatalog,
    AnimationRecipePreview,
)
from .animation_style import KeyframeStyleSet
from .animation_timeline import TimelineRetime
from .appearance import CreateDevice, MaterialAssign, UpdateDevice
from .assets import AddModifier, CreateCollection, MarkAsset
from .character_acceptance import CharacterWorkflowPreview, Level3Acceptance
from .character_blockout import BlockoutPlan, LandmarkFit, ProportionGuide
from .character_body import BodyRegionPlan, BodySymmetryAudit, ExtremityGuide, LimbGuide
from .character_face import FaceFit, FaceGuide, FaceRegions, FaceSymmetryAudit
from .character_sculpt_workflow import (
    CharacterSculptQA,
    RecoveryRestore,
    RecoverySnapshot,
    SculptRecipePreview,
)
from .cinematic_composition import CompositionApply, CompositionPreview
from .cinematic_cuts import CutApply, CutPreview, CutRelease
from .cinematic_damped_follow import DampedFollowApply, DampedFollowPreview
from .cinematic_easing import EasingApply, EasingPreview
from .cinematic_follow import FollowApply, FollowPreview, FollowRelease
from .cinematic_motion import CameraMotionApply, CameraMotionPreview
from .cinematic_rail import RailApply, RailPreview
from .cinematic_sequences import SequenceApply, SequencePreview, SequenceRelease
from .cinematic_shots import ShotApply, ShotPreview
from .cinematic_tracking import TrackingApply, TrackingPreview, TrackingRelease
from .collection_ops import (
    CollectionNameRequest,
    CollectionObjectChange,
    CreateChildCollection,
    MoveObject,
    RenameCollection,
)
from .destructive import DeleteObject
from .geometry_acceptance import GeometryWorkflowPreview, Level5Acceptance
from .geometry_architecture import ArchitectureApply, ArchitectureClear, ArchitecturePreview
from .geometry_binding import (
    GeometryModifierBind,
    GeometryModifierInspect,
    GeometryModifierRemove,
)
from .geometry_fields import FieldWorkflowApply, FieldWorkflowClear, FieldWorkflowPreview
from .geometry_nodes import (
    GeometryGroupCreate,
    GeometryLinkChange,
    GeometryNodeAdd,
    GeometryNodeRemove,
    GeometryNodeSetInput,
    GeometryTreeInspect,
)
from .geometry_primitives import PrimitiveApply, PrimitiveClear, PrimitivePreview
from .geometry_recipe_library import RecipeApply as GeometryRecipeApply
from .geometry_recipe_library import RecipeCatalog as GeometryRecipeCatalog
from .geometry_recipe_library import RecipeClear as GeometryRecipeClear
from .geometry_recipe_library import RecipePreview as GeometryRecipePreview
from .geometry_scatter import ScatterApply, ScatterClear, ScatterPreview
from .hierarchy import ParentChange
from .lighting_recipes import RecipeApply as LightingRecipeApply
from .lighting_recipes import RecipeCatalog as LightingRecipeCatalog
from .lighting_recipes import RecipePreview as LightingRecipePreview
from .lighting_recipes import RecipeRestore as LightingRecipeRestore
from .lighting_workflow import WorkflowApply as LightingWorkflowApply
from .lighting_workflow import WorkflowPreview as LightingWorkflowPreview
from .lighting_workflow import WorkflowRelease as LightingWorkflowRelease
from .material_nodes import PBRTextureAssign, PBRTextureClear, PrincipledSet, ShaderInspect
from .material_slots import (
    MaterialFaceAssign,
    MaterialSlotDuplicate,
    MaterialSlotLink,
    MaterialSlotReassign,
    MaterialSlotRemove,
)
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
from .rig_recipe_library import RecipeApply as RigRecipeApply
from .rig_recipe_library import RecipeCatalog as RigRecipeCatalog
from .rig_recipe_library import RecipePreview as RigRecipePreview
from .rigging import (
    ArmatureCreate,
    ArmatureInspect,
    BoneCreate,
    BoneHierarchyEdit,
    BoneSymmetryEdit,
    IKFKPreview,
    IKFKSetup,
    IKFKSwitch,
    MeshArmatureBinding,
    MeshWeightInspect,
    PoseBoneReset,
    PoseBoneTransform,
    PoseConstraintCreate,
    PoseConstraintRemove,
    VertexGroupRemove,
    VertexGroupWeightsSet,
)
from .safety import SafetyClass
from .scene_state import CursorSet, SceneRename, SetPivot, SetUnits
from .sculpting import SculptBrush, SculptSmooth
from .sculpting_brushes import SculptCrease, SculptFlatten, SculptGrab, SculptNormalizedBrush
from .sculpting_controls import ControlledDisplace, ControlledGrab, RegionPreview
from .sculpting_detail import DetailPlan, SubdivisionLevels, SubdivisionSetup
from .sculpting_remesh import SurfaceAnchors, SurfaceSnapshot, VoxelPlan, VoxelTarget
from .selection import SelectionChange
from .shape_ops import CreateCurve, CreateText
from .studio_lighting import (
    LookApply,
    LookPreview,
    LookRestore,
    RigApply,
    RigPreview,
    RigRelease,
    StudioPresetCatalog,
    TuneApply,
    TunePreview,
)
from .texture_workflows import AssetScope, BakePrep, ImageInspect, MaterialOnly, UDIMPlan
from .texture_workflows import RecoveryRestore as TextureRecoveryRestore
from .transform import PatchTransform
from .uv import SeamSet
from .uv_packing import TexelDensityInspect, TexelDensityPlan, UVPackApply, UVPackPlan
from .uv_workflows import UVIslandTransform, UVUnwrapApply, UVUnwrapPlan
from .tracking_clip import ClipInspect
from .validation import fields, string
from .vfx_cloth import ClothApply, ClothPreview, ClothRelease
from .vfx_cloth_collision_workflow import (
    ClothColliderApply,
    ClothColliderPreview,
    ClothColliderRelease,
)
from .vfx_collision import CollisionApply, CollisionPreview, CollisionRelease
from .vfx_ocean import OceanApply, OceanPreview, OceanRelease
from .vfx_ocean_timeline import OceanTimelineApply, OceanTimelinePreview, OceanTimelineRestore
from .vfx_scene_workflow import VfxSceneApply, VfxScenePreview, VfxSceneRelease
from .vfx_wave import WaveApply, WavePreview, WaveRelease
from .visibility import SetVisibility
from .world_lighting import WorldApply, WorldPreview, WorldRelease


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
        "rig.armature_inspect": (read, ArmatureInspect.parse),
        "rig.armature_create": (mutation, ArmatureCreate.parse),
        "rig.bone_create": (mutation, BoneCreate.parse),
        "rig.bone_hierarchy_edit": (mutation, BoneHierarchyEdit.parse),
        "rig.bone_symmetry_edit": (mutation, BoneSymmetryEdit.parse),
        "rig.pose_bone_transform": (mutation, PoseBoneTransform.parse),
        "rig.pose_bone_reset": (mutation, PoseBoneReset.parse),
        "rig.pose_constraint_create": (mutation, PoseConstraintCreate.parse),
        "rig.pose_constraint_remove": (mutation, PoseConstraintRemove.parse),
        "rig.mesh_armature_bind": (mutation, MeshArmatureBinding.parse),
        "rig.mesh_armature_unbind": (mutation, MeshArmatureBinding.parse),
        "rig.mesh_weights_inspect": (read, MeshWeightInspect.parse),
        "rig.vertex_group_weights_set": (mutation, VertexGroupWeightsSet.parse),
        "rig.vertex_group_remove": (mutation, VertexGroupRemove.parse),
        "rig.ik_fk_preview": (read, IKFKPreview.parse),
        "rig.ik_fk_setup": (mutation, IKFKSetup.parse),
        "rig.ik_fk_switch": (mutation, IKFKSwitch.parse),
        "rig.recipe_catalog": (read, RigRecipeCatalog.parse),
        "rig.recipe_preview": (read, RigRecipePreview.parse),
        "rig.recipe_apply": (mutation, RigRecipeApply.parse),
        "character.workflow_preview": (read, CharacterWorkflowPreview.parse),
        "character.level3_acceptance": (read, Level3Acceptance.parse),
        "character.proportion_guide": (read, ProportionGuide.parse),
        "character.blockout_plan": (read, BlockoutPlan.parse),
        "character.landmark_fit": (read, LandmarkFit.parse),
        "character.face_guide": (read, FaceGuide.parse),
        "character.face_landmark_fit": (read, FaceFit.parse),
        "character.face_region_plan": (read, FaceRegions.parse),
        "character.face_symmetry_audit": (read, FaceSymmetryAudit.parse),
        "character.body_region_plan": (read, BodyRegionPlan.parse),
        "character.limb_guide": (read, LimbGuide.parse),
        "character.extremity_guide": (read, ExtremityGuide.parse),
        "character.body_symmetry_audit": (read, BodySymmetryAudit.parse),
        "character.sculpt_qa": (read, CharacterSculptQA.parse),
        "character.sculpt_recipe_preview": (read, SculptRecipePreview.parse),
        "character.sculpt_recovery_snapshot": (read, RecoverySnapshot.parse),
        "character.sculpt_recovery_restore": (mutation, RecoveryRestore.parse),
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
        "geometry_nodes.tree_inspect": (read, GeometryTreeInspect.parse),
        "geometry_nodes.group_create": (mutation, GeometryGroupCreate.parse),
        "geometry_nodes.node_add": (mutation, GeometryNodeAdd.parse),
        "geometry_nodes.node_remove": (mutation, GeometryNodeRemove.parse),
        "geometry_nodes.node_set_input": (mutation, GeometryNodeSetInput.parse),
        "geometry_nodes.link_add": (mutation, GeometryLinkChange.parse),
        "geometry_nodes.link_remove": (mutation, GeometryLinkChange.parse),
        "geometry_nodes.modifier_inspect": (read, GeometryModifierInspect.parse),
        "geometry_nodes.modifier_bind": (mutation, GeometryModifierBind.parse),
        "geometry_nodes.modifier_remove": (mutation, GeometryModifierRemove.parse),
        "geometry_nodes.field_preview": (read, FieldWorkflowPreview.parse),
        "geometry_nodes.field_apply": (mutation, FieldWorkflowApply.parse),
        "geometry_nodes.field_clear": (mutation, FieldWorkflowClear.parse),
        "geometry_nodes.primitive_preview": (read, PrimitivePreview.parse),
        "geometry_nodes.primitive_apply": (mutation, PrimitiveApply.parse),
        "geometry_nodes.primitive_clear": (mutation, PrimitiveClear.parse),
        "geometry_nodes.scatter_preview": (read, ScatterPreview.parse),
        "geometry_nodes.scatter_apply": (mutation, ScatterApply.parse),
        "geometry_nodes.scatter_clear": (mutation, ScatterClear.parse),
        "geometry_nodes.architecture_preview": (read, ArchitecturePreview.parse),
        "geometry_nodes.architecture_apply": (mutation, ArchitectureApply.parse),
        "geometry_nodes.architecture_clear": (mutation, ArchitectureClear.parse),
        "geometry_nodes.recipe_catalog": (read, GeometryRecipeCatalog.parse),
        "geometry_nodes.recipe_preview": (read, GeometryRecipePreview.parse),
        "geometry_nodes.recipe_apply": (mutation, GeometryRecipeApply.parse),
        "geometry_nodes.recipe_clear": (mutation, GeometryRecipeClear.parse),
        "geometry_nodes.workflow_preview": (read, GeometryWorkflowPreview.parse),
        "geometry_nodes.level5_acceptance": (read, Level5Acceptance.parse),
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
        "material.slots_inspect": (read, object_id),
        "material.slot_link": (mutation, MaterialSlotLink.parse),
        "material.slot_reassign": (mutation, MaterialSlotReassign.parse),
        "material.slot_duplicate": (mutation, MaterialSlotDuplicate.parse),
        "material.slot_remove": (mutation, MaterialSlotRemove.parse),
        "material.face_assign": (mutation, MaterialFaceAssign.parse),
        "material.shader_inspect": (read, ShaderInspect.parse),
        "material.principled_set": (mutation, PrincipledSet.parse),
        "material.pbr_texture_assign": (mutation, PBRTextureAssign.parse),
        "material.pbr_texture_clear": (mutation, PBRTextureClear.parse),
        "texture.image_inspect": (read, ImageInspect.parse),
        "texture.udim_plan": (read, UDIMPlan.parse),
        "texture.channel_qa": (read, MaterialOnly.parse),
        "texture.bake_prep": (read, BakePrep.parse),
        "texture.consistency_qa": (read, MaterialOnly.parse),
        "texture.recovery_snapshot": (read, MaterialOnly.parse),
        "texture.recovery_restore": (mutation, TextureRecoveryRestore.parse),
        "texture.asset_qa": (read, AssetScope.parse),
        "texture.workflow_preview": (read, AssetScope.parse),
        "texture.level4_acceptance": (read, AssetScope.parse),
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
        "sculpt.detail_plan": (read, DetailPlan.parse),
        "sculpt.subdivision_setup": (mutation, SubdivisionSetup.parse),
        "sculpt.subdivision_set_levels": (mutation, SubdivisionLevels.parse),
        "sculpt.voxel_plan": (read, VoxelPlan.parse),
        "sculpt.voxel_target_density": (read, VoxelTarget.parse),
        "sculpt.surface_snapshot": (read, SurfaceSnapshot.parse),
        "sculpt.surface_anchor_plan": (read, SurfaceAnchors.parse),
        "uv.inspect": (read, object_id),
        "uv.seam_set": (mutation, SeamSet.parse),
        "uv.unwrap_plan": (read, UVUnwrapPlan.parse),
        "uv.unwrap_apply": (mutation, UVUnwrapApply.parse),
        "uv.island_transform": (mutation, UVIslandTransform.parse),
        "uv.pack_plan": (read, UVPackPlan.parse),
        "uv.pack_apply": (mutation, UVPackApply.parse),
        "uv.texel_density_inspect": (read, TexelDensityInspect.parse),
        "uv.texel_density_plan": (read, TexelDensityPlan.parse),
        "collection.create": (mutation, CreateCollection.parse),
        "asset.mark": (mutation, MarkAsset.parse),
        "animation.inspect": (read, AnimationInspect.parse),
        "animation.set_range": (mutation, FrameRange.parse),
        "animation.set_frame": (mutation, SetFrame.parse),
        "animation.insert_keyframe": (mutation, InsertKeyframe.parse),
        "animation.edit_keyframe": (mutation, EditKeyframe.parse),
        "animation.remove_keyframe": (mutation, RemoveKeyframe.parse),
        "animation.replace_keyframe": (mutation, ReplaceKeyframe.parse),
        "animation.keyframe_style_set": (mutation, KeyframeStyleSet.parse),
        "animation.pose_bone_inspect": (read, PoseBoneAnimationInspect.parse),
        "animation.pose_bone_keyframe_insert": (mutation, PoseBoneKeyframeInsert.parse),
        "camera.optics_animation_inspect": (read, CameraAnimationInspect.parse),
        "camera.optics_keyframe_insert": (mutation, CameraOpticsKeyframeInsert.parse),
        "cinema.shot_preview": (read, ShotPreview.parse),
        "cinema.shot_frame": (mutation, ShotApply.parse),
        "cinema.composition_preview": (read, CompositionPreview.parse),
        "cinema.composition_apply": (mutation, CompositionApply.parse),
        "cinema.motion_preview": (read, CameraMotionPreview.parse),
        "cinema.motion_apply": (mutation, CameraMotionApply.parse),
        "cinema.rail_preview": (read, RailPreview.parse),
        "cinema.rail_apply": (mutation, RailApply.parse),
        "cinema.easing_preview": (read, EasingPreview.parse),
        "cinema.easing_apply": (mutation, EasingApply.parse),
        "cinema.track_preview": (read, TrackingPreview.parse),
        "cinema.track_apply": (mutation, TrackingApply.parse),
        "cinema.track_release": (mutation, TrackingRelease.parse),
        "cinema.follow_preview": (read, FollowPreview.parse),
        "cinema.follow_apply": (mutation, FollowApply.parse),
        "cinema.follow_release": (mutation, FollowRelease.parse),
        "cinema.damped_preview": (read, DampedFollowPreview.parse),
        "cinema.damped_apply": (mutation, DampedFollowApply.parse),
        "cinema.cut_preview": (read, CutPreview.parse),
        "cinema.cut_apply": (mutation, CutApply.parse),
        "cinema.cut_release": (mutation, CutRelease.parse),
        "cinema.sequence_preview": (read, SequencePreview.parse),
        "cinema.sequence_apply": (mutation, SequenceApply.parse),
        "cinema.sequence_release": (mutation, SequenceRelease.parse),
        "lighting.preset_catalog": (read, StudioPresetCatalog.parse),
        "lighting.world_preview": (read, WorldPreview.parse),
        "lighting.world_apply": (mutation, WorldApply.parse),
        "lighting.world_release": (mutation, WorldRelease.parse),
        "lighting.studio_preview": (read, RigPreview.parse),
        "lighting.studio_apply": (mutation, RigApply.parse),
        "lighting.studio_release": (mutation, RigRelease.parse),
        "lighting.tune_preview": (read, TunePreview.parse),
        "lighting.tune_apply": (mutation, TuneApply.parse),
        "lighting.look_preview": (read, LookPreview.parse),
        "lighting.look_apply": (mutation, LookApply.parse),
        "lighting.look_restore": (mutation, LookRestore.parse),
        "lighting.recipe_catalog": (read, LightingRecipeCatalog.parse),
        "lighting.recipe_preview": (read, LightingRecipePreview.parse),
        "lighting.recipe_apply": (mutation, LightingRecipeApply.parse),
        "lighting.recipe_restore": (mutation, LightingRecipeRestore.parse),
        "lighting.workflow_preview": (read, LightingWorkflowPreview.parse),
        "lighting.workflow_apply": (mutation, LightingWorkflowApply.parse),
        "lighting.workflow_release": (mutation, LightingWorkflowRelease.parse),
        "vfx.cloth_preview": (read, ClothPreview.parse),
        "vfx.cloth_apply": (mutation, ClothApply.parse),
        "vfx.cloth_release": (mutation, ClothRelease.parse),
        "vfx.collision_preview": (read, CollisionPreview.parse),
        "vfx.collision_apply": (mutation, CollisionApply.parse),
        "vfx.collision_release": (mutation, CollisionRelease.parse),
        "vfx.cloth_collision_preview": (read, ClothColliderPreview.parse),
        "vfx.cloth_collision_apply": (mutation, ClothColliderApply.parse),
        "vfx.cloth_collision_release": (mutation, ClothColliderRelease.parse),
        "vfx.scene_preview": (read, VfxScenePreview.parse),
        "vfx.scene_apply": (mutation, VfxSceneApply.parse),
        "vfx.scene_release": (mutation, VfxSceneRelease.parse),
        "tracking.clip_inspect": (read, ClipInspect.parse),
        "vfx.wave_preview": (read, WavePreview.parse),
        "vfx.wave_apply": (mutation, WaveApply.parse),
        "vfx.wave_release": (mutation, WaveRelease.parse),
        "vfx.ocean_preview": (read, OceanPreview.parse),
        "vfx.ocean_apply": (mutation, OceanApply.parse),
        "vfx.ocean_release": (mutation, OceanRelease.parse),
        "vfx.ocean_timeline_preview": (read, OceanTimelinePreview.parse),
        "vfx.ocean_timeline_apply": (mutation, OceanTimelineApply.parse),
        "vfx.ocean_timeline_restore": (mutation, OceanTimelineRestore.parse),
        "animation.control_inspect": (read, ControlInspect.parse),
        "animation.control_keyframe_insert": (mutation, ControlKeyframeInsert.parse),
        "animation.retime_preview": (read, TimelineRetime.parse),
        "animation.retime_apply": (mutation, TimelineRetime.parse),
        "animation.recipe_catalog": (read, AnimationRecipeCatalog.parse),
        "animation.recipe_preview": (read, AnimationRecipePreview.parse),
        "animation.recipe_apply": (mutation, AnimationRecipeApply.parse),
        "animation.qa_inspect": (read, AnimationQAInspect.parse),
        "animation.recovery_capture": (read, AnimationRecoveryCapture.parse),
        "animation.recovery_restore": (mutation, AnimationRecoveryRestore.parse),
        "animation.level7_acceptance": (read, Level7Acceptance.parse),
        "animation.nla_inspect": (read, NLAInspect.parse),
        "animation.nla_strip_create": (mutation, NLAStripCreate.parse),
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
