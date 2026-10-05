"""Trusted --python entrypoint. bpy work runs on the background Blender main thread."""

import os
import socket
import sys
from pathlib import Path


def read_environment(environment):
    # Consume all bridge secrets/settings before validation or importing Blender.
    names = (
        "SHUVI_BRIDGE_TOKEN",
        "SHUVI_BRIDGE_PORT",
        "SHUVI_ALLOW_MUTATIONS",
        "SHUVI_ALLOW_DESTRUCTIVE",
        "SHUVI_ALLOW_FILE_WRITES",
        "SHUVI_ALLOW_RENDERING",
        "SHUVI_OUTPUT_DIRECTORY",
    )
    settings = {name: environment.pop(name, "") for name in names}
    token, port = settings[names[0]], settings[names[1]]
    if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
        raise RuntimeError("Invalid bridge configuration")
    if (
        not port.isascii()
        or not port.isdecimal()
        or not 1 <= len(port) <= 5
        or not 1 <= int(port) <= 65535
    ):
        raise RuntimeError("Invalid bridge configuration")
    from shuvi_blender_agent.safety import SafetyPolicy

    values = [settings[name] or "0" for name in names[2:6]]
    if any(value not in ("0", "1") for value in values):
        raise RuntimeError("Invalid bridge policy")
    return token, int(port), SafetyPolicy(*(value == "1" for value in values)), settings[names[6]]


def main() -> None:
    # Blender's bundled Python need not have this package installed separately.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    token, port, policy, output_directory = read_environment(os.environ)
    import bpy

    from shuvi_blender_agent.bridge import serve
    from shuvi_blender_agent.files import OutputWorkspace
    from shuvi_blender_agent.service import create_registry

    if not bpy.app.background:
        raise RuntimeError("Only controlled background sessions are supported")
    workspace = OutputWorkspace(Path(output_directory)) if output_directory else None
    registry = create_registry(bpy, policy, workspace)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        serve(connection, token, registry)


if __name__ == "__main__":
    main()
