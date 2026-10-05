# Codex handoff

Updated: 2026-10-05. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest verified pushed source/package commit: bbd14094b50ba8d7fa3260c9974a540344cc13f4.
The commit containing this file is the current checkpoint; resolve it with git log -1.
A commit cannot contain its own SHA. Later checkpoints record the preceding verified pushed SHA.

## Level 1 active checkpoint
Latest preceding push: 1e0f86120e12dd6425293d4c2055b9b7aa5f2703 (primitives).
Added object.rename, object.set_properties, object.patch_transform, object.set_visibility,
selection.set and selection.inspect; strict host allowlist and readback. Object revisions now
include selected state, display properties, constraint and data summaries; scene revision
includes mode, active/selection state and view-layer name. 211 local tests passed, 1 skipped.
Level 1 source approximately 50%; runtime 0%. Current checkpoint CI pending.
Next: hierarchy/collections and scene/cursor controls, mode contracts, documentation/package audit.
Earlier completion below describes the prior source-hardening pass, not Level 1.

## Current phase
Phases 1-11 initial bounded source capabilities implemented. Source hardening pass complete;
unit, package and all six CI matrix jobs verified. This checkpoint records the final evidence.
Phase 12 suite/checklist prepared. Actual Blender acceptance awaits explicit authorization.

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
Source: 23 registered typed tools and host/orchestration interface. Unit tests: 194 passed
on Linux/Windows CI; locally 193 passed, 1 skipped (symlink creation unsupported by account).
Lint/format: passing. Current wheel/sdist: built and contents/clean offline install verified.
CI: bbd14094b50ba8d7fa3260c9974a540344cc13f4 passed all six jobs, including package smoke:
https://github.com/shuvinexofficial143-design/shuvi-blender-agent/actions/runs/37328700111
Linux/Windows Python 3.11/3.12/3.13. Every preceding checkpoint this pass also passed.
This documentation checkpoint's own CI can be resolved in Actions from git log -1.
Real Blender runtime verification: none. Production ready: no.

## Active work
Source work complete and checkpointed. No unfinished local source work. Real Blender,
checkpoint reopen/recovery and production acceptance remain future work.

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
With later explicit runtime authorization, follow docs/RUNTIME_ACCEPTANCE.md and run the opt-in suite
in its factory-startup temporary workspace. Rendering needs separate authorization/flag.
Then add independent checkpoint reopening/recovery acceptance and main Shuvi integration
acceptance. Preserve source/runtime/CI/production distinctions. Deletion stays deferred.
Until the user explicitly authorizes runtime: do not install, probe, launch or render Blender.
