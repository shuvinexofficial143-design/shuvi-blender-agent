# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest pushed commit before this checkpoint: 623a6b7981742349b80d72f837ae62e9eb478a14.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Current phase
Phases 1-4 initial source layers complete; Phase 5 safe objects/transforms next.

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

## Status
Source: foundation, discovery, bridge and inspection implemented. Unit tests: 57 passing.
Lint/format: passing. Foundation wheel/sdist: built.
CI foundation/discovery/bridge: success. Latest bridge run 37310526776. Current CI pending.
Real Blender runtime verification: none. Production ready: no.

## Active work
models.py, inspection.py, bootstrap.py, tests/fake_bpy.py, test_inspection.py.
Next: operations.py and verification.py, safe creation and exact local transforms.

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
Build safe object creation/local transforms using expected scene/object revisions.
Read actual state after mutations, compare, return verified only on match. Test failures.
