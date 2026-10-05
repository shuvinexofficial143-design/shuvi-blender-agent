import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Result, Status
from shuvi_blender_agent.client import BlenderController
from shuvi_blender_agent.models import ObjectTarget, Transform
from shuvi_blender_agent.plans import Binding, Plan, PlanRunner, PlanStep
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.service import create_registry


class RegistryTransport:
    def __init__(self, registry):
        self.registry = registry
        self.calls = []

    def call(self, request):
        self.calls.append(request.operation)
        return self.registry.dispatch(request)


def setup(mutations=True):
    bpy = fake_bpy()
    transport = RegistryTransport(create_registry(bpy, SafetyPolicy(allow_mutations=mutations)))
    return bpy, transport, BlenderController(transport)


def plan(name="New"):
    return Plan(
        (
            PlanStep("scene", Request("scene.inspect")),
            PlanStep(
                "create",
                Request(
                    "object.create",
                    {
                        "name": name,
                        "kind": "CUBE",
                        "transform": {
                            "location": [0, 0, 0],
                            "rotation_euler": [0, 0, 0],
                            "scale": [1, 1, 1],
                        },
                        "expected_scene_revision": None,
                    },
                ),
                (Binding("scene", ("data", "revision"), ("expected_scene_revision",)),),
            ),
            PlanStep(
                "inspect",
                Request("object.inspect", {"object_id": None}),
                (Binding("create", ("data", "after", "object_id"), ("object_id",)),),
            ),
        )
    )


def test_capability_catalog_and_typed_client():
    bpy, _, controller = setup()
    catalog = controller.capabilities()
    assert catalog["object.create"]["enabled"]
    assert not catalog["render.execute"]["enabled"]
    assert len(catalog) == 22
    scene = controller.inspect_scene()
    assert scene.data["object_count"] == 2
    snap = controller.list_objects().data["items"][0]
    result = controller.set_transform(
        ObjectTarget.from_snapshot(snap), Transform((1, 2, 3), (0, 0, 0), (1, 1, 1))
    )
    assert result.status == Status.VERIFIED
    assert tuple(bpy.data.objects.get("Cube").location) == (1, 2, 3)


def test_declarative_inspect_create_inspect_plan():
    bpy, transport, controller = setup()
    source = plan()
    assert Plan.from_dict(source.to_dict()) == source
    report = PlanRunner(controller).run(source)
    assert report.completed
    assert report.results["create"].status == Status.VERIFIED
    assert report.results["inspect"].data["name"] == "New"
    assert bpy.data.objects.get("New") is not None
    assert transport.calls == [
        "system.capabilities",
        "scene.inspect",
        "object.create",
        "object.inspect",
    ]


def test_plan_fail_fast_and_no_retry():
    _, transport, controller = setup()
    report = PlanRunner(controller).run(plan("Cube"))
    assert not report.completed
    assert report.results["create"].error.code == ErrorCode.AMBIGUOUS_TARGET
    assert "inspect" not in report.results
    assert transport.calls.count("object.create") == 1


def test_denied_or_unknown_operations_preflight_before_mutation():
    _, transport, controller = setup(mutations=False)
    with pytest.raises(AgentError) as error:
        PlanRunner(controller).run(plan())
    assert error.value.code == ErrorCode.SAFETY_DENIED
    assert transport.calls == ["system.capabilities"]
    with pytest.raises(AgentError):
        PlanRunner(controller).run(Plan((PlanStep("code", Request("exec", {"code": "anything"})),)))


def test_forward_references_and_duplicate_commands_rejected():
    with pytest.raises(AgentError):
        Plan(
            (
                PlanStep(
                    "first", Request("system.ping"), (Binding("future", ("data", "ready"), ("x",)),)
                ),
            )
        )
    request = Request("system.ping")
    with pytest.raises(AgentError):
        Plan((PlanStep("a", request), PlanStep("b", request)))


def test_invalid_reference_stops_without_dispatching_mutation():
    _, transport, controller = setup()
    bad = Plan(
        (
            PlanStep("scene", Request("scene.inspect")),
            PlanStep(
                "next",
                Request("object.inspect", {"object_id": None}),
                (Binding("scene", ("data", "missing"), ("object_id",)),),
            ),
        )
    )
    report = PlanRunner(controller).run(bad)
    assert not report.completed
    assert report.results["next"].error.code == ErrorCode.INVALID_REQUEST
    assert "object.inspect" not in transport.calls


def test_unverified_mutation_response_rejected_by_controller():
    _, transport, controller = setup()
    controller.capabilities()
    transport.call = lambda req: Result(req.request_id, req.command_id, Status.SUCCEEDED)
    result = controller.execute(Request("object.create", {}))
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
