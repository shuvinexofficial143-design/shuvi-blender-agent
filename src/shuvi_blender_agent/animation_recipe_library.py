"""Level 7 M9: versioned, bounded animation timeline recipe library."""

from dataclasses import dataclass

from .animation_timeline import AnimationTimelineOperations, TimelineRetime
from .contracts import Request, Result, Status
from .inspection import revision
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, integer, invalid, string

LIBRARY_VERSION = 1
MIN_BLENDER_VERSION = "4.2"
COMPATIBILITY = "SOURCE_VALIDATED_RUNTIME_UNVERIFIED"

# Recipes compile to one existing atomic M4 retime operation; no dynamic bpy/Python.
RECIPE_SPECS = {
    "timeline.reverse": {
        "description": "Reverse the timing of selected complete transform keys",
        "parameter_schema": {"frames": "2..32 unique keyed frames (int 1..100000)"},
    },
    "timeline.shift": {
        "description": "Shift selected complete transform keys by a signed frame offset",
        "parameter_schema": {
            "frames": "1..32 unique keyed frames (int 1..100000)",
            "offset": "nonzero integer -10000..10000",
        },
    },
    "timeline.stretch": {
        "description": "Stretch selected keys away from their earliest frame",
        "parameter_schema": {
            "frames": "2..32 unique keyed frames (int 1..100000)",
            "factor": "integer 2..4; earliest frame remains unchanged",
        },
    },
}


def _descriptor(recipe_id):
    spec = RECIPE_SPECS[recipe_id]
    return {
        "recipe_id": recipe_id,
        "recipe_version": 1,
        "library_version": LIBRARY_VERSION,
        "minimum_blender_version": MIN_BLENDER_VERSION,
        "compatibility": COMPATIBILITY,
        "delegate_operation": "animation.retime_apply",
        "description": spec["description"],
        "parameter_schema": dict(spec["parameter_schema"]),
        "operations": ["preview", "apply"],
        "source_only": True,
        "real_runtime_verified": False,
    }


def _frames(values, minimum):
    if not isinstance(values, list) or not minimum <= len(values) <= 32:
        raise invalid(f"frames must contain {minimum}..32 integer frames")
    result = sorted(integer(value, "frame", 1, 100_000) for value in values)
    if len(set(result)) != len(result):
        raise invalid("Recipe frames must be unique")
    return result


def _delegate(data, recipe_id):
    parameters = data["parameters"]
    if not isinstance(parameters, dict):
        raise invalid("parameters must be an object")
    if recipe_id == "timeline.shift":
        fields(parameters, {"frames", "offset"})
        frames = _frames(parameters["frames"], 1)
        offset = integer(parameters["offset"], "offset", -10_000, 10_000)
        if not offset:
            raise invalid("Shift offset must be nonzero")
        pairs = [(frame, frame + offset) for frame in frames]
    elif recipe_id == "timeline.reverse":
        fields(parameters, {"frames"})
        frames = _frames(parameters["frames"], 2)
        pairs = list(zip(frames, reversed(frames), strict=True))
    else:
        fields(parameters, {"frames", "factor"})
        frames = _frames(parameters["frames"], 2)
        factor = integer(parameters["factor"], "factor", 2, 4)
        anchor = frames[0]
        pairs = [(frame, anchor + (frame - anchor) * factor) for frame in frames]
    mappings = [
        {"source_frame": source, "target_frame": target}
        for source, target in pairs
        if source != target
    ]
    if not mappings:
        raise invalid("Recipe must move at least one key")
    return TimelineRetime.parse(
        {
            "target": data["target"],
            "expected_animation_revision": data["expected_animation_revision"],
            "mappings": mappings,
        }
    )


@dataclass(frozen=True)
class AnimationRecipeCatalog:
    @classmethod
    def parse(cls, data):
        fields(data, set())
        return cls()


@dataclass(frozen=True)
class AnimationRecipeAction:
    recipe_id: str
    delegate: TimelineRetime

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"recipe_id", "recipe_version", "target", "expected_animation_revision", "parameters"},
        )
        recipe_id = string(data["recipe_id"], "recipe_id", limit=64)
        if recipe_id not in RECIPE_SPECS:
            raise invalid("Unknown managed animation recipe")
        integer(data["recipe_version"], "recipe_version", 1, 1)
        return cls(recipe_id, _delegate(data, recipe_id))


AnimationRecipePreview = AnimationRecipeAction
AnimationRecipeApply = AnimationRecipeAction


class AnimationRecipeLibraryOperations:
    def __init__(self, timeline: AnimationTimelineOperations):
        self.timeline = timeline

    def catalog(self, request: Request, action: AnimationRecipeCatalog):
        recipes = [_descriptor(recipe_id) for recipe_id in sorted(RECIPE_SPECS)]
        data = {
            "library_version": LIBRARY_VERSION,
            "minimum_blender_version": MIN_BLENDER_VERSION,
            "compatibility": COMPATIBILITY,
            "recipe_count": len(recipes),
            "recipes": recipes,
            "source_only": True,
            "real_runtime_verified": False,
        }
        data["catalog_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def preview(self, request: Request, action: AnimationRecipePreview):
        result = self.timeline.preview(request, action.delegate)
        return Result(
            request.request_id,
            request.command_id,
            result.status,
            {"recipe": _descriptor(action.recipe_id), "preview": dict(result.data or {})},
            result.error,
            result.verification,
        )

    def apply(self, request: Request, action: AnimationRecipeApply):
        result = self.timeline.apply(request, action.delegate)
        return Result(
            request.request_id,
            request.command_id,
            result.status,
            {"recipe": _descriptor(action.recipe_id), "delegate_result": dict(result.data or {})},
            result.error,
            result.verification,
        )

    def tools(self):
        return [
            Tool(
                "animation.recipe_catalog",
                SafetyClass.READ_ONLY,
                AnimationRecipeCatalog.parse,
                self.catalog,
            ),
            Tool(
                "animation.recipe_preview",
                SafetyClass.READ_ONLY,
                AnimationRecipePreview.parse,
                self.preview,
            ),
            Tool(
                "animation.recipe_apply",
                SafetyClass.MUTATION,
                AnimationRecipeApply.parse,
                self.apply,
            ),
        ]
