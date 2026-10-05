"""Bounded declarative execution, separate from AI planning and model providers."""

import copy
import time
from dataclasses import dataclass, field, replace

from .client import BlenderController
from .contracts import Request, Result, Status, failure
from .errors import AgentError, ErrorCode
from .validation import MAX_MESSAGE_BYTES, encode, fields, integer, invalid, string

MAX_PLAN_RESULT_BYTES = 4 * MAX_MESSAGE_BYTES


def path(value) -> tuple:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 8:
        raise invalid("Reference paths require 1..8 components")
    for part in value:
        if type(part) is int:
            integer(part, "path index", 0, 4096)
        else:
            string(part, "path key", limit=128)
    return tuple(value)


def read_path(data, keys):
    try:
        for key in keys:
            if isinstance(data, dict) and isinstance(key, str):
                data = data[key]
            elif isinstance(data, list) and type(key) is int:
                data = data[key]
            else:
                raise KeyError(key)
        return copy.deepcopy(data)
    except (IndexError, KeyError) as exc:
        raise invalid("Reference path does not exist") from exc


@dataclass(frozen=True)
class Binding:
    source_step: str
    source_path: tuple
    target_path: tuple

    def __post_init__(self):
        string(self.source_step, "source_step", limit=80)
        path(self.source_path)
        path(self.target_path)

    @classmethod
    def from_dict(cls, data):
        fields(data, {"source_step", "source_path", "target_path"})
        return cls(data["source_step"], path(data["source_path"]), path(data["target_path"]))

    def to_dict(self):
        return {
            "source_step": self.source_step,
            "source_path": list(self.source_path),
            "target_path": list(self.target_path),
        }


@dataclass(frozen=True)
class PlanStep:
    name: str
    request: Request
    bindings: tuple[Binding, ...] = ()

    def __post_init__(self):
        string(self.name, "step name", limit=80)
        if not isinstance(self.request, Request) or len(self.bindings) > 16:
            raise invalid("Request and at most 16 bindings required")
        if any(not isinstance(binding, Binding) for binding in self.bindings):
            raise invalid("Invalid plan binding")


@dataclass(frozen=True)
class Plan:
    steps: tuple[PlanStep, ...]
    timeout_ms: int = 120_000

    def __post_init__(self):
        integer(self.timeout_ms, "plan timeout", 1, 120_000)
        if not 1 <= len(self.steps) <= 32:
            raise invalid("Plan requires 1..32 steps")
        seen = set()
        command_ids = set()
        request_ids = set()
        bindings = 0
        for step in self.steps:
            if not isinstance(step, PlanStep) or step.name in seen:
                raise invalid("Plan step names must be unique")
            if step.request.command_id in command_ids:
                raise invalid("Plan command IDs must be unique")
            if step.request.request_id in request_ids:
                raise invalid("Plan request IDs must be unique")
            if any(binding.source_step not in seen for binding in step.bindings):
                raise invalid("References must point to an earlier step")
            seen.add(step.name)
            command_ids.add(step.request.command_id)
            request_ids.add(step.request.request_id)
            bindings += len(step.bindings)
            destinations = [binding.target_path for binding in step.bindings]
            for index, destination in enumerate(destinations):
                read_path(step.request.payload, destination)
                for other in destinations[:index]:
                    if (
                        destination[: len(other)] == other
                        or other[: len(destination)] == destination
                    ):
                        raise invalid("Binding destinations must not overlap")
        if bindings > 256:
            raise invalid("Plan exceeds 256 total bindings")
        encode(self.to_dict())

    def to_dict(self):
        return {
            "timeout_ms": self.timeout_ms,
            "steps": [
                {
                    "name": step.name,
                    "request": step.request.to_dict(),
                    "bindings": [b.to_dict() for b in step.bindings],
                }
                for step in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, data):
        fields(data, {"steps"}, {"timeout_ms"})
        encode(data)
        if not isinstance(data["steps"], list) or not 1 <= len(data["steps"]) <= 32:
            raise invalid("Plan requires 1..32 steps")
        steps = []
        for item in data["steps"]:
            fields(item, {"name", "request"}, {"bindings"})
            bindings = item.get("bindings", [])
            if not isinstance(bindings, list) or len(bindings) > 16:
                raise invalid("Invalid binding list")
            steps.append(
                PlanStep(
                    item["name"],
                    Request.from_bytes(encode(item["request"])),
                    tuple(Binding.from_dict(binding) for binding in bindings),
                )
            )
        return cls(tuple(steps), data.get("timeout_ms", 120_000))


@dataclass(frozen=True)
class PlanReport:
    completed: bool
    results: dict[str, Result] = field(default_factory=dict)
    unexecuted_steps: tuple[str, ...] = ()

    def to_dict(self):
        return {
            "completed": self.completed,
            "results": {name: result.to_dict() for name, result in self.results.items()},
            "unexecuted_steps": list(self.unexecuted_steps),
            "outcome_unknown": any(
                result.data.get("outcome") == "unknown" for result in self.results.values()
            ),
        }


class PlanRunner:
    def __init__(self, controller: BlenderController):
        self.controller = controller

    def run(self, plan: Plan) -> PlanReport:
        plan = Plan.from_dict(plan.to_dict())
        started = time.monotonic()
        self.controller.capabilities(timeout_ms=min(plan.timeout_ms, 10_000))
        # Reject unavailable/denied operation names before executing any plan step.
        for step in plan.steps:
            self.controller.validate_operation(step.request.operation)
            if not step.bindings:
                self.controller.validate_payload(step.request)
        results = {}
        result_bytes = 0
        for index, step in enumerate(plan.steps):
            request = step.request
            try:
                remaining = int(plan.timeout_ms - (time.monotonic() - started) * 1000)
                if remaining < 1:
                    raise AgentError(ErrorCode.TIMEOUT, "Plan deadline exceeded before dispatch")
                if result_bytes + MAX_MESSAGE_BYTES > MAX_PLAN_RESULT_BYTES:
                    raise AgentError(
                        ErrorCode.SAFETY_DENIED, "Plan result budget exhausted before dispatch"
                    )
                payload = copy.deepcopy(request.payload)
                for binding in step.bindings:
                    value = read_path(results[binding.source_step].to_dict(), binding.source_path)
                    parent = payload
                    if len(binding.target_path) > 1:
                        # Read returns a copy, so traverse the destination separately.
                        for key in binding.target_path[:-1]:
                            read_path(parent, (key,))
                            parent = parent[key]
                    final = binding.target_path[-1]
                    read_path(parent, (final,))
                    parent[final] = value
                request = replace(
                    request, payload=payload, timeout_ms=min(request.timeout_ms, remaining)
                )
                result = self.controller.execute(request)
                if (
                    time.monotonic() - started
                ) * 1000 >= plan.timeout_ms and result.status != Status.FAILED:
                    result = failure(
                        request,
                        AgentError(ErrorCode.TIMEOUT, "Plan deadline exceeded after response"),
                        data={"outcome": "known", "completed_status": result.status.value},
                    )
            except AgentError as exc:
                result = failure(request, exc)
            except (IndexError, KeyError, TypeError):
                result = failure(request, invalid("Invalid destination reference path"))
            results[step.name] = result
            result_bytes += len(result.to_bytes())
            if result.status == Status.FAILED:
                return PlanReport(
                    False, results, tuple(item.name for item in plan.steps[index + 1 :])
                )
        return PlanReport(True, results)
