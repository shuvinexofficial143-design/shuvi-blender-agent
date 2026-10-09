"""Level 11 M10: one guarded native green-screen compositor shot workflow.

Creates the complete five-node, seven-link Blender graph from an already-loaded
MovieClip and existing background/Composite nodes. Never loads files, replaces
foreign links, evaluates frames or renders. Rollback and release are owned-only.
"""

from dataclasses import dataclass
from uuid import uuid4

from .compositor_alpha_over import BACKGROUND_TYPES, BLEND_NODE
from .compositor_keying import CLIP_NODE, KEY_NODE, graph_revision, require_scene
from .compositor_matte import ALPHA_NODE, MATTE_NODE
from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, number, string
from .verification import compare

OWNED_NAMES = (CLIP_NODE, KEY_NODE, MATTE_NODE, ALPHA_NODE, BLEND_NODE)


@dataclass(frozen=True)
class ShotPreview:
    scene_name: str
    clip_name: str
    background_node: str
    composite_node: str
    key_color: tuple[float, ...]
    clip_black: float
    clip_white: float
    despill_factor: float
    matte_distance: int
    opacity: float
    use_premultiply: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "clip_name",
                "background_node",
                "composite_node",
                "key_color",
                "clip_black",
                "clip_white",
                "despill_factor",
                "matte_distance",
                "opacity",
                "use_premultiply",
            },
        )
        rgb = data["key_color"]
        if not isinstance(rgb, list) or len(rgb) != 3:
            raise AgentError(ErrorCode.INVALID_REQUEST, "key_color requires RGB")
        black = number(data["clip_black"], "clip_black", 0, 1)
        white = number(data["clip_white"], "clip_white", 0, 1)
        if black >= white:
            raise AgentError(ErrorCode.INVALID_REQUEST, "clip_white must exceed clip_black")
        premultiply = data["use_premultiply"]
        if type(premultiply) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "use_premultiply must be Boolean")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["clip_name"], "clip_name", limit=120),
            string(data["background_node"], "background_node", limit=120),
            string(data["composite_node"], "composite_node", limit=120),
            tuple(number(value, "key_color", 0, 1) for value in rgb),
            black,
            white,
            number(data["despill_factor"], "despill_factor", 0, 1),
            integer(data["matte_distance"], "matte_distance", -8, 8),
            number(data["opacity"], "opacity", 0, 1),
            premultiply,
        )


@dataclass(frozen=True)
class ShotApply:
    preview: ShotPreview
    expected_shot_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, set(ShotPreview.__dataclass_fields__) | {"expected_shot_revision"})
        payload = dict(data)
        expected = string(
            payload.pop("expected_shot_revision"), "expected_shot_revision", limit=64
        )
        return cls(ShotPreview.parse(payload), expected)


@dataclass(frozen=True)
class ShotRelease:
    expected_shot_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_shot_token"})
        return cls(string(data["expected_shot_token"], "expected_shot_token", limit=64))


def shot_expected(plan):
    return {
        "clip_node_type": "CompositorNodeMovieClip",
        "key_node_type": "CompositorNodeKeying",
        "clip_name": plan["clip_name"],
        "key_color": plan["key_color"],
        "clip_black": plan["clip_black"],
        "clip_white": plan["clip_white"],
        "despill_factor": plan["despill_factor"],
        "matte_node_type": "CompositorNodeDilateErode",
        "matte_mode": "STEP",
        "matte_distance": plan["matte_distance"],
        "set_alpha_node_type": "CompositorNodeSetAlpha",
        "set_alpha_mode": "REPLACE_ALPHA",
        "blend_node_type": "CompositorNodeAlphaOver",
        "opacity": plan["opacity"],
        "use_premultiply": plan["use_premultiply"],
        "links_verified": True,
    }


def shot_actual(tree, nodes, background, output):
    movie, key, matte, set_alpha, blend = nodes
    links = (
        (movie.outputs["Image"], key.inputs["Image"]),
        (key.outputs["Matte"], matte.inputs["Mask"]),
        (key.outputs["Image"], set_alpha.inputs["Image"]),
        (matte.outputs["Mask"], set_alpha.inputs["Alpha"]),
        (background.outputs["Image"], blend.inputs[1]),
        (set_alpha.outputs["Image"], blend.inputs[2]),
        (blend.outputs["Image"], output.inputs["Image"]),
    )
    owned_links = [
        link
        for link in tree.links
        if link.from_node in nodes or link.to_node in nodes
    ]
    valid = len(owned_links) == len(links) and all(
        sum(link.from_socket is source and link.to_socket is sink for link in owned_links) == 1
        for source, sink in links
    )
    return {
        "clip_node_type": str(movie.bl_idname),
        "key_node_type": str(key.bl_idname),
        "clip_name": movie.clip.name if movie.clip is not None else None,
        "key_color": [float(x) for x in key.inputs["Key Color"].default_value],
        "clip_black": float(key.clip_black),
        "clip_white": float(key.clip_white),
        "despill_factor": float(key.despill_factor),
        "matte_node_type": str(matte.bl_idname),
        "matte_mode": str(matte.mode),
        "matte_distance": int(matte.distance),
        "set_alpha_node_type": str(set_alpha.bl_idname),
        "set_alpha_mode": str(set_alpha.mode),
        "blend_node_type": str(blend.bl_idname),
        "opacity": float(blend.inputs[0].default_value),
        "use_premultiply": bool(blend.use_premultiply),
        "links_verified": valid,
    }


class GreenScreenShotOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if len(self.bpy.data.movieclips) > 32:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many loaded MovieClips")
        clip = self.bpy.data.movieclips.get(action.clip_name)
        if clip is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Clip must already be loaded")
        if getattr(clip, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Linked clips not permitted")
        if any(tree.nodes.get(name) is not None for name in OWNED_NAMES):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved shot nodes already exist")
        if action.background_node == action.composite_node:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Separate background and output required")
        background = tree.nodes.get(action.background_node)
        output = tree.nodes.get(action.composite_node)
        if background is None or output is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Background/Composite node missing")
        if background.bl_idname not in BACKGROUND_TYPES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported background type")
        if output.bl_idname != "CompositorNodeComposite":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composite output required")
        if any(link.to_socket is output.inputs["Image"] for link in tree.links):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composite output already connected")
        if any(state["scene"] is scene for state in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shot already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned shot workflows")
        plan = {
            "scene_name": scene.name,
            "clip_name": clip.name,
            "background_node": background.name,
            "composite_node": output.name,
            "key_color": list(action.key_color) + [1.0],
            "clip_black": action.clip_black,
            "clip_white": action.clip_white,
            "despill_factor": action.despill_factor,
            "matte_distance": action.matte_distance,
            "opacity": action.opacity,
            "use_premultiply": action.use_premultiply,
            "graph_before": graph_revision(tree),
            "source_only": True,
            "mutation_performed": False,
            "render_verified": False,
        }
        plan["shot_revision"] = revision(plan)
        return scene, tree, clip, background, output, plan

    def preview(self, request, action):
        plan = self._plan(action)[5]
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, plan)

    def apply(self, request, action):
        scene, tree, clip, background, output, plan = self._plan(action.preview)
        if plan["shot_revision"] != action.expected_shot_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Shot preview stale")
        created = []
        try:
            movie = tree.nodes.new("CompositorNodeMovieClip")
            created.append(movie)
            movie.name = CLIP_NODE
            movie.clip = clip
            key = tree.nodes.new("CompositorNodeKeying")
            created.append(key)
            key.name = KEY_NODE
            key.inputs["Key Color"].default_value = tuple(plan["key_color"])
            key.clip_black = plan["clip_black"]
            key.clip_white = plan["clip_white"]
            key.despill_factor = plan["despill_factor"]
            matte = tree.nodes.new("CompositorNodeDilateErode")
            created.append(matte)
            matte.name = MATTE_NODE
            matte.mode = "STEP"
            matte.distance = plan["matte_distance"]
            set_alpha = tree.nodes.new("CompositorNodeSetAlpha")
            created.append(set_alpha)
            set_alpha.name = ALPHA_NODE
            set_alpha.mode = "REPLACE_ALPHA"
            blend = tree.nodes.new("CompositorNodeAlphaOver")
            created.append(blend)
            blend.name = BLEND_NODE
            blend.inputs[0].default_value = plan["opacity"]
            blend.use_premultiply = plan["use_premultiply"]
            tree.links.new(movie.outputs["Image"], key.inputs["Image"])
            tree.links.new(key.outputs["Matte"], matte.inputs["Mask"])
            tree.links.new(key.outputs["Image"], set_alpha.inputs["Image"])
            tree.links.new(matte.outputs["Mask"], set_alpha.inputs["Alpha"])
            tree.links.new(background.outputs["Image"], blend.inputs[1])
            tree.links.new(set_alpha.outputs["Image"], blend.inputs[2])
            tree.links.new(blend.outputs["Image"], output.inputs["Image"])
            nodes = (movie, key, matte, set_alpha, blend)
            expected = shot_expected(plan)
            checked = compare(expected, shot_actual(tree, nodes, background, output))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Shot RNA/link mismatch")
            after = graph_revision(tree)
            token = revision(
                {"before": plan["graph_before"], "after": after, "nonce": uuid4().hex}
            )
            self._owned[token] = {
                "scene": scene,
                "tree": tree,
                "clip": clip,
                "background": background,
                "output": output,
                "nodes": nodes,
                "before": plan["graph_before"],
                "after": after,
                "expected": expected,
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "shot_token": token,
                    "nodes_created": 5,
                    "links_created": 7,
                    "composite_node": output.name,
                    "source_only": True,
                    "render_verified": False,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            for node in reversed(created):
                if any(item is node for item in tree.nodes):
                    tree.nodes.remove(node)
            if graph_revision(tree) != plan["graph_before"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Shot rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Shot setup failed; owned nodes rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_shot_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used shot token")
        scene, tree = require_scene(self.bpy, state["scene"].name)
        if (
            scene is not state["scene"]
            or tree is not state["tree"]
            or graph_revision(tree) != state["after"]
            or self.bpy.data.movieclips.get(state["clip"].name) is not state["clip"]
            or tree.nodes.get(state["background"].name) is not state["background"]
            or tree.nodes.get(state["output"].name) is not state["output"]
            or any(tree.nodes.get(node.name) is not node for node in state["nodes"])
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shot graph or references edited")
        if not compare(
            state["expected"],
            shot_actual(tree, state["nodes"], state["background"], state["output"]),
        ).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Shot parameters changed externally")
        for node in reversed(state["nodes"]):
            tree.nodes.remove(node)
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Shot restore mismatch")
        del self._owned[action.expected_shot_token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"owned_nodes_removed": 5, "owned_links_removed": 7, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool("compositor.shot_preview", SafetyClass.READ_ONLY, ShotPreview.parse, self.preview),
            Tool("compositor.shot_apply", SafetyClass.MUTATION, ShotApply.parse, self.apply),
            Tool("compositor.shot_release", SafetyClass.MUTATION, ShotRelease.parse, self.release),
        ]
