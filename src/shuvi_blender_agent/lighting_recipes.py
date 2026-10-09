"""Level 9 M9: bounded, reversible multi-property cinematic lamp recipes."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .safety import SafetyClass
from .studio_lighting import StudioLightingOperations
from .tools import Tool
from .validation import fields, string


# Each recipe changes *real, existing, owned* AREA lamp color, power,
# emitter size, spread and casting. Values are source defaults, not
# tested visual/render results. No arbitrary bpy code, paths or materials.
RECIPES = {
    "INTERVIEW_SOFTBOX": {
        "intent": "Soft key and fill for a documentary/interview subject",
        "colors": ((1.0, 0.91, 0.81), (0.82, 0.9, 1.0), (1.0, 0.9, 0.83)),
        "energy": (1.10, 0.92, 0.80),
        "size": (1.65, 1.45, 1.25),
        "spread": 3.141592653589793,
        "shadows": True,
    },
    "NOIR_PORTRAIT": {
        "intent": "Crisper cinematic portrait with very restrained fill",
        "colors": ((1.0, 0.83, 0.68), (0.40, 0.59, 0.85), (1.0, 0.96, 0.9)),
        "energy": (1.18, 0.25, 1.30),
        "size": (0.52, 0.76, 0.68),
        "spread": 1.5707963267948966,
        "shadows": True,
    },
    "PRODUCT_SHOWCASE": {
        "intent": "Broad white sources for studio product illumination",
        "colors": ((1.0, 0.99, 0.97), (0.92, 0.97, 1.0), (1.0, 1.0, 1.0)),
        "energy": (1.10, 1.15, 1.32),
        "size": (1.35, 1.40, 1.28),
        "spread": 3.141592653589793,
        "shadows": True,
    },
}
ROLES = ("Key", "Fill", "Rim", "Catchlight", "Top", "Edge")
ROLE_SLOT = {"Key": 0, "Fill": 1, "Rim": 2, "Catchlight": 1, "Top": 0, "Edge": 2}


@dataclass(frozen=True)
class RecipeCatalog:
    @classmethod
    def parse(cls, data):
        fields(data, set())
        return cls()


@dataclass(frozen=True)
class RecipePreview:
    lighting_token: str
    recipe: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_lighting_token", "recipe"})
        recipe = string(data["recipe"], "recipe", limit=40)
        if recipe not in RECIPES:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unsupported lighting recipe")
        return cls(
            string(data["expected_lighting_token"], "expected_lighting_token", limit=64),
            recipe,
        )


@dataclass(frozen=True)
class RecipeApply:
    preview: RecipePreview
    expected_recipe_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_lighting_token", "recipe", "expected_recipe_revision"})
        return cls(
            RecipePreview.parse({k: v for k, v in data.items() if k != "expected_recipe_revision"}),
            string(data["expected_recipe_revision"], "expected_recipe_revision", limit=64),
        )


@dataclass(frozen=True)
class RecipeRestore:
    expected_recipe_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_recipe_token"})
        return cls(string(data["expected_recipe_token"], "expected_recipe_token", limit=64))


class LightingRecipeOperations:
    def __init__(self, studio: StudioLightingOperations):
        self.studio = studio

    def catalog(self, request: Request, action: RecipeCatalog):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "recipes": [
                    {"name": name, "intent": settings["intent"], "supported_roles": list(ROLES)}
                    for name, settings in RECIPES.items()
                ],
                "mutation_performed": False,
                "source_only": True,
                "render_verified": False,
            },
        )

    def _plan(self, action: RecipePreview):
        owned = self.studio._live_owned(action.lighting_token)
        if owned.get("recipe_undo") is not None or owned.get("look_undo") is not None:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Restore or expire active look/recipe before another"
            )
        style = RECIPES[action.recipe]
        wanted = []
        for role, original in zip(owned["roles"], owned["expected"], strict=True):
            slot = ROLE_SLOT[role]
            row = dict(original)
            row["energy"] = min(100_000.0, max(1.0, original["energy"] * style["energy"][slot]))
            row["color"] = list(style["colors"][slot])
            row["size"] = min(50_000.0, max(0.2, original["size"] * style["size"][slot]))
            row["spread"] = style["spread"]
            row["use_shadow"] = style["shadows"]
            wanted.append(row)
        plan = {
            "recipe": action.recipe,
            "lighting_token": action.lighting_token,
            "roles": list(owned["roles"]),
            "before": owned["expected"],
            "after": wanted,
            "scene_revision": owned["after_scene"],
            "mutation_performed": False,
            "source_only": True,
            "render_verified": False,
        }
        plan["recipe_revision"] = revision(plan)
        return owned, wanted, plan

    def preview(self, request: Request, action: RecipePreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[2]
        )

    def apply(self, request: Request, action: RecipeApply):
        owned, wanted, plan = self._plan(action.preview)
        if plan["recipe_revision"] != action.expected_recipe_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Lighting recipe changed since preview")
        previous = [dict(row) for row in owned["expected"]]
        if wanted == previous:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Recipe makes no light changes")
        checked = self.studio._mutate_lights(owned, wanted)
        if not checked.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {"rolled_back": True, "recovery_verified": True},
                AgentError(ErrorCode.VERIFICATION_FAILED, "Recipe light readback mismatch"),
                checked.to_dict(),
            )
        token = revision(
            {
                "lighting_token": action.preview.lighting_token,
                "before": previous,
                "after": wanted,
                "scene": owned["after_scene"],
                "recipe": action.preview.recipe,
            }
        )
        owned["recipe_undo"] = {"token": token, "before": previous, "after": wanted}
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {
                "recipe_token": token,
                "lighting_token": action.preview.lighting_token,
                "lights_updated": len(wanted),
                "recipe": action.preview.recipe,
                "source_only": True,
                "render_verified": False,
            },
            verification=checked.to_dict(),
        )

    def restore(self, request: Request, action: RecipeRestore):
        matches = [
            (lighting_token, owned)
            for lighting_token, owned in self.studio._owned.items()
            if (owned.get("recipe_undo") or {}).get("token") == action.expected_recipe_token
        ]
        if len(matches) != 1:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or expired recipe token")
        _, owned = matches[0]
        self.studio._live_owned(matches[0][0])
        snapshot = owned["recipe_undo"]
        if owned["expected"] != snapshot["after"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Recipe was changed after application")
        checked = self.studio._mutate_lights(owned, snapshot["before"])
        if not checked.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {"rolled_back": True, "recovery_verified": True},
                AgentError(ErrorCode.VERIFICATION_FAILED, "Recipe restore readback mismatch"),
                checked.to_dict(),
            )
        owned["recipe_undo"] = None
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"restored_previous_settings": True, "source_only": True, "render_verified": False},
            verification=checked.to_dict(),
        )

    def tools(self):
        return [
            Tool(
                "lighting.recipe_catalog", SafetyClass.READ_ONLY, RecipeCatalog.parse, self.catalog
            ),
            Tool(
                "lighting.recipe_preview", SafetyClass.READ_ONLY, RecipePreview.parse, self.preview
            ),
            Tool("lighting.recipe_apply", SafetyClass.MUTATION, RecipeApply.parse, self.apply),
            Tool(
                "lighting.recipe_restore", SafetyClass.MUTATION, RecipeRestore.parse, self.restore
            ),
        ]
