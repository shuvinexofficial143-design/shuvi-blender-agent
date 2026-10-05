"""Explicit controlled Blender launch. This module never launches on import."""

import os
import secrets
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .bridge import BlenderClient, authenticate
from .contracts import Request
from .errors import AgentError, ErrorCode
from .safety import SafetyPolicy
from .validation import integer


@dataclass(frozen=True)
class LaunchConfig:
    executable: Path
    blend_file: Path | None = None
    startup_timeout_ms: int = 15_000
    policy: SafetyPolicy = SafetyPolicy()

    def __post_init__(self) -> None:
        integer(self.startup_timeout_ms, "startup_timeout_ms", 1, 120_000)
        if not Path(self.executable).is_file():
            raise AgentError(ErrorCode.BLENDER_NOT_FOUND, "Blender executable does not exist")
        if self.blend_file is not None:
            path = Path(self.blend_file)
            if not path.is_file() or path.suffix.lower() != ".blend":
                raise AgentError(ErrorCode.NOT_FOUND, "Existing .blend file required")


def launch_arguments(config: LaunchConfig) -> list[str]:
    args = [
        str(Path(config.executable).resolve()),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
    ]
    if config.blend_file is not None:
        args.append(str(Path(config.blend_file).resolve()))
    args.extend(["--python", str(Path(__file__).with_name("bootstrap.py"))])
    return args


def stop_owned_process(process) -> None:
    """Only a Popen handle created by this launcher may be supplied here."""
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


class BlenderSession:
    def __init__(self, process, client: BlenderClient):
        self.process = process
        self.client = client

    def close(self) -> None:
        self.client.close()
        stop_owned_process(self.process)

    def __enter__(self) -> "BlenderSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def launch(config: LaunchConfig, *, popen: Callable = subprocess.Popen) -> BlenderSession:
    """Call only after real Blender runtime launch is authorized by the host/user."""
    token = secrets.token_hex(32)
    process = None
    connection = None
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        deadline = time.monotonic() + config.startup_timeout_ms / 1000
        env = dict(os.environ)
        # Secret is passed through the child environment, not command line or protocol logs.
        env.update(
            {
                "SHUVI_BRIDGE_PORT": str(listener.getsockname()[1]),
                "SHUVI_BRIDGE_TOKEN": token,
                "SHUVI_ALLOW_MUTATIONS": "1" if config.policy.allow_mutations else "0",
                "SHUVI_ALLOW_DESTRUCTIVE": "1" if config.policy.allow_destructive else "0",
                "SHUVI_ALLOW_FILE_WRITES": "1" if config.policy.allow_file_writes else "0",
            }
        )
        process = popen(
            launch_arguments(config),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        while connection is None:
            if process.poll() is not None:
                raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender exited before bridge startup")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentError(ErrorCode.TIMEOUT, "Blender bridge startup timed out")
            listener.settimeout(min(remaining, 0.1))
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
        authenticate(connection, token, deadline)
        client = BlenderClient(connection)
        # Delivery is insufficient; require a real roundtrip before returning a session.
        ping = client.call(
            Request(
                "system.ping",
                timeout_ms=max(1, min(120_000, int((deadline - time.monotonic()) * 1000))),
            )
        )
        if ping.error is not None or ping.data.get("ready") is not True:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender bridge readiness failed")
        return BlenderSession(process, client)
    except AgentError:
        if connection is not None:
            connection.close()
        if process is not None:
            stop_owned_process(process)
        raise
    except OSError as exc:
        if connection is not None:
            connection.close()
        if process is not None:
            stop_owned_process(process)
        raise AgentError(ErrorCode.TRANSPORT_ERROR, "Cannot start Blender bridge") from exc
    finally:
        listener.close()
