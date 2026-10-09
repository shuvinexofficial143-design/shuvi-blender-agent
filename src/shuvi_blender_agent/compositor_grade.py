"""Level 12 M1: reversible native compositor Bright/Contrast image grading.

Connects an existing native image source to a previously unlinked Composite or
Viewer output, without changing any foreign links, scene settings or files.
"""

from dataclasses import dataclass
from uuid import uuid4

from .compositor_keying import graph_revision, require_scene
from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .verification import compare

GRADE_NODE = "ShuviColorGrade"
IMAGE_SOURCES = {
    "CompositorNodeImage",
    "CompositorNodeMovieClip",
    "CompositorNodeRLayers",
    "CompositorNodeKeying",
    "CompositorNodeAlphaOver",
    "CompositorNodeSetAlpha",
    "CompositorNodeBrightContrast",
    "CompositorNodeHueSat",
    "CompositorNodeLensdist",
}
IMAGE_SINKS = {"CompositorNodeComposite", "CompositorNodeViewer"}


@dataclass(frozen=True)
class GradePreview:
    scene_name: str
    source_node: str
    output_node: str
    brightness: float
    contrast: float
    use_premultiply: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "source_node",
                "output_node",
                "brightness",
                "contrast",
                "use_premultiply",
            },
        )
        premultiply = data["use_premultiply"]
        if type(premultiply) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "use_premultiply must be Boolean")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["source_node"], "source_node", limit=120),
            string(data["output_node"], "output_node", limit=120),
            number(data["brightness"], "brightness", -100, 100),
            number(data["contrast"], "contrast", -100, 100),
            premultiply,
        )


@dataclass(frozen=True)
class GradeApply:
    preview: GradePreview
    expected_grade_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, set(GradePreview.__dataclass_fields__) | {"expected_grade_revision"})
        payload = dict(data)
        expected = string(
            payload.pop("expected_grade_revision"), "expected_grade_revision", limit=64
        )
        return cls(GradePreview.parse(payload), expected)


@dataclass(frozen=True)
class GradeRelease:
    expected_grade_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_grade_token"})
        return cls(string(data["expected_grade_token"], "expected_grade_token", limit=64))


def actual(tree, source, output, grade):
    links = [item for item in tree.links if item.from_node is grade or item.to_node is grade]
    pairs = (
        (source.outputs["Image"], grade.inputs["Image"]),
        (grade.outputs["Image"], output.inputs["Image"]),
    )
    correct = len(links) == 2 and all(
        sum(item.from_socket is a and item.to_socket is b for item in links) == 1 for a, b in pairs
    )
    return {
        "node_type": str(grade.bl_idname),
        "brightness": float(grade.inputs["Bright"].default_value),
        "contrast": float(grade.inputs["Contrast"].default_value),
        "use_premultiply": bool(grade.use_premultiply),
        "links_verified": correct,
    }


def expected(plan):
    return {
        "node_type": "CompositorNodeBrightContrast",
        "brightness": plan["brightness"],
        "contrast": plan["contrast"],
        "use_premultiply": plan["use_premultiply"],
        "links_verified": True,
    }


class ColorGradeOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if len(tree.nodes) >= 128 or len(tree.links) > 254:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor capacity exceeded")
        if tree.nodes.get(GRADE_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved grade node exists")
        if action.source_node == action.output_node:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Separate source and output required")
        source, output = tree.nodes.get(action.source_node), tree.nodes.get(action.output_node)
        if source is None or output is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Source or output node missing")
        if source.bl_idname not in IMAGE_SOURCES or output.bl_idname not in IMAGE_SINKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported native compositor nodes")
        if any(link.to_socket is output.inputs["Image"] for link in tree.links):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Output already connected")
        if any(state["scene"] is scene for state in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color grade already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned color grades")
        plan = {
            "scene_name": scene.name,
            "source_node": source.name,
            "output_node": output.name,
            "brightness": action.brightness,
            "contrast": action.contrast,
            "use_premultiply": action.use_premultiply,
            "graph_before": graph_revision(tree),
            "mutation_performed": False,
            "source_only": True,
            "render_verified": False,
        }
        plan["grade_revision"] = revision(plan)
        return scene, tree, source, output, plan

    def preview(self, request, action):
        plan = self._plan(action)[4]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, source, output, plan = self._plan(action.preview)
        if action.expected_grade_revision != plan["grade_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Color grade preview stale")
        node = None
        try:
            node = tree.nodes.new("CompositorNodeBrightContrast")
            node.name = GRADE_NODE
            node.inputs["Bright"].default_value = plan["brightness"]
            node.inputs["Contrast"].default_value = plan["contrast"]
            node.use_premultiply = plan["use_premultiply"]
            tree.links.new(source.outputs["Image"], node.inputs["Image"])
            tree.links.new(node.outputs["Image"], output.inputs["Image"])
            settings = expected(plan)
            checked = compare(settings, actual(tree, source, output, node))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Grade RNA/link readback failed")
            after = graph_revision(tree)
            token = revision({"before": plan["graph_before"], "after": after, "nonce": uuid4().hex})
            self._owned[token] = {
                "scene": scene,
                "tree": tree,
                "source": source,
                "output": output,
                "node": node,
                "before": plan["graph_before"],
                "after": after,
                "expected": settings,
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "grade_token": token,
                    "grade_node": GRADE_NODE,
                    "links_created": 2,
                    "source_only": True,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            if node is not None and any(item is node for item in tree.nodes):
                tree.nodes.remove(node)
            if graph_revision(tree) != plan["graph_before"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Grade rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Grade setup failed; owned node rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_grade_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used grade token")
        scene, tree = require_scene(self.bpy, state["scene"].name)
        if (
            scene is not state["scene"]
            or tree is not state["tree"]
            or graph_revision(tree) != state["after"]
            or any(
                tree.nodes.get(x.name) is not x
                for x in (state["source"], state["output"], state["node"])
            )
            or not compare(
                state["expected"],
                actual(tree, state["source"], state["output"], state["node"]),
            ).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color grade graph edited externally")
        tree.nodes.remove(state["node"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Grade restore mismatch")
        del self._owned[action.expected_grade_token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"owned_nodes_removed": 1, "owned_links_removed": 2, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "compositor.grade_preview", SafetyClass.READ_ONLY, GradePreview.parse, self.preview
            ),
            Tool("compositor.grade_apply", SafetyClass.MUTATION, GradeApply.parse, self.apply),
            Tool(
                "compositor.grade_release", SafetyClass.MUTATION, GradeRelease.parse, self.release
            ),
        ]
