"""Strict bounded JSON validation used at every external boundary."""

import json
import math
from typing import Any

from .errors import AgentError, ErrorCode

MAX_MESSAGE_BYTES = 1_048_576


def invalid(message: str) -> AgentError:
    return AgentError(ErrorCode.INVALID_REQUEST, message)


def fields(data: Any, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise invalid("Expected a JSON object")
    optional = optional or set()
    if not required <= data.keys() or data.keys() - required - optional:
        raise invalid(f"Expected fields {sorted(required)}; optional {sorted(optional)}")
    return data


def string(value: Any, name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= limit or "\x00" in value:
        raise invalid(f"{name} must be a nonempty string of at most {limit} characters")
    return value


def integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise invalid(f"{name} must be an integer in [{low}, {high}]")
    return value


def number(value: Any, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise invalid(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


def json_value(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise invalid("JSON nesting exceeds 32 levels")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            json_value(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            json_value(item, depth + 1)
        return
    raise invalid("Value must be finite JSON data with string keys")


def encode(data: dict) -> bytes:
    json_value(data)
    try:
        raw = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise invalid("Invalid JSON data") from exc
    if len(raw) > MAX_MESSAGE_BYTES:
        raise invalid("Message exceeds size limit")
    return raw


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise invalid(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def decode(raw: bytes) -> dict:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise invalid("Message exceeds size limit")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
        fields(data, set(), set(data) if isinstance(data, dict) else set())
        json_value(data)
        return data
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise invalid("Malformed JSON message") from exc
