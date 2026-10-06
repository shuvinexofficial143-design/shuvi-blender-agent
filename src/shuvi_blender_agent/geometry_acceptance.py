"""Level 5 milestone 10: bounded Geometry Nodes source QA and acceptance reporting."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .geometry_recipe_library import (
    LIBRARY_VERSION,
    RECIPE_SPECS,
    GeometryRecipeLibraryOperations,
    RecipePreview,
)
from .inspection import revision
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool

MAX_GEOMETRY_NODES = 64
MAX_GEOMETRY_LINKS = 128
EXPECTED_RECIPE_COUNT = 10
EXPECTED_FAMILIES = {"primitive", "field", "scatter", "architecture"}


@dataclass(frozen=True)
class GeometryWorkflowPreview:
    recipe_id: str
    prefix: str
    parameters: dict
    delegate: RecipePreview

    @classmethod
    def parse(cls, data):
        delegate = RecipePreview.parse(data)
        return cls(
            delegate.recipe_id,
            delegate.prefix,
            delegate.parameters,
            delegate,
        )


@dataclass(frozen=True)
class Level5Acceptance:
    recipe_id: str
    prefix: str
    parameters: dict
    delegate: RecipePreview

    @classmethod
    def parse(cls, data):
        delegate = RecipePreview.parse(data)
        return cls(
            delegate.recipe_id,
            delegate.prefix,
            delegate.parameters,
            delegate,
        )


class GeometryAcceptanceOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.library = GeometryRecipeLibraryOperations(objects)

    @staticmethod
    def _request(operation, payload):
        return Request(operation, payload)

    def _evidence(self, action):
        catalog = self.library._catalog()
        preview_payload = {
            "recipe_id": action.recipe_id,
            "prefix": action.prefix,
            "parameters": action.parameters,
        }
        library_preview = self.library.preview(
            self._request("geometry_nodes.recipe_preview", preview_payload),
            action.delegate,
        )
        direct_preview = self.library._operation(action.recipe_id).preview(
            self._request("geometry_nodes.recipe_preview", preview_payload),
            action.delegate.delegate,
        )
        return {
            "catalog": catalog,
            "library_preview": library_preview.data,
            "direct_preview": direct_preview.data,
        }

    @staticmethod
    def _checks(action, evidence):
        catalog = evidence["catalog"]
        library_preview = evidence["library_preview"]
        direct_preview = evidence["direct_preview"]
        descriptors = catalog["recipes"]
        recipe_ids = [item["recipe_id"] for item in descriptors]
        families = {item["family"] for item in descriptors}
        family_result = library_preview["family_result"]
        nodes = family_result.get("nodes", [])
        links = family_result.get("links", [])

        return [
            {
                "name": "FIXED_RECIPE_CATALOG",
                "status": (
                    "PASS"
                    if catalog["recipe_count"] == EXPECTED_RECIPE_COUNT
                    and recipe_ids == sorted(RECIPE_SPECS)
                    and len(set(recipe_ids)) == EXPECTED_RECIPE_COUNT
                    else "BLOCKED"
                ),
            },
            {
                "name": "VERSIONED_COMPATIBILITY_METADATA",
                "status": (
                    "PASS"
                    if catalog["library_version"] == LIBRARY_VERSION == 1
                    and all(item["recipe_version"] == 1 for item in descriptors)
                    and all(item["library_version"] == 1 for item in descriptors)
                    else "BLOCKED"
                ),
            },
            {
                "name": "STATIC_FAMILY_ROUTING",
                "status": (
                    "PASS"
                    if families == EXPECTED_FAMILIES
                    and all(
                        item["operations"] == ["preview", "apply", "clear"]
                        for item in descriptors
                    )
                    else "BLOCKED"
                ),
            },
            {
                "name": "SELECTED_RECIPE_PRESENT",
                "status": "PASS" if action.recipe_id in recipe_ids else "BLOCKED",
            },
            {
                "name": "DIRECT_FAMILY_PREVIEW_EQUIVALENCE",
                "status": "PASS" if family_result == direct_preview else "BLOCKED",
            },
            {
                "name": "BOUNDED_GRAPH_PLAN",
                "status": (
                    "PASS"
                    if len(nodes) <= MAX_GEOMETRY_NODES
                    and len(links) <= MAX_GEOMETRY_LINKS
                    else "BLOCKED"
                ),
            },
            {
                "name": "SOURCE_RUNTIME_BOUNDARY",
                "status": (
                    "PASS"
                    if catalog["source_only"] is True
                    and catalog["real_runtime_verified"] is False
                    and library_preview["recipe"]["source_only"] is True
                    and library_preview["recipe"]["real_runtime_verified"] is False
                    else "BLOCKED"
                ),
            },
        ]

    def preview(self, request: Request, action: GeometryWorkflowPreview):
        evidence = self._evidence(action)
        checks = self._checks(action, evidence)
        source_status = (
            "READY" if all(item["status"] == "PASS" for item in checks) else "BLOCKED"
        )
        stages = [
            {
                "stage": 1,
                "operation": "geometry_nodes.recipe_catalog",
                "purpose": "verify the fixed versioned Level 5 recipe catalog",
                "mutation": False,
            },
            {
                "stage": 2,
                "operation": "direct managed family preview",
                "purpose": "derive the authoritative bounded family plan",
                "mutation": False,
            },
            {
                "stage": 3,
                "operation": "geometry_nodes.recipe_preview",
                "purpose": "verify recipe-library routing matches the direct family preview",
                "mutation": False,
            },
            {
                "stage": 4,
                "operation": "geometry_nodes.group_create",
                "purpose": (\n                    "create a fresh empty local GeometryNodeTree only when execution "\n                    "is authorized"\n                ),
                "mutation": True,
            },
            {
                "stage": 5,
                "operation": "geometry_nodes.recipe_apply",
                "purpose": (\n                    "apply only with a fresh expected group revision and existing "\n                    "family bounds"\n                ),
                "mutation": True,
            },
            {
                "stage": 6,
                "operation": "geometry_nodes.tree_inspect",
                "purpose": "read back the exact managed graph and fresh group revision",
                "mutation": False,
            },
            {
                "stage": 7,
                "operation": "stale/cross-family negative gates",
                "purpose": (\n                    "fail closed on stale state, mismatched family parameters and "\n                    "foreign graph state"\n                ),
                "mutation": False,
            },
            {
                "stage": 8,
                "operation": "geometry_nodes.recipe_clear",
                "purpose": "clear only exact managed state and preserve verified rebuild recovery",
                "mutation": True,
            },
            {
                "stage": 9,
                "operation": "geometry_nodes.level5_acceptance",
                "purpose": "emit final source/fake-bpy Level 5 acceptance evidence",
                "mutation": False,
            },
        ]
        data = {
            "recipe_id": action.recipe_id,
            "family": RECIPE_SPECS[action.recipe_id]["family"],
            "source_gate_status": source_status,
            "checks": checks,
            "check_count": len(checks),
            "stages": stages,
            "stage_count": len(stages),
            "fresh_group_revision_required_for_mutations": True,
            "automatic_mutation_execution": False,
            "cross_family_payloads_fail_closed": True,
            "verified_recovery_required": True,
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
            "production_ready": False,
        }
        data["workflow_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def acceptance(self, request: Request, action: Level5Acceptance):
        evidence = self._evidence(action)
        checks = self._checks(action, evidence)
        source_status = (
            "READY" if all(item["status"] == "PASS" for item in checks) else "BLOCKED"
        )
        data = {
            "recipe_id": action.recipe_id,
            "family": RECIPE_SPECS[action.recipe_id]["family"],
            "checks": checks,
            "check_count": len(checks),
            "source_acceptance_status": source_status,
            "source_level_complete_when_passed": 5,
            "source_scope": "LEVEL_5_SOURCE_AND_FAKE_BPY_ACCEPTANCE_ONLY",
            "catalog_revision": evidence["catalog"]["catalog_revision"],
            "fresh_state_required_for_mutations": True,
            "stale_state_must_fail_closed": True,
            "exact_readback_required": True,
            "verified_recovery_required": True,
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
            "production_ready": False,
        }
        data["acceptance_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "geometry_nodes.workflow_preview",
                SafetyClass.READ_ONLY,
                GeometryWorkflowPreview.parse,
                self.preview,
            ),
            Tool(
                "geometry_nodes.level5_acceptance",
                SafetyClass.READ_ONLY,
                Level5Acceptance.parse,
                self.acceptance,
            ),
        ]
