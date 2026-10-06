# Codex handoff

Updated: 2026-10-06. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest verified pushed Level 5 source/test commit: f14a111329b6815f9f96286e956d1db2a5762a4d.
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

## Level 2 active checkpoint
Latest verified Level 2 source checkpoint: 85c5872f75605de247edce25cea69c4fa90f8759.
CI run 37419984678 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **371 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **50 package modules**.

Level 2 Professional Modeling is now **100% source complete** against the current ten-milestone
roadmap. Milestone 10 adds:
- `modeling.qa_inspect`: aggregate bounded structural QA across geometry, repair, shading,
  retopology and modifier-stack state with blocker/advisory codes and a fresh `qa_revision`.
- `modeling.workflow_preview`: no-mutation preview for CLEAN_BASE_MESH and
  CLEAN_ORIENT_BASE_MESH, including initial triggered steps and explicit re-evaluation
  semantics after each mutation.
- `modeling.workflow_apply`: transactional composition of existing verified repair/orientation
  tools with fresh object/geometry/QA state, final QA invariants, complete initial
  geometry+smoothing capture and verified full-workflow recovery on later failure.
- runtime acceptance now has a separate `--allow-level2-modeling` opt-in that exercises a
  disposable Level 2 repair/QA/workflow/modifier-recipe path. The injected fake-session path
  is CI-tested but does not count as Blender runtime verification.

Known-failure recovery returns `rolled_back=true` / `recovery_verified=true` only after the
initial indexed geometry and per-face smoothing are read back successfully. Recovery failure
escalates to verification failure rather than claiming a known safe outcome. Existing metadata
guards remain active: the repair workflow does not silently discard shape keys, modifiers,
materials, UV/color layers or vertex groups.

The factory now exposes **91 typed tools**. Level 1 source remains 100% complete and the
current Level 2 source roadmap is also 100% complete.
No Blender install, launch, bpy runtime test or render was performed; real Blender runtime
verification for both levels remains 0%.

There is no additional required Level 2 source milestone in the current roadmap. Next choices
are separately authorized real Blender 4.2+ acceptance, integration into main Shuvi, or
starting the separately scoped Level 3 work.

## Level 3 final source checkpoint
Latest verified Level 3 source/test checkpoint: e9c818533d202028212fe2f888e839f405bdc042.
CI run 37427027522 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **445 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **60 package modules**.

Level 3 Sculpting + Character Modeling source roadmap is now **100% complete**
(Milestones 1-10 of 10).

Milestone 10 adds:
- `character.workflow_preview`: a fixed 12-stage end-to-end character workflow composition
  around existing Level 3 body/face planning, structural QA, recovery and recipe tools. It
  reports READY/REVIEW/BLOCKED and never auto-executes mutations.
- `character.level3_acceptance`: eight bounded source-side acceptance checks across body
  landmarks, body regions, face fit, face regions, face symmetry, structural sculpt QA,
  allowlisted recipe preview and surface baseline.
- explicit acceptance boundaries: source/fake-adapter scope only,
  `runtime_acceptance_required=true`, `real_runtime_verified=false`,
  `production_ready=false`.
- runtime acceptance preparation now has a separate `--allow-level3-character` opt-in. Its
  injected fake-session path creates a disposable symmetric mesh, runs Level 3 planning/QA,
  captures a bounded recovery patch, performs one controlled mirrored grab, verifies recovery,
  and exercises workflow/source-acceptance surfaces. This fake path does not count as Blender
  runtime verification.

The factory now exposes **126 typed tools**. Level 1 source is 100%, Level 2 source is 100%,
and Level 3 source is 100%. No Blender install, version probe, launch, bpy runtime test,
Sculpt Mode execution or render was performed while completing Level 3. Level 3 real Blender
runtime verification remains **0%** and production readiness remains **No**.

There is no additional required Level 3 source milestone in the current roadmap. Level 4 has
now been explicitly started by the user.

## Level 4 active checkpoint
Latest verified Level 4 source/test checkpoint: 0d139c038db86a00590c15971ace2f88991e9da9.
CI run 37449038646 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **527 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **66 package modules**.

