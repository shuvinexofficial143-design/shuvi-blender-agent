"""One factory for Blender execution and fake-adapter integration tests."""

from .animation import AnimationOperations
from .animation_acceptance import AnimationAcceptanceOperations
from .animation_camera import CameraAnimationOperations
from .animation_controls import AnimationControlOperations
from .animation_keyframes import AdvancedAnimationOperations
from .animation_nla import ManagedNLAOperations
from .animation_pose import PoseBoneAnimationOperations
from .animation_recipe_library import AnimationRecipeLibraryOperations
from .animation_style import AnimationStyleOperations
from .animation_timeline import AnimationTimelineOperations
from .appearance import AppearanceOperations
from .assets import AssetOperations
from .character_acceptance import CharacterAcceptanceOperations
from .character_blockout import CharacterBlockoutOperations
from .character_body import CharacterBodyOperations
from .character_face import CharacterFaceOperations
from .character_sculpt_workflow import CharacterSculptWorkflowOperations
from .cinematic_composition import CinematicCompositionOperations
from .cinematic_cuts import CameraCutOperations
from .cinematic_damped_follow import CameraDampedFollowOperations
from .cinematic_easing import CameraEasingOperations
from .cinematic_follow import CameraFollowOperations
from .cinematic_motion import CameraMotionOperations
from .cinematic_rail import CameraRailOperations
from .cinematic_sequences import CinematicSequenceOperations
from .cinematic_shots import CinematicShotOperations
from .cinematic_tracking import CameraTrackingOperations
from .collection_ops import CollectionOperations
from .compositor_alpha_over import AlphaCompositeOperations
from .compositor_grade import ColorGradeOperations
from .compositor_lens import LensDistortionOperations
from .compositor_keying import ChromaKeyOperations
from .compositor_matte import MatteRefinementOperations
from .compositor_shot import GreenScreenShotOperations
from .contracts import Result, Status
from .destructive import DestructiveOperations
from .files import OutputWorkspace
from .geometry_acceptance import GeometryAcceptanceOperations
from .geometry_architecture import GeometryArchitectureOperations
from .geometry_binding import GeometryBindingOperations
from .geometry_fields import GeometryFieldOperations
from .geometry_nodes import GeometryNodeOperations
from .geometry_primitives import ProceduralPrimitiveOperations
from .geometry_recipe_library import GeometryRecipeLibraryOperations
from .geometry_scatter import GeometryScatterOperations
from .hierarchy import HierarchyOperations
from .inspection import BpyInspector
from .lighting_recipes import LightingRecipeOperations
from .lighting_workflow import LightingWorkflowOperations
from .material_nodes import MaterialNodeOperations
from .material_slots import MaterialSlotOperations
from .mesh import MeshOperations
from .mesh_transform import MeshTransformOperations
from .mode_ops import ModeOperations
from .modeling import ModelingOperations
from .modeling_edit import ModelingEditOperations
from .modeling_hardsurface import HardSurfaceOperations
from .modeling_modifier_workflows import ModelingModifierWorkflowOperations
from .modeling_qa import ModelingQAOperations
from .modeling_region import ModelingRegionOperations
from .modeling_repair import ModelingRepairOperations
from .modeling_retopology import ModelingRetopologyOperations
from .modeling_shading import ModelingShadingOperations
from .modeling_topology import ModelingTopologyOperations
from .object_core import ObjectCore
from .operations import ObjectOperations
from .rendering import RenderOperations
from .rig_recipe_library import RigRecipeLibraryOperations
from .rigging import RiggingOperations
from .safety import SafetyClass, SafetyPolicy
from .scene_state import SceneStateOperations
from .sculpting import SculptingOperations
from .sculpting_brushes import SculptBrushOperations
from .sculpting_controls import SculptControlOperations
from .sculpting_detail import SculptDetailOperations
from .sculpting_remesh import SculptRemeshPlanningOperations
from .selection import SelectionOperations
from .shape_ops import ShapeOperations
from .studio_lighting import StudioLightingOperations
from .texture_workflows import TextureWorkflowOperations
from .tools import Tool, ToolRegistry, ping_tool
from .tracking_calibration import MovieClipCameraCalibrationOperations
from .tracking_clip import MovieClipInspectionOperations
from .tracking_configuration import MovieTrackingTrackConfigOperations
from .tracking_markers import MarkerPlacementOperations
from .transform import TransformOperations
from .uv import UVOperations
from .uv_packing import UVPackingOperations
from .uv_workflows import UVWorkflowOperations
from .validation import fields
from .vfx_cloth import ClothSimulationOperations
from .vfx_cloth_collision_workflow import ClothColliderWorkflowOperations
from .vfx_collision import CollisionSimulationOperations
from .vfx_ocean import OceanSimulationOperations
from .vfx_ocean_timeline import OceanTimelineOperations
from .vfx_scene_workflow import VfxSceneWorkflowOperations
from .vfx_wave import WaveSimulationOperations
from .visibility import VisibilityOperations
from .world_lighting import WorldLightingOperations


