"""One factory for Blender execution and fake-adapter integration tests."""

from .animation import AnimationOperations
from .appearance import AppearanceOperations
from .assets import AssetOperations
from .collection_ops import CollectionOperations
from .contracts import Result, Status
from .destructive import DestructiveOperations
from .files import OutputWorkspace
from .hierarchy import HierarchyOperations
from .inspection import BpyInspector
from .mesh import MeshOperations
from .mesh_transform import MeshTransformOperations
from .mode_ops import ModeOperations
from .object_core import ObjectCore
from .operations import ObjectOperations
from .rendering import RenderOperations
from .safety import SafetyClass, SafetyPolicy
from .scene_state import SceneStateOperations
from .selection import SelectionOperations
from .shape_ops import ShapeOperations
from .tools import Tool, ToolRegistry, ping_tool
from .transform import TransformOperations
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
        CollectionOperations(objects),
        SceneStateOperations(objects),
        ModeOperations(objects),
        ShapeOperations(objects),
        AppearanceOperations(objects),
        AssetOperations(objects),
        AnimationOperations(objects),
        RenderOperations(objects, policy, workspace),
        MeshOperations(objects),
        MeshTransformOperations(objects),
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
