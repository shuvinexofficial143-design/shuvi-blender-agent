"""Windows-first bounded discovery. Merely discovering paths never runs Blender."""

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from threading import Event, Thread

from .errors import AgentError, ErrorCode
from .validation import integer, string


@dataclass(frozen=True, order=True)
class BlenderVersion:
    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, output: str) -> "BlenderVersion":
        if not isinstance(output, str) or len(output) > 65536:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Version response exceeds bounds")
        match = re.search(
            r"(?m)^Blender ([0-9]{1,4})\.([0-9]{1,4})(?:\.([0-9]{1,4}))?(?:\s|$)", output
        )
        if match is None:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Not a Blender version response")
        return cls(int(match[1]), int(match[2]), int(match[3] or 0))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class Installation:
    executable: Path
    source: str
    priority: int
    version: BlenderVersion | None = None

    def to_dict(self) -> dict:
        return {
            "executable": str(self.executable),
            "source": self.source,
            "version": str(self.version) if self.version else None,
        }


@dataclass(frozen=True)
class DiscoveryConfig:
    configured_paths: tuple[Path, ...] = ()
    search_roots: tuple[Path, ...] = ()
    max_candidates: int = 256
    version_timeout_ms: int = 3000
    max_directory_entries: int = 4096

    def __post_init__(self) -> None:
        integer(self.max_candidates, "max_candidates", 1, 256)
        integer(self.version_timeout_ms, "version_timeout_ms", 1, 10_000)
        integer(self.max_directory_entries, "max_directory_entries", 1, 4096)
        if len(self.configured_paths) > 32 or len(self.search_roots) > 32:
            raise ValueError("At most 32 configured paths/search roots")


@dataclass
class DiscoveryReport:
    installations: list[Installation] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    truncated: bool = False

    def select(self, minimum: BlenderVersion | None = None) -> Installation:
        eligible = [
            item
            for item in self.installations
            if minimum is None or (item.version is not None and item.version >= minimum)
        ]
        if not eligible:
            raise AgentError(ErrorCode.BLENDER_NOT_FOUND, "No eligible Blender installation found")
        # Explicit configured order wins; then PATH; then newest known standard installation.
        return sorted(
            eligible,
            key=lambda item: (
                item.priority,
                -(item.version.major if item.version else -1),
                -(item.version.minor if item.version else -1),
                -(item.version.patch if item.version else -1),
                str(item.executable).casefold(),
            ),
        )[0]

    def to_dict(self) -> dict:
        return {
            "installed": bool(self.installations),
            "installations": [item.to_dict() for item in self.installations],
            "issues": self.issues,
            "truncated": self.truncated,
        }


def _bounded_version_run(args, *, timeout, popen=subprocess.Popen, **kwargs):
    process = popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = bytearray()
    oversized = Event()
    read_failed = Event()

    def read():
        try:
            while chunk := process.stdout.read(4096):
                if len(output) + len(chunk) > 65536:
                    oversized.set()
                    process.kill()
                    break
                output.extend(chunk)
        except OSError:
            read_failed.set()

    worker = Thread(target=read, daemon=True)
    worker.start()
    try:
        process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        worker.join(timeout=2)
        if not worker.is_alive():
            process.stdout.close()
    if oversized.is_set() or read_failed.is_set() or worker.is_alive():
        raise AgentError(
            ErrorCode.EXECUTION_ERROR, "Version response exceeds bounds or is unreadable"
        )
    try:
        return subprocess.CompletedProcess(args, process.returncode, bytes(output).decode("utf-8"))
    except UnicodeError as exc:
        raise AgentError(ErrorCode.EXECUTION_ERROR, "Invalid version response encoding") from exc


def probe_version(
    executable: Path, timeout_ms: int = 3000, *, run: Callable = _bounded_version_run
) -> BlenderVersion:
    """Explicit lightweight subprocess probe; never invoked by discovery unless requested."""
    integer(timeout_ms, "timeout_ms", 1, 10_000)
    try:
        completed = run(
            [str(executable), "--version"],
            timeout=timeout_ms / 1000,
            capture_output=True,
            text=True,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(ErrorCode.TIMEOUT, "Blender version probe timed out") from exc
    except OSError as exc:
        raise AgentError(ErrorCode.EXECUTION_ERROR, "Cannot execute Blender version probe") from exc
    if completed.returncode != 0:
        raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender version probe failed")
    return BlenderVersion.parse(completed.stdout)


def default_roots(platform: str, env: Mapping[str, str]) -> tuple[Path, ...]:
    if platform == "win32":
        roots = []
        for key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            if env.get(key):
                roots.append(Path(env[key]) / "Blender Foundation")
        return tuple(dict.fromkeys(roots))
    if platform == "darwin":
        return (Path("/Applications"),)
    return (Path("/opt"),)


def discover(
    config: DiscoveryConfig | None = None,
    *,
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    which: Callable = shutil.which,
    version_probe: Callable[[Path, int], BlenderVersion] | None = None,
) -> DiscoveryReport:
    """Shallow scans only. Version probing is opt-in and injectable for unit tests."""
    config = config or DiscoveryConfig()
    env = os.environ if env is None else env
    report = DiscoveryReport()
    candidates: list[tuple[Path, str, int]] = []
    executable_name = "blender.exe" if platform == "win32" else "blender"
    for index, path in enumerate(config.configured_paths):
        path = Path(path).expanduser()
        if path.is_dir():
            path = path / executable_name
        candidates.append((path, "configured", index))
    path_result = which(executable_name, path=env.get("PATH", ""))
    if path_result:
        candidates.append((Path(path_result), "PATH", 100))
    roots = config.search_roots or default_roots(platform, env)
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            # Sorting yields a reproducible cap; no recursive filesystem crawl.
            children = list(islice(root.iterdir(), config.max_directory_entries + 1))
            if len(children) > config.max_directory_entries:
                report.truncated = True
                report.issues.append({"path": str(root), "code": "directory_work_limit"})
                continue
            children.sort(key=lambda child: child.name.casefold())
            if len(children) > config.max_candidates:
                report.truncated = True
            for child in children[: config.max_candidates]:
                if not child.name.casefold().startswith("blender"):
                    continue
                path = child / executable_name
                if platform == "darwin":
                    path = child / "Contents" / "MacOS" / "Blender"
                candidates.append((path, "standard", 200))
        except OSError:
            report.issues.append({"path": str(root), "code": "unreadable_directory"})
    seen = set()
    for path, source, priority in candidates:
        key = str(path.resolve()).casefold() if platform == "win32" else str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        if len(report.installations) >= config.max_candidates:
            report.truncated = True
            break
        if not path.is_file():
            if source == "configured":
                report.issues.append({"path": str(path), "code": "not_found"})
            continue
        string(str(path), "executable", limit=4096)
        version = None
        if version_probe is not None:
            try:
                version = version_probe(path, config.version_timeout_ms)
            except AgentError as exc:
                report.issues.append({"path": str(path), "code": exc.code.value})
                continue
        report.installations.append(Installation(path.resolve(), source, priority, version))
    return report
