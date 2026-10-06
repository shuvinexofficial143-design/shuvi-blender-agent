"""Level 5 milestone 9: bounded Geometry Nodes managed recipe library."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .geometry_architecture import (
    ArchitectureApply,
    ArchitectureClear,
    ArchitecturePreview,
    GeometryArchitectureOperations,
)
from .geometry_fields import (
    FieldWorkflowApply,
    FieldWorkflowClear,
    FieldWorkflowPreview,
    GeometryFieldOperations,
)
from .geometry_primitives import (
    PrimitiveApply,
    PrimitiveClear,
    PrimitivePreview,
    ProceduralPrimitiveOperations,
)
from .geometry_scatter import (
    GeometryScatterOperations,
    ScatterApply,
    ScatterClear,
    ScatterPreview,
)
from .inspection import revision
from .models import object_name
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, invalid, string

LIBRARY_VERSION = 1
MIN_BLENDER_VERSION = "4.2"
COMPATIBILITY = "SOURCE_VALIDATED_RUNTIME_UNVERIFIED"

RECIPE_SPECS = {
    "primitive.cube": {
        "family": "primitive",
        "family_recipe": "CUBE",
        "parameter_schema": {
            "size": "vector3 float 0.001..1000",
            "vertices": "int 2..64",
        },
    },
    "primitive.ico_sphere": {
        "family": "primitive",
        "family_recipe": "ICO_SPHERE",
        "parameter_schema": {
            "radius": "float 0.001..1000",
            "subdivisions": "int 1..5",
        },
    },
    "primitive.twin_cube": {
        "family": "primitive",
        "family_recipe": "TWIN_CUBE",
        "parameter_schema": {
            "size": "vector3 float 0.001..1000",
            "vertices": "int 2..64",
            "offset": "vector3 float -1000..1000",
        },
    },
    "field.index_attribute": {
        "family": "field",
        "family_recipe": "INDEX_ATTRIBUTE",
        "parameter_schema": {
            "size": "vector3 float 0.001..1000",
            "vertices": "int 2..64",
            "attribute_name": "ASCII shuvi_* max 48 bytes",
        },
    },
    "field.position_attribute": {
        "family": "field",
        "family_recipe": "POSITION_ATTRIBUTE",
        "parameter_schema": {
            "size": "vector3 float 0.001..1000",
            "vertices": "int 2..64",
            "attribute_name": "ASCII shuvi_* max 48 bytes",
        },
    },
    "field.normal_attribute": {
        "family": "field",
        "family_recipe": "NORMAL_ATTRIBUTE",
        "parameter_schema": {
            "size": "vector3 float 0.001..1000",
            "vertices": "int 2..64",
            "attribute_name": "ASCII shuvi_* max 48 bytes",
        },
    },
    "scatter.cube": {
        "family": "scatter",
        "family_recipe": "CUBE_SCATTER",
        "parameter_schema": {
            "point_size": "vector3 float 0.001..1000",
            "point_vertices": "vector3 int 2..20; estimated instances <=2048",
            "rotation": "vector3 float -2pi..2pi",
            "scale": "vector3 float 0.001..100",
            "instance_size": "vector3 float 0.001..1000",
            "instance_vertices": "int 2..8",
        },
    },
    "scatter.ico_sphere": {
        "family": "scatter",
        "family_recipe": "ICO_SPHERE_SCATTER",
        "parameter_schema": {
            "point_size": "vector3 float 0.001..1000",
            "point_vertices": "vector3 int 2..20; estimated instances <=2048",
            "rotation": "vector3 float -2pi..2pi",
            "scale": "vector3 float 0.001..100",
            "instance_radius": "float 0.001..1000",
            "instance_subdivisions": "int 1..3",
        },
    },
    "architecture.modular_wall": {
        "family": "architecture",
        "family_recipe": "MODULAR_WALL",
        "parameter_schema": {
            "module_size": "vector3 float 0.001..1000",
            "count": "int 1..16",
            "gap": "float 0..1000",
            "base_offset": "vector3 float -1000..1000",
        },
    },
    "architecture.block_grid": {
        "family": "architecture",
        "family_recipe": "BLOCK_GRID",
        "parameter_schema": {
            "block_size": "vector3 float 0.001..1000",
            "count_x": "int 1..6",
            "count_y": "int 1..6; count_x*count_y <=24",
            "gap_x": "float 0..1000",
            "gap_y": "float 0..1000",
            "base_offset": "vector3 float -1000..1000",
        },
    },
}


def _recipe_id(value):
    recipe_id = string(value, "recipe_id", limit=64)
    if recipe_id not in RECIPE_SPECS:
        raise invalid("Unknown managed Geometry Nodes recipe_id")
    return recipe_id


def _descriptor(recipe_id):
    spec = RECIPE_SPECS[recipe_id]
    return {
        "recipe_id": recipe_id,
        "family": spec["family"],
        "family_recipe": spec["family_recipe"],
        "recipe_version": 1,
        "library_version": LIBRARY_VERSION,
        "minimum_blender_version": MIN_BLENDER_VERSION,
        "compatibility": COMPATIBILITY,
        "operations": ["preview", "apply", "clear"],
        "parameter_schema": dict(spec["parameter_schema"]),
        "source_only": True,
        "real_runtime_verified": False,
    }


def _parse_family_preview(recipe_id, prefix, parameters):
    spec = RECIPE_SPECS[recipe_id]
    payload = {
        "prefix": prefix,
        "parameters": parameters,
    }
    if spec["family"] == "primitive":
        payload["recipe"] = spec["family_recipe"]
        return PrimitivePreview.parse(payload)
    if spec["family"] == "field":
        payload["workflow"] = spec["family_recipe"]
        return FieldWorkflowPreview.parse(payload)
    if spec["family"] == "scatter":
        payload["recipe"] = spec["family_recipe"]
        return ScatterPreview.parse(payload)
    payload["recipe"] = spec["family_recipe"]
    return ArchitecturePreview.parse(payload)


def _parse_family_mutation(
    recipe_id,
    group_name,
    expected_group_revision,
    prefix,
    parameters,
):
    spec = RECIPE_SPECS[recipe_id]
    payload = {
        "group_name": group_name,
        "expected_group_revision": expected_group_revision,
        "prefix": prefix,
        "parameters": parameters,
    }
    if spec["family"] == "primitive":
        payload["recipe"] = spec["family_recipe"]
        return PrimitiveApply.parse(payload)
    if spec["family"] == "field":
        payload["workflow"] = spec["family_recipe"]
        return FieldWorkflowApply.parse(payload)
    if spec["family"] == "scatter":
        payload["recipe"] = spec["family_recipe"]
        return ScatterApply.parse(payload)
    payload["recipe"] = spec["family_recipe"]
    return ArchitectureApply.parse(payload)


@dataclass(frozen=True)
class RecipeCatalog:
    @classmethod
    def parse(cls, data):
        fields(data, set())
        return cls()


@dataclass(frozen=True)
class RecipePreview:
    recipe_id: str
    prefix: str
    parameters: dict
    delegate: object

    @classmethod
    def parse(cls, data):
        fields(data, {"recipe_id", "prefix", "parameters"})
        recipe_id = _recipe_id(data["recipe_id"])
        delegate = _parse_family_preview(
            recipe_id,
            data["prefix"],
            data["parameters"],
        )
        return cls(
            recipe_id,
            delegate.prefix,
            delegate.parameters,
            delegate,
        )


@dataclass(frozen=True)
class RecipeMutation:
    recipe_id: str
    group_name: str
    expected_group_revision: str
    prefix: str
    parameters: dict
    delegate: object

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "recipe_id",
                "group_name",
                "expected_group_revision",
                "prefix",
                "parameters",
            },
        )
        recipe_id = _recipe_id(data["recipe_id"])
        delegate = _parse_family_mutation(
            recipe_id,
            data["group_name"],
            data["expected_group_revision"],
            data["prefix"],
            data["parameters"],
        )
        return cls(
            recipe_id,
            delegate.group_name,
            delegate.expected_group_revision,
            delegate.prefix,
            delegate.parameters,
            delegate,
        )


RecipeApply = RecipeMutation
RecipeClear = RecipeMutation


class GeometryRecipeLibraryOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.primitives = ProceduralPrimitiveOperations(objects)
        self.fields = GeometryFieldOperations(objects)
        self.scatter = GeometryScatterOperations(objects)
        self.architecture = GeometryArchitectureOperations(objects)

    @staticmethod
    def _catalog():
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
        return data

    @staticmethod
    def _metadata(recipe_id):
        descriptor = _descriptor(recipe_id)
        return {
            "recipe_id": descriptor["recipe_id"],
            "family": descriptor["family"],
            "family_recipe": descriptor["family_recipe"],
            "recipe_version": descriptor["recipe_version"],
            "library_version": descriptor["library_version"],
            "minimum_blender_version": descriptor["minimum_blender_version"],
            "compatibility": descriptor["compatibility"],
            "source_only": True,
            "real_runtime_verified": False,
        }

    def catalog(self, request: Request, action: RecipeCatalog):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._catalog(),
        )

    def _operation(self, recipe_id):
        family = RECIPE_SPECS[recipe_id]["family"]
        if family == "primitive":
            return self.primitives
        if family == "field":
            return self.fields
        if family == "scatter":
            return self.scatter
        return self.architecture

    def _wrap(self, request, recipe_id, result):
        return Result(
            request.request_id,
            request.command_id,
            result.status,
            {
                "recipe": self._metadata(recipe_id),
                "family_result": dict(result.data),
            },
            result.error,
            result.verification,
        )

    def preview(self, request: Request, action: RecipePreview):
        result = self._operation(action.recipe_id).preview(request, action.delegate)
        return self._wrap(request, action.recipe_id, result)

    def apply(self, request: Request, action: RecipeApply):
        result = self._operation(action.recipe_id).apply(request, action.delegate)
        return self._wrap(request, action.recipe_id, result)

    def clear(self, request: Request, action: RecipeClear):
        spec = RECIPE_SPECS[action.recipe_id]
        if spec["family"] == "primitive":
            delegate = PrimitiveClear(
                action.delegate.group_name,
                action.delegate.expected_group_revision,
                action.delegate.recipe,
                action.delegate.prefix,
                action.delegate.parameters,
            )
        elif spec["family"] == "field":
            delegate = FieldWorkflowClear(
                action.delegate.group_name,
                action.delegate.expected_group_revision,
                action.delegate.workflow,
                action.delegate.prefix,
                action.delegate.parameters,
            )
        elif spec["family"] == "scatter":
            delegate = ScatterClear(
                action.delegate.group_name,
                action.delegate.expected_group_revision,
                action.delegate.recipe,
                action.delegate.prefix,
                action.delegate.parameters,
            )
        else:
            delegate = ArchitectureClear(
                action.delegate.group_name,
                action.delegate.expected_group_revision,
                action.delegate.recipe,
                action.delegate.prefix,
                action.delegate.parameters,
            )
        result = self._operation(action.recipe_id).clear(request, delegate)
        return self._wrap(request, action.recipe_id, result)

    def tools(self):
        return [
            Tool(
                "geometry_nodes.recipe_catalog",
                SafetyClass.READ_ONLY,
                RecipeCatalog.parse,
                self.catalog,
            ),
            Tool(
                "geometry_nodes.recipe_preview",
                SafetyClass.READ_ONLY,
                RecipePreview.parse,
                self.preview,
            ),
            Tool(
                "geometry_nodes.recipe_apply",
                SafetyClass.MUTATION,
                RecipeApply.parse,
                self.apply,
            ),
            Tool(
                "geometry_nodes.recipe_clear",
                SafetyClass.MUTATION,
                RecipeClear.parse,
                self.clear,
            ),
        ]
