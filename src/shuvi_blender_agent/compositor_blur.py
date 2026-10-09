"""Level 12 M4: reversible native fixed-radius Gaussian image blur.

Connects an existing native image source to a previously unlinked Composite or
Viewer output, without changing any foreign links, scene settings or files.
"""

from dataclasses import dataclass
from uuid import uuid4

from .compositor_grade import IMAGE_SINKS, IMAGE_SOURCES
from .compositor_keying import graph_revision, require_scene
from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, string
from .verification import compare

BLUR_NODE = "ShuviGaussianBlur"


@dataclass(frozen=True)
class BlurPreview:
    scene_name: str
    source_node: str
    output_node: str
    radius_x: int
    radius_y: int
    filter_type: str
    use_extended_bounds: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "source_node",
                "output_node",
                "radius_x",
                "radius_y",
                "filter_type",
                "use_extended_bounds",
            },
        )
        filter_type = string(data["filter_type"], "filter_type", limit=20)
        if filter_type not in ("GAUSS", "FAST_GAUSS"):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unsupported blur filter")
        if type(data["use_extended_bounds"]) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "use_extended_bounds must be Boolean")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["source_node"], "source_node", limit=120),
            string(data["output_node"], "output_node", limit=120),
            integer(data["radius_x"], "radius_x", 1, 64),
            integer(data["radius_y"], "radius_y", 1, 64),
            filter_type,
            data["use_extended_bounds"],
        )


@dataclass(frozen=True)
class BlurApply:
    preview: BlurPreview
    expected_blur_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, set(BlurPreview.__dataclass_fields__) | {"expected_blur_revision"})
        payload = dict(data)
        expected = string(payload.pop("expected_blur_revision"), "expected_blur_revision", limit=64)
        return cls(BlurPreview.parse(payload), expected)


@dataclass(frozen=True)
class BlurRelease:
    expected_blur_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_blur_token"})
        return cls(string(data["expected_blur_token"], "expected_blur_token", limit=64))


def actual(tree, source, output, node):
    links = [link for link in tree.links if link.from_node is node or link.to_node is node]
    pairs = (
        (source.outputs["Image"], node.inputs["Image"]),
        (node.outputs["Image"], output.inputs["Image"]),
    )
    correct = len(links) == 2 and all(
        sum(link.from_socket is a and link.to_socket is b for link in links) == 1 for a, b in pairs
    )
    return {
        "node_type": str(node.bl_idname),
        "radius_x": int(node.size_x),
        "radius_y": int(node.size_y),
        "filter_type": str(node.filter_type),
        "use_extended_bounds": bool(node.use_extended_bounds),
        "use_relative": bool(node.use_relative),
        "use_variable_size": bool(node.use_variable_size),
        "links_verified": correct,
    }


def expected(plan):
    return {
        "node_type": "CompositorNodeBlur",
        "radius_x": plan["radius_x"],
        "radius_y": plan["radius_y"],
        "filter_type": plan["filter_type"],
        "use_extended_bounds": plan["use_extended_bounds"],
        "use_relative": False,
        "use_variable_size": False,
        "links_verified": True,
    }


class GaussianBlurOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if len(tree.nodes) >= 128 or len(tree.links) > 254:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor capacity exceeded")
        if tree.nodes.get(BLUR_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved blur node exists")
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
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color blur already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned color blurs")
        plan = {
            "scene_name": scene.name,
            "source_node": source.name,
            "output_node": output.name,
            "radius_x": action.radius_x,
            "radius_y": action.radius_y,
            "filter_type": action.filter_type,
            "use_extended_bounds": action.use_extended_bounds,
            "graph_before": graph_revision(tree),
            "mutation_performed": False,
            "source_only": True,
            "render_verified": False,
        }
        plan["blur_revision"] = revision(plan)
        return scene, tree, source, output, plan

    def preview(self, request, action):
        plan = self._plan(action)[4]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, source, output, plan = self._plan(action.preview)
        if action.expected_blur_revision != plan["blur_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Color blur preview stale")
        node = None
        try:
            node = tree.nodes.new("CompositorNodeBlur")
            node.name = BLUR_NODE
            node.size_x = plan["radius_x"]
            node.size_y = plan["radius_y"]
            node.filter_type = plan["filter_type"]
            node.use_relative = False
            node.use_variable_size = False
            node.use_extended_bounds = plan["use_extended_bounds"]
            tree.links.new(source.outputs["Image"], node.inputs["Image"])
            tree.links.new(node.outputs["Image"], output.inputs["Image"])
            settings = expected(plan)
            checked = compare(settings, actual(tree, source, output, node))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Blur RNA/link readback failed")
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
                    "blur_token": token,
                    "blur_node": BLUR_NODE,
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
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Blur rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Blur setup failed; owned node rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_blur_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used blur token")
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
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color blur graph edited externally")
        tree.nodes.remove(state["node"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Blur restore mismatch")
        del self._owned[action.expected_blur_token]
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
            Tool("compositor.blur_preview", SafetyClass.READ_ONLY, BlurPreview.parse, self.preview),
            Tool("compositor.blur_apply", SafetyClass.MUTATION, BlurApply.parse, self.apply),
            Tool("compositor.blur_release", SafetyClass.MUTATION, BlurRelease.parse, self.release),
        ]
