# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest pushed commit before this checkpoint: 7755a3f7aca6a1c89a68fd2ca0ee872def2f08a0.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Current phase
Phases 1-9 initial bounded source capabilities implemented; Phase 10 mesh tooling next.

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
- Material creation/assignment, perspective camera and four light kinds, actual property
  verification, conservative shared-data guards and created-data cleanup.
- Bounded BEVEL/SUBSURF/SOLIDIFY addition, additive collection creation/object linking,
  local asset marking, metadata readback and creation cleanup. Source distribution includes tests/docs.
- Frame range/selection and bounded transform keyframes on session-owned actions;
  legacy/slotted action readback, coordinates/interpolation verification, no overwrites.
- CPU-only bounded render configuration/execution, disabled render policy by default,
  confined non-overwriting outputs, structural PNG verification and .blend copy checkpoints.

## Status
Source: foundation through initial rendering/checkpoint tools implemented. Unit tests: 107 passing.
Lint/format: passing. Foundation wheel/sdist: built.
CI all prior checkpoints: success. Latest assets run 37314216937. Current CI pending.
Real Blender runtime verification: none. Production ready: no.

## Active work
rendering.py, files.py, safety.py, process.py, inspection.py, tests/test_rendering.py.
Next: bounded indexed mesh inspection/creation/editing with geometry revision checks.

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
Build bounded indexed mesh workflows and actual geometry readback using bpy-shaped fakes.
Deletion stays deferred until runtime-verified checkpoint recovery. Never launch Blender.
Keep destructive deletion deferred until checkpoint/recovery exists. Do not launch Blender.
