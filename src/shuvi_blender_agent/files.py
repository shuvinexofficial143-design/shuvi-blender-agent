"""Confined non-overwriting file outputs and bounded structural verification."""

import os
import re
import stat
import struct
import zlib
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from .errors import AgentError, ErrorCode
from .validation import invalid, string

MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_PNG_BYTES = 4 * 1024 * 1024


def file_state(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    ):
        raise AgentError(
            ErrorCode.VERIFICATION_FAILED, "Output must be a regular file without reparse points"
        )
    if info.st_nlink != 1:
        raise AgentError(ErrorCode.VERIFICATION_FAILED, "Hard-linked outputs are unsupported")
    return info


def identity(info):
    return info.st_dev, info.st_ino


def filename(name: str, suffix: str) -> str:
    string(name, "filename", limit=128)
    if (
        not name.lower().endswith(suffix)
        or any(ord(char) < 32 for char in name)
        or any(char in name for char in '<>:"/\\|?*')
        or name.endswith((" ", "."))
    ):
        raise invalid(f"A plain {suffix} filename is required")
    base = name.split(".")[0].rstrip(" ").upper()
    if base in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"(?:COM|LPT)[1-9\u00b9\u00b2\u00b3]", base
    ):
        raise invalid("Reserved Windows filename")
    return name


class OutputWorkspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise AgentError(ErrorCode.NOT_FOUND, "Existing output directory required")
        self._root_identity = identity(self.root.stat())

    def check_root(self):
        try:
            if (
                self.root.resolve() == self.root
                and identity(self.root.stat()) == self._root_identity
            ):
                return
        except OSError:
            pass
        raise AgentError(ErrorCode.SAFETY_DENIED, "Configured output directory was replaced")

    def verify(self, path):
        self.check_root()
        if path.parent != self.root:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Output escapes configured directory")
        return file_state(path)

    @contextmanager
    def reserve(self, name: str, suffix: str):
        name = filename(name, suffix)
        self.check_root()
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Output escapes configured directory")
        try:
            with path.open("xb"):
                pass
            reserved = file_state(path)
        except FileExistsError as exc:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Output already exists; overwrite denied"
            ) from exc
        try:
            yield path
            self.verify(path)
        finally:
            # Preserve nonempty partial outputs for diagnosis/recovery.
            try:
                info = self.verify(path)
                if identity(info) == identity(reserved) and info.st_size == 0:
                    path.unlink()
            except (AgentError, OSError):
                pass


def read_output(path: Path, kind: str) -> dict:
    if kind not in ("BLEND", "PNG"):
        raise invalid("Unsupported output format")
    before = file_state(path)
    size = before.st_size
    limit = MAX_PNG_BYTES if kind == "PNG" else MAX_OUTPUT_BYTES
    if not 12 <= size <= limit:
        raise AgentError(
            ErrorCode.VERIFICATION_FAILED, "Output size is outside verification bounds"
        )
    digest = sha256()
    header = b""
    chunks = []
    count = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Output replaced before readback")
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > size:
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Output grew during readback")
            if not header:
                header = chunk[:12]
            digest.update(chunk)
            if kind == "PNG":
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    entry = file_state(path)
    if (
        count != size
        or identity(entry) != identity(before)
        or after.st_size != size
        or entry.st_mtime_ns != before.st_mtime_ns
    ):
        raise AgentError(ErrorCode.VERIFICATION_FAILED, "Output changed during readback")
    result = {
        "path": str(path.resolve()),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "format": kind,
    }
    if kind == "BLEND":
        if (
            header[:7] != b"BLENDER"
            or header[7:8] not in (b"_", b"-")
            or header[8:9] not in (b"v", b"V")
            or not header[9:12].isdigit()
        ):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Invalid uncompressed Blender header")
    elif kind == "PNG":
        result.update(verify_png(b"".join(chunks)))
    return result


def verify_png(raw: bytes) -> dict:
    def fail():
        raise AgentError(ErrorCode.VERIFICATION_FAILED, "Invalid or unsupported PNG output")

    if len(raw) > MAX_PNG_BYTES or raw[:8] != b"\x89PNG\r\n\x1a\n":
        fail()
    offset = 8
    header = None
    compressed = bytearray()
    ended = False
    idat_ended = False
    idat_started = False
    palette_seen = False
    while offset + 12 <= len(raw):
        length = struct.unpack("!I", raw[offset : offset + 4])[0]
        tag = raw[offset + 4 : offset + 8]
        if not all(65 <= char <= 90 or 97 <= char <= 122 for char in tag):
            fail()
        if tag[2] >= 97:
            fail()
        if tag[0] < 97 and tag not in (b"IHDR", b"PLTE", b"IDAT", b"IEND"):
            fail()
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
            if idat_ended:
                fail()
            compressed.extend(data)
            idat_started = True
        elif idat_started:
            idat_ended = True
        if tag == b"PLTE":
            if palette_seen or idat_started or not 3 <= length <= 768 or length % 3:
                fail()
            palette_seen = True
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