Level 4 UV / Texture / Materials is now **100% source complete** (Milestones 1-10 of 10).

Milestones 1-8 remain the bounded UV diagnostics/editing/packing/texel-density, material-slot,
Principled shader and typed PBR channel foundation documented in LEVEL_4_UV_MATERIALS.md.

Milestone 9 adds:
- `texture.image_inspect`: bounded metadata for one existing local image, including size,
  colorspace, tiled/packed state and up to 256 UDIM tile numbers without exposing filepath.
- `texture.udim_plan`: source-only face-to-UDIM planning with deterministic tile-boundary,
  split-face and out-of-range diagnostics.
- `texture.channel_qa`: seven-channel managed PBR image/colorspace/link and normal-chain QA.
- `texture.consistency_qa`: image-dimension and cross-channel reuse diagnostics.
- `texture.bake_prep`: material assignment, UV overlap/degeneracy, UDIM and channel readiness
  checks; planning only, no Blender bake execution.

Milestone 10 adds:
- `texture.recovery_snapshot`: bounded Shuvi-managed Principled/Normal/Bump/PBR state with a
  deterministic recovery revision.
- `texture.recovery_restore`: strict managed-state restore requiring fresh shader state,
  referenced image/colorspace validation, readback verification and verified fallback rollback.
- `texture.asset_qa`: aggregate UV/material/texture PASS/REVIEW/BLOCKED structural QA.
- `texture.workflow_preview`: fixed ten-stage non-mutating Level 4 workflow.
- `texture.level4_acceptance`: eight source/fake-adapter acceptance checks with deterministic
  acceptance revision and explicit runtime-required / not-production-ready boundaries.
- runtime_acceptance.py now exposes a separately gated `--allow-level4-textures` path behind
  `--authorize-runtime`; injected fake-session CI covers it but does not count as real runtime.

The factory now exposes **155 typed tools** under the centralized **160-tool** hard
registry/catalog cap. No arbitrary Python, unrestricted node/material operator, filesystem
image-loading surface, real bake execution or hidden runtime/production claim was introduced.

Level 1 source is 100%, Level 2 source is 100%, Level 3 source is 100%, and Level 4 source is
100%. No Blender install/probe/launch, bpy runtime test, real Blender UV/material/texture/bake
execution, render or GPU-heavy action was performed. Level 4 real Blender runtime verification
remains 0% and production readiness remains No.

There is no additional required Level 4 source milestone in the current roadmap. Do not
silently create Milestone 11. Next scope must be explicitly selected as Level 5 Geometry Nodes,
integration into main Shuvi, or separately authorized real Blender 4.2+ Level 4 acceptance.

## Level 5 active checkpoint
Latest verified Level 5 source/test checkpoint: f14a111329b6815f9f96286e956d1db2a5762a4d.
CI run 37495296260 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **659 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **72 package modules**.

Level 5 Geometry Nodes is now **80% source complete** (Milestones 1-8 of 10).

Milestones 1-7 remain the bounded GeometryNodeTree inspection, typed node creation/default
editing, typed link/recovery, NODES modifier binding, procedural primitives, attribute/field
workflows and scatter systems documented in LEVEL_5_GEOMETRY_NODES.md.

Milestone 8 adds:
- `geometry_nodes.architecture_preview`: deterministic source-only plans for exactly
  MODULAR_WALL and BLOCK_GRID.
- MODULAR_WALL repeats bounded cube modules along X with module size 0.001..1000, count 1..16,
  gap 0..1000 and base offset within ±1000.
- BLOCK_GRID repeats bounded cubes on an XY grid with per-axis counts 1..6 and a hard total
  module limit of 24. Size, gaps and base offset are independently bounded.
- every module uses one Mesh Cube plus one Transform Geometry; all transformed outputs feed one
  Join Geometry multi-input socket and then one Group Output.
- cube vertex counts are fixed at 2 per axis; transform rotation is fixed zero and scale fixed
  one. No external object, collection, asset-library or material references are accepted.
