"""Level 2 milestone 9: typed modifier recipes, composition and stack diagnostics."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .modeling_hardsurface import (
    MAX_MODIFIERS,
    STACK_KINDS,
    HardSurfaceOperations,
    _full_settings,
)
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string

MAX_COMPOSE_ENTRIES = 8
SUPPORTED_STACK_TYPES = {
    "BEVEL",
    "SUBSURF",
    "SOLIDIFY",
    "BOOLEAN",
    "SHRINKWRAP",
}
RECIPES = ("PANEL_SHELL", "SUBDIV_BEVEL", "HARD_SURFACE_TRIPLE")


def _prefix(value):
    prefix = string(value, "prefix", limit=40)
    if not prefix:
        raise invalid("prefix cannot be empty")
    if len(prefix.encode("utf-8")) > 40:
        raise invalid("prefix exceeds 40 UTF-8 bytes")
    return prefix


def _recipe_parameters(recipe, parameters):
    if not isinstance(parameters, dict):
        raise invalid("parameters must be an object")
    if recipe == "PANEL_SHELL":
        fields(parameters, {"thickness", "width", "segments"})
        return {
            "thickness": number(parameters["thickness"], "thickness", -100, 100),
            "width": number(parameters["width"], "width", 0, 100),
            "segments": integer(parameters["segments"], "segments", 1, 16),
        }
    if recipe == "SUBDIV_BEVEL":
        fields(parameters, {"width", "segments", "levels", "render_levels"})
        return {
            "width": number(parameters["width"], "width", 0, 100),
            "segments": integer(parameters["segments"], "segments", 1, 16),
            "levels": integer(parameters["levels"], "levels", 0, 3),
            "render_levels": integer(parameters["render_levels"], "render_levels", 0, 3),
        }
    if recipe == "HARD_SURFACE_TRIPLE":
        fields(
            parameters,
            {"thickness", "width", "segments", "levels", "render_levels"},
        )
        return {
            "thickness": number(parameters["thickness"], "thickness", -100, 100),
            "width": number(parameters["width"], "width", 0, 100),
            "segments": integer(parameters["segments"], "segments", 1, 16),
            "levels": integer(parameters["levels"], "levels", 0, 3),
            "render_levels": integer(
                parameters["render_levels"], "render_levels", 0, 3
            ),
        }
    raise invalid("Unsupported modifier recipe")


def _recipe_entries(recipe, prefix, parameters):
    if recipe == "PANEL_SHELL":
        specs = [
            (
                f"{prefix}_Solidify",
                "SOLIDIFY",
                {"thickness": parameters["thickness"]},
            ),
            (
                f"{prefix}_Bevel",
                "BEVEL",
                {"width": parameters["width"], "segments": parameters["segments"]},
            ),
        ]
    elif recipe == "SUBDIV_BEVEL":
        specs = [
            (
                f"{prefix}_Bevel",
                "BEVEL",
                {"width": parameters["width"], "segments": parameters["segments"]},
            ),
            (
                f"{prefix}_Subsurf",
                "SUBSURF",
                {
                    "levels": parameters["levels"],
                    "render_levels": parameters["render_levels"],
                },
            ),
        ]
    elif recipe == "HARD_SURFACE_TRIPLE":
        specs = [
            (
                f"{prefix}_Solidify",
                "SOLIDIFY",
                {"thickness": parameters["thickness"]},
            ),
            (
                f"{prefix}_Bevel",
                "BEVEL",
                {"width": parameters["width"], "segments": parameters["segments"]},
            ),
            (
                f"{prefix}_Subsurf",
                "SUBSURF",
                {
                    "levels": parameters["levels"],
                    "render_levels": parameters["render_levels"],
                },
            ),
        ]
    else:
        raise invalid("Unsupported modifier recipe")

    return [
        {
            "name": object_name(name),
            "kind": kind,
            "settings": _full_settings(kind, settings),
        }
        for name, kind, settings in specs
    ]


def _parse_compose_entries(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_COMPOSE_ENTRIES:
        raise invalid(f"entries requires 1..{MAX_COMPOSE_ENTRIES} modifier specs")
    parsed = []
    names = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise invalid("Modifier spec must be an object")
        fields(raw, {"name", "kind", "settings"})
        kind = raw["kind"]
        if not isinstance(kind, str) or kind not in STACK_KINDS:
            raise invalid("Composed kind must be BEVEL, SUBSURF or SOLIDIFY")
        name = object_name(raw["name"])
        if name in names:
            raise invalid("Composed modifier names must be unique")
        names.add(name)
        parsed.append(
            {
                "name": name,
                "kind": kind,
                "settings": _full_settings(kind, raw["settings"]),
            }
        )
    return tuple(parsed)


@dataclass(frozen=True)
class StackCompose:
    target: ObjectTarget
    expected_stack_revision: str
    entries: tuple[dict, ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_stack_revision", "entries"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            _parse_compose_entries(data["entries"]),
        )


@dataclass(frozen=True)
class RecipePreview:
    recipe: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"recipe", "prefix", "parameters"})
        recipe = data["recipe"]
        if not isinstance(recipe, str) or recipe not in RECIPES:
            raise invalid("Unsupported modifier recipe")
        return cls(recipe, _prefix(data["prefix"]), _recipe_parameters(recipe, data["parameters"]))


@dataclass(frozen=True)
class RecipeApply:
    target: ObjectTarget
    expected_stack_revision: str
    recipe: str
    prefix: str
    parameters: dict

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_stack_revision",
                "recipe",
                "prefix",
                "parameters",
            },
        )
        preview = RecipePreview.parse(
            {
                "recipe": data["recipe"],
                "prefix": data["prefix"],
                "parameters": data["parameters"],
            }
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            preview.recipe,
            preview.prefix,
            preview.parameters,
        )


class ModelingModifierWorkflowOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.modifiers = HardSurfaceOperations(objects)

    def diagnose(self, request: Request, object_id: str):
        obj = self.inspector.resolve(object_id)
        if obj.type != "MESH":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        stack = self.modifiers.stack_snapshot(obj)
        items = stack["items"]
        type_counts = {}
        unsupported = []
        disabled_viewport = []
        disabled_render = []
        missing_references = []
        subsurf_before_bevel = []

        for index, item in enumerate(items):
            kind = item["type"]
            type_counts[kind] = type_counts.get(kind, 0) + 1
            if kind not in SUPPORTED_STACK_TYPES:
                unsupported.append(index)
            if not item["show_viewport"]:
                disabled_viewport.append(index)
            if not item["show_render"]:
                disabled_render.append(index)
            if kind == "BOOLEAN" and item["settings"].get("cutter_object_id") is None:
                missing_references.append(index)
            if kind == "SHRINKWRAP" and item["settings"].get("target_object_id") is None:
                missing_references.append(index)

        bevel_indices = [index for index, item in enumerate(items) if item["type"] == "BEVEL"]
        subsurf_indices = [index for index, item in enumerate(items) if item["type"] == "SUBSURF"]
        for subsurf_index in subsurf_indices:
            for bevel_index in bevel_indices:
                if subsurf_index < bevel_index:
                    subsurf_before_bevel.append([subsurf_index, bevel_index])

        reference_modifier_count = sum(item["type"] in ("BOOLEAN", "SHRINKWRAP") for item in items)
        warnings = []
        if unsupported:
            warnings.append("UNSUPPORTED_MODIFIER_TYPES")
        if missing_references:
            warnings.append("MISSING_OBJECT_REFERENCES")
        if subsurf_before_bevel:
            warnings.append("SUBSURF_BEFORE_BEVEL")
        if disabled_viewport:
            warnings.append("VIEWPORT_DISABLED_ENTRIES")
        if disabled_render:
            warnings.append("RENDER_DISABLED_ENTRIES")

        data = {
            "object_id": stack["object_id"],
            "name": stack["name"],
            "stack_revision": stack["stack_revision"],
            "count": stack["count"],
            "type_counts": dict(sorted(type_counts.items())),
            "unsupported_modifier_indices": unsupported,
            "disabled_viewport_indices": disabled_viewport,
            "disabled_render_indices": disabled_render,
            "missing_reference_indices": sorted(set(missing_references)),
            "subsurf_before_bevel_pairs": subsurf_before_bevel,
            "reference_modifier_count": reference_modifier_count,
            "complexity_score": stack["count"] + 2 * reference_modifier_count,
            "warnings": warnings,
        }
        data["diagnostic_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    @staticmethod
    def _expected_entry(spec):
        return {
            "name": spec["name"],
            "type": spec["kind"],
            "show_viewport": True,
            "show_render": True,
            "settings": spec["settings"],
        }

    def _apply_entries(self, request, target, expected_stack_revision, entries, evidence):
        obj, object_before = self.modifiers._mesh_target(target)
        before = self.modifiers.stack_snapshot(obj)
        require_revision(expected_stack_revision, before["stack_revision"])
        if len(obj.modifiers) + len(entries) > MAX_MODIFIERS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Composed stack exceeds modifier limit")

        names = [entry["name"] for entry in entries]
        if len(set(names)) != len(names):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Composed modifier names must be unique")
        collisions = [name for name in names if obj.modifiers.get(name) is not None]
        if collisions:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Modifier name already exists")

        created = []
        try:
            for spec in entries:
                modifier = obj.modifiers.new(spec["name"], spec["kind"])
                created.append(modifier)
                for key, value in spec["settings"].items():
                    setattr(modifier, key, value)
            self.bpy.context.view_layer.update()
            after = self.modifiers.stack_snapshot(obj)
            after.update(evidence)
            expected_items = before["items"] + [self._expected_entry(spec) for spec in entries]
            expected = {
                "count": before["count"] + len(entries),
                "items": expected_items,
            } | evidence
            result = self.objects._result(
                request,
                {"object": object_before, "stack": before},
                after,
                expected,
            )
            if result.status == Status.FAILED:
                for modifier in reversed(created):
                    self.modifiers._remove_if_present(obj, modifier)
                self.bpy.context.view_layer.update()
                result.data["rolled_back"] = True
            return result
        except Exception:
            for modifier in reversed(created):
                self.modifiers._remove_if_present(obj, modifier)
            self.bpy.context.view_layer.update()
            raise

    def compose(self, request: Request, action: StackCompose):
        entries = [dict(entry) for entry in action.entries]
        return self._apply_entries(
            request,
            action.target,
            action.expected_stack_revision,
            entries,
            {
                "composed_modifier_names": [entry["name"] for entry in entries],
                "composed_modifier_count": len(entries),
            },
        )

    def recipe_preview(self, request: Request, action: RecipePreview):
        entries = _recipe_entries(action.recipe, action.prefix, action.parameters)
        data = {
            "recipe": action.recipe,
            "prefix": action.prefix,
            "parameters": action.parameters,
            "entries": entries,
            "entry_count": len(entries),
        }
        data["recipe_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def recipe_apply(self, request: Request, action: RecipeApply):
        entries = _recipe_entries(action.recipe, action.prefix, action.parameters)
        return self._apply_entries(
            request,
            action.target,
            action.expected_stack_revision,
            entries,
            {
                "recipe": action.recipe,
                "recipe_prefix": action.prefix,
                "recipe_parameters": action.parameters,
                "recipe_modifier_names": [entry["name"] for entry in entries],
            },
        )

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool(
                "modifier.stack_diagnose",
                SafetyClass.READ_ONLY,
                parse_id,
                self.diagnose,
            ),
            Tool(
                "modifier.stack_compose",
                SafetyClass.MUTATION,
                StackCompose.parse,
                self.compose,
            ),
            Tool(
                "modifier.recipe_preview",
                SafetyClass.READ_ONLY,
                RecipePreview.parse,
                self.recipe_preview,
            ),
            Tool(
                "modifier.recipe_apply",
                SafetyClass.MUTATION,
                RecipeApply.parse,
                self.recipe_apply,
            ),
        ]
