# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest pushed commit before this checkpoint: 924507e2c7633d61f5d7da592ac5154b79ee36b9.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Current phase
Phases 1-5 initial source layers complete; Phase 6 materials/cameras/lights next.

## Completed and verified
- Fetched actual public remote; empty repository, no prior commits/files to preserve.
- GitHub connector write permission confirmed. Local CLI has no GitHub credentials.
- No Blender installation, launch, render, or bpy runtime test performed.
- Windows-first discovery: configured paths, PATH, standard directories, opt-in version
  probes, deterministic selection, diagnostics, bounds, CLI. macOS/Linux path support.
- Controlled background launcher, authenticated loopback bridge, bounded frames/deadlines,
  correlated replies, readiness ping, owned-process cleanup and session replay protection.
- Read-only scene/object inspection, typed bounded queries, object/session identities,
  metadata revision fingerprints, stale pagination protection and bpy fake-data tests.
- Safe cube/plane/empty creation, local transforms, mesh/empty duplication, actual
  before/after comparison, collision/stale protection and created-data cleanup.

## Status
Source: foundation through initial object actions implemented. Unit tests: 71 passing.
Lint/format: passing. Foundation wheel/sdist: built.
CI foundation/discovery/bridge: success. Latest bridge run 37310526776. Current CI pending.
Real Blender runtime verification: none. Production ready: no.

## Active work
models.py, operations.py, verification.py, bootstrap.py, test_operations.py, fake_bpy.py.
Next: verified typed material/camera/light actions with bounded payloads.

## Decisions
- Standard-library runtime; pytest is a development dependency.
- Typed allowlisted requests; no arbitrary Python execution tool.
- Keep planning outside execution. Only readback comparison can verify mutation success.
- Blender-dependent implementation stays behind adapters.
- Checkpoint through connected GitHub API using non-forced branch updates.
- Fetch remote before each checkpoint; preserve concurrent work and never force push.
- Discovery never executes Blender by default; versions use injectable probes.
- No registry/Store/Steam discovery or running-process attachment yet.
- Local sandbox tests use a fresh workspace --basetemp=../pytest-<unique-name>.
- Owned background sessions only; no GUI or existing-process attachment.
- bpy stays on main thread; sequential client, no automatic mutation retries.
- Timeouts cannot interrupt bpy calls: outcome may be unknown.
- Target Blender 4.2+ with Python 3.11+; runtime compatibility remains unverified.

## Blockers
None for source development. Heavy Blender runtime actions require later user authorization.

## Exact next task
Build material creation/assignment and camera/light creation with actual property readback.
Keep destructive deletion deferred until checkpoint/recovery exists. Do not launch Blender.
