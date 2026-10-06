"""Typed importable host facade. Never imports bpy or a model provider."""

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from typing import Protocol

from .contracts import Request, Result, Status, failure
from .errors import AgentError, ErrorCode
from .input_contracts import builtin_contracts
from .models import CreateObject, ObjectTarget, PageQuery, SetTransform, Transform
from .safety import SafetyClass
from .tools import MAX_REGISTERED_TOOLS
from .validation import integer, string
from .verification import compare


class Transport(Protocol):
    def call(self, request: Request) -> Result: ...


class BlenderController:
    def __init__(self, transport: Transport):
        self.transport = transport
        self._catalog: dict | None = None

    def capabilities(self, *, timeout_ms: int = 10_000) -> dict:
        if self._catalog is None:
            request = Request("system.capabilities", timeout_ms=timeout_ms)
            try:
                result = self.transport.call(request)
                result = self._correlate(request, result)
            except AgentError:
                raise
            except Exception as exc:
                raise AgentError(ErrorCode.TRANSPORT_ERROR, "Capability transport failed") from exc
            if result.status != Status.SUCCEEDED:
                raise result.error or AgentError(
                    ErrorCode.TRANSPORT_ERROR, "Capabilities unavailable"
                )
            try:
                catalog = result.data["operations"]
                if not isinstance(catalog, list) or not 1 <= len(catalog) <= MAX_REGISTERED_TOOLS:
                    raise ValueError("Invalid catalog")
                parsed = {}
                contracts = builtin_contracts()
                integer(result.data["protocol_version"], "protocol_version", 1, 1)
                string(result.data["session_id"], "session_id", limit=128)
                for item in catalog:
                    name = string(item["name"], "capability name", limit=80)
                    if type(item["enabled"]) is not bool:
                        raise ValueError("Invalid capability permission")
                    classification = SafetyClass(item["classification"])
                    if name in parsed or name not in contracts:
                        raise ValueError("Duplicate capability")
                    if classification != contracts[name][0]:
                        raise ValueError("Capability safety class mismatch")
                    parsed[name] = {
                        "enabled": item["enabled"],
                        "classification": classification,
                    }
                    metadata = {
                        "verification_required": classification != SafetyClass.READ_ONLY,
                        "runtime_required": name != "system.ping",
                        "file_write_permission_required": classification
                        in (SafetyClass.FILE_WRITE, SafetyClass.RENDER),
                        "render_permission_required": classification == SafetyClass.RENDER,
                    }
                    for key, expected in metadata.items():
                        if key in item and (type(item[key]) is not bool or item[key] != expected):
                            raise ValueError("Capability metadata mismatch")
                    payload_fields = item.get("payload_fields")
                    if payload_fields is not None:
                        if not isinstance(payload_fields, list) or len(payload_fields) > 32:
                            raise ValueError("Invalid payload fields")
                        payload_fields = [
                            string(value, "payload field", limit=128) for value in payload_fields
                        ]
                    parsed[name].update(metadata | {"payload_fields": payload_fields})
                self._catalog = parsed
            except (AgentError, ValueError, KeyError, TypeError) as exc:
                self._catalog = None
                raise AgentError(ErrorCode.TRANSPORT_ERROR, "Malformed capability catalog") from exc
        return deepcopy(self._catalog)

    def validate_operation(self, name: str) -> SafetyClass:
        spec = self.capabilities().get(name)
        if spec is None:
            raise AgentError(ErrorCode.UNSUPPORTED_OPERATION, "Operation not advertised by Blender")
        if not spec["enabled"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Operation disabled by session policy")
        return spec["classification"]

    @staticmethod
    def _correlate(request: Request, result: Result) -> Result:
        result = Result.from_bytes(result.to_bytes())
        if (request.request_id, request.command_id) != (result.request_id, result.command_id):
            raise AgentError(ErrorCode.TRANSPORT_ERROR, "Response correlation failed")
        return result

    def execute(self, request: Request) -> Result:
        request = Request.from_bytes(request.to_bytes())
        classification = self.validate_operation(request.operation)
        try:
            self.validate_payload(request)
        except AgentError as exc:
            return failure(request, exc)
        try:
            result = self.transport.call(request)
            result = self._correlate(request, result)
        except AgentError as exc:
            return failure(request, exc, data={"outcome": "unknown", "inspect_before_retry": True})
        except Exception:
            return failure(
                request,
                AgentError(ErrorCode.TRANSPORT_ERROR, "Transport failed"),
                data={"outcome": "unknown", "inspect_before_retry": True},
            )
        if classification != SafetyClass.READ_ONLY and result.status != Status.FAILED:
            evidence = result.verification
            if (
                result.status != Status.VERIFIED
                or not isinstance(evidence, dict)
                or not isinstance(evidence.get("expected"), dict)
                or not evidence["expected"]
                or not isinstance(evidence.get("actual"), dict)
                or not compare(evidence["expected"], evidence["actual"]).matched
            ):
                return failure(
                    request,
                    AgentError(
                        ErrorCode.VERIFICATION_FAILED,
                        "Mutation response lacks matching actual evidence",
                    ),
                    data=result.data,
                )
        return result

    def validate_payload(self, request: Request) -> None:
        contract = builtin_contracts().get(request.operation)
        if contract is None:
            raise AgentError(ErrorCode.UNSUPPORTED_OPERATION, "Unknown host payload contract")
        contract[1](request.payload)

    def list_collections(self, query: PageQuery | None = None) -> Result:
        return self.submit("collections.list", query or PageQuery())

    def submit(self, operation: str, action) -> Result:
        if not is_dataclass(action) or isinstance(action, type):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Typed action instance required")
        # Dataclass tuples are normalized to JSON arrays; the execution parser revalidates.
        return self.execute(Request(operation, asdict(action)))

    def inspect_scene(self) -> Result:
        return self.execute(Request("scene.inspect"))

    def list_objects(self, query: PageQuery | None = None) -> Result:
        return self.submit("objects.list", query or PageQuery())

    def inspect_object(self, object_id: str) -> Result:
        return self.execute(Request("object.inspect", {"object_id": object_id}))

    def create_object(self, action: CreateObject) -> Result:
        return self.submit("object.create", action)

    def set_transform(self, target: ObjectTarget, transform: Transform) -> Result:
        return self.submit("object.set_transform", SetTransform(target, transform))
