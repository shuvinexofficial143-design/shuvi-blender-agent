"""Level 12 M2: native Lens Distortion and chromatic dispersion compositor pass.

Adds an owned Lensdist node between an existing image source and initially
unconnected Composite or Viewer target. No implicit footage loading or rendering.
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

LENS_NODE = "ShuviLensDistortion"


@dataclass(frozen=True)
class LensPreview:
    scene_name: str
    source_node: str
    output_node: str
    distortion: float
    dispersion: float
    use_fit: bool
    use_jitter: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "source_node",
                "output_node",
                "distortion",
                "dispersion",
                "use_fit",
                "use_jitter",
            },
        )
        if type(data["use_fit"]) is not bool or type(data["use_jitter"]) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Lens flags must be Boolean")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["source_node"], "source_node", limit=120),
            string(data["output_node"], "output_node", limit=120),
            number(data["distortion"], "distortion", -0.5, 0.5),
            number(data["dispersion"], "dispersion", 0, 0.25),
            data["use_fit"],
            data["use_jitter"],
        )


@dataclass(frozen=True)
class LensApply:
    preview: LensPreview
    expected_lens_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, set(LensPreview.__dataclass_fields__) | {"expected_lens_revision"})
        payload = dict(data)
        expected = string(payload.pop("expected_lens_revision"), "expected_lens_revision", limit=64)
        return cls(LensPreview.parse(payload), expected)


@dataclass(frozen=True)
class LensRelease:
    expected_lens_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_lens_token"})
        return cls(string(data["expected_lens_token"], "expected_lens_token", limit=64))


def expected(plan):
    return {
        "node_type": "CompositorNodeLensdist",
        "distortion": plan["distortion"],
        "dispersion": plan["dispersion"],
        "use_fit": plan["use_fit"],
        "use_jitter": plan["use_jitter"],
        "use_projector": False,
        "links_verified": True,
    }


def actual(tree, source, output, lens):
    links = [link for link in tree.links if link.from_node is lens or link.to_node is lens]
    pairs = (
        (source.outputs["Image"], lens.inputs["Image"]),
        (lens.outputs["Image"], output.inputs["Image"]),
    )
    matches = len(links) == 2 and all(
        sum(link.from_socket is a and link.to_socket is b for link in links) == 1 for a, b in pairs
    )
    return {
        "node_type": str(lens.bl_idname),
        "distortion": float(lens.inputs["Distort"].default_value),
        "dispersion": float(lens.inputs["Dispersion"].default_value),
        "use_fit": bool(lens.use_fit),
        "use_jitter": bool(lens.use_jitter),
        "use_projector": bool(lens.use_projector),
        "links_verified": matches,
    }


class LensDistortionOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if len(tree.nodes) >= 128 or len(tree.links) > 254:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor capacity exceeded")
        if tree.nodes.get(LENS_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved lens node exists")
        if action.source_node == action.output_node:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Separate lens source and target required")
        source = tree.nodes.get(action.source_node)
        output = tree.nodes.get(action.output_node)
        if source is None or output is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Lens source/target missing")
        if source.bl_idname not in IMAGE_SOURCES or output.bl_idname not in IMAGE_SINKS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported native image source/target")
        if any(link.to_socket is output.inputs["Image"] for link in tree.links):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Lens target already connected")
        if any(state["scene"] is scene for state in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Lens already owned in scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned lens passes")
        plan = {
            "scene_name": scene.name,
            "source_node": source.name,
            "output_node": output.name,
            "distortion": action.distortion,
            "dispersion": action.dispersion,
            "use_fit": action.use_fit,
            "use_jitter": action.use_jitter,
            "graph_before": graph_revision(tree),
            "mutation_performed": False,
            "source_only": True,
            "render_verified": False,
        }
        plan["lens_revision"] = revision(plan)
        return scene, tree, source, output, plan

    def preview(self, request, action):
        plan = self._plan(action)[4]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, source, output, plan = self._plan(action.preview)
        if plan["lens_revision"] != action.expected_lens_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Lens preview stale")
        node = None
        try:
            node = tree.nodes.new("CompositorNodeLensdist")
            node.name = LENS_NODE
            node.inputs["Distort"].default_value = plan["distortion"]
            node.inputs["Dispersion"].default_value = plan["dispersion"]
            node.use_fit = plan["use_fit"]
            node.use_jitter = plan["use_jitter"]
            node.use_projector = False
            tree.links.new(source.outputs["Image"], node.inputs["Image"])
            tree.links.new(node.outputs["Image"], output.inputs["Image"])
            settings = expected(plan)
            checked = compare(settings, actual(tree, source, output, node))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lens RNA/link readback mismatch")
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
                    "lens_token": token,
                    "lens_node": LENS_NODE,
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
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lens rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Lens setup failed; owned node rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_lens_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used lens token")
        scene, tree = require_scene(self.bpy, state["scene"].name)
        if (
            scene is not state["scene"]
            or tree is not state["tree"]
            or graph_revision(tree) != state["after"]
            or any(
                tree.nodes.get(node.name) is not node
                for node in (state["source"], state["output"], state["node"])
            )
            or not compare(
                state["expected"],
                actual(tree, state["source"], state["output"], state["node"]),
            ).matched
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Lens graph edited externally")
        tree.nodes.remove(state["node"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lens restore mismatch")
        del self._owned[action.expected_lens_token]
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
            Tool("compositor.lens_preview", SafetyClass.READ_ONLY, LensPreview.parse, self.preview),
            Tool("compositor.lens_apply", SafetyClass.MUTATION, LensApply.parse, self.apply),
            Tool("compositor.lens_release", SafetyClass.MUTATION, LensRelease.parse, self.release),
        ]
