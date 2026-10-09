"""Level 11 M9: guarded native matte dilation/erosion and alpha replacement.

Existing Keying Image/Matte feed owned Dilate/Erode and Set Alpha nodes.
The refined Image output remains available for downstream compositing; no foreign
output, footage, clip or project file is changed or rendered.
"""

from dataclasses import dataclass

from .compositor_keying import graph_revision, require_scene
from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, string
from .verification import compare

MATTE_NODE = "ShuviMatteRefine"
ALPHA_NODE = "ShuviMatteOutput"


def matte_expected(distance):
    return {
        "matte_node_type": "CompositorNodeDilateErode",
        "matte_mode": "STEP",
        "distance": distance,
        "alpha_node_type": "CompositorNodeSetAlpha",
        "alpha_mode": "REPLACE_ALPHA",
        "links_verified": True,
    }


def matte_actual(tree, key, matte, alpha):
    pairs = (
        (key.outputs["Matte"], matte.inputs["Mask"]),
        (key.outputs["Image"], alpha.inputs["Image"]),
        (matte.outputs["Mask"], alpha.inputs["Alpha"]),
    )
    links = [
        link
        for link in tree.links
        if link.from_node in (matte, alpha) or link.to_node in (matte, alpha)
    ]
    correct = len(links) == 3 and all(
        sum(link.from_socket is source and link.to_socket is target for link in links) == 1
        for source, target in pairs
    )
    return {
        "matte_node_type": str(matte.bl_idname),
        "matte_mode": str(matte.mode),
        "distance": int(matte.distance),
        "alpha_node_type": str(alpha.bl_idname),
        "alpha_mode": str(alpha.mode),
        "links_verified": correct,
    }


@dataclass(frozen=True)
class MattePreview:
    scene_name: str
    key_node: str
    distance: int

    @classmethod
    def parse(cls, data):
        fields(data, {"scene_name", "key_node", "distance"})
        return cls(
            string(data["scene_name"], "scene_name", limit=120),
            string(data["key_node"], "key_node", limit=120),
            integer(data["distance"], "distance", -8, 8),
        )


@dataclass(frozen=True)
class MatteApply:
    preview: MattePreview
    expected_matte_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"scene_name", "key_node", "distance", "expected_matte_revision"})
        payload = dict(data)
        expected = string(
            payload.pop("expected_matte_revision"), "expected_matte_revision", limit=64
        )
        return cls(MattePreview.parse(payload), expected)


@dataclass(frozen=True)
class MatteRelease:
    expected_matte_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_matte_token"})
        return cls(string(data["expected_matte_token"], "expected_matte_token", limit=64))


class MatteRefinementOperations:
    def __init__(self, bpy):
        self.bpy = bpy
        self._owned = {}

    def _plan(self, action):
        scene, tree = require_scene(self.bpy, action.scene_name)
        if any(tree.nodes.get(name) is not None for name in (MATTE_NODE, ALPHA_NODE)):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Reserved matte nodes already exist")
        key = tree.nodes.get(action.key_node)
        if key is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Keying node not found")
        if key.bl_idname != "CompositorNodeKeying":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Native Keying source required")
        if any(state["scene"] is scene for state in self._owned.values()):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Matte already owned in scene")
        if len(self._owned) >= 8:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Too many owned matte workflows")
        key_state = [
            float(key.clip_black),
            float(key.clip_white),
            float(key.despill_factor),
            [float(value) for value in key.inputs["Key Color"].default_value],
        ]
        plan = {
            "scene_name": scene.name,
            "key_node": key.name,
            "distance": action.distance,
            "key_state": key_state,
            "graph_before": graph_revision(tree),
            "source_only": True,
            "mutation_performed": False,
            "render_verified": False,
        }
        plan["matte_revision"] = revision(plan)
        return scene, tree, key, plan

    def preview(self, request, action):
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[3])

    def apply(self, request, action):
        scene, tree, key, plan = self._plan(action.preview)
        if plan["matte_revision"] != action.expected_matte_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Matte preview is stale")
        created = []
        try:
            matte = tree.nodes.new("CompositorNodeDilateErode")
            created.append(matte)
            matte.name = MATTE_NODE
            matte.mode = "STEP"
            matte.distance = plan["distance"]
            alpha = tree.nodes.new("CompositorNodeSetAlpha")
            created.append(alpha)
            alpha.name = ALPHA_NODE
            alpha.mode = "REPLACE_ALPHA"
            tree.links.new(key.outputs["Matte"], matte.inputs["Mask"])
            tree.links.new(key.outputs["Image"], alpha.inputs["Image"])
            tree.links.new(matte.outputs["Mask"], alpha.inputs["Alpha"])
            expected = matte_expected(plan["distance"])
            checked = compare(expected, matte_actual(tree, key, matte, alpha))
            if not checked.matched:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Matte RNA/link readback mismatch")
            after = graph_revision(tree)
            token = revision({"before": plan["graph_before"], "after": after, "expected": expected})
            self._owned[token] = {
                "scene": scene,
                "tree": tree,
                "key": key,
                "matte": matte,
                "alpha": alpha,
                "after": after,
                "before": plan["graph_before"],
                "expected": expected,
                "key_state": plan["key_state"],
            }
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "matte_token": token,
                    "refined_image_node": ALPHA_NODE,
                    "nodes_created": 2,
                    "links_created": 3,
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
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Matte rollback uncertain") from exc
            code = exc.code if isinstance(exc, AgentError) else ErrorCode.EXECUTION_ERROR
            raise AgentError(code, "Matte creation failed; owned nodes rolled back") from exc

    def release(self, request, action):
        state = self._owned.get(action.expected_matte_token)
        if state is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or used matte token")
        scene, tree = require_scene(self.bpy, state["scene"].name)
        if (
            scene is not state["scene"]
            or tree is not state["tree"]
            or tree.nodes.get(MATTE_NODE) is not state["matte"]
            or tree.nodes.get(ALPHA_NODE) is not state["alpha"]
            or tree.nodes.get(state["key"].name) is not state["key"]
            or graph_revision(tree) != state["after"]
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Matte graph edited externally")
        key = state["key"]
        current_key_state = [
            float(key.clip_black),
            float(key.clip_white),
            float(key.despill_factor),
            [float(value) for value in key.inputs["Key Color"].default_value],
        ]
        if current_key_state != state["key_state"] or not compare(
            state["expected"],
            matte_actual(tree, key, state["matte"], state["alpha"]),
        ).matched:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Matte or Keying settings edited")
        tree.nodes.remove(state["alpha"])
        tree.nodes.remove(state["matte"])
        if graph_revision(tree) != state["before"]:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Matte restore mismatch")
        del self._owned[action.expected_matte_token]
        checked = compare({"restored": True}, {"restored": True})
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"owned_nodes_removed": 2, "owned_links_removed": 3, "source_only": True},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool("compositor.matte_preview", SafetyClass.READ_ONLY, MattePreview.parse, self.preview),
            Tool("compositor.matte_apply", SafetyClass.MUTATION, MatteApply.parse, self.apply),
            Tool("compositor.matte_release", SafetyClass.MUTATION, MatteRelease.parse, self.release),
        ]
