"""Level 11 M7: native Blender compositor chroma key on already-loaded footage.

Creates owned Movie Clip → Keying nodes on an existing compositor tree without
changing scene.use_nodes, linking output sockets or rendering frames.
"""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .verification import compare

CLIP_NODE = "ShuviGreenClip"
KEY_NODE = "ShuviGreenKey"


def require_scene(bpy, name):
    scene = bpy.data.scenes.get(name)
    if scene is None:
        raise AgentError(ErrorCode.NOT_FOUND, "Loaded scene not found")
    if getattr(scene, "library", None) is not None or not scene.use_nodes:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Existing local compositor required")
    tree = scene.node_tree
    if tree is None or len(tree.nodes) > 128 or len(tree.links) > 256:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor graph unavailable or too large")
    return scene, tree


def _socket_index(sockets, member):
    for index, socket in enumerate(sockets):
        if socket is member:
            return index
    raise AgentError(ErrorCode.SAFETY_DENIED, "Disconnected compositor socket")


def graph_revision(tree):
    """Track foreign rewires, not just node counts and labels."""
    nodes = sorted((str(node.name), str(node.bl_idname)) for node in tree.nodes)
    if len(nodes) != len(set(name for name, _ in nodes)):
        raise AgentError(ErrorCode.SAFETY_DENIED, "Ambiguous compositor node names")
    links = sorted(
        (
            link.from_node.name,
            _socket_index(link.from_node.outputs, link.from_socket),
            link.to_node.name,
            _socket_index(link.to_node.inputs, link.to_socket),
        )
        for link in tree.links
    )
    return revision({"nodes": nodes, "links": links})


@dataclass(frozen=True)
class KeyPreview:
    scene_name: str
    clip_name: str
    key_color: tuple[float, ...]
    clip_black: float
    clip_white: float
    despill_factor: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"scene_name", "clip_name", "key_color", "clip_black", "clip_white", "despill_factor"},
        )
        rgb = data["key_color"]
        if not isinstance(rgb, list) or len(rgb) != 3:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Key color requires RGB")
        color = tuple(number(x, "key_color", 0, 1) for x in rgb)
        black = number(data["clip_black"], "clip_black", 0, 1)
        white = number(data["clip_white"], "clip_white", 0, 1)
        if black >= white:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Key white must exceed black")
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["clip_name"], "clip_name", limit=120),
            color,
            black,
            white,
            number(data["despill_factor"], "despill_factor", 0, 1),
        )


@dataclass(frozen=True)
class KeyApply:
    preview: KeyPreview
    expected_key_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "scene_name",
                "clip_name",
                "key_color",
                "clip_black",
                "clip_white",
                "despill_factor",
                "expected_key_revision",
            },
        )
        prepared = dict(data)
        token = string(prepared.pop("expected_key_revision"), "expected_key_revision", limit=64)
        return cls(KeyPreview.parse(prepared), token)


@dataclass(frozen=True)
class KeyRelease:
    expected_key_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_key_token"})
        return cls(string(data["expected_key_token"], "expected_key_token", limit=64))


class ChromaKeyOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        clips = self.bpy.data.movieclips
        if len(clips) > 32:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many loaded MovieClips")
        clip = clips.get(action.clip_name)
        if clip is None:
            raise AgentError(ErrorCode.NOT_FOUND, "MovieClip must already be loaded")
        if getattr(clip, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Linked MovieClip not permitted")
        if tree.nodes.get(CLIP_NODE) is not None or tree.nodes.get(KEY_NODE) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved chroma nodes already exist")
        if any(s["scene"] is scene for s in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Chroma key already owned for scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned keying workflows")
        plan = {
            "scene_name": scene.name,
            "clip_name": clip.name,
            "graph_before": graph_revision(tree),
            "key_color": list(action.key_color) + [1.0],
            "clip_black": action.clip_black,
            "clip_white": action.clip_white,
            "despill_factor": action.despill_factor,
            "source_only": True,
            "mutation_performed": False,
            "render_verified": False,
        }
        plan["key_revision"] = revision(plan)
        return scene, tree, clip, plan

    @staticmethod
    def _read(clip_node, key_node):
        return {
            "clip_node_type": str(clip_node.bl_idname),
            "key_node_type": str(key_node.bl_idname),
            "clip_name": clip_node.clip.name if clip_node.clip is not None else None,
            "key_color": [float(x) for x in key_node.inputs["Key Color"].default_value],
            "clip_black": float(key_node.clip_black),
            "clip_white": float(key_node.clip_white),
            "despill_factor": float(key_node.despill_factor),
        }

    @staticmethod
    def _expected(plan):
        return {
            "clip_node_type": "CompositorNodeMovieClip",
            "key_node_type": "CompositorNodeKeying",
            "clip_name": plan["clip_name"],
            "key_color": plan["key_color"],
            "clip_black": plan["clip_black"],
            "clip_white": plan["clip_white"],
            "despill_factor": plan["despill_factor"],
        }

    def preview(self, request, action):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[3]
        )

    def apply(self, request, action):
        scene, tree, clip, plan = self._plan(action.preview)
        if action.expected_key_revision != plan["key_revision"]:
            raise AgentError(ErrorCode.STALE_STATE, "Keying preview is stale")
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
            tree.links.new(movie.outputs["Image"], key.inputs["Image"])
            checked = compare(self._expected(plan), self._read(movie, key))
            if (
                not checked.matched
                or len(
                    [
                        link
                        for link in tree.links
                        if link.from_node is movie
                        and link.to_node is key
                        and link.from_socket is movie.outputs["Image"]
                        and link.to_socket is key.inputs["Image"]
                    ]
                )
                != 1
            ):
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Chroma key RNA readback failed")
            after = graph_revision(tree)
            token = revision(
                {"before": plan["graph_before"], "after": after, "settings": self._expected(plan)}
            )
            self._owned[token] = {
                "scene": scene,
                "tree": tree,
                "movie": movie,
                "key": key,
                "expected": self._expected(plan),
                "after": after,
                "before": plan["graph_before"],
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "key_token": token,
                    "movie_node": CLIP_NODE,
                    "key_node": KEY_NODE,
                    "render_verified": False,
                    "source_only": True,
                },
                verification=checked.to_dict(),
            )
        except Exception as exc:
            for node in reversed(created):
                if any(x is node for x in tree.nodes):
                    tree.nodes.remove(node)
            if graph_revision(tree) != plan["graph_before"]:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Key rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Chroma setup failed; owned nodes rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_key_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or consumed key token")
        scene, tree = require_scene(self.bpy, state["scene"].name)
        if scene is not state["scene"] or tree is not state["tree"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Compositor was replaced")
        if (
            tree.nodes.get(CLIP_NODE) is not state["movie"]
            or tree.nodes.get(KEY_NODE) is not state["key"]
            or graph_revision(tree) != state["after"]
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Chroma compositor edited externally")
        if not compare(state["expected"], self._read(state["movie"], state["key"])).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Chroma properties edited externally")
        tree.nodes.remove(state["key"])
        tree.nodes.remove(state["movie"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Chroma restore mismatch")
        del self._owned[action.expected_key_token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"owned_nodes_removed": 2, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool("compositor.key_preview", SafetyClass.READ_ONLY, KeyPreview.parse, self.preview),
            Tool("compositor.key_apply", SafetyClass.MUTATION, KeyApply.parse, self.apply),
            Tool("compositor.key_release", SafetyClass.MUTATION, KeyRelease.parse, self.release),
        ]
