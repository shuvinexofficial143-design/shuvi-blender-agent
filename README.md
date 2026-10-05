# Shuvi Blender Agent

Blender-specific control engine for later integration with Shuvi. This is an automation
engine, not a model training project. Runtime dependencies: Python standard library.
Python 3.11+ on the host; Blender compatibility requires separate acceptance testing.

```text
Typed request → strict validation → safety policy → controller → bpy adapter
             → actual readback → verification → correlated structured result
```

The package imports without Blender. No unrestricted Python execution tool is exposed.
Planning, model providers, authentication, billing, and frontend belong to the main Shuvi
project and are outside this repository.

The execution factory currently registers 46 typed tools. The host client validates its own
allowlist and safety classes, verifies response correlation/readback and executes bounded
declarative plans. Scene queries stream revision construction and cap nested work, page
bytes and metadata. File outputs use exclusive reservations and verified readback.

## Integration and acceptance

- [Level 1 broad Blender control status](docs/LEVEL_1_CONTROL.md)
- [Tool reference and exact limits](docs/TOOL_REFERENCE.md)
- [Host client and stable integration interface](docs/CLIENT.md)
- [Source audit and practical limits](docs/SOURCE_AUDIT.md)
- [Future Blender 4.2+ acceptance checklist](docs/RUNTIME_ACCEPTANCE.md)

The prepared acceptance module uses a disposable factory-startup project and requires
explicit runtime authorization. Running it without arguments only reports preparation:

```powershell
python -m shuvi_blender_agent.runtime_acceptance
```

Source and fake-data tests are available; real Blender runtime verification remains 0%.
Production ready: no. Real launch, bpy, render and recovery behavior need the separately
authorized acceptance procedure. No Blender is installed or launched by package import.

## Develop

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m build
.venv\Scripts\python scripts/check_distribution.py
```

Read [architecture](docs/ARCHITECTURE.md) and [handoff](docs/CODEX_HANDOFF.md) before
continuing development. Source implementation, unit testing, CI, actual Blender runtime
verification, and production readiness are tracked separately. No Blender runtime
verification or production readiness is claimed.