- worst-case BLOCK_GRID uses 24 modules and exactly 50 nodes, staying under the existing
  64-node Geometry Nodes source work limit.
- `geometry_nodes.architecture_apply`: fresh group revision, completely empty local tree and
  at-most-one-user guard. It verifies exact interface, node names/types/locations, selected
  defaults and complete link topology.
- known apply verification failure removes the full managed architecture graph/interface and
  verifies restoration of the original empty group revision.
- `geometry_nodes.architecture_clear`: requires an exact current recipe/prefix/parameter
  match; changed size/spacing/translation/links/interfaces or foreign nodes fail closed. Known
  clear failure rebuilds the exact architecture graph and verifies the original group revision.

The centralized registry/client hard cap was deliberately raised from **176 to 184**.
Milestone 8 adds three typed operations, taking the factory to **177 tools**. No generic
architecture graph executor, unrestricted repetition surface or Python execution was added.

Level 1 source is 100%, Level 2 source is 100%, Level 3 source is 100%, Level 4 source is
100%, and Level 5 source is 80%. No Blender install/probe/launch, bpy runtime test, real
Geometry Nodes architecture evaluation, render or GPU-heavy action was performed. Level 5
real Blender runtime verification remains 0% and production readiness remains No.

Milestone 9 — Geometry Nodes recipe library — is next, but must not start without explicit
user permission.

## Current phase
Level 1 source is complete at 100%. Level 2 Professional Modeling source is 100% complete.
Level 3 Sculpting + Character Modeling source is **100% complete** (Milestones 1-10 of 10).
Level 4 UV / Texture / Materials source is **100% complete** (Milestones 1-10 of 10).
Level 5 Geometry Nodes source is **80% complete** (Milestones 1-8 of 10).
Real Blender runtime acceptance remains prepared but unexecuted pending explicit authorization.

## Completed and verified
- Fetched actual remote main at 9a5b848 and reconciled the Milestone 3 starting state;
  preserved concurrent work and checked latest main before the Level 5 checkpoint.
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
- Host payload/safety allowlist mirrors all 177 registered tools; remote catalog cannot
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
- Wheel/sdist built from source; all 72 package modules, bootstrap, docs/tests/scripts/CI
  verified in archives. Fresh offline wheel install/imports/CLI smoke passed without bpy.
  CI now runs scripts/check_distribution.py after build; README included in wheel metadata.

## Status
Source: 177 typed host contracts/tools under the bounded 184-tool cap. Level 1 source: **100%**.
Level 2 modeling source: **100%**. Level 3 sculpting/character-modeling source: **100%**.
Level 4 UV/texture/materials source: **100%**. Level 5 Geometry Nodes source: **80%**
(Milestones 1-8 of 10). Verified Level 5 source/test checkpoint:
f14a111329b6815f9f96286e956d1db2a5762a4d. CI run 37495296260 passed all six
Linux/Windows Python 3.11/3.12/3.13 jobs with 659 tests, lint/format, package build,
72-module distribution audit and clean install/import without bpy.
Real Blender runtime verification: none (0%). Production ready: no.

## Active work
Level 5 Milestones 1-8 are complete at 80%. Stop here. Do not begin Milestone 9 without
explicit user permission. Keep source/fake evidence separate from real Blender runtime
verification.

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
None for the completed 80% source checkpoint. The registry/client cap is deliberately bounded
at 184 with 177 tools registered. Heavy Blender runtime actions still require separate user
authorization.

## Exact next task
Wait for explicit user permission. If the user asks to continue Level 5, start only Milestone 9:
Geometry Nodes recipe library. Build a bounded catalog over already-supported managed recipe
families rather than exposing arbitrary graph execution. Require explicit typed recipe IDs and
bounded parameter schemas, deterministic preview metadata, compatibility/version markers,
fresh tree state for mutation, exact source readback and verified recovery. Do not start
Milestone 10 automatically. Do not install, probe, launch, render or execute Blender runtime
acceptance unless the user separately authorizes it.
