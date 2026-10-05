"""Typed importable host facade. Never imports bpy or a model provider."""

import json
from dataclasses import asdict, is_dataclass
from typing import Protocol

from .contracts import Request, Result, Status, failure
from .errors import AgentError, ErrorCode
from .models import CreateObject, ObjectTarget, PageQuery, SetTransform, Transform
from .safety import SafetyClass
from .verification import compare


class Transport(Protocol):
    def call(self, request: Request) -> Result: ...


class BlenderController:
    def __init__(self, transport: Transport):
        self.transport = transport
        self._catalog: dict | None = None

    def capabilities(self) -> dict:
        if self._catalog is None:
            request = Request("system.capabilities")
            result = self.transport.call(request)
            self._correlate(request, result)
            if result.status != Status.SUCCEEDED:
                raise result.error or AgentError(
                    ErrorCode.TRANSPORT_ERROR, "Capabilities unavailable"
                )
            try:
                catalog = result.data["operations"]
                if not isinstance(catalog, list) or not 1 <= len(catalog) <= 128:
                    raise ValueError("Invalid catalog")
                self._catalog = {}
                for item in catalog:
                    if type(item["enabled"]) is not bool:
                        raise ValueError("Invalid capability permission")
                    classification = SafetyClass(item["classification"])
                    if item["name"] in self._catalog:
                        raise ValueError("Duplicate capability")
                    self._catalog[item["name"]] = {
                        "enabled": item["enabled"],
                        "classification": classification,
                    }
            except (ValueError, KeyError, TypeError) as exc:
                self._catalog = None
                raise AgentError(ErrorCode.TRANSPORT_ERROR, "Malformed capability catalog") from exc
        return {name: dict(spec) for name, spec in self._catalog.items()}

    def validate_operation(self, name: str) -> SafetyClass:
        spec = self.capabilities().get(name)
        if spec is None:
            raise AgentError(ErrorCode.UNSUPPORTED_OPERATION, "Operation not advertised by Blender")
        if not spec["enabled"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Operation disabled by session policy")
        return spec["classification"]

    @staticmethod
    def _correlate(request: Request, result: Result) -> None:
        Result.from_bytes(result.to_bytes())
        if (request.request_id, request.command_id) != (result.request_id, result.command_id):
            raise AgentError(ErrorCode.TRANSPORT_ERROR, "Response correlation failed")

    def execute(self, request: Request) -> Result:
        request = Request.from_bytes(request.to_bytes())
        classification = self.validate_operation(request.operation)
        result = self.transport.call(request)
        self._correlate(request, result)
        if classification != SafetyClass.READ_ONLY and result.status != Status.FAILED:
            evidence = result.verification
            if (
                result.status != Status.VERIFIED
                or not isinstance(evidence, dict)
                or not isinstance(evidence.get("expected"), dict)
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

    def submit(self, operation: str, action) -> Result:
        if not is_dataclass(action) or isinstance(action, type):
            raise AgentError(ErrorCode.INVALID_REQUEST, "Typed action instance required")
        # Dataclass tuples are normalized to JSON arrays; the execution parser revalidates.
        payload = json.loads(json.dumps(asdict(action), allow_nan=False))
        return self.execute(Request(operation, payload))

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
