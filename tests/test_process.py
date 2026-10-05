import socket
import subprocess
import threading
from pathlib import Path

import pytest

from shuvi_blender_agent import AgentError, ErrorCode
from shuvi_blender_agent.bridge import serve
from shuvi_blender_agent.contracts import Request
from shuvi_blender_agent.process import LaunchConfig, launch, launch_arguments, stop_owned_process
from shuvi_blender_agent.tools import ToolRegistry, ping_tool


def test_launch_arguments_disable_scripts_and_no_user_code(tmp_path):
    executable = tmp_path / "blender.exe"
    executable.touch()
    blend = tmp_path / "scene with spaces.blend"
    blend.touch()
    args = launch_arguments(LaunchConfig(executable, blend))
    assert args[0] == str(executable.resolve())
    assert "--disable-autoexec" in args
    assert "--factory-startup" in args
    assert args[args.index("--python") - 1] == str(blend.resolve())
    assert Path(args[-1]).name == "bootstrap.py"


def test_missing_paths_rejected(tmp_path):
    with pytest.raises(AgentError):
        LaunchConfig(tmp_path / "missing")
    executable = tmp_path / "blender.exe"
    executable.touch()
    with pytest.raises(AgentError):
        LaunchConfig(executable, tmp_path / "missing.blend")


def test_process_exit_before_startup_and_launch_configuration(tmp_path):
    executable = tmp_path / "blender.exe"
    executable.touch()
    calls = []

    class ExitedProcess:
        def poll(self):
            return 1

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return ExitedProcess()

    with pytest.raises(AgentError) as error:
        launch(LaunchConfig(executable), popen=popen)
    assert error.value.code == ErrorCode.EXECUTION_ERROR
    kwargs = calls[0][1]
    assert kwargs["shell"] is False
    assert len(kwargs["env"]["SHUVI_BRIDGE_TOKEN"]) == 64
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["env"]["SHUVI_ALLOW_MUTATIONS"] == "0"


def test_stop_only_owned_handle_and_escalates_bounded():
    events = []

    class StubbornProcess:
        def poll(self):
            return None

        def wait(self, timeout):
            events.append(("wait", timeout))
            if len(events) < 5:
                raise subprocess.TimeoutExpired("owned", timeout)

        def terminate(self):
            events.append(("terminate",))

        def kill(self):
            events.append(("kill",))

    stop_owned_process(StubbornProcess())
    assert events == [("wait", 1), ("terminate",), ("wait", 2), ("kill",), ("wait", 2)]


def test_launch_readiness_and_cleanup_without_blender(tmp_path):
    executable = tmp_path / "fake-blender.exe"
    executable.touch()
    threads = []

    def popen(args, **kwargs):
        env = kwargs["env"]

        def child():
            with socket.create_connection(("127.0.0.1", int(env["SHUVI_BRIDGE_PORT"]))) as sock:
                try:
                    serve(sock, env["SHUVI_BRIDGE_TOKEN"], ToolRegistry([ping_tool()]))
                except AgentError:
                    pass

        worker = threading.Thread(target=child)
        worker.start()
        threads.append(worker)

        class FakeProcess:
            def poll(self):
                return None if worker.is_alive() else 0

            def wait(self, timeout):
                worker.join(timeout=timeout)
                if worker.is_alive():
                    raise subprocess.TimeoutExpired("fake", timeout)
                return 0

        return FakeProcess()

    with launch(LaunchConfig(executable), popen=popen) as session:
        assert session.client.call(Request("system.ping")).data["ready"] is True
    assert all(not worker.is_alive() for worker in threads)


def test_startup_timeout_stops_owned_child(tmp_path):
    executable = tmp_path / "fake-blender.exe"
    executable.touch()
    events = []

    class FakeProcess:
        def poll(self):
            return None

        def wait(self, timeout):
            events.append("cleanup")
            return 0

    with pytest.raises(AgentError) as error:
        launch(LaunchConfig(executable, startup_timeout_ms=10), popen=lambda *a, **k: FakeProcess())
    assert error.value.code == ErrorCode.TIMEOUT
    assert events == ["cleanup"]
