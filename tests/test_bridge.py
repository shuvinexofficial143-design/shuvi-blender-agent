import socket
import struct
import threading
import time

import pytest

from shuvi_blender_agent import AgentError, ErrorCode, Request, Result, Status
from shuvi_blender_agent.bridge import (
    BlenderClient,
    CommandSession,
    authenticate,
    receive_frame,
    send_frame,
    serve,
)
from shuvi_blender_agent.tools import Tool, ToolRegistry, ping_tool
from shuvi_blender_agent.validation import MAX_MESSAGE_BYTES, encode


def test_frame_fragmentation_and_bounded_size():
    left, right = socket.socketpair()
    try:
        raw = b'{"ok":true}'

        def sender():
            for chunk in (
                struct.pack("!I", len(raw))[:2],
                struct.pack("!I", len(raw))[2:],
                raw[:3],
                raw[3:],
            ):
                right.sendall(chunk)

        worker = threading.Thread(target=sender)
        worker.start()
        assert receive_frame(left, time.monotonic() + 2) == raw
        worker.join(timeout=2)
        right.sendall(struct.pack("!I", MAX_MESSAGE_BYTES + 1))
        with pytest.raises(AgentError) as error:
            receive_frame(left, time.monotonic() + 2)
        assert error.value.code == ErrorCode.INVALID_REQUEST
    finally:
        left.close()
        right.close()


def test_real_python_socket_roundtrip():
    left, right = socket.socketpair()
    errors = []

    def server():
        try:
            serve(right, "secret", ToolRegistry([ping_tool()]))
        except AgentError as exc:
            errors.append(exc.code)
        finally:
            right.close()

    worker = threading.Thread(target=server)
    worker.start()
    try:
        authenticate(left, "secret", time.monotonic() + 2)
        client = BlenderClient(left)
        assert client.call(Request("system.ping")).data == {"ready": True}
        assert client.call(Request("exec")).error.code == ErrorCode.UNSUPPORTED_OPERATION
        client.close()
    finally:
        left.close()
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert errors == [ErrorCode.TRANSPORT_ERROR]


def test_wrong_token_rejected():
    left, right = socket.socketpair()
    try:
        send_frame(right, encode({"protocol_version": 1, "token": "wrong"}), time.monotonic() + 1)
        with pytest.raises(AgentError) as error:
            authenticate(left, "expected", time.monotonic() + 1)
        assert error.value.code == ErrorCode.SAFETY_DENIED
    finally:
        left.close()
        right.close()


def test_timeout_and_disconnect_close_client():
    left, right = socket.socketpair()
    client = BlenderClient(left)
    try:
        with pytest.raises(AgentError) as error:
            client.call(Request("system.ping", timeout_ms=10))
        assert error.value.code == ErrorCode.TIMEOUT
        assert client.closed
        with pytest.raises(AgentError):
            client.call(Request("system.ping"))
    finally:
        right.close()


def test_uncorrelated_reply_closes_connection():
    left, right = socket.socketpair()
    try:
        send_frame(
            right, Result("wrong", "wrong", Status.SUCCEEDED).to_bytes(), time.monotonic() + 1
        )
        client = BlenderClient(left)
        with pytest.raises(AgentError) as error:
            client.call(Request("system.ping"))
        assert error.value.code == ErrorCode.TRANSPORT_ERROR
        assert client.closed
    finally:
        left.close()
        right.close()


def test_replay_is_bounded_and_never_executes_twice():
    calls = []

    def execute(request, payload):
        calls.append(request.command_id)
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, {"count": len(calls)}
        )

    registry = ToolRegistry([Tool("read", ping_tool().classification, lambda p: p, execute)])
    session = CommandSession(registry, cache_size=1, max_commands=2)
    first = Request("read")
    assert session.execute(first).data == session.execute(first).data
    changed = Request("read", {"x": 1}, command_id=first.command_id, request_id=first.request_id)
    assert session.execute(changed).error.code == ErrorCode.INVALID_REQUEST
    assert session.execute(Request("read")).status == Status.SUCCEEDED
    assert session.execute(first).error.code == ErrorCode.SAFETY_DENIED
    assert session.execute(Request("read")).error.code == ErrorCode.SAFETY_DENIED
    assert len(calls) == 2


@pytest.mark.parametrize("packet", [b"\x00\x00", struct.pack("!I", 20) + b"short"])
def test_truncated_frames_have_structured_disconnect(packet):
    left, right = socket.socketpair()
    try:
        right.sendall(packet)
        right.close()
        with pytest.raises(AgentError) as error:
            receive_frame(left, time.monotonic() + 1)
        assert error.value.code == ErrorCode.TRANSPORT_ERROR
    finally:
        left.close()
        right.close()


def test_unicode_token_is_rejected_without_typeerror():
    left, right = socket.socketpair()
    try:
        send_frame(right, encode({"protocol_version": 1, "token": "\u2603"}), time.monotonic() + 1)
        with pytest.raises(AgentError) as error:
            authenticate(left, "secret", time.monotonic() + 1)
        assert error.value.code == ErrorCode.SAFETY_DENIED
    finally:
        left.close()
        right.close()


def test_replay_memory_budget_eviction_never_reexecutes():
    registry = ToolRegistry([ping_tool()])
    session = CommandSession(registry, cache_size=2, max_cache_bytes=300)
    first = Request("system.ping")
    session.execute(first)
    session.execute(Request("system.ping"))
    assert session._cache_bytes <= 300
    assert session.execute(first).error.code == ErrorCode.SAFETY_DENIED


def test_request_id_cannot_be_reused_for_a_new_command():
    session = CommandSession(ToolRegistry([ping_tool()]))
    session.execute(Request("system.ping", request_id="same"))
    result = session.execute(Request("system.ping", request_id="same"))
    assert result.error.code == ErrorCode.INVALID_REQUEST
    assert len(session._seen) == 1


def test_deadline_result_is_cached_consistently(monkeypatch):
    session = CommandSession(ToolRegistry([ping_tool()]))
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr("shuvi_blender_agent.bridge.time.monotonic", lambda: next(ticks))
    request = Request("system.ping", timeout_ms=1)
    result = session.execute(request)
    assert result.error.code == ErrorCode.TIMEOUT
    assert result.data == {"outcome": "known", "completed_status": "succeeded"}
    assert session.execute(request).to_dict() == result.to_dict()


def test_concurrent_call_does_not_corrupt_the_active_request():
    left, right = socket.socketpair()
    client = BlenderClient(left)
    request = Request("system.ping")
    results = []
    worker = threading.Thread(target=lambda: results.append(client.call(request)))
    try:
        worker.start()
        received = Request.from_bytes(receive_frame(right, time.monotonic() + 2))
        assert received == request
        with pytest.raises(AgentError) as error:
            client.call(Request("system.ping"))
        assert error.value.code == ErrorCode.SAFETY_DENIED
        assert not client.closed
        send_frame(
            right,
            Result(request.request_id, request.command_id, Status.SUCCEEDED).to_bytes(),
            time.monotonic() + 2,
        )
        worker.join(timeout=2)
        assert len(results) == 1
    finally:
        client.close()
        right.close()
        worker.join(timeout=2)


def test_non_loopback_peer_is_rejected():
    class RemoteSocket:
        family = socket.AF_INET

        def getpeername(self):
            return ("192.0.2.1", 12345)

    with pytest.raises(AgentError) as error:
        BlenderClient(RemoteSocket())
    assert error.value.code == ErrorCode.SAFETY_DENIED
