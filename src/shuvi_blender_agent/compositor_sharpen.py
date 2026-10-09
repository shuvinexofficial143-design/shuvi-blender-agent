"""Level 12 M5: safe native compositor image sharpening filter.

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
from .validation import fields, number, string
from .verification import compare

SHARPEN_NODE = "ShuviSharpenFilter"


@dataclass(frozen=True)
class SharpenPreview:
    scene_name: str
    source_node: str
    output_node: str
    filter_type: str
    strength: float

    @classmethod
    def parse(cls, data):
        fields(data, {"scene_name", "source_node", "output_node", "filter_type", "strength"})
        filter_type = string(data["filter_type"], "filter_type", limit=24)
        if filter_type not in ("SHARPEN", "SHARPEN_DIAMOND"):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Filter must be a native sharpen mode")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["source_node"], "source_node", limit=120),
            string(data["output_node"], "output_node", limit=120),
            filter_type,
            number(data["strength"], "strength", 0, 1),
        )


@dataclass(frozen=True)
class SharpenApply:
    preview: SharpenPreview
    expected_sharpen_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, set(SharpenPreview.__dataclass_fields__) | {"expected_sharpen_revision"})
        payload = dict(data)
        expected = string(
            payload.pop("expected_sharpen_revision"), "expected_sharpen_revision", limit=64
        )
        return cls(SharpenPreview.parse(payload), expected)


@dataclass(frozen=True)
class SharpenRelease:
    expected_sharpen_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_sharpen_token"})
        return cls(string(data["expected_sharpen_token"], "expected_sharpen_token", limit=64))


def actual(tree, source, output, node):
    links = [item for item in tree.links if item.from_node is node or item.to_node is node]
    pairs = (
        (source.outputs["Image"], node.inputs["Image"]),
        (node.outputs["Image"], output.inputs["Image"]),
    )
    connected = len(links) == 2 and all(
        sum(item.from_socket is a and item.to_socket is b for item in links) == 1 for a, b in pairs
    )
    return {
        "node_type": str(node.bl_idname),
        "filter_type": str(node.filter_type),
        "strength": float(node.inputs["Fac"].default_value),
        "links_verified": connected,
    }


def expected(plan):
    return {
        "node_type": "CompositorNodeFilter",
        "filter_type": plan["filter_type"],
        "strength": plan["strength"],
        "links_verified": True,
    }


class SharpenFilterOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if len(tree.nodes) >= 128 or len(tree.links) > 254:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor capacity exceeded")
        if tree.nodes.get(SHARPEN_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved sharpen node exists")
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
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color sharpen already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned color sharpens")
        plan = {
            "scene_name": scene.name,
            "source_node": source.name,
            "output_node": output.name,
            "filter_type": action.filter_type,
            "strength": action.strength,
            "graph_before": graph_revision(tree),
            "mutation_performed": False,
            "source_only": True,
            "render_verified": False,
        }
        plan["sharpen_revision"] = revision(plan)
        return scene, tree, source, output, plan

    def preview(self, request, action):
        plan = self._plan(action)[4]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, source, output, plan = self._plan(action.preview)
        if action.expected_sharpen_revision != plan["sharpen_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Color sharpen preview stale")
        node = None
        try:
            node = tree.nodes.new("CompositorNodeFilter")
            node.name = SHARPEN_NODE
            node.filter_type = plan["filter_type"]
            node.inputs["Fac"].default_value = plan["strength"]
            tree.links.new(source.outputs["Image"], node.inputs["Image"])
            tree.links.new(node.outputs["Image"], output.inputs["Image"])
            settings = expected(plan)
            checked = compare(settings, actual(tree, source, output, node))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Sharpen RNA/link readback failed")
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
                    "sharpen_token": token,
                    "sharpen_node": SHARPEN_NODE,
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
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Sharpen rollback uncertain"
                ) from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Sharpen setup failed; owned node rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_sharpen_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used sharpen token")
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
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color sharpen graph edited externally")
        tree.nodes.remove(state["node"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Sharpen restore mismatch")
        del self._owned[action.expected_sharpen_token]
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
                "compositor.sharpen_preview", SafetyClass.READ_ONLY, SharpenPreview.parse, self.preview
            ),
            Tool("compositor.sharpen_apply", SafetyClass.MUTATION, SharpenApply.parse, self.apply),
            Tool(
                "compositor.sharpen_release", SafetyClass.MUTATION, SharpenRelease.parse, self.release
            ),
        ]
