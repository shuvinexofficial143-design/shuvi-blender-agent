"""Level 2 milestone 6: bounded hard-surface modifier stack and Boolean workflow."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_MODIFIERS = 16
STACK_KINDS = ("BEVEL", "SUBSURF", "SOLIDIFY")
BOOLEAN_OPERATIONS = ("DIFFERENCE", "UNION", "INTERSECT")
BOOLEAN_SOLVERS = ("EXACT", "FAST")


def _bool(value, name):
    if type(value) is not bool:
        raise invalid(f"{name} must be boolean")
    return value


def _full_settings(kind, settings):
    if kind == "BEVEL":
        fields(settings, {"width", "segments"})
        return {
            "width": number(settings["width"], "width", 0, 100),
            "segments": integer(settings["segments"], "segments", 1, 16),
        }
    if kind == "SUBSURF":
        fields(settings, {"levels", "render_levels"})
        return {
            "levels": integer(settings["levels"], "levels", 0, 3),
            "render_levels": integer(settings["render_levels"], "render_levels", 0, 3),
        }
    if kind == "SOLIDIFY":
        fields(settings, {"thickness"})
        return {"thickness": number(settings["thickness"], "thickness", -100, 100)}
    raise invalid("Unsupported hard-surface modifier type")


def _patch_settings(kind, settings):
    if not isinstance(settings, dict) or not settings:
        raise invalid("Modifier settings patch cannot be empty")
    common = {"show_viewport", "show_render"}
    allowed = {
        "BEVEL": {"width", "segments"} | common,
        "SUBSURF": {"levels", "render_levels"} | common,
        "SOLIDIFY": {"thickness"} | common,
        "BOOLEAN": {"operation", "solver"} | common,
    }.get(kind)
    if allowed is None:
        raise invalid("Unsupported modifier type")
    fields(settings, set(), allowed)
    parsed = {}
    for key, value in settings.items():
        if key in common:
            parsed[key] = _bool(value, key)
        elif key == "width":
            parsed[key] = number(value, key, 0, 100)
        elif key == "segments":
            parsed[key] = integer(value, key, 1, 16)
        elif key in ("levels", "render_levels"):
            parsed[key] = integer(value, key, 0, 3)
        elif key == "thickness":
            parsed[key] = number(value, key, -100, 100)
        elif key == "operation":
            if not isinstance(value, str) or value not in BOOLEAN_OPERATIONS:
                raise invalid("operation must be DIFFERENCE, UNION or INTERSECT")
            parsed[key] = value
        elif key == "solver":
            if not isinstance(value, str) or value not in BOOLEAN_SOLVERS:
                raise invalid("solver must be EXACT or FAST")
            parsed[key] = value
    return parsed


@dataclass(frozen=True)
class StackAdd:
    target: ObjectTarget
    expected_stack_revision: str
    name: str
    kind: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_stack_revision", "name", "kind", "settings"})
        kind = data["kind"]
        if not isinstance(kind, str) or kind not in STACK_KINDS:
            raise invalid("kind must be BEVEL, SUBSURF or SOLIDIFY")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            kind,
            _full_settings(kind, data["settings"]),
        )


@dataclass(frozen=True)
class BooleanAdd:
    target: ObjectTarget
    cutter: ObjectTarget
    expected_stack_revision: str
    name: str
    operation: str
    solver: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "cutter",
                "expected_stack_revision",
                "name",
                "operation",
                "solver",
            },
        )
        operation = data["operation"]
        solver = data["solver"]
        if not isinstance(operation, str) or operation not in BOOLEAN_OPERATIONS:
            raise invalid("operation must be DIFFERENCE, UNION or INTERSECT")
        if not isinstance(solver, str) or solver not in BOOLEAN_SOLVERS:
            raise invalid("solver must be EXACT or FAST")
        return cls(
            ObjectTarget.parse(data["target"]),
            ObjectTarget.parse(data["cutter"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            operation,
            solver,
        )


@dataclass(frozen=True)
class ModifierUpdate:
    target: ObjectTarget
    expected_stack_revision: str
    name: str
    kind: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_stack_revision", "name", "kind", "settings"})
        kind = data["kind"]
        if not isinstance(kind, str):
            raise invalid("kind must be a string")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            kind,
            _patch_settings(kind, data["settings"]),
        )


@dataclass(frozen=True)
class ModifierMove:
    target: ObjectTarget
    expected_stack_revision: str
    name: str
    index: int

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_stack_revision", "name", "index"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            integer(data["index"], "index", 0, MAX_MODIFIERS - 1),
        )


class HardSurfaceOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def _mesh_target(self, target):
        obj, before = self.inspector.target(target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if obj.data.library is not None or obj.data.shape_keys is not None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Local mesh without shape keys required for hard-surface modifiers",
            )
        if (
            len(obj.data.vertices) > 4096
            or len(obj.data.polygons) > 4096
            or sum(len(face.vertices) for face in obj.data.polygons) > 32768
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier input exceeds mesh work limit")
        if len(obj.modifiers) > MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack work limit exceeded")
        return obj, before

    def _entry(self, modifier):
        data = {
            "name": modifier.name,
            "type": modifier.type,
            "show_viewport": bool(modifier.show_viewport),
            "show_render": bool(modifier.show_render),
            "settings": {},
        }
        if modifier.type == "BEVEL":
            data["settings"] = {
                "width": float(getattr(modifier, "width", 0.0)),
                "segments": int(getattr(modifier, "segments", 1)),
            }
        elif modifier.type == "SUBSURF":
            data["settings"] = {
                "levels": int(getattr(modifier, "levels", 0)),
                "render_levels": int(getattr(modifier, "render_levels", 0)),
            }
        elif modifier.type == "SOLIDIFY":
            data["settings"] = {"thickness": float(getattr(modifier, "thickness", 0.0))}
        elif modifier.type == "BOOLEAN":
            cutter = getattr(modifier, "object", None)
            data["settings"] = {
                "operation": getattr(modifier, "operation", None),
                "solver": getattr(modifier, "solver", None),
                "cutter_object_id": self.inspector.identity(cutter) if cutter else None,
                "cutter_name": cutter.name if cutter else None,
            }
        return data

    def stack_snapshot(self, obj):
        if len(obj.modifiers) > MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack work limit exceeded")
        items = [self._entry(modifier) for modifier in obj.modifiers]
        state = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "count": len(items),
            "items": items,
        }
        state["stack_revision"] = revision({"items": items})
        return state

    def inspect_stack(self, request: Request, object_id: str):
        obj = self.inspector.resolve(object_id)
        if obj.type != "MESH":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self.stack_snapshot(obj),
        )

    @staticmethod
    def _remove_if_present(obj, modifier):
        if obj.modifiers.get(modifier.name) == modifier:
            obj.modifiers.remove(modifier)

    def add_stack_modifier(self, request: Request, action: StackAdd):
        obj, object_before = self._mesh_target(action.target)
        before = self.stack_snapshot(obj)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        if len(obj.modifiers) >= MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack is full")
        if obj.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already exists")

        modifier = obj.modifiers.new(action.name, action.kind)
        try:
            for key, value in action.settings.items():
                setattr(modifier, key, value)
            self.bpy.context.view_layer.update()
            after = self.stack_snapshot(obj)
            expected_entry = {
                "name": action.name,
                "type": action.kind,
                "show_viewport": True,
                "show_render": True,
                "settings": action.settings,
            }
            result = self.objects._result(
                request,
                {"object": object_before, "stack": before},
                after,
                {
                    "count": before["count"] + 1,
                    "items": before["items"] + [expected_entry],
                },
            )
            if result.status == Status.FAILED:
                self._remove_if_present(obj, modifier)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._remove_if_present(obj, modifier)
            self.bpy.context.view_layer.update()
            raise

    def add_boolean(self, request: Request, action: BooleanAdd):
        obj, object_before = self._mesh_target(action.target)
        cutter, cutter_before = self._mesh_target(action.cutter)
        if cutter == obj:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Boolean cutter must be a different object")
        before = self.stack_snapshot(obj)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        if len(obj.modifiers) >= MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Modifier stack is full")
        if obj.modifiers.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already exists")

        modifier = obj.modifiers.new(action.name, "BOOLEAN")
        try:
            modifier.operation = action.operation
            modifier.solver = action.solver
            modifier.object = cutter
            self.bpy.context.view_layer.update()
            after = self.stack_snapshot(obj)
            expected_entry = {
                "name": action.name,
                "type": "BOOLEAN",
                "show_viewport": True,
                "show_render": True,
                "settings": {
                    "operation": action.operation,
                    "solver": action.solver,
                    "cutter_object_id": cutter_before["object_id"],
                    "cutter_name": cutter_before["name"],
                },
            }
            result = self.objects._result(
                request,
                {
                    "object": object_before,
                    "cutter": cutter_before,
                    "stack": before,
                },
                after,
                {
                    "count": before["count"] + 1,
                    "items": before["items"] + [expected_entry],
                },
            )
            if result.status == Status.FAILED:
                self._remove_if_present(obj, modifier)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            self._remove_if_present(obj, modifier)
            self.bpy.context.view_layer.update()
            raise

    def update_modifier(self, request: Request, action: ModifierUpdate):
        obj, object_before = self._mesh_target(action.target)
        before = self.stack_snapshot(obj)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        modifier = obj.modifiers.get(action.name)
        if modifier is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Modifier not found")
        if modifier.type != action.kind:
            raise AgentError(ErrorCode.STALE_STATE, "Modifier type changed")
        previous = {key: getattr(modifier, key) for key in action.settings}

        try:
            for key, value in action.settings.items():
                setattr(modifier, key, value)
            self.bpy.context.view_layer.update()
            after = self.stack_snapshot(obj)
            expected_items = [dict(item) for item in before["items"]]
            index = next(i for i, item in enumerate(expected_items) if item["name"] == action.name)
            expected_items[index] = {
                **expected_items[index],
                "show_viewport": (
                    action.settings["show_viewport"]
                    if "show_viewport" in action.settings
                    else expected_items[index]["show_viewport"]
                ),
                "show_render": (
                    action.settings["show_render"]
                    if "show_render" in action.settings
                    else expected_items[index]["show_render"]
                ),
                "settings": {
                    **expected_items[index]["settings"],
                    **{
                        key: value
                        for key, value in action.settings.items()
                        if key not in ("show_viewport", "show_render")
                    },
                },
            }
            result = self.objects._result(
                request,
                {"object": object_before, "stack": before},
                after,
                {"count": before["count"], "items": expected_items},
            )
            if result.status == Status.FAILED:
                for key, value in previous.items():
                    setattr(modifier, key, value)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            for key, value in previous.items():
                setattr(modifier, key, value)
            self.bpy.context.view_layer.update()
            raise

    def move_modifier(self, request: Request, action: ModifierMove):
        obj, object_before = self._mesh_target(action.target)
        before = self.stack_snapshot(obj)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        modifier = obj.modifiers.get(action.name)
        if modifier is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Modifier not found")
        if action.index >= len(obj.modifiers):
            raise invalid("Modifier destination index does not exist")
        old_index = next(index for index, item in enumerate(obj.modifiers) if item == modifier)

        try:
            obj.modifiers.move(old_index, action.index)
            self.bpy.context.view_layer.update()
            after = self.stack_snapshot(obj)
            expected_items = list(before["items"])
            moved = expected_items.pop(old_index)
            expected_items.insert(action.index, moved)
            result = self.objects._result(
                request,
                {"object": object_before, "stack": before},
                after,
                {"count": before["count"], "items": expected_items},
            )
            if result.status == Status.FAILED:
                current = next(
                    index for index, item in enumerate(obj.modifiers) if item == modifier
                )
                obj.modifiers.move(current, old_index)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            current = next(
                (index for index, item in enumerate(obj.modifiers) if item == modifier),
                None,
            )
            if current is not None and current != old_index:
                obj.modifiers.move(current, old_index)
                self.bpy.context.view_layer.update()
            raise

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool(
                "modifier.stack_inspect",
                SafetyClass.READ_ONLY,
                parse_id,
                self.inspect_stack,
            ),
            Tool(
                "modifier.stack_add",
                SafetyClass.MUTATION,
                StackAdd.parse,
                self.add_stack_modifier,
            ),
            Tool(
                "modifier.boolean_add",
                SafetyClass.MUTATION,
                BooleanAdd.parse,
                self.add_boolean,
            ),
            Tool(
                "modifier.update",
                SafetyClass.MUTATION,
                ModifierUpdate.parse,
                self.update_modifier,
            ),
            Tool(
                "modifier.move",
                SafetyClass.MUTATION,
                ModifierMove.parse,
                self.move_modifier,
            ),
        ]
