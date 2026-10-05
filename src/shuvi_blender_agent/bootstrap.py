"""Trusted --python entrypoint. bpy work runs on the background Blender main thread."""

import os
import socket
import sys
from pathlib import Path


def main() -> None:
    # Blender's bundled Python need not have this package installed separately.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import bpy

    from shuvi_blender_agent.animation import AnimationOperations
    from shuvi_blender_agent.appearance import AppearanceOperations
    from shuvi_blender_agent.assets import AssetOperations
    from shuvi_blender_agent.bridge import serve
    from shuvi_blender_agent.files import OutputWorkspace
    from shuvi_blender_agent.inspection import BpyInspector
    from shuvi_blender_agent.operations import ObjectOperations
    from shuvi_blender_agent.rendering import RenderOperations
    from shuvi_blender_agent.safety import SafetyPolicy
    from shuvi_blender_agent.tools import ToolRegistry, ping_tool

    if not bpy.app.background:
        raise RuntimeError("Only controlled background sessions are supported")
    token = os.environ.pop("SHUVI_BRIDGE_TOKEN")
    port = int(os.environ.pop("SHUVI_BRIDGE_PORT"))
    if not 1 <= port <= 65535 or len(token) != 64:
        raise RuntimeError("Invalid bridge configuration")
    policy = SafetyPolicy(
        allow_mutations=os.environ.pop("SHUVI_ALLOW_MUTATIONS", "0") == "1",
        allow_destructive=os.environ.pop("SHUVI_ALLOW_DESTRUCTIVE", "0") == "1",
        allow_file_writes=os.environ.pop("SHUVI_ALLOW_FILE_WRITES", "0") == "1",
        allow_rendering=os.environ.pop("SHUVI_ALLOW_RENDERING", "0") == "1",
    )
    inspector = BpyInspector(bpy)
    operations = ObjectOperations(inspector)
    appearance = AppearanceOperations(operations)
    assets = AssetOperations(operations)
    animation = AnimationOperations(operations)
    output_directory = os.environ.pop("SHUVI_OUTPUT_DIRECTORY", "")
    rendering = RenderOperations(
        operations, policy, OutputWorkspace(Path(output_directory)) if output_directory else None
    )
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        serve(
            connection,
            token,
            ToolRegistry(
                [
                    ping_tool(),
                    *inspector.tools(),
                    *operations.tools(),
                    *appearance.tools(),
                    *assets.tools(),
                    *animation.tools(),
                    *rendering.tools(),
                ],
                policy,
            ),
        )


if __name__ == "__main__":
    main()
