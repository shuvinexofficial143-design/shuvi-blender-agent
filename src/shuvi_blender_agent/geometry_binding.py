"""Level 5 milestone 4: bounded Geometry Nodes modifier and node-group binding."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .geometry_nodes import GeometryNodeOperations
from .inspection import revision
from .modeling_hardsurface import MAX_MODIFIERS
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, string
from .verification import compare


@dataclass(frozen=True)
class GeometryModifierInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class GeometryModifierBind:
    target: ObjectTarget
    group_name: str
    expected_group_revision: str
    modifier_name: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "group_name",
                "expected_group_revision",
                "modifier_name",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["group_name"]),
            string(data["expected_group_revision"], "expected_group_revision", limit=64),
            object_name(data["modifier_name"]),
        )


@dataclass(frozen=True)
class GeometryModifierRemove:
    target: ObjectTarget
    group_name: str
    expected_group_revision: str
    modifier_name: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "group_name",
                "expected_group_revision",
                "modifier_name",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            object_name(data["group_name"]),
            string(data["expected_group_revision"], "expected_group_revision", limit=64),
            object_name(data["modifier_name"]),
        )


class GeometryBindingOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.geometry = GeometryNodeOperations(objects)

    def _mesh_target(self, target):
        obj, before = self.inspector.target(target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Editable mesh object required")
        if getattr(obj.data, "library", None) is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Local mesh data required")
        if getattr(obj.data, "shape_keys", None) is not None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry Nodes binding does not support shape-key meshes yet",
            )
        if (
            len(obj.data.vertices) > 4096
            or len(obj.data.polygons) > 4096
            or sum(len(face.vertices) for face in obj.data.polygons) > 32768
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Geometry Nodes modifier input exceeds mesh work limit",
            )
        if len(obj.modifiers) > MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack work limit exceeded")
        return obj, before

    def _group(self, name, expected_revision=None):
        group = self.geometry._group(name)
        snapshot = self.geometry._snapshot(group)
        if expected_revision is not None:
            require_revision(expected_revision, snapshot["group_revision"])
        return group, snapshot

    @staticmethod
    def _object_modifier_row(snapshot, name):
        return next((item for item in snapshot["modifiers"] if item["name"] == name), None)

    def _binding_row(self, modifier):
        group = getattr(modifier, "node_group", None)
        row = {
            "modifier_name": str(modifier.name),
            "modifier_type": str(modifier.type),
            "show_viewport": bool(modifier.show_viewport),
            "show_render": bool(modifier.show_render),
            "group_name": str(group.name) if group is not None else None,
            "group_local": False,
            "group_tree_type": None,
            "group_revision": None,
        }
        if group is not None:
            row["group_tree_type"] = str(getattr(group, "bl_idname", ""))
            row["group_local"] = getattr(group, "library", None) is None
            if row["group_local"] and row["group_tree_type"] == "GeometryNodeTree":
                row["group_revision"] = self.geometry._snapshot(group)["group_revision"]
        return row

    def inspect(self, request: Request, action: GeometryModifierInspect):
        obj = self.inspector.resolve(action.object_id)
        if obj.type != "MESH":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if len(obj.modifiers) > MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack work limit exceeded")
        snapshot = self.inspector.snapshot(obj)
        bindings = [
            self._binding_row(modifier)
            for modifier in obj.modifiers
            if str(modifier.type) == "NODES"
        ]
        data = {
            "object_id": snapshot["object_id"],
            "object_name": snapshot["name"],
            "object_revision": snapshot["revision"],
            "modifier_count": snapshot["modifier_count"],
            "geometry_nodes_modifier_count": len(bindings),
            "bindings": bindings,
        }
        data["binding_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _binding_evidence(self, obj, group, modifier_name):
        object_snapshot = self.inspector.snapshot(obj)
        group_snapshot = self.geometry._snapshot(group)
        modifier = obj.modifiers.get(modifier_name)
        bound_group = getattr(modifier, "node_group", None) if modifier is not None else None
        return {
            "object": object_snapshot,
            "group_revision": group_snapshot["group_revision"],
            "binding": {
                "present": modifier is not None,
                "name": str(modifier.name) if modifier is not None else modifier_name,
                "type": str(modifier.type) if modifier is not None else None,
                "group_name": str(bound_group.name) if bound_group is not None else None,
            },
        }

    def _recovery_check(self, obj, group, before, group_revision):
        recovered_object = self.inspector.snapshot(obj)
        recovered_group = self.geometry._snapshot(group)
        recovery = compare(
            {
                "object_revision": before["revision"],
                "group_revision": group_revision,
            },
            {
                "object_revision": recovered_object["revision"],
                "group_revision": recovered_group["group_revision"],
            },
        )
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Geometry Nodes modifier recovery could not be verified",
            )
        return recovered_object, recovered_group, recovery

    def bind(self, request: Request, action: GeometryModifierBind):
        obj, before = self._mesh_target(action.target)
        group, group_before = self._group(
            action.group_name,
            action.expected_group_revision,
        )
        if len(obj.modifiers) >= MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack work limit reached")
        if obj.modifiers.get(action.modifier_name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already exists")

        modifier = None
        try:
            modifier = obj.modifiers.new(action.modifier_name, "NODES")
            modifier.node_group = group
            self.bpy.context.view_layer.update()
            evidence = self._binding_evidence(obj, group, action.modifier_name)
            row = self._object_modifier_row(
                evidence["object"],
                action.modifier_name,
            )
            expected = {
                "modifier_count": before["modifier_count"] + 1,
                "group_revision": group_before["group_revision"],
                "binding": {
                    "present": True,
                    "name": action.modifier_name,
                    "type": "NODES",
                    "group_name": action.group_name,
                },
                "object_modifier": {
                    "name": action.modifier_name,
                    "type": "NODES",
                    "settings": {"node_group_name": action.group_name},
                },
            }
            actual = {
                "modifier_count": evidence["object"]["modifier_count"],
                "group_revision": evidence["group_revision"],
                "binding": evidence["binding"],
                "object_modifier": row,
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": evidence["object"], "binding": evidence["binding"]},
                    verification=verification.to_dict(),
                )

            obj.modifiers.remove(modifier)
            modifier = None
            self.bpy.context.view_layer.update()
            recovered_object, recovered_group, _ = self._recovery_check(
                obj,
                group,
                before,
                group_before["group_revision"],
            )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": evidence["object"],
                    "restored": recovered_object,
                    "restored_group_revision": recovered_group["group_revision"],
                    "rolled_back": True,
                    "recovery_verified": True,
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Geometry Nodes modifier binding readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if modifier is not None and obj.modifiers.get(action.modifier_name) is modifier:
                obj.modifiers.remove(modifier)
                self.bpy.context.view_layer.update()
            raise

    @staticmethod
    def _restore_modifier(obj, state):
        modifier = obj.modifiers.new(state["name"], "NODES")
        modifier.node_group = state["group"]
        modifier.show_viewport = state["show_viewport"]
        modifier.show_render = state["show_render"]
        current_index = len(obj.modifiers) - 1
        if current_index != state["index"]:
            obj.modifiers.move(current_index, state["index"])
        return modifier

    def remove(self, request: Request, action: GeometryModifierRemove):
        obj, before = self._mesh_target(action.target)
        group, group_before = self._group(
            action.group_name,
            action.expected_group_revision,
        )
        modifier = obj.modifiers.get(action.modifier_name)
        if modifier is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Geometry Nodes modifier not found")
        if str(modifier.type) != "NODES":
            raise AgentError(ErrorCode.SAFETY_DENIED, "NODES modifier required")
        if getattr(modifier, "node_group", None) is not group:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Modifier is not bound to the requested Geometry Nodes group",
            )
        state = {
            "name": str(modifier.name),
            "group": group,
            "show_viewport": bool(modifier.show_viewport),
            "show_render": bool(modifier.show_render),
            "index": list(obj.modifiers).index(modifier),
        }

        removed = False
        try:
            obj.modifiers.remove(modifier)
            removed = True
            self.bpy.context.view_layer.update()
            evidence = self._binding_evidence(obj, group, action.modifier_name)
            expected = {
                "modifier_count": before["modifier_count"] - 1,
                "group_revision": group_before["group_revision"],
                "binding": {
                    "present": False,
                    "name": action.modifier_name,
                    "type": None,
                    "group_name": None,
                },
                "object_modifier_absent": True,
            }
            actual = {
                "modifier_count": evidence["object"]["modifier_count"],
                "group_revision": evidence["group_revision"],
                "binding": evidence["binding"],
                "object_modifier_absent": self._object_modifier_row(
                    evidence["object"],
                    action.modifier_name,
                )
                is None,
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "before": before,
                        "after": evidence["object"],
                        "removed_binding": {
                            "name": state["name"],
                            "group_name": action.group_name,
                            "index": state["index"],
                        },
                    },
                    verification=verification.to_dict(),
                )

            self._restore_modifier(obj, state)
            removed = False
            self.bpy.context.view_layer.update()
            recovered_object, recovered_group, _ = self._recovery_check(
                obj,
                group,
                before,
                group_before["group_revision"],
            )
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": evidence["object"],
                    "restored": recovered_object,
                    "restored_group_revision": recovered_group["group_revision"],
                    "rolled_back": True,
                    "recovery_verified": True,
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Geometry Nodes modifier removal readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if removed and obj.modifiers.get(action.modifier_name) is None:
                self._restore_modifier(obj, state)
                self.bpy.context.view_layer.update()
            raise

    def tools(self):
        return [
            Tool(
                "geometry_nodes.modifier_inspect",
                SafetyClass.READ_ONLY,
                GeometryModifierInspect.parse,
                self.inspect,
            ),
            Tool(
                "geometry_nodes.modifier_bind",
                SafetyClass.MUTATION,
                GeometryModifierBind.parse,
                self.bind,
            ),
            Tool(
                "geometry_nodes.modifier_remove",
                SafetyClass.MUTATION,
                GeometryModifierRemove.parse,
                self.remove,
            ),
        ]
