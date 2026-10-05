"""Fail-closed classification and preconditions independent of Blender."""

from dataclasses import dataclass
from enum import StrEnum

from .errors import AgentError, ErrorCode


class SafetyClass(StrEnum):
    READ_ONLY = "read_only"
    MUTATION = "mutation"
    DESTRUCTIVE = "destructive"
    FILE_WRITE = "file_write"
    RENDER = "render"


@dataclass(frozen=True)
class SafetyPolicy:
    allow_mutations: bool = False
    allow_destructive: bool = False
    allow_file_writes: bool = False
    allow_rendering: bool = False

    def __post_init__(self):
        if any(
            type(value) is not bool
            for value in (
                self.allow_mutations,
                self.allow_destructive,
                self.allow_file_writes,
                self.allow_rendering,
            )
        ):
            raise ValueError("Safety permissions must be explicit booleans")

    def check(self, classification: SafetyClass) -> None:
        allowed = {
            SafetyClass.READ_ONLY: True,
            SafetyClass.MUTATION: self.allow_mutations,
            SafetyClass.DESTRUCTIVE: self.allow_mutations and self.allow_destructive,
            SafetyClass.FILE_WRITE: self.allow_file_writes,
            SafetyClass.RENDER: self.allow_mutations
            and self.allow_file_writes
            and self.allow_rendering,
        }
        if classification not in allowed or not allowed[classification]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Operation denied by execution policy")


def require_revision(expected: str, actual: str) -> None:
    if expected != actual:
        raise AgentError(ErrorCode.STALE_STATE, "Target changed since inspection; inspect again")
