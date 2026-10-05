"""Offline package content and clean installed import/CLI checks. Never runs Blender."""

import subprocess
import sys
import tarfile
import venv
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

SMOKE = """
import importlib
import importlib.metadata
import pkgutil
import sys
import shuvi_blender_agent
for item in pkgutil.iter_modules(shuvi_blender_agent.__path__):
    importlib.import_module('shuvi_blender_agent.' + item.name)
assert 'bpy' not in sys.modules
assert importlib.metadata.version('shuvi-blender-agent') == '0.1.0'
print('Clean installed imports passed without bpy')
"""


def check_distribution(dist: Path):
    wheels = list(dist.glob("*.whl"))
    sources = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise RuntimeError("Expected one current wheel and one source archive")
    root = Path(__file__).resolve().parent.parent
    expected_modules = {
        f"shuvi_blender_agent/{path.name}"
        for path in (root / "src/shuvi_blender_agent").glob("*.py")
    }
    with zipfile.ZipFile(wheels[0]) as archive:
        if not expected_modules <= set(archive.namelist()):
            raise RuntimeError("Wheel is missing package modules or bootstrap")
        metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        if b"Requires-Python: >=3.11" not in archive.read(metadata):
            raise RuntimeError("Wheel Python requirement missing")
    with tarfile.open(sources[0], "r:gz") as archive:
        names = {name.partition("/")[2] for name in archive.getnames()}
        required = {
            "README.md",
            "pyproject.toml",
            "docs/TOOL_REFERENCE.md",
            "docs/RUNTIME_ACCEPTANCE.md",
            "docs/SOURCE_AUDIT.md",
            "docs/CLIENT.md",
            "docs/CODEX_HANDOFF.md",
            ".github/workflows/ci.yml",
            "tests/fake_bpy.py",
            "tests/test_runtime_acceptance.py",
            "scripts/check_distribution.py",
        }
        if not required <= names or not {"src/" + name for name in expected_modules} <= names:
            raise RuntimeError("Source archive is missing required docs, tests or package modules")
    with TemporaryDirectory(prefix="shuvi-package-smoke-") as directory:
        clean = Path(directory)
        venv.EnvBuilder(with_pip=True).create(clean / "environment")
        executable = (
            clean
            / "environment"
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        subprocess.run(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheels[0].resolve()),
            ],
            cwd=clean,
            check=True,
            timeout=60,
            capture_output=True,
            text=True,
        )
        subprocess.run([str(executable), "-I", "-c", SMOKE], cwd=clean, check=True, timeout=30)
        subprocess.run(
            [str(executable), "-I", "-m", "shuvi_blender_agent", "--help"],
            cwd=clean,
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(
            [str(executable), "-I", "-m", "shuvi_blender_agent.runtime_acceptance"],
            cwd=clean,
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        )
        if '"status": "prepared"' not in completed.stdout:
            raise RuntimeError("Acceptance CLI must default to preparation only")
    print(
        f"Verified wheel/source content ({len(expected_modules)} modules) and clean offline install"
    )


if __name__ == "__main__":
    check_distribution(Path(sys.argv[1]) if len(sys.argv) == 2 else Path("dist"))
