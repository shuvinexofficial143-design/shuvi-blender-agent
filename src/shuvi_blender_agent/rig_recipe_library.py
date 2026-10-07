"""Level 6 milestone 9: bounded versioned rig recipe library."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .operations import ObjectOperations
from .rigging import IKFKSetup, PoseConstraintCreate, RiggingOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, string

LIBRARY_VERSION = 1
MIN_BLENDER_VERSION = "4.2"
COMPATIBILITY = "SOURCE_VALIDATED_RUNTIME_UNVERIFIED"

RECIPE_SPECS = {
    "constraint.limit_rotation": {
        "family": "constraint",
        "delegate_operation": "rig.pose_constraint_create",
        "parameter_schema": {
            "bone_name": "existing pose bone name",
            "constraint_name": "unique constraint name",
            "influence": "float 0..1",
            "mute": "boolean",
            "use_limit_x": "boolean",
            "min_x": "float -1000..1000 radians",
            "max_x": "float -1000..1000 radians; min_x <= max_x",
            "use_limit_y": "boolean",
            "min_y": "float -1000..1000 radians",
            "max_y": "float -1000..1000 radians; min_y <= max_y",
            "use_limit_z": "boolean",
            "min_z": "float -1000..1000 radians",
            "max_z": "float -1000..1000 radians; min_z <= max_z",
        },
    },
    "constraint.same_armature_ik": {
        "family": "constraint",
        "delegate_operation": "rig.pose_constraint_create",
        "parameter_schema": {
            "bone_name": "existing owner pose bone name",
            "constraint_name": "unique constraint name",
            "influence": "float 0..1",
            "mute": "boolean",
            "target_bone_name": "distinct existing same-armature pose bone",
            "chain_count": "int 1..64",
        },
    },
    "control.three_bone_ik_fk": {
        "family": "ik_fk",
        "delegate_operation": "rig.ik_fk_setup",
        "parameter_schema": {
            "upper_bone": "existing deform bone",
            "middle_bone": "existing deform child of upper_bone",
            "end_bone": "existing deform child of middle_bone",
            "target_bone": "distinct existing non-deforming control bone",
            "constraint_name": "unique managed IK constraint name",
            "initial_mode": "IK or FK",
        },
    },
}


def _recipe_id(value):
    recipe_id = string(value, "recipe_id", limit=64)
    if recipe_id not in RECIPE_SPECS:
        raise invalid("Unknown managed rig recipe_id")
    return recipe_id


def _descriptor(recipe_id):
    spec = RECIPE_SPECS[recipe_id]
    return {
        "recipe_id": recipe_id,
        "family": spec["family"],
        "delegate_operation": spec["delegate_operation"],
        "recipe_version": 1,
        "library_version": LIBRARY_VERSION,
        "minimum_blender_version": MIN_BLENDER_VERSION,
        "compatibility": COMPATIBILITY,
        "operations": ["preview", "apply"],
        "parameter_schema": dict(spec["parameter_schema"]),
        "source_only": True,
        "real_runtime_verified": False,
    }


def _delegate(recipe_id, target, expected_rig_revision, parameters):
    if not isinstance(parameters, dict):
        raise invalid("parameters must be an object")
    payload = {
        "target": target,
        "expected_rig_revision": expected_rig_revision,
        **parameters,
    }
    if recipe_id == "constraint.limit_rotation":
        payload["constraint_type"] = "LIMIT_ROTATION"
        return PoseConstraintCreate.parse(payload)
    if recipe_id == "constraint.same_armature_ik":
        payload["constraint_type"] = "IK"
        return PoseConstraintCreate.parse(payload)
    return IKFKSetup.parse(payload)


@dataclass(frozen=True)
class RecipeCatalog:
    @classmethod
    def parse(cls, data):
        fields(data, set())
        return cls()


@dataclass(frozen=True)
class RecipeAction:
    recipe_id: str
    delegate: object

    @classmethod
    def parse(cls, data):
        fields(data, {"recipe_id", "target", "expected_rig_revision", "parameters"})
        recipe_id = _recipe_id(data["recipe_id"])
        expected_rig_revision = string(
            data["expected_rig_revision"], "expected_rig_revision", limit=64
        )
        delegate = _delegate(
            recipe_id,
            data["target"],
            expected_rig_revision,
            data["parameters"],
        )
        return cls(recipe_id, delegate)


RecipePreview = RecipeAction
RecipeApply = RecipeAction


class RigRecipeLibraryOperations:
    def __init__(self, objects: ObjectOperations):
        self.rigging = RiggingOperations(objects)

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
            "delegate_operation": descriptor["delegate_operation"],
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

    def _constraint_preview(self, action):
        delegate = action.delegate
        obj, target_before, before, _pose_bone, pose_before = self.rigging._pose_target(delegate)
        blockers = []
        existing = self.rigging._constraint_from_snapshot(
            pose_before, delegate.constraint_name
        )
        if existing is not None:
            blockers.append("CONSTRAINT_NAME_EXISTS")
        if pose_before["constraint_count"] >= 64:
            blockers.append("POSE_BONE_CONSTRAINT_LIMIT")
        if before["total_pose_constraint_count"] >= 512:
            blockers.append("TOTAL_POSE_CONSTRAINT_LIMIT")

        target_state = None
        if delegate.constraint_type == "IK":
            if delegate.target_bone_name == delegate.bone_name:
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "IK target bone must differ from owner bone",
                )
            bone_names = {item["name"] for item in before["bones"]}
            pose_names = {item["name"] for item in before["pose_bones"]}
            if (
                delegate.target_bone_name not in bone_names
                or delegate.target_bone_name not in pose_names
            ):
                raise AgentError(ErrorCode.NOT_FOUND, "IK target bone not found in armature")
            target_state = delegate.target_bone_name

        plan = {
            "operation": "rig.pose_constraint_create",
            "bone_name": delegate.bone_name,
            "constraint_name": delegate.constraint_name,
            "constraint_type": delegate.constraint_type,
            "influence": delegate.influence,
            "mute": delegate.mute,
        }
        if delegate.constraint_type == "LIMIT_ROTATION":
            for axis in ("x", "y", "z"):
                plan[f"use_limit_{axis}"] = getattr(delegate, f"use_limit_{axis}")
                plan[f"min_{axis}"] = getattr(delegate, f"min_{axis}")
                plan[f"max_{axis}"] = getattr(delegate, f"max_{axis}")
        else:
            plan.update(
                {
                    "target_bone_name": target_state,
                    "chain_count": delegate.chain_count,
                }
            )

        return {
            "ready": not blockers,
            "blockers": blockers,
            "plan": plan,
            "object_id": target_before["object_id"],
            "rig_revision": before["rig_revision"],
            "source_only": True,
            "real_runtime_verified": False,
        }

    def _ik_fk_preview(self, action):
        delegate = action.delegate
        obj, target_before = self.rigging._require_editable_active_armature(delegate.target)
        before = self.rigging._snapshot(obj)
        require_revision(delegate.expected_rig_revision, before["rig_revision"])
        state = self.rigging._ik_fk_state(obj, before, delegate)

        blockers = []
        if state["constraint"] is not None:
            blockers.append("CONSTRAINT_NAME_EXISTS")
        end_pose = next(
            item for item in before["pose_bones"] if item["name"] == delegate.end_bone
        )
        if end_pose["constraint_count"] >= 64:
            blockers.append("POSE_BONE_CONSTRAINT_LIMIT")
        if before["total_pose_constraint_count"] >= 512:
            blockers.append("TOTAL_POSE_CONSTRAINT_LIMIT")

        return {
            "ready": not blockers,
            "blockers": blockers,
            "plan": {
                "operation": "rig.ik_fk_setup",
                "upper_bone": delegate.upper_bone,
                "middle_bone": delegate.middle_bone,
                "end_bone": delegate.end_bone,
                "target_bone": delegate.target_bone,
                "constraint_name": delegate.constraint_name,
                "initial_mode": delegate.initial_mode,
            },
            "current_ik_fk": state,
            "object_id": target_before["object_id"],
            "rig_revision": before["rig_revision"],
            "source_only": True,
            "real_runtime_verified": False,
        }

    def preview(self, request: Request, action: RecipePreview):
        if RECIPE_SPECS[action.recipe_id]["family"] == "constraint":
            preview = self._constraint_preview(action)
        else:
            preview = self._ik_fk_preview(action)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "recipe": self._metadata(action.recipe_id),
                "preview": preview,
            },
        )

    def apply(self, request: Request, action: RecipeApply):
        if RECIPE_SPECS[action.recipe_id]["family"] == "constraint":
            result = self.rigging.create_pose_constraint(request, action.delegate)
        else:
            result = self.rigging.setup_ik_fk(request, action.delegate)
        return Result(
            request.request_id,
            request.command_id,
            result.status,
            {
                "recipe": self._metadata(action.recipe_id),
                "delegate_result": dict(result.data or {}),
            },
            result.error,
            result.verification,
        )

    def tools(self):
        return [
            Tool(
                "rig.recipe_catalog",
                SafetyClass.READ_ONLY,
                RecipeCatalog.parse,
                self.catalog,
            ),
            Tool(
                "rig.recipe_preview",
                SafetyClass.READ_ONLY,
                RecipePreview.parse,
                self.preview,
            ),
            Tool(
                "rig.recipe_apply",
                SafetyClass.MUTATION,
                RecipeApply.parse,
                self.apply,
            ),
        ]
