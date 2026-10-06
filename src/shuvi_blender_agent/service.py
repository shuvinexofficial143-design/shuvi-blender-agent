"""One factory for Blender execution and fake-adapter integration tests."""

from .animation import AnimationOperations
from .appearance import AppearanceOperations
from .assets import AssetOperations
from .character_acceptance import CharacterAcceptanceOperations
from .character_blockout import CharacterBlockoutOperations
from .character_body import CharacterBodyOperations
from .character_face import CharacterFaceOperations
from .character_sculpt_workflow import CharacterSculptWorkflowOperations
from .collection_ops import CollectionOperations
from .contracts import Result, Status
from .destructive import DestructiveOperations
from .files import OutputWorkspace
from .geometry_binding import GeometryBindingOperations
from .geometry_fields import GeometryFieldOperations
from .geometry_nodes import GeometryNodeOperations
from .geometry_primitives import ProceduralPrimitiveOperations
from .hierarchy import HierarchyOperations
from .inspection import BpyInspector
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
from .safety import SafetyClass, SafetyPolicy
from .scene_state import SceneStateOperations
from .sculpting import SculptingOperations
from .sculpting_brushes import SculptBrushOperations
from .sculpting_controls import SculptControlOperations
from .sculpting_detail import SculptDetailOperations
from .sculpting_remesh import SculptRemeshPlanningOperations
from .selection import SelectionOperations
from .shape_ops import ShapeOperations
from .texture_workflows import TextureWorkflowOperations
from .tools import Tool, ToolRegistry, ping_tool
from .transform import TransformOperations
from .uv import UVOperations
from .uv_packing import UVPackingOperations
from .uv_workflows import UVWorkflowOperations
from .validation import fields
from .visibility import VisibilityOperations


def create_registry(
    bpy, policy: SafetyPolicy | None = None, workspace: OutputWorkspace | None = None
) -> ToolRegistry:
    policy = policy or SafetyPolicy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    adapters = [
        inspector,
        objects,
        ObjectCore(objects),
        VisibilityOperations(objects),
        TransformOperations(objects),
        SelectionOperations(objects),
        HierarchyOperations(objects),
        GeometryNodeOperations(objects),
        GeometryBindingOperations(objects),
        GeometryFieldOperations(objects),
        ProceduralPrimitiveOperations(objects),
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
        AnimationOperations(objects),
        RenderOperations(objects, policy, workspace),
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
