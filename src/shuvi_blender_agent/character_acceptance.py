"""Level 3 milestone 10: bounded character workflow composition and source acceptance."""

from dataclasses import dataclass

from .character_blockout import CharacterBlockoutOperations, LandmarkFit, _preset
from .character_body import BodyRegionPlan, CharacterBodyOperations
from .character_face import (
    CharacterFaceOperations,
    FaceFit,
    FaceRegions,
    FaceSymmetryAudit,
    _front,
)
from .character_sculpt_workflow import (
    CharacterSculptQA,
    CharacterSculptWorkflowOperations,
    SculptRecipePreview,
    _recipe,
)
from .contracts import Request, Result, Status
from .inspection import revision
from .operations import ObjectOperations
from .safety import SafetyClass
from .sculpting_remesh import SculptRemeshPlanningOperations, SurfaceSnapshot
from .tools import Tool
from .validation import fields, number, string

MAX_WORKFLOW_STAGES = 16


@dataclass(frozen=True)
class CharacterWorkflowPreview:
    object_id: str
    preset: str
    front_direction: str
    symmetry_tolerance: float
    face_fit_threshold: float
    recipe: str
    intensity: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "object_id",
                "preset",
                "front_direction",
                "symmetry_tolerance",
                "face_fit_threshold",
                "recipe",
                "intensity",
            },
        )
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _preset(data["preset"]),
            _front(data["front_direction"]),
            number(data["symmetry_tolerance"], "symmetry_tolerance", 1e-6, 100),
            number(data["face_fit_threshold"], "face_fit_threshold", 0.001, 2.0),
            _recipe(data["recipe"]),
            number(data["intensity"], "intensity", 0.05, 1.0),
        )


@dataclass(frozen=True)
class Level3Acceptance:
    object_id: str
    preset: str
    front_direction: str
    symmetry_tolerance: float
    face_fit_threshold: float
    recipe: str
    intensity: float

    @classmethod
    def parse(cls, data):
        action = CharacterWorkflowPreview.parse(data)
        return cls(
            action.object_id,
            action.preset,
            action.front_direction,
            action.symmetry_tolerance,
            action.face_fit_threshold,
            action.recipe,
            action.intensity,
        )


class CharacterAcceptanceOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.blockout = CharacterBlockoutOperations(objects)
        self.body = CharacterBodyOperations(objects)
        self.face = CharacterFaceOperations(objects)
        self.workflow = CharacterSculptWorkflowOperations(objects)
        self.remesh = SculptRemeshPlanningOperations(objects)

    @staticmethod
    def _request(operation):
        return Request(operation)

    def _evidence(self, action):
        landmark_fit = self.blockout.fit_landmarks(
            self._request("character.landmark_fit"),
            LandmarkFit(action.object_id, action.preset),
        ).data
        body_regions = self.body.body_regions(
            self._request("character.body_region_plan"),
            BodyRegionPlan(action.object_id, action.preset),
        ).data
        face_fit = self.face.fit(
            self._request("character.face_landmark_fit"),
            FaceFit(
                action.object_id,
                action.front_direction,
                action.face_fit_threshold,
            ),
        ).data
        face_regions = self.face.regions(
            self._request("character.face_region_plan"),
            FaceRegions(action.object_id, action.front_direction),
        ).data
        face_symmetry = self.face.symmetry(
            self._request("character.face_symmetry_audit"),
            FaceSymmetryAudit(
                action.object_id,
                action.front_direction,
                action.symmetry_tolerance,
            ),
        ).data
        sculpt_qa = self.workflow.qa(
            self._request("character.sculpt_qa"),
            CharacterSculptQA(action.object_id, action.symmetry_tolerance),
        ).data
        recipe = self.workflow.recipe_preview(
            self._request("character.sculpt_recipe_preview"),
            SculptRecipePreview(action.recipe, action.intensity),
        ).data
        surface = self.remesh.surface_snapshot(
            self._request("sculpt.surface_snapshot"),
            SurfaceSnapshot(action.object_id),
        ).data
        return {
            "landmark_fit": landmark_fit,
            "body_regions": body_regions,
            "face_fit": face_fit,
            "face_regions": face_regions,
            "face_symmetry": face_symmetry,
            "sculpt_qa": sculpt_qa,
            "recipe": recipe,
            "surface": surface,
        }

    @staticmethod
    def _gate(evidence):
        blockers = []
        advisories = []
        sculpt_qa = evidence["sculpt_qa"]
        face_fit = evidence["face_fit"]
        face_symmetry = evidence["face_symmetry"]

        if sculpt_qa["qa_status"] == "BLOCKED":
            blockers.extend(f"SCULPT_QA:{item}" for item in sculpt_qa["blockers"])
        elif sculpt_qa["qa_status"] == "REVIEW":
            advisories.extend(f"SCULPT_QA:{item}" for item in sculpt_qa["advisories"])

        if face_fit["rejected_count"]:
            advisories.append("FACE_LANDMARK_FIT_REVIEW")
        if face_symmetry["symmetry_status"] != "PASS":
            advisories.append("FACE_SYMMETRY_REVIEW")

        source_status = "BLOCKED" if blockers else ("REVIEW" if advisories else "READY")
        return source_status, sorted(set(blockers)), sorted(set(advisories))

    def preview(self, request: Request, action: CharacterWorkflowPreview):
        evidence = self._evidence(action)
        source_status, blockers, advisories = self._gate(evidence)
        stages = [
            {
                "stage": 1,
                "operation": "character.landmark_fit",
                "purpose": "fit body proportion landmark candidates",
                "mutation": False,
            },
            {
                "stage": 2,
                "operation": "character.body_region_plan",
                "purpose": "derive torso/limb/hand/foot sculpt regions",
                "mutation": False,
            },
            {
                "stage": 3,
                "operation": "character.face_landmark_fit",
                "purpose": "fit facial landmark candidates",
                "mutation": False,
            },
            {
                "stage": 4,
                "operation": "character.face_region_plan",
                "purpose": "derive facial sculpt regions",
                "mutation": False,
            },
            {
                "stage": 5,
                "operation": "character.face_symmetry_audit",
                "purpose": "review local-X facial candidate symmetry",
                "mutation": False,
            },
            {
                "stage": 6,
                "operation": "character.sculpt_qa",
                "purpose": "gate structural character sculpt readiness",
                "mutation": False,
            },
            {
                "stage": 7,
                "operation": "character.sculpt_recovery_snapshot",
                "purpose": "capture explicit coordinate patch before mutations",
                "mutation": False,
            },
            {
                "stage": 8,
                "operation": "character.sculpt_recipe_preview",
                "purpose": f"preview allowlisted {action.recipe} recipe",
                "mutation": False,
            },
            {
                "stage": 9,
                "operation": "typed recipe mutation tools",
                "purpose": "execute only with fresh object/geometry state per mutation",
                "mutation": True,
            },
            {
                "stage": 10,
                "operation": "character.sculpt_qa",
                "purpose": "re-run QA after each accepted mutation group",
                "mutation": False,
            },
            {
                "stage": 11,
                "operation": "character.sculpt_recovery_restore",
                "purpose": "restore bounded coordinate patch only when explicitly requested",
                "mutation": True,
            },
            {
                "stage": 12,
                "operation": "character.level3_acceptance",
                "purpose": "evaluate final source-side Level 3 acceptance gates",
                "mutation": False,
            },
        ]
        if len(stages) > MAX_WORKFLOW_STAGES:
            raise AssertionError("Character workflow stage budget exceeded")

        data = {
            "object_id": evidence["surface"]["object_id"],
            "name": evidence["surface"]["name"],
            "geometry_revision": evidence["surface"]["geometry_revision"],
            "preset": action.preset,
            "front_direction": action.front_direction,
            "recipe": action.recipe,
            "intensity": action.intensity,
            "source_gate_status": source_status,
            "blockers": blockers,
            "advisories": advisories,
            "stages": stages,
            "stage_count": len(stages),
            "recipe_steps": evidence["recipe"]["steps"],
            "fresh_state_required_per_mutation": True,
            "automatic_mutation_execution": False,
            "recovery_snapshot_required_before_mutation_group": True,
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
        }
        data["workflow_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def acceptance(self, request: Request, action: Level3Acceptance):
        evidence = self._evidence(action)
        source_status, blockers, advisories = self._gate(evidence)

        checks = [
            {
                "name": "BODY_LANDMARK_CANDIDATES",
                "status": (
                    "PASS"
                    if evidence["landmark_fit"]["landmark_count"] > 0
                    else "BLOCKED"
                ),
            },
            {
                "name": "BODY_REGION_PLAN",
                "status": (
                    "PASS" if evidence["body_regions"]["region_count"] == 17 else "BLOCKED"
                ),
            },
            {
                "name": "FACE_LANDMARK_FIT",
                "status": (
                    "PASS" if evidence["face_fit"]["rejected_count"] == 0 else "REVIEW"
                ),
            },
            {
                "name": "FACE_REGION_PLAN",
                "status": (
                    "PASS" if evidence["face_regions"]["region_count"] == 6 else "BLOCKED"
                ),
            },
            {
                "name": "FACE_SYMMETRY",
                "status": evidence["face_symmetry"]["symmetry_status"],
            },
            {
                "name": "STRUCTURAL_SCULPT_QA",
                "status": evidence["sculpt_qa"]["qa_status"],
            },
            {
                "name": "RECIPE_PREVIEW",
                "status": (
                    "PASS"
                    if evidence["recipe"]["step_count"] > 0
                    and evidence["recipe"]["automatic_execution"] is False
                    else "BLOCKED"
                ),
            },
            {
                "name": "SURFACE_BASELINE",
                "status": (
                    "PASS"
                    if evidence["surface"]["vertex_count"] > 0
                    and evidence["surface"]["face_count"] > 0
                    else "BLOCKED"
                ),
            },
        ]

        if any(item["status"] == "BLOCKED" for item in checks):
            source_status = "BLOCKED"
        elif any(item["status"] == "REVIEW" for item in checks) and source_status == "READY":
            source_status = "REVIEW"

        data = {
            "object_id": evidence["surface"]["object_id"],
            "name": evidence["surface"]["name"],
            "geometry_revision": evidence["surface"]["geometry_revision"],
            "preset": action.preset,
            "front_direction": action.front_direction,
            "recipe": action.recipe,
            "checks": checks,
            "check_count": len(checks),
            "blockers": blockers,
            "advisories": advisories,
            "source_acceptance_status": source_status,
            "source_level_complete_when_passed": 3,
            "source_scope": "LEVEL_3_SOURCE_AND_FAKE_ADAPTER_ACCEPTANCE_ONLY",
            "runtime_acceptance_required": True,
            "real_runtime_verified": False,
            "production_ready": False,
        }
        data["acceptance_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "character.workflow_preview",
                SafetyClass.READ_ONLY,
                CharacterWorkflowPreview.parse,
                self.preview,
            ),
            Tool(
                "character.level3_acceptance",
                SafetyClass.READ_ONLY,
                Level3Acceptance.parse,
                self.acceptance,
            ),
        ]
