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

## Develop

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
```

Read [architecture](docs/ARCHITECTURE.md) and [handoff](docs/CODEX_HANDOFF.md) before
continuing development. Source implementation, unit testing, CI, actual Blender runtime
verification, and production readiness are tracked separately. No Blender runtime
verification or production readiness is claimed.
