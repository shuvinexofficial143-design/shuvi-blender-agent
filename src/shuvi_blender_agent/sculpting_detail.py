"""Level 3 milestone 4: bounded subdivision sculpt-detail planning and level controls."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .modeling_hardsurface import HardSurfaceOperations, ModifierUpdate, StackAdd
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, string

MAX_SCULPT_SUBDIV_LEVEL = 3
MAX_ESTIMATED_FACES = 250_000


def _estimate_faces(base_faces, level):
    return base_faces * (4**level)


@dataclass(frozen=True)
class DetailPlan:
    object_id: str
    viewport_level: int
    render_level: int

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id", "viewport_level", "render_level"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            integer(data["viewport_level"], "viewport_level", 0, MAX_SCULPT_SUBDIV_LEVEL),
            integer(data["render_level"], "render_level", 0, MAX_SCULPT_SUBDIV_LEVEL),
        )


@dataclass(frozen=True)
class SubdivisionSetup:
    target: ObjectTarget
    expected_stack_revision: str
    name: str
    viewport_level: int
    render_level: int

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_stack_revision",
                "name",
                "viewport_level",
                "render_level",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            integer(data["viewport_level"], "viewport_level", 0, MAX_SCULPT_SUBDIV_LEVEL),
            integer(data["render_level"], "render_level", 0, MAX_SCULPT_SUBDIV_LEVEL),
        )


@dataclass(frozen=True)
class SubdivisionLevels:
    target: ObjectTarget
    expected_stack_revision: str
    name: str
    viewport_level: int
    render_level: int

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_stack_revision",
                "name",
                "viewport_level",
                "render_level",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_stack_revision"], "expected_stack_revision", limit=64),
            object_name(data["name"]),
            integer(data["viewport_level"], "viewport_level", 0, MAX_SCULPT_SUBDIV_LEVEL),
            integer(data["render_level"], "render_level", 0, MAX_SCULPT_SUBDIV_LEVEL),
        )


class SculptDetailOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.hard = HardSurfaceOperations(objects)

    def plan(self, request: Request, action: DetailPlan):
        obj = self.inspector.resolve(action.object_id)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        base_faces = len(obj.data.polygons)
        viewport_faces = _estimate_faces(base_faces, action.viewport_level)
        render_faces = _estimate_faces(base_faces, action.render_level)
        if max(viewport_faces, render_faces) > MAX_ESTIMATED_FACES:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Requested subdivision estimate exceeds sculpt detail work limit",
            )
        stack = self.hard.stack_snapshot(obj)
        subsurf = [item for item in stack["items"] if item["type"] == "SUBSURF"]
        data = {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "base_face_count": base_faces,
            "requested_viewport_level": action.viewport_level,
            "requested_render_level": action.render_level,
            "estimated_viewport_face_count": viewport_faces,
            "estimated_render_face_count": render_faces,
            "estimate_model": "BASE_FACES_X_4_POW_LEVEL",
            "stack_revision": stack["stack_revision"],
            "existing_subsurf_entries": subsurf,
            "existing_subsurf_count": len(subsurf),
            "multires_runtime_required": True,
            "multires_source_status": "PLANNING_ONLY",
        }
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def setup(self, request: Request, action: SubdivisionSetup):
        obj, _ = self.hard._mesh_target(action.target)
        before = self.hard.stack_snapshot(obj)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        if before["count"] != 0:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Sculpt subdivision setup requires an empty modifier stack",
            )
        plan = self.plan(
            Request("sculpt.detail_plan"),
            DetailPlan(
                self.inspector.identity(obj),
                action.viewport_level,
                action.render_level,
            ),
        ).data
        result = self.hard.add_stack_modifier(
            request,
            StackAdd(
                action.target,
                action.expected_stack_revision,
                action.name,
                "SUBSURF",
                {
                    "levels": action.viewport_level,
                    "render_levels": action.render_level,
                },
            ),
        )
        result.data.setdefault("after", {}).update(
            {
                "sculpt_detail_mode": "SUBSURF_PREVIEW",
                "estimated_viewport_face_count": plan["estimated_viewport_face_count"],
                "estimated_render_face_count": plan["estimated_render_face_count"],
                "multires_runtime_required": True,
            }
        )
        return result

    def set_levels(self, request: Request, action: SubdivisionLevels):
        obj, _ = self.hard._mesh_target(action.target)
        before = self.hard.stack_snapshot(obj)
        require_revision(action.expected_stack_revision, before["stack_revision"])
        modifier = obj.modifiers.get(action.name)
        if modifier is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Subdivision modifier not found")
        if modifier.type != "SUBSURF":
            raise AgentError(ErrorCode.STALE_STATE, "Named modifier is not SUBSURF")
        plan = self.plan(
            Request("sculpt.detail_plan"),
            DetailPlan(
                self.inspector.identity(obj),
                action.viewport_level,
                action.render_level,
            ),
        ).data
        result = self.hard.update_modifier(
            request,
            ModifierUpdate(
                action.target,
                action.expected_stack_revision,
                action.name,
                "SUBSURF",
                {
                    "levels": action.viewport_level,
                    "render_levels": action.render_level,
                },
            ),
        )
        result.data.setdefault("after", {}).update(
            {
                "sculpt_detail_mode": "SUBSURF_PREVIEW",
                "estimated_viewport_face_count": plan["estimated_viewport_face_count"],
                "estimated_render_face_count": plan["estimated_render_face_count"],
                "multires_runtime_required": True,
            }
        )
        return result

    def tools(self):
        return [
            Tool("sculpt.detail_plan", SafetyClass.READ_ONLY, DetailPlan.parse, self.plan),
            Tool(
                "sculpt.subdivision_setup",
                SafetyClass.MUTATION,
                SubdivisionSetup.parse,
                self.setup,
            ),
            Tool(
                "sculpt.subdivision_set_levels",
                SafetyClass.MUTATION,
                SubdivisionLevels.parse,
                self.set_levels,
            ),
        ]
