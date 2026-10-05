"""Acceptance harness tests use injected fake sessions; they never run Blender."""

from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy
from test_rendering import png

from shuvi_blender_agent import AgentError, ErrorCode
from shuvi_blender_agent.discovery import BlenderVersion
from shuvi_blender_agent.files import OutputWorkspace
from shuvi_blender_agent.runtime_acceptance import main, run_acceptance
from shuvi_blender_agent.service import create_registry


def test_acceptance_requires_explicit_authorization_before_any_launch():
    calls = []
    with pytest.raises(AgentError) as error:
        run_acceptance(Path("missing"), launcher=lambda config: calls.append(config))
    assert error.value.code == ErrorCode.SAFETY_DENIED
    assert not calls


def test_default_cli_only_reports_preparation(capsys):
    assert main([]) == 0
    assert '"status": "prepared"' in capsys.readouterr().out


@pytest.mark.parametrize("allow_render", [False, True])
def test_acceptance_fake_session_exercises_flow_and_cleans_temporary_workspace(
    tmp_path, allow_render
):
    executable = tmp_path / "fake-blender.exe"
    executable.touch()
    configurations = []
    sessions = []

    def launcher(config):
        configurations.append(config)
        assert config.blend_file is None
        bpy = fake_bpy()
        bpy.ops = NS(
            wm=NS(save_as_mainfile=lambda **kwargs: save(kwargs)),
            render=NS(render=lambda **kwargs: render()),
        )

        def save(kwargs):
            assert kwargs["copy"] and not kwargs["compress"]
            Path(kwargs["filepath"]).write_bytes(b"BLENDER-v402" + b"fake data")
            return {"FINISHED"}

        def render():
            Path(bpy.context.scene.render.filepath).write_bytes(png())
            return {"FINISHED"}

        registry = create_registry(bpy, config.policy, OutputWorkspace(config.output_directory))

        class Client:
            closed = False

            def call(self, request):
                return registry.dispatch(request)

        class Session:
            client = Client()
            process = NS(poll=lambda: 0)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.client.closed = True

        session = Session()
        sessions.append(session)
        return session

    report = run_acceptance(
        executable,
        runtime_authorized=True,
        allow_render=allow_render,
        launcher=launcher,
        version_probe=lambda *args: BlenderVersion(4, 2),
    )
    assert report["suite_completed"], report.get("error")
    assert report["cleanup_confirmed"]
    assert report["workspace_removed"]
    assert not report["real_runtime_verified"]
    operations = {item["operation"] for item in report["cases"]}
    assert ("render.execute" in operations) == allow_render
    assert {"mesh.translate_vertices", "file.checkpoint", "animation.insert_keyframe"} <= operations
    assert sessions[0].client.closed
    assert not configurations[0].output_directory.exists()
