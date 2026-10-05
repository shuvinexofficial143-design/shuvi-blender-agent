import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuvi_blender_agent import AgentError, ErrorCode
from shuvi_blender_agent.discovery import (
    BlenderVersion,
    DiscoveryConfig,
    default_roots,
    discover,
    probe_version,
)


def executable(directory: Path, name="blender.exe") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.touch()
    return path


def test_discovery_never_probes_by_default(tmp_path):
    path = executable(tmp_path / "custom")
    report = discover(
        DiscoveryConfig((path,)), platform="win32", env={}, which=lambda *args, **kwargs: None
    )
    assert report.select().executable == path
    assert report.select().version is None


def test_priority_versions_dedup_and_determinism(tmp_path):
    custom = executable(tmp_path / "custom")
    standard = tmp_path / "standard"
    old = executable(standard / "Blender 4.2")
    new = executable(standard / "Blender 5.0")
    versions = {custom: BlenderVersion(4, 2), old: BlenderVersion(4, 2), new: BlenderVersion(5, 0)}
    config = DiscoveryConfig((custom,), (standard,))
    report = discover(
        config,
        platform="win32",
        env={},
        which=lambda *a, **kw: str(custom),
        version_probe=lambda path, timeout: versions[path],
    )
    assert len(report.installations) == 3
    assert report.select().executable == custom
    assert report.select(BlenderVersion(5, 0)).executable == new
    no_custom = discover(
        DiscoveryConfig(search_roots=(standard,)),
        platform="win32",
        env={},
        which=lambda *a, **kw: None,
        version_probe=lambda path, timeout: versions[path],
    )
    assert no_custom.select().executable == new


def test_configured_order_beats_version(tmp_path):
    first, second = executable(tmp_path / "a"), executable(tmp_path / "b")
    report = discover(
        DiscoveryConfig((first, second)),
        env={},
        platform="win32",
        which=lambda *a, **kw: None,
        version_probe=lambda p, t: BlenderVersion(4 if p == first else 5, 2),
    )
    assert report.select().executable == first


def test_missing_and_failed_probe(tmp_path):
    missing = tmp_path / "missing.exe"
    present = executable(tmp_path / "present")

    def fail(*args):
        raise AgentError(ErrorCode.TIMEOUT, "Timeout")

    report = discover(
        DiscoveryConfig((missing, present)),
        platform="win32",
        env={},
        which=lambda *a, **kw: None,
        version_probe=fail,
    )
    assert [issue["code"] for issue in report.issues] == ["not_found", "timeout"]
    with pytest.raises(AgentError) as error:
        report.select()
    assert error.value.code == ErrorCode.BLENDER_NOT_FOUND


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Blender 4.2.3\nbuild info", BlenderVersion(4, 2, 3)),
        ("Blender 5.0\n", BlenderVersion(5, 0)),
    ],
)
def test_versions(output, expected):
    assert BlenderVersion.parse(output) == expected


@pytest.mark.parametrize("output", ["Other 5.0", "Blender 4.x", "Blender 5.0garbage"])
def test_invalid_versions(output):
    with pytest.raises(AgentError):
        BlenderVersion.parse(output)


def test_probe_no_shell_and_timeout():
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="Blender 4.2.1\n")

    assert probe_version(Path("C:/Blender Folder/blender.exe"), 1234, run=run) == (
        BlenderVersion(4, 2, 1)
    )
    assert calls[0][0] == [str(Path("C:/Blender Folder/blender.exe")), "--version"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 1.234

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("blender", 1)

    with pytest.raises(AgentError) as error:
        probe_version(Path("blender"), run=timeout)
    assert error.value.code == ErrorCode.TIMEOUT


def test_standard_windows_roots_and_bounded_scan(tmp_path):
    roots = default_roots("win32", {"ProgramFiles": "C:/Programs", "ProgramW6432": "C:/Programs"})
    assert len(roots) == 1
    for index in range(4):
        executable(tmp_path / f"Blender {index}")
    report = discover(
        DiscoveryConfig(search_roots=(tmp_path,), max_candidates=2),
        env={},
        platform="win32",
        which=lambda *a, **kw: None,
    )
    assert report.truncated
    assert len(report.installations) == 2


def test_macos_app_bundle(tmp_path):
    path = executable(tmp_path / "Blender.app" / "Contents" / "MacOS", "Blender")
    report = discover(
        DiscoveryConfig(search_roots=(tmp_path,)),
        platform="darwin",
        env={},
        which=lambda *a, **kw: None,
    )
    assert report.select().executable == path
