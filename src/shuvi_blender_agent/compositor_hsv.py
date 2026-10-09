"""Level 12 M3: reversible native compositor Hue/Saturation/Value adjustment.

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

HUE_NODE = "ShuviHSVAdjust"


@dataclass(frozen=True)
class HuePreview:
    scene_name: str
    source_node: str
    output_node: str
    hue: float
    saturation: float
    value: float
    factor: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"scene_name", "source_node", "output_node", "hue", "saturation", "value", "factor"},
        )
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["source_node"], "source_node", limit=120),
            string(data["output_node"], "output_node", limit=120),
            number(data["hue"], "hue", 0, 1),
            number(data["saturation"], "saturation", 0, 2),
            number(data["value"], "value", 0, 2),
            number(data["factor"], "factor", 0, 1),
        )


@dataclass(frozen=True)
class HueApply:
    preview: HuePreview
    expected_hue_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, set(HuePreview.__dataclass_fields__) | {"expected_hue_revision"})
        payload = dict(data)
        expected = string(payload.pop("expected_hue_revision"), "expected_hue_revision", limit=64)
        return cls(HuePreview.parse(payload), expected)


@dataclass(frozen=True)
class HueRelease:
    expected_hue_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_hue_token"})
        return cls(string(data["expected_hue_token"], "expected_hue_token", limit=64))


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
        "hue": float(node.inputs["Hue"].default_value),
        "saturation": float(node.inputs["Saturation"].default_value),
        "value": float(node.inputs["Value"].default_value),
        "factor": float(node.inputs["Fac"].default_value),
        "links_verified": correct,
    }


def expected(plan):
    return {
        "node_type": "CompositorNodeHueSat",
        "hue": plan["hue"],
        "saturation": plan["saturation"],
        "value": plan["value"],
        "factor": plan["factor"],
        "links_verified": True,
    }


class HSVColorOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if len(tree.nodes) >= 128 or len(tree.links) > 254:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor capacity exceeded")
        if tree.nodes.get(HUE_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved hue node exists")
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
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color hue already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned color hues")
        plan = {
            "scene_name": scene.name,
            "source_node": source.name,
            "output_node": output.name,
            "hue": action.hue,
            "saturation": action.saturation,
            "value": action.value,
            "factor": action.factor,
            "graph_before": graph_revision(tree),
            "mutation_performed": False,
            "source_only": True,
            "render_verified": False,
        }
        plan["hue_revision"] = revision(plan)
        return scene, tree, source, output, plan

    def preview(self, request, action):
        plan = self._plan(action)[4]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, source, output, plan = self._plan(action.preview)
        if action.expected_hue_revision != plan["hue_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Color hue preview stale")
        node = None
        try:
            node = tree.nodes.new("CompositorNodeHueSat")
            node.name = HUE_NODE
            node.inputs["Hue"].default_value = plan["hue"]
            node.inputs["Saturation"].default_value = plan["saturation"]
            node.inputs["Value"].default_value = plan["value"]
            node.inputs["Fac"].default_value = plan["factor"]
            tree.links.new(source.outputs["Image"], node.inputs["Image"])
            tree.links.new(node.outputs["Image"], output.inputs["Image"])
            settings = expected(plan)
            checked = compare(settings, actual(tree, source, output, node))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Hue RNA/link readback failed")
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
                    "hue_token": token,
                    "hue_node": HUE_NODE,
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
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Hue rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Hue setup failed; owned node rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_hue_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used hue token")
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
            raise AgentError(ErrorCode.SAFETY_DENIED, "Color hue graph edited externally")
        tree.nodes.remove(state["node"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Hue restore mismatch")
        del self._owned[action.expected_hue_token]
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
            Tool("compositor.hsv_preview", SafetyClass.READ_ONLY, HuePreview.parse, self.preview),
            Tool("compositor.hsv_apply", SafetyClass.MUTATION, HueApply.parse, self.apply),
            Tool("compositor.hsv_release", SafetyClass.MUTATION, HueRelease.parse, self.release),
        ]
