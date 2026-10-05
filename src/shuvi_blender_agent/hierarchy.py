"""Typed parent/child hierarchy controls with cycle rejection and readback verification."""

from copy import deepcopy
from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget
from .object_state import boolean
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string

MAX_HIERARCHY_DEPTH = 256
MAX_CHILDREN_RESULT = 256


@dataclass(frozen=True)
class ParentChange:
    child: ObjectTarget
    parent: ObjectTarget | None
    keep_world: bool

    @classmethod
    def parse(cls, data):
        fields(data, {"child", "parent", "keep_world"})
        return cls(
            ObjectTarget.parse(data["child"]),
            ObjectTarget.parse(data["parent"]) if data["parent"] is not None else None,
            boolean(data["keep_world"]),
        )


def _parse_object_id(data):
    fields(data, {"object_id"})
    return string(data["object_id"], "object_id", limit=128)


class HierarchyOperations:
    def __init__(self, objects):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def _local_parent(self, obj):
        if obj.library is not None or obj.override_library is not None or not obj.is_editable:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Linked/overridden/read-only parent cannot be used"
            )
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")

    def _reject_cycle(self, child, parent):
        current = parent
        for _ in range(MAX_HIERARCHY_DEPTH):
            if current is None:
                return
            if current == child:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Parenting cycle rejected")
            current = current.parent
        raise AgentError(ErrorCode.SAFETY_DENIED, "Hierarchy depth exceeds safety limit")

    def inspect_origin(self, req, object_id):
        obj = self.inspector.resolve(object_id)
        matrix = obj.matrix_world
        data = {
            "object_id": self.inspector.identity(obj),
            "local_location": [float(value) for value in obj.location],
            "world_location": [
                float(matrix[0][3]),
                float(matrix[1][3]),
                float(matrix[2][3]),
            ],
            "parent_id": self.inspector.identity(obj.parent) if obj.parent else None,
        }
        return Result(req.request_id, req.command_id, Status.SUCCEEDED, data)

    def inspect(self, req, object_id):
        obj = self.inspector.resolve(object_id)
        children = [item for item in self.inspector.scene_objects() if item.parent == obj]
        child_ids = [self.inspector.identity(item) for item in children[:MAX_CHILDREN_RESULT]]
        data = {
            "object_id": self.inspector.identity(obj),
            "parent_id": self.inspector.identity(obj.parent) if obj.parent else None,
            "child_ids": child_ids,
            "child_count": len(children),
            "children_truncated": len(children) > MAX_CHILDREN_RESULT,
        }
        return Result(req.request_id, req.command_id, Status.SUCCEEDED, data)

    def set_parent(self, req, action):
        child, before = self.inspector.target(action.child)
        self.objects._editable(child)

        parent = None
        parent_id = None
        if action.parent is not None:
            parent, parent_before = self.inspector.target(action.parent)
            self._local_parent(parent)
            if parent == child:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Object cannot parent itself")
            self._reject_cycle(child, parent)
            parent_id = parent_before["object_id"]

        world_before = deepcopy([list(row) for row in child.matrix_world])
        child.parent = parent
        if action.keep_world:
            child.matrix_world = deepcopy(world_before)
        self.bpy.context.view_layer.update()

        expected = {
            "object_id": before["object_id"],
            "parent_id": parent_id,
        }
        if action.keep_world:
            expected["matrix_world"] = world_before
        return self.objects._result(
            req,
            before,
            self.objects._readback(child),
            expected,
        )

    def tools(self):
        return [
            Tool("hierarchy.inspect", SafetyClass.READ_ONLY, _parse_object_id, self.inspect),
            Tool("origin.inspect", SafetyClass.READ_ONLY, _parse_object_id, self.inspect_origin),
            Tool(
                "hierarchy.set_parent",
                SafetyClass.MUTATION,
                ParentChange.parse,
                self.set_parent,
            ),
        ]
