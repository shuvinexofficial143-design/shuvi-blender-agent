"""Confined non-overwriting file outputs and bounded structural verification."""

import re
import struct
import zlib
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from .errors import AgentError, ErrorCode
from .validation import invalid, string

MAX_OUTPUT_BYTES = 128 * 1024 * 1024


def filename(name: str, suffix: str) -> str:
    string(name, "filename", limit=128)
    if (
        not name.lower().endswith(suffix)
        or any(ord(char) < 32 for char in name)
        or any(char in name for char in '<>:"/\\|?*')
        or name.endswith((" ", "."))
    ):
        raise invalid(f"A plain {suffix} filename is required")
    base = name.split(".")[0].upper()
    if base in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", base):
        raise invalid("Reserved Windows filename")
    return name


class OutputWorkspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise AgentError(ErrorCode.NOT_FOUND, "Existing output directory required")

    @contextmanager
    def reserve(self, name: str, suffix: str):
        name = filename(name, suffix)
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Output escapes configured directory")
        try:
            with path.open("xb"):
                pass
        except FileExistsError as exc:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Output already exists; overwrite denied"
            ) from exc
        try:
            yield path
        finally:
            # Preserve nonempty partial outputs for diagnosis/recovery.
            if path.is_file() and path.stat().st_size == 0:
                path.unlink()


def read_output(path: Path, kind: str) -> dict:
    size = path.stat().st_size
    if not 12 <= size <= MAX_OUTPUT_BYTES:
        raise AgentError(
            ErrorCode.VERIFICATION_FAILED, "Output size is outside verification bounds"
        )
    with path.open("rb") as stream:
        raw = stream.read(MAX_OUTPUT_BYTES + 1)
    if len(raw) != size or len(raw) > MAX_OUTPUT_BYTES:
        raise AgentError(ErrorCode.VERIFICATION_FAILED, "Output changed during readback")
    result = {"path": str(path), "bytes": size, "sha256": sha256(raw).hexdigest(), "format": kind}
    if kind == "BLEND":
        if raw[:7] != b"BLENDER" or raw[7:8] not in (b"_", b"-") or raw[8:9] not in (b"v", b"V"):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Invalid uncompressed Blender header")
    elif kind == "PNG":
        result.update(verify_png(raw))
    else:
        raise invalid("Unsupported output format")
    return result


def verify_png(raw: bytes) -> dict:
    def fail():
        raise AgentError(ErrorCode.VERIFICATION_FAILED, "Invalid or unsupported PNG output")

    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        fail()
    offset = 8
    header = None
    compressed = bytearray()
    ended = False
    while offset + 12 <= len(raw):
        length = struct.unpack("!I", raw[offset : offset + 4])[0]
        tag = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            fail()
        data = raw[offset + 8 : end - 4]
        crc = struct.unpack("!I", raw[end - 4 : end])[0]
        if zlib.crc32(tag + data) != crc:
            fail()
        if header is None:
            if tag != b"IHDR" or length != 13:
                fail()
            header = struct.unpack("!IIBBBBB", data)
        elif tag == b"IHDR":
            fail()
        if tag == b"IDAT":
            compressed.extend(data)
        if tag == b"IEND":
            if length != 0 or end != len(raw):
                fail()
            ended = True
            break
        offset = end
    if not ended or header is None or not compressed:
        fail()
    width, height, depth, color, compression, filtering, interlace = header
    if (
        not 16 <= width <= 512
        or not 16 <= height <= 512
        or (depth, color, compression, filtering, interlace) != (8, 6, 0, 0, 0)
    ):
        fail()
    expected_bytes = height * (1 + width * 4)
    try:
        inflater = zlib.decompressobj()
        pixels = inflater.decompress(compressed, expected_bytes + 1)
    except zlib.error:
        fail()
    if (
        len(pixels) != expected_bytes
        or not inflater.eof
        or inflater.unused_data
        or inflater.unconsumed_tail
    ):
        fail()
    if any(pixels[row * (1 + width * 4)] > 4 for row in range(height)):
        fail()
    return {"width": width, "height": height, "color_mode": "RGBA", "bit_depth": 8}
