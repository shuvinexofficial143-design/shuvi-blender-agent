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

The execution factory currently registers 243 typed tools. The host client validates its own
allowlist and safety classes, verifies response correlation/readback and executes bounded
declarative plans. Scene queries stream revision construction and cap nested work, page
bytes and metadata. File outputs use exclusive reservations and verified readback.

## Integration and acceptance

- [Level 1 broad Blender control status](docs/LEVEL_1_CONTROL.md)
- [Level 2 professional modeling roadmap/status](docs/LEVEL_2_MODELING.md)
- [Level 3 sculpting + character modeling roadmap/status](docs/LEVEL_3_SCULPTING.md)
- [Level 4 UV / texture / materials roadmap/status](docs/LEVEL_4_UV_MATERIALS.md)
- [Level 5 Geometry Nodes roadmap/status](docs/LEVEL_5_GEOMETRY_NODES.md)
- [Level 6 Rigging roadmap/status](docs/LEVEL_6_RIGGING.md)
- [Level 7 Advanced Animation roadmap/status](docs/LEVEL_7_ANIMATION.md)
- [Level 8 Cinematography roadmap/status](docs/LEVEL_8_CINEMATOGRAPHY.md)
- [Tool reference and exact limits](docs/TOOL_REFERENCE.md)
- [Host client and stable integration interface](docs/CLIENT.md)
- [Source audit and practical limits](docs/SOURCE_AUDIT.md)
- [Future Blender 4.2+ acceptance checklist](docs/RUNTIME_ACCEPTANCE.md)

The prepared acceptance module uses a disposable factory-startup project and requires
explicit runtime authorization. Running it without arguments only reports preparation:

```powershell
python -m shuvi_blender_agent.runtime_acceptance
```

Level 1 source-side control is **100% complete** against the current Level 1 roadmap.
Level 2 professional modeling source-side roadmap is **100% complete**.
Level 3 sculpting + character-modeling source roadmap is **100% complete**.
Level 4 UV / texture / materials source roadmap is **100% complete** (Milestones 1-10 of 10).
Level 5 Geometry Nodes source roadmap is **100% complete** (Milestones 1-10 of 10).
Level 6 Rigging source roadmap is **100% complete** (Milestones 1-10 of 10).
Level 7 Advanced Animation source roadmap is **100% complete** (Milestones 1-10 of 10).
Level 8 Cinematography source roadmap is **80% complete** (Milestones 1-8 of 10).
Level 7 Milestone 10 adds bounded animation structure QA, current-session managed Action recovery capture/restore with readback verification and rollback, and scoped source-only acceptance. These source capabilities are not live Blender acceptance.
Level 8 Milestone 1 adds bounded subject-centered camera shot planning and verified camera framing using lens, sensor width, render aspect, conservative subject bounds, explicit angles and safety checks.
Level 8 Milestone 2 adds nine fixed Rule-of-Thirds composition anchors, actual camera plane repositioning, adaptive clipping/framing clearance and shared verified camera rollback.
Level 8 Milestone 3 adds bounded ORBIT, DOLLY_IN and DOLLY_OUT camera Action keyframes (6 channels, 3 poses) with exact source readback.
Level 8 Milestone 4 adds five-pose cubic Bézier camera rails (6 channels, 30 keys), revisioned previews and guarded rollback; actual Blender evaluated motion is unverified.
Level 8 Milestone 5 adds real BEZIER interpolation/explicit FREE handles and adjustable EASE_IN/EASE_OUT/EASE_IN_OUT time remapping to new five-pose camera Actions, with full handle readback and recovery.
Level 8 Milestone 6 adds a bounded, dynamically evaluated TRACK_TO constraint to follow a subject's orientation, safe initial camera framing, verified constraint readback and same-session owned release.
Level 8 Milestone 7 adds COPY_LOCATION with world offset before TRACK_TO, making the camera move with subject translation while retaining subject aim, with verified creation and owned release.
Level 8 Milestone 8 adds bounded time-normalized EMA damping from existing LINEAR subject position keyframes and bakes a safe camera location/rotation Action with exact readback, without falsely claiming realtime damping.
Source and fake-data tests are available; real Blender runtime verification remains 0% and production readiness is still not claimed.
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
