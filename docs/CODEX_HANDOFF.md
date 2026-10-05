# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest verified pushed Level 1 source/package commit: 09fc38034e8d82d2dbd9b2e3a15c366de8e61bc0.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Level 1 active checkpoint
Latest verified source checkpoint: 09fc38034e8d82d2dbd9b2e3a15c366de8e61bc0.
All six Linux/Windows Python 3.11/3.12/3.13 CI jobs passed, including package build,
distribution checks and clean install/import without bpy. 230 tests passed.

Level 1 now includes expanded bounded mesh primitives; rename/display properties; full and
partial transforms; independent and linked mesh duplication; visibility; selection/active
state; parent/unparent with cycle rejection; hierarchy and origin inspection; collection
inspect/rename/link/unlink/move/child creation with orphan, scene-reachability, hierarchy-depth and linked-collection guards;
cursor, scene-name, units, pivot and mode inspection; scene object-type counts/world
presence; bounded data-block and constraint summaries. Host allowlist currently has 46
typed tools. Real Blender runtime verification remains 0%.

Level 1 source is approximately 84% against the broad roadmap. Remaining items are mainly
context-sensitive operations intentionally deferred without real Blender: mode mutation,
apply transforms, origin mutation, Curve/Text primitive workflows, destructive deletion
and destructive project switching. Current documentation checkpoints follow the verified
source commit and should not be treated as runtime evidence.

Next: finish Level 1 documentation/package consistency and keep runtime-sensitive operations
deferred until explicit Blender authorization.

## Current phase
Original phases 1-11 and source hardening are complete. Level 1 broad-control source
expansion is in final documentation/package-audit work. Phase 12 runtime suite/checklist is
prepared, but actual Blender acceptance still awaits explicit authorization.

## Completed and verified
- Fetched actual remote main at acf13dc and reconciled the prior session's identical local
  client/plan files without discarding work. Checked latest main before every checkpoint.
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
- TOOL_REFERENCE.md, RUNTIME_ACCEPTANCE.md and SOURCE_AUDIT.md added; README and existing
  operation/client/bridge/discovery docs synchronized. Stable capability metadata exposed
  and validated by the controller, with independent returned copies.
- runtime_acceptance.py prepared: explicit authorization guard, disposable factory project,
  all principal tools, bounded plan and separate tiny-render opt-in, cleanup evidence.
  Harness tested with injected fake sessions only; injected sessions cannot claim real runtime.
- Final response boundaries clone validated result data before comparison/return, bound
  structured public errors, sanitize capability exceptions, and flag partial mutation
  exceptions as unknown outcomes. PNG palette/reserved-bit validation strengthened.
- Wheel/sdist built from source; all 27 package modules, bootstrap, docs/tests/scripts/CI
  verified in archives. Fresh offline wheel install/imports/CLI smoke passed without bpy.
  CI now runs scripts/check_distribution.py after build; README included in wheel metadata.

## Status
Source: 46 typed host contracts/tools including the Level 1 broad-control expansion.
Unit/CI tests: 230 passed at 09fc38034e8d82d2dbd9b2e3a15c366de8e61bc0.
Lint/format: passing. Wheel/sdist build, distribution contents and clean install/import
without bpy passed. CI run 37339239729 passed all six Linux/Windows Python 3.11/3.12/3.13
jobs. Documentation checkpoints after that source commit have their own CI runs.
Real Blender runtime verification: none (0%). Production ready: no.

## Active work
Level 1 documentation/package consistency and final source audit. No Blender runtime work is
authorized. Context-sensitive mode/apply/origin/destructive operations remain deliberately
deferred rather than being simulated as runtime-verified behavior.

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
Finish Level 1 docs/package audit and stop at the source/runtime boundary for operations that
cannot be honestly validated without Blender. With later explicit runtime authorization,
follow docs/RUNTIME_ACCEPTANCE.md in its disposable factory workspace. Rendering needs
separate authorization/flag. Then validate mode changes, apply/origin workflows, checkpoint
reopening/recovery and main Shuvi integration. Deletion stays deferred until recovery is
runtime-verified. Until explicitly authorized: do not install, probe, launch or render Blender.
