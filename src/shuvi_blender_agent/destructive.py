"""Explicit destructive Level 1 operations with fresh-state guards."""

from dataclasses import dataclass

from .contracts import Request
from .errors import AgentError, ErrorCode
from .files import OutputWorkspace, filename, read_output
from .models import ObjectTarget
from .operations import ObjectOperations
from .rendering import FileAction
from .safety import SafetyClass, SafetyPolicy, require_revision
from .tools import Tool
from .validation import fields, string


@dataclass(frozen=True)
class DeleteObject:
    target: ObjectTarget
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_scene_revision"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


class DestructiveOperations:
    def __init__(
        self,
        objects: ObjectOperations,
        policy: SafetyPolicy,
        workspace: OutputWorkspace | None = None,
    ):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.policy = policy
        self.workspace = workspace

    def delete_object(self, request: Request, action: DeleteObject):
        self.policy.check(SafetyClass.DESTRUCTIVE)
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        obj, before = self.inspector.target(action.target)
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object deletion requires Object mode")
        if obj.library is not None or obj.override_library is not None or not obj.is_editable:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Only editable local objects may be deleted")
        if any(item.parent == obj for item in self.inspector.scene_objects()):
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Delete children or unparent them before deleting parent"
            )

        name = obj.name
        uid = before["object_id"]
        layer = self.bpy.context.view_layer
        if getattr(layer.objects, "active", None) == obj:
            layer.objects.active = None
        if self.bpy.context.scene.camera == obj:
            self.bpy.context.scene.camera = None

        self.bpy.data.objects.remove(obj, do_unlink=True)
        self.bpy.context.view_layer.update()
        after = {
            "object_id": uid,
            "name": name,
            "present": self.bpy.data.objects.get(name) is not None,
            "scene_member": self.bpy.context.scene.objects.get(name) is not None,
        }
        return self.objects._result(
            request,
            before,
            after,
            {"object_id": uid, "name": name, "present": False, "scene_member": False},
        )

    def open_checkpoint(self, request: Request, action: FileAction):
        self.policy.check(SafetyClass.DESTRUCTIVE)
        if self.workspace is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "No confined checkpoint workspace configured")
        before = self.inspector.summary()
        require_revision(action.expected_scene_revision, before["revision"])

        name = filename(action.name, ".blend")
        self.workspace.check_root()
        path = (self.workspace.root / name).resolve()
        if path.parent != self.workspace.root:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Checkpoint escapes configured workspace")
        self.workspace.verify(path)
        checkpoint = read_output(path, "BLEND")

        old_session_id = self.inspector.session_id
        outcome = self.bpy.ops.wm.open_mainfile(
            filepath=str(path),
            load_ui=False,
            use_scripts=False,
        )
        if outcome != {"FINISHED"}:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender checkpoint open did not finish")

        new_session_id = self.inspector.reset_session()
        self.bpy.context.view_layer.update()
        after = self.inspector.summary()
        after["checkpoint_sha256"] = checkpoint["sha256"]
        after["previous_session_id"] = old_session_id
        if new_session_id == old_session_id:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Project replacement kept stale session")
        return self.objects._result(
            request,
            before,
            after,
            {
                "file": str(path),
                "session_id": new_session_id,
                "checkpoint_sha256": checkpoint["sha256"],
                "previous_session_id": old_session_id,
            },
        )

    def tools(self):
        return [
            Tool(
                "object.delete",
                SafetyClass.DESTRUCTIVE,
                DeleteObject.parse,
                self.delete_object,
            ),
            Tool(
                "file.open_checkpoint",
                SafetyClass.DESTRUCTIVE,
                FileAction.parse_blend,
                self.open_checkpoint,
            ),
        ]
