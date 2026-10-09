"""Explicit allowlist: a tool couples a typed parser with a classified executor."""

from collections.abc import Callable
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as model_fields
from typing import Any

from .contracts import Request, Result, Status, failure
from .errors import AgentError, ErrorCode
from .safety import SafetyClass, SafetyPolicy
from .validation import fields, string
from .verification import compare

MAX_REGISTERED_TOOLS = 265


@dataclass(frozen=True)
class Tool:
    name: str
    classification: SafetyClass
    parse: Callable[[dict], Any]
    execute: Callable[[Request, Any], Result]

    def __post_init__(self):
        string(self.name, "tool name", limit=80)
        if (
            not isinstance(self.classification, SafetyClass)
            or not callable(self.parse)
            or not callable(self.execute)
        ):
            raise ValueError("A tool requires a known classification, parser and executor")


class ToolRegistry:
    def __init__(self, tools: list[Tool], policy: SafetyPolicy | None = None):
        self.policy = policy or SafetyPolicy()
        if len(tools) > MAX_REGISTERED_TOOLS:
            raise ValueError("Registry limit exceeded")
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Duplicate tool names")

    def dispatch(self, request: Request) -> Result:
        dispatched = False
        tool = None
        try:
            # Revalidate even when a caller mutated a dict inside the frozen envelope.
            request = Request.from_bytes(request.to_bytes())
            tool = self._tools.get(request.operation)
            if tool is None:
                raise AgentError(ErrorCode.UNSUPPORTED_OPERATION, "Operation is not allowlisted")
            self.policy.check(tool.classification)
            payload = tool.parse(request.payload)
            dispatched = True
            result = tool.execute(request, payload)
            result = Result.from_bytes(result.to_bytes())
            if (result.request_id, result.command_id) != (request.request_id, request.command_id):
                raise AgentError(ErrorCode.EXECUTION_ERROR, "Executor returned uncorrelated result")
            if tool.classification != SafetyClass.READ_ONLY and result.status != Status.FAILED:
                evidence = result.verification
                if (
                    result.status != Status.VERIFIED
                    or not isinstance(evidence, dict)
                    or not isinstance(evidence.get("expected"), dict)
                    or not evidence["expected"]
                    or not isinstance(evidence.get("actual"), dict)
                    or not compare(evidence["expected"], evidence["actual"]).matched
                ):
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Mutation lacks matching actual readback"
                    )
            return result
        except AgentError as exc:
            uncertain = (
                dispatched
                and tool.classification != SafetyClass.READ_ONLY
                and exc.code
                in (ErrorCode.EXECUTION_ERROR, ErrorCode.TIMEOUT, ErrorCode.VERIFICATION_FAILED)
            )
            return failure(
                request,
                exc,
                data={"outcome": "unknown", "inspect_before_retry": True} if uncertain else None,
            )
        except Exception:
            # Never send internal tracebacks or arbitrary exception strings over the bridge.
            return failure(
                request,
                AgentError(
                    ErrorCode.EXECUTION_ERROR, "Executor failed; inspect state before retry"
                ),
                data={"outcome": "unknown", "inspect_before_retry": True}
                if dispatched and tool.classification != SafetyClass.READ_ONLY
                else None,
            )

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools or len(self._tools) >= MAX_REGISTERED_TOOLS:
            raise ValueError("Duplicate tool or registry limit exceeded")
        self._tools[tool.name] = tool

    def catalog(self) -> list[dict]:
        result = []
        for tool in sorted(self._tools.values(), key=lambda tool: tool.name):
            enabled = True
            try:
                self.policy.check(tool.classification)
            except AgentError:
                enabled = False
            model = getattr(tool.parse, "__self__", None)
            payload_fields = (
                [item.name for item in model_fields(model)] if is_dataclass(model) else None
            )
            result.append(
                {
                    "name": tool.name,
                    "classification": tool.classification.value,
                    "enabled": enabled,
                    "payload_fields": payload_fields,
                    "verification_required": tool.classification != SafetyClass.READ_ONLY,
                    "runtime_required": tool.name != "system.ping",
                    "file_write_permission_required": tool.classification
                    in (SafetyClass.FILE_WRITE, SafetyClass.RENDER),
                    "render_permission_required": tool.classification == SafetyClass.RENDER,
                }
            )
        return result


def ping_tool() -> Tool:
    def execute(request: Request, _: dict) -> Result:
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, {"ready": True})

    return Tool("system.ping", SafetyClass.READ_ONLY, lambda data: fields(data, set()), execute)
