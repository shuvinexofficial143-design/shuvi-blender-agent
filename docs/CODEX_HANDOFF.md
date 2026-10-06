# Codex handoff

Updated: 2026-10-06. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest verified pushed Level 1 source/package commit: 48bb15d3c065428aa7b13e4461c9fd6c96abd221.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Level 1 active checkpoint
Latest verified source checkpoint: 48bb15d3c065428aa7b13e4461c9fd6c96abd221.
CI run 37409190864 passed all six Linux/Windows Python 3.11/3.12/3.13 jobs, including
lint, format, 261 tests, package build, distribution checks and clean install/import without bpy.
The distribution audit verified 40 package modules. Real Blender runtime verification remains 0%.

Level 1 now exposes 55 typed host contracts/tools and the current Level 1 source roadmap is
**100% implemented**. The final source slice adds typed `mode.set`, destructive
`object.delete`, confined destructive `file.open_checkpoint`, project-wide session identity
rotation after checkpoint reopening, and an acceptance harness that covers the complete
Level 1 surface with separate render/destructive opt-ins.

Mode transitions are allowlisted by object type and require a selected, active, editable local
target plus fresh scene/object revisions. Destructive deletion requires explicit destructive
policy, refuses linked/overridden/read-only targets and parents with children, and verifies
absence from scene/data. Checkpoint reopening accepts only a verified regular BLEND file inside
the configured OutputWorkspace, then invalidates all old object IDs by rotating the session.

This completes **Level 1 source implementation at 100%**. It does not mean real Blender runtime
verification or production readiness is complete. Runtime acceptance remains 0% until the
explicitly authorized Blender 4.2+ suite is actually executed.

Next: no additional Level 1 source feature is required. The next phase is real Blender runtime
acceptance and then integration into main Shuvi, only after explicit authorization.

## Current phase
Original phases 1-11, source hardening and the complete Level 1 source roadmap are finished.
Level 1 source is at 100%. Phase 12 runtime acceptance remains prepared but unexecuted and
still requires explicit authorization.

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
- Host payload/safety allowlist mirrors all 55 registered tools; remote catalog cannot
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
- Wheel/sdist built from source; all 40 package modules, bootstrap, docs/tests/scripts/CI
  verified in archives. Fresh offline wheel install/imports/CLI smoke passed without bpy.
  CI now runs scripts/check_distribution.py after build; README included in wheel metadata.

## Status
Source: 55 typed host contracts/tools; Level 1 source **100% complete** for the current roadmap.
Unit/CI tests: 261 passed at 48bb15d3c065428aa7b13e4461c9fd6c96abd221.
Lint/format: passing. Wheel/sdist build, 40-module distribution audit and clean install/import
without bpy passed. CI run 37409190864 passed all six Linux/Windows Python 3.11/3.12/3.13
jobs. Real Blender runtime verification: none (0%). Production ready: no.

## Active work
Level 1 source work is complete at 100% for the current roadmap. No further Level 1 coding is
required before runtime acceptance. Real Blender execution, rendering and destructive recovery
tests remain opt-in and have not been authorized or run.

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
After explicit runtime authorization, run docs/RUNTIME_ACCEPTANCE.md in the disposable factory
workspace. First execute the non-render/non-destructive suite, then separately opt into tiny
render and destructive checkpoint-recovery cases as authorized. Record exact Blender/OS/Python
versions and verify mode transitions, Curve/Text, device updates, mesh transform/origin,
object deletion, checkpoint reopening/session rotation, rendering and cleanup. Until explicitly
authorized: do not install, probe, launch or render Blender.
