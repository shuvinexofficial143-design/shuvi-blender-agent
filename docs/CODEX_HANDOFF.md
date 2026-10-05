# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest verified pushed commit before this checkpoint: 427880ae406a19e301ccf5ef01a51f3e89ba3f87.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Current phase
Phases 1-11 initial bounded source capabilities implemented. Source hardening in progress.
Phase 12 actual Blender acceptance is awaiting explicit runtime authorization.

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
- Indexed mesh inspection/creation and vertex translation with separate geometry revisions,
  strict work limits, prevalidated indices and actual geometry comparison.
- Capability catalog, typed host controller, shared execution factory, bounded declarative
  plans with earlier-result bindings, deadline/preflight/fail-fast behavior and no Python eval.
- Source audit checkpoint: bounded JSON node count/64-bit integers/streamed encoding,
  structured rejection of invalid Unicode and oversized numeric inputs, nonempty matching
  mutation evidence enforced at registry and host boundaries, initial registry work cap.
- Scene revisions stream object snapshots; collection count/relationships and nested
  detail work have explicit limits. Collection pagination added; continuation pages require
  revisions. Scene text/page bytes/total animation points bounded. Foreign IDs resolve
  without allocating identities. Geometry loops preflight before materialization.
- Host payload/safety allowlist mirrors all 23 registered tools; remote catalog cannot
  downgrade safety. Plan destinations preflight, overlapping bindings and reused IDs fail,
  total binding/result budgets enforced, unbound payloads preflight, deadlines include
  capabilities. Partial reports retain prior results/unexecuted steps/unknown outcome.
- Bridge verifies loopback peers, denies concurrent calls, bounds serialized replay cache
  to 4 MiB, rejects reused request IDs and caches final deadline results consistently.
  Startup settings/secrets consumed before bpy import; cleanup exit failures structured.
- Output roots pinned to filesystem identity; replaced directories/linked files denied,
  reservation cleanup preserves replaced files. BLEND hashing streams 64 KiB chunks;
  PNG input capped at 4 MiB and unknown critical chunks rejected. Windows reserved
  superscript device names rejected. One local symlink test skipped (account permission).
- Primitive creation and mesh duplication compare actual geometry fingerprints/counts;
  duplicate verifies separate mesh and preserved material slots. Oversized/shape-key/
  modifier-stack duplicates denied before copying. Modifier addition rejects existing stacks
  and caps source geometry; collection creation caps memberships. Truncated targets denied.
- Discovery bounds directory enumeration before sorting; oversized directories are skipped
  deterministically with diagnostics. Explicit version probes cap captured output at 64 KiB
  using an ordinary pipe reader (no bpy); all tests inject fake process handles.

## Status
Source: 23 registered typed tools and host/orchestration interface. Unit tests: 180 passing,
1 skipped locally (symlink creation unsupported by account).
Lint/format: passing. Foundation wheel/sdist: built.
CI: plan checkpoint 58bc06a passed (run 37322326124); later checkpoints pending recheck.
Real Blender runtime verification: none. Production ready: no.

## Active work
Audit remaining adapters, large-scene inspection, plan preflight, bridge and output safety.
Next: tool reference, opt-in temporary-workspace runtime acceptance suite (do not run
against Blender), integration documentation, clean package install/content verification.

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
Complete source hardening and package/CI verification; update README/tool reference and
runtime acceptance checklist. Do not install/launch Blender. Phase 13 final integration
acceptance follows authorized runtime testing; the source client contract is available now.
Deletion stays deferred until runtime-verified checkpoint recovery. Never launch Blender.
Keep destructive deletion deferred until checkpoint/recovery exists. Do not launch Blender.
