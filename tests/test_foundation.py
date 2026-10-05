import json
import sys

import pytest

from shuvi_blender_agent import AgentError, ErrorCode, Request, Result, Status
from shuvi_blender_agent.safety import SafetyClass, SafetyPolicy, require_revision
from shuvi_blender_agent.tools import Tool, ToolRegistry, ping_tool
from shuvi_blender_agent.validation import MAX_MESSAGE_BYTES, decode, encode, number, string


def test_import_has_no_blender_dependency():
    assert "bpy" not in sys.modules


def test_request_and_result_roundtrip():
    request = Request("system.ping")
    assert Request.from_bytes(request.to_bytes()) == request
    result = ToolRegistry([ping_tool()]).dispatch(request)
    assert result.status == Status.SUCCEEDED
    assert Result.from_bytes(result.to_bytes()) == result


@pytest.mark.parametrize(
    "change",
    [
        {"timeout_ms": True},
        {"timeout_ms": 0},
        {"timeout_ms": 120001},
        {"request_id": ""},
        {"operation": "x" * 81},
        {"payload": []},
        {"payload": {"value": float("nan")}},
        {"payload": {1: "value"}},
    ],
)
def test_invalid_envelopes(change):
    with pytest.raises(AgentError):
        Request(**({"operation": "system.ping"} | change))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b"[]",
        b"not json",
        b"\xff",
        b" " * (MAX_MESSAGE_BYTES + 1),
        b'{"x":' + b"[" * 40 + b"0" + b"]" * 40 + b"}",
    ],
    ids=["duplicate", "nan", "array", "syntax", "encoding", "oversize", "depth"],
)
def test_reject_bad_json(raw):
    with pytest.raises(AgentError):
        decode(raw)


def test_protocol_and_unknown_fields():
    data = Request("system.ping").to_dict()
    data["protocol_version"] = 2
    with pytest.raises(AgentError) as failure:
        Request.from_bytes(json.dumps(data).encode())
    assert failure.value.code == ErrorCode.PROTOCOL_MISMATCH
    data["protocol_version"] = 1
    data["code"] = "print('unsafe')"
    with pytest.raises(AgentError):
        Request.from_bytes(json.dumps(data).encode())


def test_registry_rejects_arbitrary_code_and_payloads():
    registry = ToolRegistry([ping_tool()])
    assert registry.dispatch(Request("exec", {"code": "x"})).error.code == (
        ErrorCode.UNSUPPORTED_OPERATION
    )
    assert registry.dispatch(Request("system.ping", {"code": "x"})).error.code == (
        ErrorCode.INVALID_REQUEST
    )


def test_fail_closed_safety_and_stale_state():
    for classification in SafetyClass:
        if classification != SafetyClass.READ_ONLY:
            with pytest.raises(AgentError):
                SafetyPolicy().check(classification)
    with pytest.raises(AgentError) as failure:
        require_revision("before", "changed")
    assert failure.value.code == ErrorCode.STALE_STATE
    require_revision("same", "same")


def test_mutation_without_readback_cannot_succeed():
    tool = Tool(
        "edit",
        SafetyClass.MUTATION,
        lambda data: data,
        lambda req, _: Result(req.request_id, req.command_id, Status.SUCCEEDED),
    )
    result = ToolRegistry([tool], SafetyPolicy(allow_mutations=True)).dispatch(Request("edit"))
    assert result.error.code == ErrorCode.VERIFICATION_FAILED


def test_executor_failure_is_sanitized():
    def crash(req, payload):
        raise RuntimeError("secret internal path")

    result = ToolRegistry(
        [Tool("crash", SafetyClass.READ_ONLY, lambda data: data, crash)]
    ).dispatch(Request("crash"))
    assert result.error.code == ErrorCode.EXECUTION_ERROR
    assert b"secret" not in result.to_bytes()


def test_success_invariants():
    with pytest.raises(AgentError):
        Result("r", "c", Status.VERIFIED)
    with pytest.raises(AgentError):
        Result("r", "c", Status.FAILED)
    error = AgentError(ErrorCode.TIMEOUT, "Timed out")
    original = Result("r", "c", Status.FAILED, error=error)
    assert Result.from_bytes(original.to_bytes()).error.code == ErrorCode.TIMEOUT


def test_oversized_numbers_and_unicode_are_structured_errors():
    with pytest.raises(AgentError):
        number(10**1000, "coordinate", -1_000_000, 1_000_000)
    with pytest.raises(AgentError):
        string("\ud800", "name")
    with pytest.raises(AgentError):
        Request("system.ping", {"value": 2**65})


def test_json_work_and_serialized_size_limits():
    for payload in ({"items": [None] * 65_536}, {"text": "\u2603" * 200_000}):
        with pytest.raises(AgentError):
            encode(payload)
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(AgentError):
        encode(cyclic)
    with pytest.raises(AgentError):
        decode(b'{"value":"\\ud800"}')


@pytest.mark.parametrize(
    "evidence",
    [
        {"matched": True},
        {"matched": True, "expected": {}, "actual": {}},
        {"matched": True, "expected": {"location": [1, 2, 3]}, "actual": {"location": [9, 2, 3]}},
    ],
)
def test_claimed_verification_requires_matching_nonempty_evidence(evidence):
    tool = Tool(
        "edit",
        SafetyClass.MUTATION,
        lambda data: data,
        lambda req, _: Result(
            req.request_id, req.command_id, Status.VERIFIED, verification=evidence
        ),
    )
    result = ToolRegistry([tool], SafetyPolicy(allow_mutations=True)).dispatch(Request("edit"))
    assert result.error.code == ErrorCode.VERIFICATION_FAILED


def test_initial_registry_has_same_bound_as_registration():
    tools = [
        Tool(f"tool{i}", SafetyClass.READ_ONLY, lambda data: data, lambda req, data: None)
        for i in range(129)
    ]
    with pytest.raises(ValueError):
        ToolRegistry(tools)


def test_result_protocol_mismatch_is_explicit():
    data = Result("request", "command", Status.SUCCEEDED).to_dict()
    data["protocol_version"] = 2
    with pytest.raises(AgentError) as error:
        Result.from_bytes(json.dumps(data).encode())
    assert error.value.code == ErrorCode.PROTOCOL_MISMATCH
