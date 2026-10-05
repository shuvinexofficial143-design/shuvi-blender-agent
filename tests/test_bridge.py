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
