"""Trusted --python entrypoint. bpy work runs on the background Blender main thread."""

import os
import socket
import sys
from pathlib import Path


def main() -> None:
    # Blender's bundled Python need not have this package installed separately.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import bpy

    from shuvi_blender_agent.bridge import serve
    from shuvi_blender_agent.files import OutputWorkspace
    from shuvi_blender_agent.safety import SafetyPolicy
    from shuvi_blender_agent.service import create_registry

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
    output_directory = os.environ.pop("SHUVI_OUTPUT_DIRECTORY", "")
    workspace = OutputWorkspace(Path(output_directory)) if output_directory else None
    registry = create_registry(bpy, policy, workspace)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        serve(connection, token, registry)


if __name__ == "__main__":
    main()
