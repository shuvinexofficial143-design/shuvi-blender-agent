"""Versioned envelopes. Operation payloads are validated by the tool registry."""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from .errors import AgentError, ErrorCode
from .validation import decode, encode, fields, integer, invalid, string

PROTOCOL_VERSION = 1


class Status(StrEnum):
    SUCCEEDED = "succeeded"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True)
class Request:
    operation: str
    payload: dict = field(default_factory=dict)
    timeout_ms: int = 10_000
    request_id: str = field(default_factory=lambda: str(uuid4()))
    command_id: str = field(default_factory=lambda: str(uuid4()))
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        integer(self.protocol_version, "protocol_version", 1, 1)
        string(self.operation, "operation", limit=80)
        string(self.request_id, "request_id", limit=128)
        string(self.command_id, "command_id", limit=128)
        integer(self.timeout_ms, "timeout_ms", 1, 120_000)
        fields(self.payload, set(), set(self.payload) if isinstance(self.payload, dict) else set())
        encode(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "command_id": self.command_id,
            "operation": self.operation,
            "payload": self.payload,
            "timeout_ms": self.timeout_ms,
        }

    def to_bytes(self) -> bytes:
        return encode(self.to_dict())

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Request":
        data = decode(raw)
        fields(
            data,
            {"protocol_version", "request_id", "command_id", "operation", "payload", "timeout_ms"},
        )
        if type(data["protocol_version"]) is not int or data["protocol_version"] != 1:
            raise AgentError(ErrorCode.PROTOCOL_MISMATCH, "Unsupported protocol version")
        return cls(**data)


@dataclass(frozen=True)
class Result:
    request_id: str
    command_id: str
    status: Status
    data: dict = field(default_factory=dict)
    error: AgentError | None = None
    verification: dict | None = None
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        integer(self.protocol_version, "protocol_version", 1, 1)
        string(self.request_id, "request_id", limit=128)
        string(self.command_id, "command_id", limit=128)
        if not isinstance(self.status, Status):
            raise invalid("Invalid result status")
        fields(self.data, set(), set(self.data) if isinstance(self.data, dict) else set())
        if self.error is not None and not isinstance(self.error, AgentError):
            raise invalid("Invalid structured error")
        if (self.status == Status.FAILED) != (self.error is not None):
            raise invalid("Failed results require an error; successful results cannot have one")
        if self.status == Status.VERIFIED:
            if (
                not isinstance(self.verification, dict)
                or self.verification.get("matched") is not True
            ):
                raise invalid("Verified results require matching readback evidence")
        encode(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "command_id": self.command_id,
            "status": self.status.value,
            "data": self.data,
            "error": self.error.to_dict() if self.error else None,
            "verification": self.verification,
        }

    def to_bytes(self) -> bytes:
        return encode(self.to_dict())

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Result":
        data = decode(raw)
        fields(
            data,
            {
                "protocol_version",
                "request_id",
                "command_id",
                "status",
                "data",
                "error",
                "verification",
            },
        )
        if (
            type(data["protocol_version"]) is not int
            or data["protocol_version"] != PROTOCOL_VERSION
        ):
            raise AgentError(ErrorCode.PROTOCOL_MISMATCH, "Unsupported protocol version")
        try:
            data["status"] = Status(data["status"])
            if data["error"] is not None:
                data["error"] = AgentError.from_dict(data["error"])
            return cls(**data)
        except (ValueError, TypeError, KeyError) as exc:
            raise invalid("Malformed result") from exc


def failure(request: Request, error: AgentError, *, data: dict | None = None) -> Result:
    return Result(request.request_id, request.command_id, Status.FAILED, data or {}, error)
