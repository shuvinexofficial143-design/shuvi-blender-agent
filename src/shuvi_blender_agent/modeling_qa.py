"""Level 2 milestone 10: bounded modeling QA and recoverable workflow composition."""

from dataclasses import dataclass

from .contracts import Request, Result, Status, failure
from .errors import AgentError, ErrorCode
from .inspection import revision
from .modeling import topology_from_faces
from .modeling_modifier_workflows import ModelingModifierWorkflowOperations
from .modeling_repair import (
    CleanupFaces,
    MergeByDistance,
    ModelingRepairOperations,
    RemoveLooseVertices,
)
from .modeling_shading import ModelingShadingOperations, OrientFaces, _edge_orientation_diagnostics
from .models import ObjectTarget
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, number, string

WORKFLOWS = ("CLEAN_BASE_MESH", "CLEAN_ORIENT_BASE_MESH")


@dataclass(frozen=True)
class QAInspect:
    object_id: str
    distance: float
    area_epsilon: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "distance", "area_epsilon"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            number(data["distance"], "distance", 1e-9, 100),
            number(data["area_epsilon"], "area_epsilon", 0, 1_000_000),
        )


@dataclass(frozen=True)
class WorkflowPreview:
    object_id: str
    workflow: str
    distance: float
    area_epsilon: float

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "workflow", "distance", "area_epsilon"})
        workflow = data["workflow"]
        if not isinstance(workflow, str) or workflow not in WORKFLOWS:
            raise invalid("Unsupported modeling workflow")
        return cls(
            string(data["object_id"], "object_id", limit=128),
            workflow,
            number(data["distance"], "distance", 1e-9, 100),
            number(data["area_epsilon"], "area_epsilon", 0, 1_000_000),
        )


@dataclass(frozen=True)
class WorkflowApply:
    target: ObjectTarget
    expected_geometry_revision: str
    expected_qa_revision: str
    workflow: str
    distance: float
    area_epsilon: float

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_geometry_revision",
                "expected_qa_revision",
                "workflow",
                "distance",
                "area_epsilon",
            },
        )
        workflow = data["workflow"]
        if not isinstance(workflow, str) or workflow not in WORKFLOWS:
            raise invalid("Unsupported modeling workflow")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_geometry_revision"], "expected_geometry_revision", limit=64),
            string(data["expected_qa_revision"], "expected_qa_revision", limit=64),
            workflow,
            number(data["distance"], "distance", 1e-9, 100),
            number(data["area_epsilon"], "area_epsilon", 0, 1_000_000),
        )


class ModelingQAOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self.repair = ModelingRepairOperations(objects)
        self.shading = ModelingShadingOperations(objects)
        self.modifier_workflows = ModelingModifierWorkflowOperations(objects)

    def _qa_snapshot(self, obj, distance, area_epsilon):
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")

        object_state = self.inspector.snapshot(obj)
        repair = self.repair._repair_snapshot(obj, distance, area_epsilon)
        shading = self.shading.shading_snapshot(obj)
        topology = topology_from_faces(repair["faces"])
        users, _, _, _ = _edge_orientation_diagnostics(repair["faces"])
        high_degree = [list(edge) for edge in sorted(users) if len(users[edge]) > 2]
        valence = [0] * len(repair["vertices"])
        for a, b in topology["edges"]:
            valence[a] += 1
            valence[b] += 1
        boundary_vertices = {index for edge in topology["boundary_edges"] for index in edge}
        interior_poles = [
            index
            for index, value in enumerate(valence)
            if index not in boundary_vertices and value not in (0, 4)
        ]
        triangles = [index for index, face in enumerate(repair["faces"]) if len(face) == 3]
        quads = [index for index, face in enumerate(repair["faces"]) if len(face) == 4]
        ngons = [index for index, face in enumerate(repair["faces"]) if len(face) > 4]

        modifier_result = self.modifier_workflows.diagnose(
            Request(
                "modifier.stack_diagnose",
                {"object_id": object_state["object_id"]},
            ),
            object_state["object_id"],
        )
        modifiers = modifier_result.data

        blockers = []
        if repair["degenerate_face_count"]:
            blockers.append("DEGENERATE_FACES")
        if repair["duplicate_face_group_count"]:
            blockers.append("DUPLICATE_FACES")
        if repair["zero_length_edge_count"]:
            blockers.append("ZERO_LENGTH_EDGES")
        if high_degree:
            blockers.append("HIGH_DEGREE_NONMANIFOLD_EDGES")
        if shading["winding_conflict_edge_count"]:
            blockers.append("WINDING_CONFLICTS")
        if modifiers["missing_reference_indices"]:
            blockers.append("MISSING_MODIFIER_REFERENCES")
        if modifiers["unsupported_modifier_indices"]:
            blockers.append("UNSUPPORTED_MODIFIER_TYPES")

        advisories = []
        if repair["near_duplicate_vertex_group_count"]:
            advisories.append("NEAR_DUPLICATE_VERTICES")
        if repair["loose_vertex_count"]:
            advisories.append("LOOSE_VERTICES")
        if triangles:
            advisories.append("TRIANGLE_FACES_PRESENT")
        if ngons:
            advisories.append("NGON_FACES_PRESENT")
        advisories.extend(
            warning
            for warning in modifiers["warnings"]
            if warning not in ("UNSUPPORTED_MODIFIER_TYPES", "MISSING_OBJECT_REFERENCES")
        )

        data = {
            "object_id": object_state["object_id"],
            "name": object_state["name"],
            "object_revision": object_state["revision"],
            "geometry_revision": repair["geometry_revision"],
            "shading_revision": shading["shading_revision"],
            "stack_revision": modifiers["stack_revision"],
            "distance": distance,
            "area_epsilon": area_epsilon,
            "vertex_count": len(repair["vertices"]),
            "face_count": len(repair["faces"]),
            "edge_count": topology["edge_count"],
            "triangle_face_indices": triangles,
            "quad_face_indices": quads,
            "ngon_face_indices": ngons,
            "quad_ratio": len(quads) / len(repair["faces"]) if repair["faces"] else 0.0,
            "interior_pole_vertex_indices": interior_poles,
            "near_duplicate_vertex_groups": repair["near_duplicate_vertex_groups"],
            "near_duplicate_vertex_group_count": repair["near_duplicate_vertex_group_count"],
            "duplicate_face_groups": repair["duplicate_face_groups"],
            "duplicate_face_group_count": repair["duplicate_face_group_count"],
            "degenerate_face_indices": repair["degenerate_face_indices"],
            "degenerate_face_count": repair["degenerate_face_count"],
            "loose_vertex_indices": repair["loose_vertex_indices"],
            "loose_vertex_count": repair["loose_vertex_count"],
            "zero_length_edges": repair["zero_length_edges"],
            "zero_length_edge_count": repair["zero_length_edge_count"],
            "boundary_edge_count": repair["boundary_edge_count"],
            "high_degree_nonmanifold_edges": high_degree,
            "high_degree_nonmanifold_edge_count": len(high_degree),
            "winding_conflict_edges": shading["winding_conflict_edges"],
            "winding_conflict_edge_count": shading["winding_conflict_edge_count"],
            "modifier_diagnostics": {
                "count": modifiers["count"],
                "type_counts": modifiers["type_counts"],
                "unsupported_modifier_indices": modifiers["unsupported_modifier_indices"],
                "missing_reference_indices": modifiers["missing_reference_indices"],
                "subsurf_before_bevel_pairs": modifiers["subsurf_before_bevel_pairs"],
                "disabled_viewport_indices": modifiers["disabled_viewport_indices"],
                "disabled_render_indices": modifiers["disabled_render_indices"],
                "complexity_score": modifiers["complexity_score"],
            },
            "blockers": blockers,
            "advisories": advisories,
            "qa_status": "BLOCKED" if blockers else ("REVIEW" if advisories else "CLEAN"),
        }
        data["qa_revision"] = revision(
            {
                "object_revision": data["object_revision"],
                "geometry_revision": data["geometry_revision"],
                "shading_revision": data["shading_revision"],
                "stack_revision": data["stack_revision"],
                "distance": distance,
                "area_epsilon": area_epsilon,
                "blockers": blockers,
                "advisories": advisories,
            }
        )
        return data

    def inspect(self, request: Request, action: QAInspect):
        obj = self.inspector.resolve(action.object_id)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._qa_snapshot(obj, action.distance, action.area_epsilon),
        )

    @staticmethod
    def _preview_steps(qa, workflow):
        steps = []
        if qa["near_duplicate_vertex_group_count"]:
            steps.append("mesh.merge_by_distance")
        if qa["degenerate_face_count"] or qa["duplicate_face_group_count"]:
            steps.append("mesh.cleanup_faces")
        if qa["loose_vertex_count"]:
            steps.append("mesh.remove_loose_vertices")
        if workflow == "CLEAN_ORIENT_BASE_MESH" and qa["winding_conflict_edge_count"]:
            steps.append("mesh.orient_faces_consistently")
        return steps

    def preview(self, request: Request, action: WorkflowPreview):
        obj = self.inspector.resolve(action.object_id)
        qa = self._qa_snapshot(obj, action.distance, action.area_epsilon)
        steps = self._preview_steps(qa, action.workflow)
        data = {
            "workflow": action.workflow,
            "qa_revision": qa["qa_revision"],
            "geometry_revision": qa["geometry_revision"],
            "initial_qa_status": qa["qa_status"],
            "initial_blockers": qa["blockers"],
            "initial_advisories": qa["advisories"],
            "initial_planned_steps": steps,
            "re_evaluate_after_each_step": True,
            "no_op": not steps,
        }
        data["workflow_revision"] = revision(
            {
                "workflow": action.workflow,
                "qa_revision": qa["qa_revision"],
                "steps": steps,
                "distance": action.distance,
                "area_epsilon": action.area_epsilon,
            }
        )
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _restore_initial(self, obj, geometry, smooth):
        self.repair._replace_geometry(obj.data, geometry["vertices"], geometry["faces"])
        self.repair._restore_smooth_flags(obj, smooth)
        self.bpy.context.view_layer.update()
        restored = self.repair.meshes.snapshot(obj)
        restored_smooth = self.repair._smooth_flags(obj)
        return (
            restored["vertices"] == geometry["vertices"]
            and restored["faces"] == geometry["faces"]
            and restored_smooth == smooth
        )

    @staticmethod
    def _fresh_target(inspector, obj):
        return ObjectTarget.from_snapshot(inspector.snapshot(obj))

    def _run_step(self, operation, method, action):
        result = method(Request(operation), action)
        if result.status == Status.FAILED:
            raise result.error
        if result.status != Status.VERIFIED:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Workflow step did not return verified readback",
            )
        return {
            "operation": operation,
            "status": result.status.value,
            "verification_matched": result.verification["matched"],
        }

    def apply(self, request: Request, action: WorkflowApply):
        obj, object_before, initial_geometry = self.repair._editable_rebuild_mesh(action)
        initial_smooth = self.repair._smooth_flags(obj)
        initial_qa = self._qa_snapshot(obj, action.distance, action.area_epsilon)
        require_revision(action.expected_qa_revision, initial_qa["qa_revision"])
        require_revision(
            action.expected_geometry_revision,
            initial_qa["geometry_revision"],
        )
        initial_steps = self._preview_steps(initial_qa, action.workflow)
        if not initial_steps:
            raise invalid("Modeling workflow has no changes to apply")

        executed = []
        try:
            current = self.repair._repair_snapshot(obj, action.distance, action.area_epsilon)
            if current["near_duplicate_vertex_group_count"]:
                executed.append(
                    self._run_step(
                        "mesh.merge_by_distance",
                        self.repair.merge_by_distance,
                        MergeByDistance(
                            self._fresh_target(self.inspector, obj),
                            current["geometry_revision"],
                            action.distance,
                        ),
                    )
                )

            current = self.repair._repair_snapshot(obj, action.distance, action.area_epsilon)
            if current["degenerate_face_count"] or current["duplicate_face_group_count"]:
                executed.append(
                    self._run_step(
                        "mesh.cleanup_faces",
                        self.repair.cleanup_faces,
                        CleanupFaces(
                            self._fresh_target(self.inspector, obj),
                            current["geometry_revision"],
                            action.area_epsilon,
                            True,
                        ),
                    )
                )

            current = self.repair._repair_snapshot(obj, action.distance, action.area_epsilon)
            if current["loose_vertex_count"]:
                executed.append(
                    self._run_step(
                        "mesh.remove_loose_vertices",
                        self.repair.remove_loose_vertices,
                        RemoveLooseVertices(
                            self._fresh_target(self.inspector, obj),
                            current["geometry_revision"],
                        ),
                    )
                )

            if action.workflow == "CLEAN_ORIENT_BASE_MESH":
                shading = self.shading.shading_snapshot(obj)
                if shading["winding_conflict_edge_count"]:
                    executed.append(
                        self._run_step(
                            "mesh.orient_faces_consistently",
                            self.shading.orient_faces_consistently,
                            OrientFaces(
                                self._fresh_target(self.inspector, obj),
                                shading["geometry_revision"],
                                shading["shading_revision"],
                            ),
                        )
                    )

            final_qa = self._qa_snapshot(obj, action.distance, action.area_epsilon)
            after = {
                "workflow": action.workflow,
                "executed_steps": executed,
                "executed_step_count": len(executed),
                "geometry_revision": final_qa["geometry_revision"],
                "qa_revision": final_qa["qa_revision"],
                "qa_status": final_qa["qa_status"],
                "qa": final_qa,
                "recovery": {"performed": False, "verified": True},
            }
            expected_qa = {
                "near_duplicate_vertex_group_count": 0,
                "duplicate_face_group_count": 0,
                "degenerate_face_count": 0,
                "loose_vertex_count": 0,
                "zero_length_edge_count": 0,
            }
            if action.workflow == "CLEAN_ORIENT_BASE_MESH":
                expected_qa["winding_conflict_edge_count"] = 0
            expected = {
                "workflow": action.workflow,
                "executed_steps": executed,
                "executed_step_count": len(executed),
                "qa": expected_qa,
                "recovery": {"performed": False, "verified": True},
            }
            result = self.objects._result(
                request,
                {
                    "object": object_before,
                    "geometry": initial_geometry,
                    "face_smooth": initial_smooth,
                    "qa": initial_qa,
                },
                after,
                expected,
            )
            if result.status == Status.FAILED:
                recovered = self._restore_initial(
                    obj,
                    initial_geometry,
                    initial_smooth,
                )
                result.data["rolled_back"] = recovered
                result.data["recovery_verified"] = recovered
                if not recovered:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "Workflow verification and recovery both failed",
                    )
            return result
        except AgentError as exc:
            recovered = self._restore_initial(obj, initial_geometry, initial_smooth)
            if not recovered:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Workflow failed and initial mesh recovery could not be verified",
                ) from exc
            return failure(
                request,
                exc,
                data={
                    "outcome": "known",
                    "rolled_back": True,
                    "recovery_verified": True,
                    "executed_steps": executed,
                },
            )
        except Exception as exc:
            recovered = self._restore_initial(obj, initial_geometry, initial_smooth)
            if not recovered:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Workflow failed and initial mesh recovery could not be verified",
                ) from exc
            return failure(
                request,
                AgentError(
                    ErrorCode.EXECUTION_ERROR,
                    "Workflow failed but initial mesh state was restored",
                ),
                data={
                    "outcome": "known",
                    "rolled_back": True,
                    "recovery_verified": True,
                    "executed_steps": executed,
                },
            )

    def tools(self):
        return [
            Tool(
                "modeling.qa_inspect",
                SafetyClass.READ_ONLY,
                QAInspect.parse,
                self.inspect,
            ),
            Tool(
                "modeling.workflow_preview",
                SafetyClass.READ_ONLY,
                WorkflowPreview.parse,
                self.preview,
            ),
            Tool(
                "modeling.workflow_apply",
                SafetyClass.MUTATION,
                WorkflowApply.parse,
                self.apply,
            ),
        ]
