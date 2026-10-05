"""Selection and active state without editor-dependent operators."""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget
from .object_state import boolean
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, string


def selection_state(inspector):
    objects = inspector.scene_objects()
    layer = inspector.bpy.context.view_layer
    active = getattr(getattr(layer, "objects", None), "active", None)
    selected = [inspector.identity(obj) for obj in objects if obj.select_get()]
    return {
        "active_object_id": inspector.identity(active) if active is not None else None,
        "selected_object_ids": sorted(selected[:256]),
        "selected_count": len(selected),
        "selection_truncated": len(selected) > 256,
        "mode": inspector.bpy.context.mode,
        "view_layer": getattr(layer, "name", "ViewLayer"),
    }


@dataclass(frozen=True)
class SelectionChange:
    target: ObjectTarget | None
    selected: bool | None
    active: bool | None
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "selected", "active", "expected_scene_revision"})
        target = ObjectTarget.parse(data["target"]) if data["target"] is not None else None
        selected = boolean(data["selected"]) if data["selected"] is not None else None
        active = boolean(data["active"]) if data["active"] is not None else None
        if target is None and (selected is not False or active is not False):
            from .validation import invalid

            raise invalid("Null target is reserved for deselect-all and clear active")
        return cls(
            target,
            selected,
            active,
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


class SelectionOperations:
    def __init__(self, objects):
        self.objects = objects
        self.inspector = objects.inspector

    def change(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        before = selection_state(self.inspector)
        if before["selection_truncated"] or before["mode"] != "OBJECT":
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Selection requires bounded Object mode context"
            )
        layer = self.objects.bpy.context.view_layer
        selected = set(before["selected_object_ids"])
        expected = dict(before)
        if action.target is None:
            targets = [obj for obj in self.inspector.scene_objects() if obj.select_get()]
            for obj in targets:
                self.objects._editable(obj)
            for obj in targets:
                obj.select_set(False)
            layer.objects.active = None
            selected.clear()
            expected["active_object_id"] = None
        else:
            obj, snapshot = self.inspector.target(action.target)
            self.objects._editable(obj)
            if layer.objects.get(obj.name) != obj:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED, "Target is excluded from current view layer"
                )
            uid = snapshot["object_id"]
            if action.selected is True and uid not in selected and len(selected) >= 256:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Selection limit reached")
            if action.selected is not None:
                obj.select_set(action.selected)
                selected.add(uid) if action.selected else selected.discard(uid)
            if action.active is not None:
                if action.active:
                    layer.objects.active = obj
                    expected["active_object_id"] = uid
                elif layer.objects.active == obj:
                    layer.objects.active = None
                    expected["active_object_id"] = None
        expected.update(selected_object_ids=sorted(selected), selected_count=len(selected))
        layer.update()
        return self.objects._result(req, before, selection_state(self.inspector), expected)

    def inspect(self, req, _):
        return Result(
            req.request_id, req.command_id, Status.SUCCEEDED, selection_state(self.inspector)
        )

    def tools(self):
        return [
            Tool("selection.set", SafetyClass.MUTATION, SelectionChange.parse, self.change),
            Tool(
                "selection.inspect", SafetyClass.READ_ONLY, lambda p: fields(p, set()), self.inspect
            ),
        ]
