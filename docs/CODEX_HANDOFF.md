# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest pushed commit before this checkpoint: ca54f06a89404738fcbdd86fe77fb067c1ee0e5e.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Current phase
Phases 1 and 2 source-side complete; Phase 3 controlled bridge next.

## Completed and verified
- Fetched actual public remote; empty repository, no prior commits/files to preserve.
- GitHub connector write permission confirmed. Local CLI has no GitHub credentials.
- No Blender installation, launch, render, or bpy runtime test performed.
- Windows-first discovery: configured paths, PATH, standard directories, opt-in version
  probes, deterministic selection, diagnostics, bounds, CLI. macOS/Linux path support.

## Status
Source: contracts, safety, dispatcher and discovery implemented. Unit tests: 35 passing.
Lint/format: passing. Foundation wheel/sdist: built.
CI ca54f06: success, run 37308733708. This checkpoint's CI pending.
Real Blender runtime verification: none. Production ready: no.

## Active work
discovery.py, __main__.py, tests/test_discovery.py, docs/DISCOVERY.md.
Next: process.py, bridge framing/client, bootstrap and mocked transport tests.

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

## Blockers
None for source development. Heavy Blender runtime actions require later user authorization.

## Exact next task
Build controlled launch and authenticated bounded local bridge, with bpy on the main thread.
Test with ordinary Python/fake processes only. Checkpoint before expansion.
