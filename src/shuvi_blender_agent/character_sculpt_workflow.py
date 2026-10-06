"""Level 3 milestone 9: bounded character sculpt QA, recipes and recovery helpers."""

from dataclasses import dataclass

from .character_body import BodySymmetryAudit, CharacterBodyOperations
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, vector3
from .operations import ObjectOperations
from .safety import SafetyClass
from .sculpting import SculptingOperations
from .tools import Tool
from .validation import fields, integer, invalid, number, string

RECIPES = ("BODY_PRIMARY_FORMS", "FACE_PRIMARY_FORMS", "HAND_FOOT_REFINEMENT")
MAX_RECOVERY_VERTICES = 512


def _recipe(value):
    if not isinstance(value, str) or value not in RECIPES:
        raise invalid(
            "recipe must be BODY_PRIMARY_FORMS, FACE_PRIMARY_FORMS or HAND_FOOT_REFINEMENT"
        )
    return value


def _indices(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_RECOVERY_VERTICES:
        raise invalid(f"vertex_indices requires 1..{MAX_RECOVERY_VERTICES} entries")
    result = []
    seen = set()
    for item in value:
        index = integer(item, "vertex_index", 0, 1_000_000)
        if index in seen:
            raise invalid("vertex_indices must be unique")
        seen.add(index)
        result.append(index)
    return tuple(result)


def _restore_entries(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_RECOVERY_VERTICES:
        raise invalid(f"entries requires 1..{MAX_RECOVERY_VERTICES} restore entries")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise invalid("Recovery entry must be an object")
        fields(item, {"vertex_index", "restore_position"})
        index = integer(item["vertex_index"], "vertex_index", 0, 1_000_000)
        if index in seen:
            raise invalid("Recovery vertex indices must be unique")
        seen.add(index)
        result.append(
            {
                "vertex_index": index,
                "restore_position": vector3(
                    item["restore_position"],
                    "restore_position",
                    1_000_000,
                ),
            }
        )
    return tuple(result)


def _topology_revision(geometry):
    return revision(
        {
            "vertex_count": len(geometry["vertices"]),
            "faces": geometry["faces"],
        }
    )


@dataclass(frozen=True)
class CharacterSculptQA:
    object_id: str
    symmetry_tolerance: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "symmetry_tolerance"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            number(data["symmetry_tolerance"], "symmetry_tolerance", 1e-6, 100),
        )


@dataclass(frozen=True)
class SculptRecipePreview:
    recipe: str
    intensity: float

    @classmethod
    def parse(cls, data):
        fields(data, {"recipe", "intensity"})
        return cls(
            _recipe(data["recipe"]),
            number(data["intensity"], "intensity", 0.05, 1.0),
        )


@dataclass(frozen=True)
class RecoverySnapshot:
    object_id: str
    vertex_indices: tuple[int, ...]

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "vertex_indices"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            _indices(data["vertex_indices"]),
        )


@dataclass(frozen=True)
class RecoveryRestore:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_topology_revision: str
    entries: tuple[dict, ...]

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_topology_revision",
                "entries",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_topology_revision"], "expected_topology_revision", limit=64),
            _restore_entries(data["entries"]),
        )


class CharacterSculptWorkflowOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.sculpt = SculptingOperations(objects)
        self.body = CharacterBodyOperations(objects)

    def qa(self, request: Request, action: CharacterSculptQA):
        sculpt_result = self.sculpt.inspect(
            Request("sculpt.inspect"),
            action.object_id,
        )
        symmetry_result = self.body.symmetry(
            Request("character.body_symmetry_audit"),
            BodySymmetryAudit(action.object_id, action.symmetry_tolerance),
        )
        sculpt = sculpt_result.data
        symmetry = symmetry_result.data

        blockers = []
        advisories = []
        if sculpt["face_count"] == 0:
            blockers.append("NO_FACES")
        if sculpt["degenerate_face_count"]:
            blockers.append("DEGENERATE_FACES")
        if sculpt["invalid_normal_vertex_count"]:
            blockers.append("INVALID_VERTEX_NORMALS")
        if not sculpt["sculpt_ready"]:
            blockers.append("BASE_MESH_NOT_SCULPT_READY")
        if sculpt["boundary_vertex_count"]:
            advisories.append("OPEN_BOUNDARY_PRESENT")
        if symmetry["symmetry_status"] != "PASS":
            advisories.append("LOCAL_X_SYMMETRY_REVIEW")

        status = "BLOCKED" if blockers else ("REVIEW" if advisories else "PASS")
        data = {
            "object_id": sculpt["object_id"],
            "name": sculpt["name"],
            "geometry_revision": sculpt["geometry_revision"],
            "symmetry_tolerance": action.symmetry_tolerance,
            "sculpt": {
                "vertex_count": sculpt["vertex_count"],
                "face_count": sculpt["face_count"],
                "edge_count": sculpt["edge_count"],
                "boundary_vertex_count": sculpt["boundary_vertex_count"],
                "nonmanifold_edge_count": sculpt["nonmanifold_edge_count"],
                "degenerate_face_count": sculpt["degenerate_face_count"],
                "invalid_normal_vertex_count": sculpt["invalid_normal_vertex_count"],
                "sculpt_ready": sculpt["sculpt_ready"],
            },
            "symmetry": {
                "positive_vertex_count": symmetry["positive_vertex_count"],
                "negative_vertex_count": symmetry["negative_vertex_count"],
                "plane_vertex_count": symmetry["plane_vertex_count"],
                "unmatched_positive_indices": symmetry["unmatched_positive_indices"],
                "unmatched_negative_indices": symmetry["unmatched_negative_indices"],
                "collision_pairs": symmetry["collision_pairs"],
                "symmetry_status": symmetry["symmetry_status"],
            },
            "blockers": blockers,
            "advisories": advisories,
            "qa_status": status,
            "qa_scope": "STRUCTURAL_BASE_MESH_CHARACTER_QA_ONLY",
        }
        data["qa_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def recipe_preview(self, request: Request, action: SculptRecipePreview):
        intensity = action.intensity
        if action.recipe == "BODY_PRIMARY_FORMS":
            steps = [
                {
                    "tool": "character.body_region_plan",
                    "purpose": "derive torso/limb sculpt regions",
                },
                {
                    "tool": "sculpt.brush_grab_controlled",
                    "purpose": "adjust primary masses with local-X symmetry",
                    "suggested_strength": intensity,
                },
                {
                    "tool": "sculpt.brush_smooth",
                    "purpose": "relax primary transitions",
                    "suggested_strength": intensity * 0.45,
                },
            ]
        elif action.recipe == "FACE_PRIMARY_FORMS":
            steps = [
                {
                    "tool": "character.face_region_plan",
                    "purpose": "derive eye/nose/mouth/jaw/brow regions",
                },
                {
                    "tool": "sculpt.brush_grab_controlled",
                    "purpose": "place primary facial forms symmetrically",
                    "suggested_strength": intensity * 0.75,
                },
                {
                    "tool": "sculpt.brush_crease",
                    "purpose": "define selected primary facial separations",
                    "suggested_strength": intensity * 0.35,
                },
                {
                    "tool": "sculpt.brush_smooth",
                    "purpose": "blend primary facial transitions",
                    "suggested_strength": intensity * 0.30,
                },
            ]
        else:
            steps = [
                {
                    "tool": "character.extremity_guide",
                    "purpose": "derive hand/foot landmark reference",
                },
                {
                    "tool": "sculpt.brush_grab_controlled",
                    "purpose": "place major extremity silhouette",
                    "suggested_strength": intensity * 0.65,
                },
                {
                    "tool": "sculpt.brush_pinch",
                    "purpose": "refine digit/toe separation zones",
                    "suggested_strength": intensity * 0.30,
                },
                {
                    "tool": "sculpt.brush_smooth",
                    "purpose": "blend extremity transitions",
                    "suggested_strength": intensity * 0.25,
                },
            ]

        data = {
            "recipe": action.recipe,
            "intensity": intensity,
            "steps": steps,
            "step_count": len(steps),
            "execution_status": "PREVIEW_ONLY",
            "requires_fresh_state_per_mutation": True,
            "automatic_execution": False,
        }
        data["recipe_revision"] = revision(data)
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def recovery_snapshot(self, request: Request, action: RecoverySnapshot):
        obj = self.inspector.resolve(action.object_id)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        geometry = self.sculpt.meshes.snapshot(obj)
        entries = []
        for index in action.vertex_indices:
            if index >= len(geometry["vertices"]):
                raise invalid("Recovery snapshot vertex index does not exist")
            entries.append(
                {
                    "vertex_index": index,
                    "restore_position": list(geometry["vertices"][index]),
                }
            )
        data = {
            "object_id": geometry["object_id"],
            "name": geometry["name"],
            "geometry_revision": geometry["geometry_revision"],
            "topology_revision": _topology_revision(geometry),
            "entries": entries,
            "entry_count": len(entries),
            "snapshot_scope": "BOUNDED_VERTEX_COORDINATE_PATCH",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def recovery_restore(self, request: Request, action: RecoveryRestore):
        obj, object_before, before = self.sculpt._editable_mesh(action)
        topology_revision = _topology_revision(before)
        if topology_revision != action.expected_topology_revision:
            raise AgentError(
                ErrorCode.STALE_STATE,
                "Recovery topology revision does not match current mesh topology",
            )

        vertices = [list(vertex) for vertex in before["vertices"]]
        changed = []
        for entry in action.entries:
            index = entry["vertex_index"]
            if index >= len(vertices):
                raise invalid("Recovery restore vertex index does not exist")
            vertices[index] = list(entry["restore_position"])
            changed.append(index)

        evidence = {
            "recovery": "VERTEX_COORDINATE_PATCH",
            "topology_revision": topology_revision,
            "restored_vertex_indices": sorted(changed),
            "restored_vertex_count": len(changed),
        }
        return self.sculpt._verified_coordinate_mutation(
            request,
            obj,
            object_before,
            before,
            vertices,
            evidence,
            sorted(changed),
        )

    def tools(self):
        return [
            Tool(
                "character.sculpt_qa",
                SafetyClass.READ_ONLY,
                CharacterSculptQA.parse,
                self.qa,
            ),
            Tool(
                "character.sculpt_recipe_preview",
                SafetyClass.READ_ONLY,
                SculptRecipePreview.parse,
                self.recipe_preview,
            ),
            Tool(
                "character.sculpt_recovery_snapshot",
                SafetyClass.READ_ONLY,
                RecoverySnapshot.parse,
                self.recovery_snapshot,
            ),
            Tool(
                "character.sculpt_recovery_restore",
                SafetyClass.MUTATION,
                RecoveryRestore.parse,
                self.recovery_restore,
            ),
        ]
