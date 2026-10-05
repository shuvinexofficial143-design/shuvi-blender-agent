"""Fail-closed classification and preconditions independent of Blender."""

from dataclasses import dataclass
from enum import StrEnum

from .errors import AgentError, ErrorCode


class SafetyClass(StrEnum):
    READ_ONLY = "read_only"
    MUTATION = "mutation"
    DESTRUCTIVE = "destructive"
    FILE_WRITE = "file_write"


@dataclass(frozen=True)
class SafetyPolicy:
    allow_mutations: bool = False
    allow_destructive: bool = False
    allow_file_writes: bool = False

    def check(self, classification: SafetyClass) -> None:
        allowed = {
            SafetyClass.READ_ONLY: True,
            SafetyClass.MUTATION: self.allow_mutations,
            SafetyClass.DESTRUCTIVE: self.allow_mutations and self.allow_destructive,
            SafetyClass.FILE_WRITE: self.allow_file_writes,
        }
        if classification not in allowed or not allowed[classification]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Operation denied by execution policy")


def require_revision(expected: str, actual: str) -> None:
    if expected != actual:
        raise AgentError(ErrorCode.STALE_STATE, "Target changed since inspection; inspect again")
