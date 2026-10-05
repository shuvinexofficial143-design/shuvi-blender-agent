import struct
import zlib
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.files import OutputWorkspace, filename, read_output, verify_png
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.rendering import RenderOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def png(width=16, height=16):
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * (height * (1 + width * 4))))
        + chunk(b"IEND", b"")
    )


def setup(tmp_path, render_allowed=True):
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    policy = SafetyPolicy(
        allow_mutations=True, allow_file_writes=True, allow_rendering=render_allowed
    )
    ops = RenderOperations(ObjectOperations(inspector), policy, OutputWorkspace(tmp_path))
    registry = ToolRegistry(ops.tools(), policy)

    def render(**kwargs):
        scene = bpy.context.scene
        Path(scene.render.filepath).write_bytes(
            png(scene.render.resolution_x, scene.render.resolution_y)
        )
        return {"FINISHED"}

    def save(**kwargs):
        assert kwargs["copy"] is True
        assert kwargs["compress"] is False
        Path(kwargs["filepath"]).write_bytes(b"BLENDER-v402" + b"fake unit-test data")
        return {"FINISHED"}

    bpy.ops = NS(render=NS(render=render), wm=NS(save_as_mainfile=save))
    return bpy, inspector, registry


def configure(inspector, registry):
    return registry.dispatch(
        Request(
            "render.configure",
            {
                "width": 16,
                "height": 16,
                "samples": 1,
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )


def test_render_configuration_and_verified_mock_output(tmp_path):
    bpy, inspector, registry = setup(tmp_path)
    assert configure(inspector, registry).status == Status.VERIFIED
    camera = FakeObject("Camera", "CAMERA")
    camera.data = NS(type="PERSP", lens=35, clip_start=0.1, clip_end=100)
    bpy.context.scene.objects.link(camera)
    bpy.context.scene.camera = camera
    previous = bpy.context.scene.render.filepath
    result = registry.dispatch(
        Request(
            "render.execute",
            {"name": "test.png", "expected_scene_revision": inspector.summary()["revision"]},
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["width"] == 16
    assert len(result.data["after"]["sha256"]) == 64
    assert bpy.context.scene.render.filepath == previous
    assert (tmp_path / "test.png").is_file()


def test_render_is_denied_without_explicit_permission(tmp_path):
    _, inspector, registry = setup(tmp_path, render_allowed=False)
    result = registry.dispatch(
        Request(
            "render.execute",
            {"name": "test.png", "expected_scene_revision": inspector.summary()["revision"]},
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert not list(tmp_path.iterdir())


def test_checkpoint_copy_preserves_active_file_and_cannot_overwrite(tmp_path):
    bpy, inspector, registry = setup(tmp_path)
    bpy.data.filepath = "original.blend"
    payload = {
        "name": "checkpoint.blend",
        "expected_scene_revision": inspector.summary()["revision"],
    }
    result = registry.dispatch(Request("file.checkpoint", payload))
    assert result.status == Status.VERIFIED
    assert result.data["after"]["source_filepath"] == "original.blend"
    assert (
        registry.dispatch(Request("file.checkpoint", payload)).error.code == ErrorCode.SAFETY_DENIED
    )


@pytest.mark.parametrize(
    "name",
    [
        "../bad.png",
        "C:/bad.png",
        "CON.png",
        "a:b.png",
        "bad.png.",
        "COM\u00b9.png",
        "LPT\u00b2.png",
        "CON .png",
        "\\\\server\\a.png",
    ],
)
def test_output_names_confined(name):
    with pytest.raises(AgentError):
        filename(name, ".png")


@pytest.mark.parametrize("raw", [b"bad", png()[:-4], png()[:40], png()[:-1] + b"x"])
def test_corrupt_png_rejected(raw):
    with pytest.raises(AgentError):
        verify_png(raw)


def test_reservation_cleans_empty_but_preserves_partial(tmp_path):
    workspace = OutputWorkspace(tmp_path)
    with workspace.reserve("empty.png", ".png"):
        pass
    assert not (tmp_path / "empty.png").exists()
    with pytest.raises(RuntimeError):
        with workspace.reserve("partial.png", ".png") as path:
            path.write_bytes(b"partial")
            raise RuntimeError("interrupted")
    assert (tmp_path / "partial.png").read_bytes() == b"partial"


def test_replaced_workspace_is_denied_before_writing(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    workspace = OutputWorkspace(root)
    root.rename(tmp_path / "old-output")
    root.mkdir()
    with pytest.raises(AgentError) as error:
        with workspace.reserve("new.blend", ".blend"):
            pytest.fail("A replaced workspace must not be used")
    assert error.value.code == ErrorCode.SAFETY_DENIED
    assert not list(root.iterdir())


def test_replaced_reservation_is_not_deleted_by_cleanup(tmp_path):
    workspace = OutputWorkspace(tmp_path)
    with workspace.reserve("out.png", ".png") as path:
        path.rename(tmp_path / "original-reservation")
        path.touch()
    assert path.exists()
    assert (tmp_path / "original-reservation").exists()


def test_hard_link_output_is_rejected(tmp_path):
    import os

    original = tmp_path / "original.blend"
    original.write_bytes(b"BLENDER-v402" + b"data")
    linked = tmp_path / "linked.blend"
    os.link(original, linked)
    with pytest.raises(AgentError) as error:
        read_output(linked, "BLEND")
    assert error.value.code == ErrorCode.VERIFICATION_FAILED


def test_symlink_output_is_rejected_when_supported(tmp_path):
    original = tmp_path / "original.blend"
    original.write_bytes(b"BLENDER-v402" + b"data")
    linked = tmp_path / "linked.blend"
    try:
        linked.symlink_to(original)
    except OSError:
        pytest.skip("Creating symlinks is unavailable under this Windows account")
    with pytest.raises(AgentError) as error:
        read_output(linked, "BLEND")
    assert error.value.code == ErrorCode.VERIFICATION_FAILED


def test_large_blend_readback_uses_bounded_chunks(tmp_path, monkeypatch):
    import os

    path = tmp_path / "large.blend"
    path.write_bytes(b"BLENDER-v402" + b"x" * 200000)
    original = os.fdopen
    reads = []

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            reads.append(size)
            assert size <= 65536
            return self.stream.read(size)

    monkeypatch.setattr(os, "fdopen", lambda *args: BoundedReader(original(*args)))
    result = read_output(path, "BLEND")
    assert result["bytes"] == path.stat().st_size
    assert len(reads) > 3


def test_png_unknown_critical_chunk_is_denied():
    raw = png()
    tag, data = b"ABCD", b""
    unknown = struct.pack("!I", 0) + tag + data + struct.pack("!I", zlib.crc32(tag + data))
    with pytest.raises(AgentError):
        verify_png(raw[:33] + unknown + raw[33:])


def test_blend_header_version_must_be_numeric(tmp_path):
    path = tmp_path / "bad.blend"
    path.write_bytes(b"BLENDER-vBAD" + b"data")
    with pytest.raises(AgentError):
        read_output(path, "BLEND")
