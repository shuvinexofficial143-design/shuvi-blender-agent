"""Level 6 milestone 10: bounded rigging QA and source/fake-bpy acceptance."""

from dataclasses import dataclass

from .contracts import Request
from .inspection import revision
from .operations import ObjectOperations
from .rig_recipe_library import (
    LIBRARY_VERSION,
    RECIPE_SPECS,
    RecipePreview,
    RigRecipeLibraryOperations,
)
from .rigging import (
    MAX_RIG_BONES,
    MAX_WEIGHT_ASSIGNMENTS,
    MAX_WEIGHT_GROUPS,
    RiggingOperations,
)
from .validation import fields, string

EXPECTED_RECIPE_IDS = {
    "constraint.limit_rotation",
    "constraint.same_armature_ik",
    "control.three_bone_ik_fk",
}
FULL_ACCEPTANCE_RECIPE = "control.three_bone_ik_fk"


@dataclass(frozen=True)
class Level6AcceptanceRequest:
    mesh_object_id: str
    recipe_id: str
    delegate: RecipePreview

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"mesh_object_id", "recipe_id", "target", "expected_rig_revision", "parameters"},
        )
        payload = {
            "recipe_id": data["recipe_id"],
            "target": data["target"],
            "expected_rig_revision": data["expected_rig_revision"],
            "parameters": data["parameters"],
        }
        delegate = RecipePreview.parse(payload)
        return cls(
            string(data["mesh_object_id"], "mesh_object_id", limit=128),
            delegate.recipe_id,
            delegate,
        )


class RigAcceptanceOperations:
    def __init__(self, objects: ObjectOperations):
        self.rigging = RiggingOperations(objects)
        self.library = RigRecipeLibraryOperations(objects)

    @staticmethod
    def _request(operation, payload):
        return Request(operation, payload)

    @staticmethod
    def _parameters(action):
        delegate = action.delegate.delegate
        return {
            "upper_bone": delegate.upper_bone,
            "middle_bone": delegate.middle_bone,
            "end_bone": delegate.end_bone,
            "target_bone": delegate.target_bone,
            "constraint_name": delegate.constraint_name,
            "initial_mode": delegate.initial_mode,
        }

    def evaluate(self, action: Level6AcceptanceRequest):
        if action.recipe_id != FULL_ACCEPTANCE_RECIPE:
            raise ValueError("Level 6 full acceptance requires the managed three-bone IK/FK recipe")

        delegate = action.delegate.delegate
        armature = self.rigging.inspector.resolve(delegate.target.object_id)
        rig = self.rigging._snapshot(armature)
        mesh = self.rigging.inspector.resolve(action.mesh_object_id)
        weights = self.rigging._weight_snapshot(mesh, armature, rig)
        catalog = self.library._catalog()
        preview_payload = {
            "recipe_id": action.recipe_id,
            "target": {
                "object_id": delegate.target.object_id,
                "expected_name": delegate.target.expected_name,
                "expected_revision": delegate.target.expected_revision,
            },
            "expected_rig_revision": delegate.expected_rig_revision,
            "parameters": self._parameters(action),
        }
        recipe = self.library.preview(
            self._request("rig.recipe_preview", preview_payload), action.delegate
        ).data
        descriptors = catalog["recipes"]
        recipe_ids = {item["recipe_id"] for item in descriptors}
        preview = recipe["preview"]
        plan = preview["plan"]

        checks = [
            {
                "name": "ARMATURE_STRUCTURE",
                "status": (
                    "PASS"
                    if 1 <= rig["bone_count"] <= MAX_RIG_BONES
                    and rig["bone_count"] == rig["pose_bone_count"]
                    and rig["root_count"] >= 1
                    and not rig["hierarchy_cycle"]
                    and not rig["pose_missing_bones"]
                    and not rig["pose_extra_bones"]
                    and not rig["linked_object"]
                    and not rig["linked_armature_data"]
                    else "BLOCKED"
                ),
            },
            {
                "name": "MANAGED_MESH_BINDING",
                "status": (
                    "PASS"
                    if weights["mesh_object_id"] == action.mesh_object_id
                    and weights["armature_object_id"] == rig["object_id"]
                    and bool(weights["modifier_name"])
                    and weights["rig_revision"] == rig["rig_revision"]
                    else "BLOCKED"
                ),
            },
            {
                "name": "BOUNDED_SKIN_WEIGHTS",
                "status": (
                    "PASS"
                    if 1 <= weights["group_count"] <= MAX_WEIGHT_GROUPS
                    and 1 <= weights["assignment_count"] <= MAX_WEIGHT_ASSIGNMENTS
                    and not weights["unmatched_group_names"]
                    and not weights["nondeform_group_names"]
                    else "BLOCKED"
                ),
            },
            {
                "name": "FIXED_VERSIONED_RECIPE_LIBRARY",
                "status": (
                    "PASS"
                    if catalog["library_version"] == LIBRARY_VERSION == 1
                    and catalog["recipe_count"] == 3
                    and recipe_ids == EXPECTED_RECIPE_IDS == set(RECIPE_SPECS)
                    and all(item["recipe_version"] == 1 for item in descriptors)
                    else "BLOCKED"
                ),
            },
            {
                "name": "FRESH_IK_FK_RECIPE_PREVIEW",
                "status": (
                    "PASS"
                    if preview["ready"] is True
                    and preview["blockers"] == []
                    and preview["rig_revision"] == rig["rig_revision"]
                    and plan["operation"] == "rig.ik_fk_setup"
                    and plan["initial_mode"] in {"IK", "FK"}
                    else "BLOCKED"
                ),
            },
            {
                "name": "SOURCE_RUNTIME_BOUNDARY",
                "status": (
                    "PASS"
                    if rig["source_only"] is True
                    and rig["real_runtime_verified"] is False
                    and weights["source_only"] is True
                    and weights["real_runtime_verified"] is False
                    and catalog["source_only"] is True
                    and catalog["real_runtime_verified"] is False
                    and recipe["recipe"]["source_only"] is True
                    and recipe["recipe"]["real_runtime_verified"] is False
                    else "BLOCKED"
                ),
            },
        ]
        source_status = "READY" if all(item["status"] == "PASS" for item in checks) else "BLOCKED"
        data = {
            "armature_object_id": rig["object_id"],
            "mesh_object_id": action.mesh_object_id,
            "rig_revision": rig["rig_revision"],
            "weight_revision": weights["weight_revision"],
            "catalog_revision": catalog["catalog_revision"],
            "recipe_id": action.recipe_id,
            "checks": checks,
            "check_count": len(checks),
            "source_acceptance_status": source_status,
            "source_level_complete_when_passed": 6,
            "source_scope": "LEVEL_6_SOURCE_AND_FAKE_BPY_ACCEPTANCE_ONLY",
            "fresh_state_required_for_mutations": True,
            "stale_state_must_fail_closed": True,
            "exact_readback_required": True,
            "verified_recovery_required": True,
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
            "production_ready": False,
            "public_tool_added": False,
        }
        data["acceptance_revision"] = revision(data)
        return data
