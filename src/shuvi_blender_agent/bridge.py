"""Bounded framed loopback transport. Neither logs nor requests contain Python code."""

import hmac
import ipaddress
import socket
import struct
import time
from collections import OrderedDict
from hashlib import sha256
from threading import Lock

from .contracts import Request, Result, failure
from .errors import AgentError, ErrorCode
from .tools import ToolRegistry
from .validation import MAX_MESSAGE_BYTES, decode, encode, fields, integer, string


def require_loopback(sock: socket.socket) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        try:
            if ipaddress.ip_address(sock.getpeername()[0]).is_loopback:
                return
        except (ValueError, OSError):
            pass
        raise AgentError(ErrorCode.SAFETY_DENIED, "Bridge requires a loopback peer")


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AgentError(ErrorCode.TIMEOUT, "Bridge deadline exceeded; outcome may be unknown")
    return remaining


def _receive_exact(sock: socket.socket, size: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        sock.settimeout(_remaining(deadline))
        part = sock.recv(size - len(chunks))
        if not part:
            raise AgentError(ErrorCode.TRANSPORT_ERROR, "Bridge disconnected")
        chunks.extend(part)
    return bytes(chunks)


def receive_frame(sock: socket.socket, deadline: float) -> bytes:
    try:
        size = struct.unpack("!I", _receive_exact(sock, 4, deadline))[0]
        if not 1 <= size <= MAX_MESSAGE_BYTES:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Invalid bridge frame size")
        return _receive_exact(sock, size, deadline)
    except TimeoutError as exc:
        raise AgentError(ErrorCode.TIMEOUT, "Bridge timed out; outcome may be unknown") from exc
    except OSError as exc:
        raise AgentError(ErrorCode.TRANSPORT_ERROR, "Bridge receive failed") from exc


def send_frame(sock: socket.socket, raw: bytes, deadline: float) -> None:
    if not 1 <= len(raw) <= MAX_MESSAGE_BYTES:
        raise AgentError(ErrorCode.INVALID_REQUEST, "Invalid bridge frame size")
    try:
        sock.settimeout(_remaining(deadline))
        sock.sendall(struct.pack("!I", len(raw)) + raw)
    except TimeoutError as exc:
        raise AgentError(
            ErrorCode.TIMEOUT, "Bridge send timed out; outcome may be unknown"
        ) from exc
    except OSError as exc:
        raise AgentError(ErrorCode.TRANSPORT_ERROR, "Bridge send failed") from exc


def authenticate(sock: socket.socket, token: str, deadline: float) -> None:
    require_loopback(sock)
    data = decode(receive_frame(sock, deadline))
    fields(data, {"protocol_version", "token"})
    if type(data["protocol_version"]) is not int or data["protocol_version"] != 1:
        raise AgentError(ErrorCode.PROTOCOL_MISMATCH, "Bridge protocol mismatch")
    presented = string(data["token"], "token", limit=128)
    if not hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8")):
        raise AgentError(ErrorCode.SAFETY_DENIED, "Bridge authentication failed")
    send_frame(sock, encode({"protocol_version": 1, "ready": True}), deadline)


class BlenderClient:
    """Sequential single-owner session. Failure closes the connection; no implicit retry."""

    def __init__(self, sock: socket.socket):
        require_loopback(sock)
        self._socket = sock
        self.closed = False
        self._call_lock = Lock()

    def call(self, request: Request) -> Result:
        if not self._call_lock.acquire(blocking=False):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Concurrent calls on one session are denied")
        try:
            return self._call(request)
        finally:
            self._call_lock.release()

    def _call(self, request: Request) -> Result:
        if self.closed:
            raise AgentError(ErrorCode.TRANSPORT_ERROR, "Bridge session is closed")
        request = Request.from_bytes(request.to_bytes())
        deadline = time.monotonic() + request.timeout_ms / 1000
        try:
            send_frame(self._socket, request.to_bytes(), deadline)
            result = Result.from_bytes(receive_frame(self._socket, deadline))
            if (result.request_id, result.command_id) != (request.request_id, request.command_id):
                raise AgentError(ErrorCode.TRANSPORT_ERROR, "Response IDs do not match request")
            return result
        except AgentError:
            self.close()
            raise

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()


class CommandSession:
    """Bounded session-local replay protection, never persistent exactly-once semantics."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        cache_size: int = 256,
        max_commands: int = 4096,
        max_cache_bytes: int = 4 * MAX_MESSAGE_BYTES,
    ):
        integer(cache_size, "cache_size", 1, 256)
        integer(max_commands, "max_commands", cache_size, 4096)
        integer(max_cache_bytes, "max_cache_bytes", 1, 4 * MAX_MESSAGE_BYTES)
        self.registry = registry
        self.cache_size = cache_size
        self.max_commands = max_commands
        self.max_cache_bytes = max_cache_bytes
        self._cache_bytes = 0
        self._seen: dict[str, str] = {}
        self._request_ids: dict[str, str] = {}
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def execute(self, request: Request) -> Result:
        request = Request.from_bytes(request.to_bytes())
        fingerprint = sha256(request.to_bytes()).hexdigest()
        if request.command_id in self._seen:
            if self._seen[request.command_id] != fingerprint:
                return failure(
                    request,
                    AgentError(
                        ErrorCode.INVALID_REQUEST, "Command ID reused with a different request"
                    ),
                )
            if request.command_id not in self._cache:
                return failure(
                    request,
                    AgentError(ErrorCode.SAFETY_DENIED, "Prior result expired; inspect state"),
                )
            return Result.from_bytes(self._cache[request.command_id])
        if request.request_id in self._request_ids:
            return failure(
                request,
                AgentError(ErrorCode.INVALID_REQUEST, "Request ID reused for another command"),
            )
        if len(self._seen) >= self.max_commands:
            return failure(
                request,
                AgentError(ErrorCode.SAFETY_DENIED, "Session command limit reached; reconnect"),
            )
        # Mark before dispatch; even a failed partial mutation must not be replayed.
        self._seen[request.command_id] = fingerprint
        self._request_ids[request.request_id] = request.command_id
        started = time.monotonic()
        result = self.registry.dispatch(request)
        if time.monotonic() - started > request.timeout_ms / 1000:
            result = failure(
                request,
                AgentError(ErrorCode.TIMEOUT, "Execution exceeded deadline; inspect state"),
                data={"outcome": "known", "completed_status": result.status.value},
            )
        raw = result.to_bytes()
        self._cache[request.command_id] = raw
        self._cache_bytes += len(raw)
        while len(self._cache) > self.cache_size or self._cache_bytes > self.max_cache_bytes:
            _, expired = self._cache.popitem(last=False)
            self._cache_bytes -= len(expired)
        return result


def serve(
    sock: socket.socket, token: str, registry: ToolRegistry, *, idle_timeout_ms: int = 120_000
) -> None:
    """Run only on Blender's main thread in background mode; exit on invalid transport."""
    integer(idle_timeout_ms, "idle_timeout_ms", 1, 120_000)
    require_loopback(sock)
    deadline = time.monotonic() + 10
    send_frame(sock, encode({"protocol_version": 1, "token": token}), deadline)
    ack = decode(receive_frame(sock, deadline))
    fields(ack, {"protocol_version", "ready"})
    if type(ack["protocol_version"]) is not int or ack["protocol_version"] != 1:
        raise AgentError(ErrorCode.PROTOCOL_MISMATCH, "Bridge protocol mismatch")
    if ack["ready"] is not True:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Bridge handshake rejected")
    session = CommandSession(registry)
    while True:
        request = Request.from_bytes(receive_frame(sock, time.monotonic() + idle_timeout_ms / 1000))
        result = session.execute(request)
        send_frame(sock, result.to_bytes(), time.monotonic() + request.timeout_ms / 1000)