def create_registry(
    bpy, policy: SafetyPolicy | None = None, workspace: OutputWorkspace | None = None
) -> ToolRegistry:
    policy = policy or SafetyPolicy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    animation = AnimationOperations(objects)
    advanced_animation = AdvancedAnimationOperations(animation)
    timeline_animation = AnimationTimelineOperations(advanced_animation)
    rigging = RiggingOperations(objects)
    recipe_animation = AnimationRecipeLibraryOperations(timeline_animation)
    studio_lighting = StudioLightingOperations(objects)
    world_lighting = WorldLightingOperations(objects)
    recipe_lighting = LightingRecipeOperations(studio_lighting)
    ocean_simulation = OceanSimulationOperations(objects)
    nla_animation = ManagedNLAOperations(animation)
    adapters = [
        inspector,
        objects,
        ObjectCore(objects),
        VisibilityOperations(objects),
        TransformOperations(objects),
        SelectionOperations(objects),
        HierarchyOperations(objects),
        GeometryNodeOperations(objects),
        WaveSimulationOperations(objects),
        ClothSimulationOperations(objects),
        CollisionSimulationOperations(objects),
        ClothColliderWorkflowOperations(objects),
        VfxSceneWorkflowOperations(objects),
        MovieClipInspectionOperations(bpy),
        ChromaKeyOperations(bpy),
        AlphaCompositeOperations(bpy),
        ColorGradeOperations(bpy),
        LensDistortionOperations(bpy),
        MatteRefinementOperations(bpy),
        GreenScreenShotOperations(bpy),
        MovieClipCameraCalibrationOperations(bpy),
        MarkerPlacementOperations(bpy),
        MovieTrackingTrackConfigOperations(bpy),
        ocean_simulation,
        OceanTimelineOperations(ocean_simulation),
        GeometryAcceptanceOperations(objects),
        GeometryBindingOperations(objects),
        GeometryArchitectureOperations(objects),
        GeometryFieldOperations(objects),
        ProceduralPrimitiveOperations(objects),
        GeometryRecipeLibraryOperations(objects),
        GeometryScatterOperations(objects),
        CollectionOperations(objects),
        CharacterAcceptanceOperations(objects),
        CharacterBlockoutOperations(objects),
        CharacterBodyOperations(objects),
        CharacterFaceOperations(objects),
        CharacterSculptWorkflowOperations(objects),
        SceneStateOperations(objects),
        ModeOperations(objects),
        ShapeOperations(objects),
        AppearanceOperations(objects),
        MaterialSlotOperations(objects),
        MaterialNodeOperations(objects),
        TextureWorkflowOperations(objects),
        AssetOperations(objects),
        animation,
        advanced_animation,
        AnimationStyleOperations(advanced_animation),
        timeline_animation,
        recipe_animation,
        nla_animation,
        AnimationAcceptanceOperations(advanced_animation, recipe_animation, nla_animation),
        PoseBoneAnimationOperations(animation, rigging),
        CameraAnimationOperations(objects),
        CinematicShotOperations(objects),
        CinematicCompositionOperations(objects),
        CameraMotionOperations(objects),
        CameraRailOperations(objects),
        CameraEasingOperations(objects),
        CameraTrackingOperations(objects),
        CameraFollowOperations(objects),
        CameraDampedFollowOperations(objects),
        CameraCutOperations(objects),
        CinematicSequenceOperations(objects),
        studio_lighting,
        recipe_lighting,
        world_lighting,
        LightingWorkflowOperations(studio_lighting, world_lighting, recipe_lighting),
        AnimationControlOperations(animation, rigging),
        RenderOperations(objects, policy, workspace),
        rigging,
        RigRecipeLibraryOperations(objects),
        MeshOperations(objects),
        MeshTransformOperations(objects),
        ModelingOperations(objects),
        ModelingEditOperations(objects),
        HardSurfaceOperations(objects),
        ModelingModifierWorkflowOperations(objects),
        ModelingQAOperations(objects),
        ModelingRegionOperations(objects),
        ModelingRepairOperations(objects),
        ModelingRetopologyOperations(objects),
        ModelingShadingOperations(objects),
        ModelingTopologyOperations(objects),
        SculptingOperations(objects),
        SculptBrushOperations(objects),
        SculptControlOperations(objects),
        SculptDetailOperations(objects),
        SculptRemeshPlanningOperations(objects),
        UVOperations(objects),
        UVWorkflowOperations(objects),
        UVPackingOperations(objects),
        DestructiveOperations(objects, policy, workspace),
    ]
    registry = ToolRegistry(
        [ping_tool(), *(tool for adapter in adapters for tool in adapter.tools())], policy
    )

    def capabilities(request, _):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "protocol_version": 1,
                "session_id": inspector.session_id,
                "blender_version": list(bpy.app.version),
                "operations": registry.catalog(),
            },
        )

    registry.register(
        Tool("system.capabilities", SafetyClass.READ_ONLY, lambda p: fields(p, set()), capabilities)
    )
    return registry
