"""Level11 M8: connect existing green-screen foreground to a background via Alpha Over.

Only unconnected Composite image sockets may be used. Does not load images,
change foreign links, run compositing, render or write project files.
"""

from dataclasses import dataclass

from .compositor_keying import graph_revision, require_scene
from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .verification import compare

BLEND_NODE = "ShuviAlphaOver"
BACKGROUND_TYPES = {"CompositorNodeImage", "CompositorNodeMovieClip", "CompositorNodeRLayers"}


@dataclass(frozen=True)
class BlendPreview:
    scene_name: str
    foreground_node: str
    background_node: str
    composite_node: str
    opacity: float
    use_premultiply: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "foreground_node",
                "background_node",
                "composite_node",
                "opacity",
                "use_premultiply",
            },
        )
        premultiply = data["use_premultiply"]
        if type(premultiply) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "use_premultiply must be Boolean")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["foreground_node"], "foreground_node", limit=120),
            string(data["background_node"], "background_node", limit=120),
            string(data["composite_node"], "composite_node", limit=120),
            number(data["opacity"], "opacity", 0, 1),
            premultiply,
        )


@dataclass(frozen=True)
class BlendApply:
    preview: BlendPreview
    expected_blend_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "foreground_node",
                "background_node",
                "composite_node",
                "opacity",
                "use_premultiply",
                "expected_blend_revision",
            },
        )
        payload = dict(data)
        expected = string(
            payload.pop("expected_blend_revision"), "expected_blend_revision", limit=64
        )
        return cls(BlendPreview.parse(payload), expected)


@dataclass(frozen=True)
class BlendRelease:
    expected_blend_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_blend_token"})
        return cls(string(data["expected_blend_token"], "expected_blend_token", limit=64))


class AlphaCompositeOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if tree.nodes.get(BLEND_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved Alpha Over node already exists")
        names = [action.foreground_node, action.background_node, action.composite_node]
        if len(set(names)) != 3:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Separate compositor source/sink nodes")
        foreground, background, output = (tree.nodes.get(name) for name in names)
        if any(item is None for item in (foreground, background, output)):
            raise AgentError(ErrorCode.NOT_FOUND, "Required compositor nodes are missing")
        if foreground.bl_idname != "CompositorNodeKeying":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Foreground must be a native Keying node")
        if background.bl_idname not in BACKGROUND_TYPES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported existing background source")
        if output.bl_idname != "CompositorNodeComposite":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Native Composite output required")
        if any(link.to_socket is output.inputs["Image"] for link in tree.links):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composite output already linked")
        if any(state["scene"] is scene for state in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composite already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned composite workflows")
        plan = {
            "scene_name": scene.name,
            "foreground_node": foreground.name,
            "background_node": background.name,
            "composite_node": output.name,
            "opacity": action.opacity,
            "use_premultiply": action.use_premultiply,
            "graph_before": graph_revision(tree),
            "source_only": True,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["blend_revision"] = revision(plan)
        return scene, tree, (foreground, background, output), plan

    @staticmethod
    def _actual(tree, alpha, sources):
        fg, bg, target = sources
        expected_links = [
            (bg.outputs["Image"], alpha.inputs[1]),
            (fg.outputs["Image"], alpha.inputs[2]),
            (alpha.outputs["Image"], target.inputs["Image"]),
        ]
        owned_links = [
            link
            for link in tree.links
            if link.from_node is alpha or link.to_node is alpha
        ]
        correct = (
            len(owned_links) == 3
            and all(
                sum(
                    link.from_socket is source and link.to_socket is sink
                    for link in owned_links
                )
                == 1
                for source, sink in expected_links
            )
        )
        return {
            "node_type": str(alpha.bl_idname),
            "opacity": float(alpha.inputs[0].default_value),
            "use_premultiply": bool(alpha.use_premultiply),
            "source_links_verified": correct,
        }

    @staticmethod
    def _expected(plan):
        return {
            "node_type": "CompositorNodeAlphaOver",
            "opacity": plan["opacity"],
            "use_premultiply": plan["use_premultiply"],
            "source_links_verified": True,
        }

    def preview(self, request, action):
        plan = self._plan(action)[3]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, sources, plan = self._plan(action.preview)
        if action.expected_blend_revision != plan["blend_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Stale Alpha Over preview")
        alpha = None
        try:
            alpha = tree.nodes.new("CompositorNodeAlphaOver")
            alpha.name = BLEND_NODE
            alpha.inputs[0].default_value = plan["opacity"]
            alpha.use_premultiply = plan["use_premultiply"]
            fg, bg, target = sources
            tree.links.new(bg.outputs["Image"], alpha.inputs[1])
            tree.links.new(fg.outputs["Image"], alpha.inputs[2])
            tree.links.new(alpha.outputs["Image"], target.inputs["Image"])
            checked = compare(self._expected(plan), self._actual(tree, alpha, sources))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Alpha Over readback mismatch")
            after = graph_revision(tree)
            token = revision(
                {"before": plan["graph_before"], "after": after, "settings": self._expected(plan)}
            )
            self._owned[token] = {
                "scene": scene, "tree": tree, "alpha": alpha, "sources": sources,
                "after": after, "before": plan["graph_before"],
                "expected": self._expected(plan),
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "blend_token": token,
                    "alpha_node": BLEND_NODE,
                    "links_created": 3,
                    "source_only": True,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            if alpha is not None and any(node is alpha for node in tree.nodes):
                tree.nodes.remove(alpha)
            if graph_revision(tree) != plan["graph_before"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Alpha rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Alpha setup failed; owned node rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_blend_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used Alpha Over token")
        scene, tree = require_scene(self.bpy, state["scene"].name)
        if (
            scene is not state["scene"]
            or tree is not state["tree"]
            or tree.nodes.get(BLEND_NODE) is not state["alpha"]
            or graph_revision(tree) != state["after"]
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composite graph edited externally")
        if any(tree.nodes.get(obj.name) is not obj for obj in state["sources"]):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composite source replaced")
        if not compare(
            state["expected"], self._actual(tree, state["alpha"], state["sources"])
        ).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Alpha properties or links edited")
        tree.nodes.remove(state["alpha"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Alpha restore mismatch")
        del self._owned[action.expected_blend_token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id, request.command_id, Status.VERIFIED,
            {"owned_node_removed": 1, "owned_links_removed": 3, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "compositor.blend_preview", SafetyClass.READ_ONLY, BlendPreview.parse, self.preview
            ),
            Tool(
                "compositor.blend_apply", SafetyClass.MUTATION, BlendApply.parse, self.apply
            ),
            Tool(
                "compositor.blend_release", SafetyClass.MUTATION, BlendRelease.parse, self.release
            ),
        ]
