"""Stable machine-readable errors shared by clients and execution adapters."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    NOT_FOUND = "not_found"
    AMBIGUOUS_TARGET = "ambiguous_target"
    STALE_STATE = "stale_state"
    SAFETY_DENIED = "safety_denied"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    EXECUTION_ERROR = "execution_error"
    VERIFICATION_FAILED = "verification_failed"
    BLENDER_NOT_FOUND = "blender_not_found"


class AgentError(Exception):
    """Predictable public failure. Retryability never grants automatic mutation retries."""

    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False):
        if (
            not isinstance(code, ErrorCode)
            or not isinstance(message, str)
            or not 1 <= len(message) <= 512
            or "\x00" in message
            or type(retryable) is not bool
        ):
            raise ValueError("Invalid public error")
        try:
            message.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Invalid public error encoding") from exc
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message, "retryable": self.retryable}

    @classmethod
    def from_dict(cls, data: dict) -> "AgentError":
        if set(data) != {"code", "message", "retryable"}:
            raise ValueError("Invalid error fields")
        if not isinstance(data["message"], str) or type(data["retryable"]) is not bool:
            raise ValueError("Invalid error values")
        return cls(ErrorCode(data["code"]), data["message"], retryable=data["retryable"])
