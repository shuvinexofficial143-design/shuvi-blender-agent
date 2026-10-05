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
    assert len(catalog) == 23
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
    result = controller.execute(
        Request(
            "object.create",
            {**plan().steps[1].request.payload, "expected_scene_revision": "revision"},
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED


def test_all_execution_tools_match_host_contracts():
    from shuvi_blender_agent.input_contracts import builtin_contracts

    _, transport, _ = setup()
    contracts = builtin_contracts()
    assert set(contracts) == {item["name"] for item in transport.registry.catalog()}
    for item in transport.registry.catalog():
        assert contracts[item["name"]][0].value == item["classification"]


def test_catalog_metadata_is_exposed_validated_and_independently_copied():
    _, _, controller = setup()
    catalog = controller.capabilities()
    assert catalog["file.checkpoint"]["file_write_permission_required"]
    assert catalog["render.execute"]["render_permission_required"]
    assert catalog["object.create"]["verification_required"]
    assert catalog["object.create"]["runtime_required"]
    assert not catalog["system.ping"]["runtime_required"]
    catalog["object.create"]["payload_fields"].append("bad")
    assert "bad" not in controller.capabilities()["object.create"]["payload_fields"]


def test_more_than_256_total_bindings_rejected():
    steps = [PlanStep("source", Request("system.ping"))]
    for i in range(17):
        payload = {f"value{k}": None for k in range(16)}
        bindings = tuple(Binding("source", ("data", "ready"), (key,)) for key in payload)
        steps.append(PlanStep(f"step{i}", Request("system.ping", payload), bindings))
    with pytest.raises(AgentError) as error:
        Plan(tuple(steps))
    assert error.value.code == ErrorCode.INVALID_REQUEST


def test_plan_aggregate_payload_limit_precedes_execution():
    with pytest.raises(AgentError):
        Plan(
            tuple(
                PlanStep(f"step{i}", Request("system.ping", {"value": "x" * 40000}))
                for i in range(32)
            )
        )


@pytest.mark.parametrize("dest", [("missing",), ("items", "0"), ("items", -1)])
def test_invalid_destination_is_rejected_before_any_execution(dest):
    with pytest.raises(AgentError):
        Plan(
            (
                PlanStep("first", Request("system.ping")),
                PlanStep(
                    "next",
                    Request("object.inspect", {"items": [None]}),
                    (Binding("first", ("data", "ready"), dest),),
                ),
            )
        )


def test_overlapping_destinations_and_request_id_reuse_rejected():
    with pytest.raises(AgentError):
        Plan(
            (
                PlanStep("first", Request("system.ping")),
                PlanStep(
                    "next",
                    Request("object.inspect", {"target": {"name": None}}),
                    (
                        Binding("first", ("data", "ready"), ("target",)),
                        Binding("first", ("data", "ready"), ("target", "name")),
                    ),
                ),
            )
        )
    with pytest.raises(AgentError):
        Plan(
            (
                PlanStep("a", Request("system.ping", request_id="same")),
                PlanStep("b", Request("system.ping", request_id="same")),
            )
        )


def test_unbound_bad_payload_preflight_prevents_earlier_execution():
    _, transport, controller = setup()
    with pytest.raises(AgentError):
        PlanRunner(controller).run(
            Plan(
                (
                    PlanStep("first", Request("scene.inspect")),
                    PlanStep("bad", Request("object.create", {})),
                )
            )
        )
    assert transport.calls == ["system.capabilities"]


def test_transport_failure_keeps_partial_report_and_unknown_outcome():
    bpy, transport, controller = setup()
    original = transport.call

    def disconnect(request):
        if request.operation == "object.create":
            original(request)
            raise AgentError(ErrorCode.TRANSPORT_ERROR, "Bridge disconnected")
        return original(request)

    transport.call = disconnect
    source = plan()
    report = PlanRunner(controller).run(source)
    assert bpy.data.objects.get("New") is not None
    assert not report.completed
    assert report.unexecuted_steps == ("inspect",)
    assert report.to_dict()["outcome_unknown"]
    assert report.results["create"].request_id == source.steps[1].request.request_id
    assert report.results["create"].command_id == source.steps[1].request.command_id
    assert report.results["create"].error.code == ErrorCode.TRANSPORT_ERROR


def test_total_deadline_includes_capabilities_and_stops_before_dispatch(monkeypatch):
    _, transport, controller = setup()
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr("shuvi_blender_agent.plans.time.monotonic", lambda: next(ticks))
    report = PlanRunner(controller).run(
        Plan((PlanStep("ping", Request("system.ping")),), timeout_ms=1)
    )
    assert not report.completed
    assert report.results["ping"].error.code == ErrorCode.TIMEOUT
    assert transport.calls == ["system.capabilities"]


def test_plan_result_budget_stops_before_another_dispatch(monkeypatch):
    _, transport, controller = setup()
    monkeypatch.setattr("shuvi_blender_agent.plans.MAX_PLAN_RESULT_BYTES", 1_048_576)
    report = PlanRunner(controller).run(
        Plan(
            (
                PlanStep("a", Request("system.ping")),
                PlanStep("b", Request("system.ping")),
            )
        )
    )
    assert not report.completed
    assert report.results["b"].error.code == ErrorCode.SAFETY_DENIED
    assert transport.calls.count("system.ping") == 1


def test_catalog_cannot_downgrade_mutation_classification():
    _, transport, controller = setup()
    original = transport.call

    def downgrade(request):
        result = original(request)
        for item in result.data["operations"]:
            if item["name"] == "object.create":
                item["classification"] = "read_only"
        return result

    transport.call = downgrade
    with pytest.raises(AgentError) as error:
        controller.capabilities()
    assert error.value.code == ErrorCode.TRANSPORT_ERROR
    assert controller._catalog is None
