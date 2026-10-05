"""One factory for Blender execution and fake-adapter integration tests."""

from .animation import AnimationOperations
from .appearance import AppearanceOperations
from .assets import AssetOperations
from .contracts import Result, Status
from .files import OutputWorkspace
from .inspection import BpyInspector
from .mesh import MeshOperations
from .operations import ObjectOperations
from .rendering import RenderOperations
from .safety import SafetyClass, SafetyPolicy
from .tools import Tool, ToolRegistry, ping_tool
from .validation import fields


def create_registry(
    bpy, policy: SafetyPolicy | None = None, workspace: OutputWorkspace | None = None
) -> ToolRegistry:
    policy = policy or SafetyPolicy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    adapters = [
        inspector,
        objects,
        AppearanceOperations(objects),
        AssetOperations(objects),
        AnimationOperations(objects),
        RenderOperations(objects, policy, workspace),
        MeshOperations(objects),
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
