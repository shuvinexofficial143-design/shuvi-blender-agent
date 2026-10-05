"""CPU-only bounded rendering and Blender checkpoints; runtime execution defaults off."""

from dataclasses import dataclass

from .contracts import Request, Result
from .errors import AgentError, ErrorCode
from .files import OutputWorkspace, filename, read_output
from .operations import ObjectOperations
from .safety import SafetyClass, SafetyPolicy, require_revision
from .tools import Tool
from .validation import fields, integer, string


@dataclass(frozen=True)
class RenderConfig:
    width: int
    height: int
    samples: int
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"width", "height", "samples", "expected_scene_revision"})
        return cls(
            integer(data["width"], "width", 16, 512),
            integer(data["height"], "height", 16, 512),
            integer(data["samples"], "samples", 1, 16),
            string(data["expected_scene_revision"], "revision", limit=64),
        )


@dataclass(frozen=True)
class FileAction:
    name: str
    expected_scene_revision: str

    @classmethod
    def parse_png(cls, data):
        return cls.parse(data, ".png")

    @classmethod
    def parse_blend(cls, data):
        return cls.parse(data, ".blend")

    @classmethod
    def parse(cls, data, suffix):
        fields(data, {"name", "expected_scene_revision"})
        return cls(
            filename(data["name"], suffix),
            string(data["expected_scene_revision"], "revision", limit=64),
        )


class RenderOperations:
    def __init__(
        self,
        objects: ObjectOperations,
        policy: SafetyPolicy,
        workspace: OutputWorkspace | None = None,
    ):
        self.objects, self.policy, self.workspace = objects, policy, workspace
        self.inspector, self.bpy = objects.inspector, objects.bpy

    def configure(self, request: Request, action: RenderConfig) -> Result:
        before = self.inspector.summary()
        require_revision(action.expected_scene_revision, before["revision"])
        scene = self.bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = action.samples
        scene.render.resolution_x = action.width
        scene.render.resolution_y = action.height
        scene.render.resolution_percentage = 100
        scene.render.threads_mode = "FIXED"
        scene.render.threads = 1
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "8"
        after = self.inspector.summary()
        return self.objects._result(
            request,
            before,
            after,
            {
                "render": {
                    "engine": "CYCLES",
                    "resolution_x": action.width,
                    "resolution_y": action.height,
                    "resolution_percentage": 100,
                    "format": "PNG",
                    "color_mode": "RGBA",
                    "color_depth": "8",
                    "threads_mode": "FIXED",
                    "threads": 1,
                    "cycles": {"device": "CPU", "samples": action.samples},
                }
            },
        )

    def _workspace(self) -> OutputWorkspace:
        if self.workspace is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "No output workspace configured")
        return self.workspace

    def render(self, request: Request, action: FileAction) -> Result:
        self.policy.check(SafetyClass.RENDER)
        before = self.inspector.summary()
        require_revision(action.expected_scene_revision, before["revision"])
        scene = self.bpy.context.scene
        render = scene.render
        if (
            scene.camera is None
            or render.engine != "CYCLES"
            or scene.cycles.device != "CPU"
            or not 1 <= scene.cycles.samples <= 16
            or not 16 <= render.resolution_x <= 512
            or not 16 <= render.resolution_y <= 512
            or render.resolution_percentage != 100
            or render.threads_mode != "FIXED"
            or render.threads != 1
            or render.image_settings.file_format != "PNG"
            or render.image_settings.color_mode != "RGBA"
            or render.image_settings.color_depth != "8"
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Configure bounded CPU render and camera first"
            )
        previous = render.filepath
        try:
            with self._workspace().reserve(action.name, ".png") as path:
                render.filepath = str(path)
                if self.bpy.ops.render.render(write_still=True) != {"FINISHED"}:
                    raise AgentError(ErrorCode.EXECUTION_ERROR, "Render did not finish")
                after = read_output(path, "PNG")
                return self.objects._result(
                    request,
                    before,
                    after,
                    {"format": "PNG", "width": render.resolution_x, "height": render.resolution_y},
                )
        finally:
            render.filepath = previous

    def checkpoint(self, request: Request, action: FileAction) -> Result:
        self.policy.check(SafetyClass.FILE_WRITE)
        before = self.inspector.summary()
        require_revision(action.expected_scene_revision, before["revision"])
        with self._workspace().reserve(action.name, ".blend") as path:
            outcome = self.bpy.ops.wm.save_as_mainfile(
                filepath=str(path),
                copy=True,
                compress=False,
                relative_remap=False,
                check_existing=False,
            )
            if outcome != {"FINISHED"}:
                raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender checkpoint did not finish")
            after = read_output(path, "BLEND")
            after["source_filepath"] = self.bpy.data.filepath
            return self.objects._result(
                request, before, after, {"format": "BLEND", "source_filepath": before["file"]}
            )

    def tools(self) -> list[Tool]:
        return [
            Tool("render.configure", SafetyClass.MUTATION, RenderConfig.parse, self.configure),
            Tool("render.execute", SafetyClass.RENDER, FileAction.parse_png, self.render),
            Tool(
                "file.checkpoint", SafetyClass.FILE_WRITE, FileAction.parse_blend, self.checkpoint
            ),
        ]
