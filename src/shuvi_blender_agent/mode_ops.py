"""Allowlisted context mode transitions with strict active-object guards."""

from dataclasses import dataclass

from .contracts import Request
from .errors import AgentError, ErrorCode
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .scene_state import mode_snapshot
from .tools import Tool
from .validation import fields, invalid, string

MODES = (
    "OBJECT",
    "EDIT",
    "SCULPT",
    "POSE",
    "VERTEX_PAINT",
    "WEIGHT_PAINT",
    "TEXTURE_PAINT",
)

ALLOWED_BY_TYPE = {
    "MESH": {"OBJECT", "EDIT", "SCULPT", "VERTEX_PAINT", "WEIGHT_PAINT", "TEXTURE_PAINT"},
    "CURVE": {"OBJECT", "EDIT"},
    "FONT": {"OBJECT", "EDIT"},
    "SURFACE": {"OBJECT", "EDIT"},
    "META": {"OBJECT", "EDIT"},
    "LATTICE": {"OBJECT", "EDIT"},
    "ARMATURE": {"OBJECT", "EDIT", "POSE"},
}

CONTEXT_MODE = {
    ("MESH", "EDIT"): "EDIT_MESH",
    ("CURVE", "EDIT"): "EDIT_CURVE",
    ("FONT", "EDIT"): "EDIT_TEXT",
    ("SURFACE", "EDIT"): "EDIT_SURFACE",
    ("META", "EDIT"): "EDIT_METABALL",
    ("LATTICE", "EDIT"): "EDIT_LATTICE",
    ("ARMATURE", "EDIT"): "EDIT_ARMATURE",
    ("ARMATURE", "POSE"): "POSE",
    ("MESH", "SCULPT"): "SCULPT",
    ("MESH", "VERTEX_PAINT"): "PAINT_VERTEX",
    ("MESH", "WEIGHT_PAINT"): "PAINT_WEIGHT",
    ("MESH", "TEXTURE_PAINT"): "PAINT_TEXTURE",
}


def operator_mode_from_context(object_type, context_mode):
    if context_mode == "OBJECT":
        return "OBJECT"
    for (kind, operator_mode), expected in CONTEXT_MODE.items():
        if kind == object_type and expected == context_mode:
            return operator_mode
    return None


@dataclass(frozen=True)
class ModeChange:
    target: ObjectTarget
    mode: str
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "mode", "expected_scene_revision"})
        mode = data["mode"]
        if not isinstance(mode, str) or mode not in MODES:
            raise invalid("Unsupported Blender mode")
        return cls(
            ObjectTarget.parse(data["target"]),
            mode,
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


class ModeOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def set_mode(self, request: Request, action: ModeChange):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        obj, target_before = self.inspector.target(action.target)
        if obj.library is not None or obj.override_library is not None or not obj.is_editable:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Editable local active object required")
        allowed = ALLOWED_BY_TYPE.get(obj.type, {"OBJECT"})
        if action.mode not in allowed:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Requested mode is unsupported for object type",
            )

        layer = self.bpy.context.view_layer
        if getattr(layer.objects, "active", None) != obj or not obj.select_get():
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Mode transition requires target selected and active"
            )

        before = mode_snapshot(self.inspector)
        current_operator = operator_mode_from_context(obj.type, before["mode"])
        if current_operator is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Current mode is outside Level 1 mode scope")
        if action.mode != "OBJECT" and current_operator != "OBJECT":
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Enter non-Object modes only from Object mode"
            )

        expected_mode = (
            "OBJECT" if action.mode == "OBJECT" else CONTEXT_MODE[(obj.type, action.mode)]
        )
        if before["mode"] == expected_mode:
            return self.objects._result(
                request,
                before,
                before,
                {
                    "mode": expected_mode,
                    "active_object_id": target_before["object_id"],
                    "active_object_type": obj.type,
                },
            )

        outcome = self.bpy.ops.object.mode_set(mode=action.mode)
        if outcome != {"FINISHED"}:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender mode transition did not finish")
        self.bpy.context.view_layer.update()
        after = mode_snapshot(self.inspector)
        result = self.objects._result(
            request,
            before,
            after,
            {
                "mode": expected_mode,
                "active_object_id": target_before["object_id"],
                "active_object_type": obj.type,
            },
        )
        if result.status.value == "failed":
            rollback = current_operator
            try:
                self.bpy.ops.object.mode_set(mode=rollback)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = mode_snapshot(self.inspector)["mode"] == before["mode"]
            except Exception:
                result.data["rolled_back"] = False
        return result

    def tools(self):
        return [Tool("mode.set", SafetyClass.MUTATION, ModeChange.parse, self.set_mode)]
