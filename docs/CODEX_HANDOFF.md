# Codex handoff

Updated: 2026-10-08. Remote: shuvinexofficial143-design/shuvi-blender-agent, branch main.

## Checkpoint
Latest verified pushed Level 7 source/test commit: 6bd1384583bc1b1255e62799314c18de04965275.
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
Latest verified Level 5 source/test checkpoint: 8b1f51facf2b523c3c220236e0a8dbe15e28cdcf.
CI run 37501230888 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **711 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **74 package modules**.

Level 5 Geometry Nodes is now **100% source complete** (Milestones 1-10 of 10).

Milestones 1-9 remain the bounded GeometryNodeTree inspection, typed node creation/default
editing, typed link/recovery, NODES modifier binding, procedural primitives, attribute/field
workflows, scatter systems, architecture/environment recipes and managed recipe library
documented in LEVEL_5_GEOMETRY_NODES.md.

Milestone 9 adds:
- `geometry_nodes.recipe_catalog`: deterministic versioned catalog of exactly 10 managed
  recipe IDs spanning primitive, field, scatter and architecture families.
- every descriptor exposes family mapping, recipe/library version 1, minimum Blender version
  4.2, compatibility marker SOURCE_VALIDATED_RUNTIME_UNVERIFIED, bounded parameter schema,
  supported preview/apply/clear operations, source-only and runtime-unverified flags.
- catalog order is deterministic and covered by one deterministic catalog revision.
- `geometry_nodes.recipe_preview`: known recipe IDs only. Validation and normalization route
  through the existing family parser, then the existing family preview result is wrapped
  unchanged with versioned recipe metadata.
- `geometry_nodes.recipe_apply`: preserves the existing family mutation parser and operation,
  including fresh group revision, empty/shared-group guards, exact readback, verified status and
  rollback/recovery behavior.
- `geometry_nodes.recipe_clear`: routes cleanup through the exact managed family clear path so
  family-specific exact-match and rebuild/recovery rules remain authoritative.
- source tests compare recipe-library previews with direct family previews and execute verified
  apply→clear round trips for all 10 managed recipe IDs.
- Geometry Nodes recipe host parser imports are explicitly aliased away from the pre-existing
  modeling RecipeApply/RecipePreview names, preventing host-contract parser shadowing.
- no arbitrary recipe registration, dynamic import, file-backed recipe loading, remote recipe
  source, arbitrary node ID or generic graph payload is exposed.

Milestone 9 adds four typed tools, taking the factory from 177 to **181 tools** under the
existing bounded **184-tool** registry/client cap.

Milestone 10 adds:
- `geometry_nodes.workflow_preview`: fixed nine-stage read-only Level 5 workflow composition over
  catalog verification, direct-family preview equivalence, fresh-state mutation gates, exact
  readback, stale/cross-family negative gates, recovery expectations and final acceptance.
- `geometry_nodes.level5_acceptance`: seven-check source/fake-bpy acceptance report covering
  the fixed ten-recipe catalog, version/compatibility metadata, four-family routing, recipe
  membership, direct preview equivalence, graph bounds and explicit runtime separation.
- all 10 managed recipe IDs are exercised through final acceptance tests.
- representative primitive, field, scatter and architecture recipes verify stale-revision
  refusal and recipe-wrapper rollback/recovery consistency.
- cross-family parameter payloads fail closed through the existing typed family parsers.
- Milestone 10 adds two read-only tools, taking the factory from 181 to **183 tools** under the
  existing bounded **184-tool** registry/client cap.

Level 1 source is 100%, Level 2 source is 100%, Level 3 source is 100%, Level 4 source is
100%, and Level 5 source is 100%. No Blender install/probe/launch, bpy runtime test, real
Geometry Nodes evaluation, render or GPU-heavy action was performed. Level 5 real Blender
runtime verification remains 0% and production readiness remains No.

Milestone 10 — Geometry Nodes QA / recovery / acceptance — is complete. Do not begin Level 6
without explicit user permission.

## Level 6 active checkpoint
Latest verified Level 6 source/test checkpoint: 8b1f76baebcb02bd285e95dd8754df4fb9e787d4.
CI run 37657039445 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **807 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **77 package modules**.

Level 6 Rigging is now **100% source complete** (Milestones 1-10 of 10).

Milestone 1 adds:
- `rig.armature_inspect`: one bounded read-only armature/pose inspection surface using a
  current-session object ID.
- exact bounded armature hierarchy readback: names, parents, local head/tail, optional local
  matrix, connect/deform flags and inherit-scale mode.
- bounded pose readback: location, Euler/quaternion rotation, scale and pose-constraint
  name/type/mute/influence metadata.
- root-bone reporting, hierarchy-cycle diagnostic, pose/data name mismatch diagnostics and one
  deterministic `rig_revision`.
- fail-closed limits of 256 armature bones, 256 pose bones, 64 constraints per pose bone and
  512 total pose constraints.
- non-finite coordinate/matrix/influence values fail closed.
- no armature/bone creation, edit/pose mutation, constraint creation, IK, skin binding, weight
  editing, arbitrary Python or unrestricted bpy operation was added.
- Milestone 1 adds one read-only tool, taking the factory from 183 to **184 tools**.
- the centralized registry/client hard cap is raised from 184 to **192** for later bounded
  Level 6 milestones.

Milestone 2 adds:
- `rig.armature_create`: fresh-scene-revision-gated creation of one empty local armature
  datablock and one scene-linked ARMATURE object with exact transform/object/rig readback and
  cleanup on verification mismatch.
- `rig.bone_create`: fresh ObjectTarget + fresh `rig_revision` gated creation of one
  standalone root edit bone with bounded head/tail coordinates and optional deform flag.
- bone creation requires an editable local armature in Object mode, selected and active, then
  uses only the bounded internal Object → Edit Armature → Object transition required by Blender.
- bone name is unique and bounded; head/tail coordinates are limited to ±100000 and must differ.
- parent remains null and `use_connect=false`; parenting/connect/rename/symmetry are deferred
  to Milestone 3.
- successful source readback verifies +1 bone count, exact name/head/tail/deform state, root
  status, disconnected state, same object identity and final Object mode.
- known verification mismatch removes only the just-created bone and verifies recovery to the
  original `rig_revision`.
- Milestone 2 adds two mutation tools, taking the factory from 184 to **186 tools** under the
  existing bounded **192-tool** registry/client cap.

Milestone 3 adds:
- `rig.bone_hierarchy_edit`: fresh ObjectTarget + fresh `rig_revision` gated parent/connect/
  rename editing for one explicit bone with unique-name checks and complete hierarchy-cycle
  preflight before mutation.
- connected hierarchy edits explicitly snap the child head to the requested parent's tail and
  verify final name, parent, connect state, expected coordinates/deform state, unchanged count,
  same object identity, Object mode and no hierarchy cycle.
- hierarchy verification failure restores original name, parent, head, tail and connect state
  and verifies recovery to the original `rig_revision`.
- `rig.bone_symmetry_edit`: explicit matching `.L` / `.R` pair editing that mirrors bounded
  left head/tail coordinates across local X; fuzzy counterpart discovery and global mirror
  operators are not exposed.
- symmetry editing requires disconnected bones, preserves parent/deform state, verifies both
  exact coordinate results and restores both bones on known verification mismatch.
- Milestone 3 adds two mutation tools, taking the factory from 186 to **188 tools** under the
  bounded **192-tool** cap.

Milestone 4 adds:
- `rig.pose_bone_transform`: fresh ObjectTarget + fresh `rig_revision` gated mutation of one
  explicit existing pose bone's raw location/rotation/scale channels.
- rotation mode is explicitly `XYZ` or `QUATERNION`; Euler components are bounded to ±1000
  radians, quaternion components are bounded to [-1,1], zero quaternion is rejected and accepted
  quaternions are normalized deterministically before exact readback verification.
- pose location components are bounded to ±100000 Blender units and scale components are finite
  positive values in [0.001,1000].
- known pose-transform verification mismatch restores rotation mode, location, Euler rotation,
  quaternion rotation and scale and verifies recovery to the original `rig_revision`.
- `rig.pose_bone_reset`: fresh-revision-gated identity reset for one explicit pose bone to
  quaternion mode, zero location/Euler rotation, identity quaternion and unit scale, with exact
  readback and complete pose-state rollback on known verification mismatch.
- pose constraints are not created/changed/removed; constraints and IK remain Milestone 5.
- Milestone 4 adds two mutation tools, taking the factory from 188 to **190 tools** under the
  bounded **192-tool** cap.

Milestone 5 adds:
- `rig.pose_constraint_create`: fresh ObjectTarget + fresh `rig_revision` gated creation of
  one explicit unique pose constraint, restricted to `LIMIT_ROTATION` and same-armature `IK`.
- common constraint state is bounded to explicit name, influence in [0,1] and mute state; existing
  caps remain 64 constraints per pose bone and 512 total pose constraints.
- `LIMIT_ROTATION` requires all X/Y/Z enable/min/max values, with finite ±1000-radian bounds
  and minimum <= maximum validation.
- `IK` requires one explicit different target pose bone in the same armature and chain count
  1..64; arbitrary target objects, pole targets and generic solver/settings payloads are not
  exposed.
- successful creation verifies full managed state, per-bone/total counts, object identity and
  Object mode; mismatch removes the exact created constraint and verifies original revision.
- `rig.pose_constraint_remove`: removes an explicit expected managed constraint only when it is
  final in the pose-bone constraint stack, preserving exact ordering for append-based rollback.
- bounded removal mismatch recreates the exact managed snapshot and verifies recovery to the
  original `rig_revision`.
- Milestone 5 adds two mutation tools, taking the factory from 190 to **192 tools**, exactly at
  the current bounded **192-tool** registry/client cap.

Milestone 6 adds:
- `rig.mesh_armature_bind`: fresh mesh ObjectTarget + fresh armature ObjectTarget + fresh
  `rig_revision` gated creation of exactly one explicit `ARMATURE` modifier.
- binding requires local editable Object-mode objects/data, an unparented mesh, no shape keys,
  no vertex groups, an empty modifier stack, and bounded mesh work of at most 4096 vertices,
  4096 polygons and 32768 polygon indices.
- the managed modifier targets exactly the supplied armature object and fixes
  `use_vertex_groups=true`, `use_bone_envelopes=false`, viewport/render enabled.
- Milestone 6 intentionally does not parent the mesh, create groups/weights, invoke automatic
  weights, use envelopes or expose generic modifier settings.
- bind readback verifies mesh identity, armature identity, exact modifier settings/count,
  unchanged parent state and unchanged armature `rig_revision`; mismatch removes the exact
  created modifier and verifies both original revisions.
- `rig.mesh_armature_unbind`: removes only the sole exact M6-managed ARMATURE modifier from an
  unparented zero-group mesh; mismatch recreates the managed modifier and verifies recovery.
- the zero-group unbind restriction is intentional until Milestone 7 owns vertex-group/weight
  workflows.
- Milestone 6 raises the bounded registry/client cap from 192 to **200** and adds two mutation
  tools, taking the factory from 192 to **194 tools**.

Milestone 7 adds:
- `rig.mesh_weights_inspect`: bounded read-only inspection of one managed M6-bound mesh/armature
  pair, including exact group order/indices, sparse vertex weights, mismatch diagnostics,
  deterministic `weight_revision` and current `rig_revision`.
- inspection caps remain 4096 vertices, 4096 polygons and 32768 polygon indices and additionally
  cap 64 groups, 64 memberships per vertex and 16384 total sparse assignments.
- malformed/noncontiguous group indices, unknown memberships, non-finite weights or weights
  outside [0,1] fail closed.
- `rig.vertex_group_weights_set`: fresh mesh/armature ObjectTargets + fresh rig/weight revisions
  gated full replacement of one deform-bone-matched vertex group's sparse map.
- set accepts 1..4096 unique actual vertex indices and weights in 0.000001..1.0; absent matching
  groups can be appended under the 64-group cap.
- existing groups must all correspond to deform-enabled armature bones; arbitrary group names,
  automatic weights, envelopes, normalization, transfer and generic Weight Paint operations are
  not exposed.
- successful set verifies exact group index/name/weights, group/assignment counts, identities,
  Object mode and unchanged `rig_revision`; mismatch restores the original `weight_revision`.
- `rig.vertex_group_remove`: removes only an explicit deform-bone-matched **final** group so
  append-based recovery preserves group ordering; mismatch recreates exact sparse weights.
- Milestone 7 adds three tools, taking the factory from 194 to **197 tools** under the existing
  bounded **200-tool** registry/client cap.

Milestone 8 adds:
- `rig.ik_fk_preview`: read-only validation/reporting for one explicit upper → middle → end
  deform chain plus one distinct non-deforming control target, including managed helper state,
  current IK/FK mode and current `rig_revision`.
- chain names must be four distinct existing data+pose bones; hierarchy must be exact and the
  control target must be non-deforming.
- `rig.ik_fk_setup`: fresh ObjectTarget + fresh `rig_revision` gated creation of exactly one
  managed same-armature IK constraint on the end bone with influence 1.0 and chain count 3.
- setup accepts explicit initial mode: IK leaves the constraint unmuted; FK mutes it.
- helper setup does not create bones, pole targets, drivers, custom properties, arbitrary
  constraint types or automatic rig structures. Existing bounded bone creation can create the
  non-deforming target/control bone when needed.
- `rig.ik_fk_switch`: accepts only the recognized managed helper and changes only its mute field
  between IK and FK. No pose channels, weights, hierarchy or constraint topology are changed.
- setup mismatch removes the exact created constraint; switch mismatch restores the original mute
  state; both verify recovery to the original `rig_revision`.
- existing `rig.pose_constraint_remove` is the cleanup path.
- Milestone 8 adds three tools, taking the factory from 197 to **200 tools**, exactly at the
  current bounded **200-tool** registry/client cap.

Milestone 9 adds:
- `rig.recipe_catalog`: deterministic versioned catalog for exactly three fixed managed recipes:
  bounded LIMIT_ROTATION, bounded same-armature IK and the managed three-bone IK/FK helper.
- library/recipe version 1, minimum Blender 4.2 marker, explicit
  `SOURCE_VALIDATED_RUNTIME_UNVERIFIED` compatibility and deterministic catalog revision.
- `rig.recipe_preview`: fresh ObjectTarget + fresh `rig_revision` gated read-only planning that
  reuses existing Milestone 5/Milestone 8 validators and reports deterministic blockers/plan.
- `rig.recipe_apply`: delegates only to existing verified pose-constraint creation or IK/FK
  setup paths, preserving their exact readback, stale-state rejection and rollback/recovery.
- recipe `parameters` are exact-schema validated; unknown/missing/untyped fields fail closed.
- no dynamic executable recipes, arbitrary Python/bpy/property paths, automatic rig generation,
  pole targets, drivers, custom properties or generic solver payloads are exposed.
- Milestone 9 raises the bounded registry/client cap from 200 to **203** and adds three tools,
  taking the factory from 200 to **203 tools**.

Milestone 10 adds:
- an internal `rig_acceptance.py` source/fake-bpy acceptance harness over the existing M1-M9
  rigging surfaces without adding a public protocol tool.
- the registry/client remains exactly **203/203 tools**; no cap increase is used for QA-only work.
- final acceptance requires bounded armature structure, exact managed M6 binding, non-empty
  deform-bone-matched M7 weights, the fixed M9 recipe catalog and a fresh managed M8/M9
  three-bone IK/FK preview inside the same inspector/session.
- stale state is proven to fail closed, and forced IK/FK readback mismatch is proven to remove
  the created constraint, report verified recovery and allow the recovered rig to pass the final
  acceptance harness again.
- runtime/production boundaries remain explicit: source/fake-bpy acceptance is not real Blender
  execution.

Level 6 real Blender runtime verification remains 0%. Production readiness remains No.

Milestone 10 — Rigging QA / recovery / acceptance — is complete. Do not begin Level 7 without
explicit user permission.

## Current phase
Level 1 source is complete at 100%. Level 2 Professional Modeling source is 100% complete.
Level 3 Sculpting + Character Modeling source is **100% complete** (Milestones 1-10 of 10).
Level 4 UV / Texture / Materials source is **100% complete** (Milestones 1-10 of 10).
Level 5 Geometry Nodes source is **100% complete** (Milestones 1-10 of 10).
Level 6 Rigging source is **100% complete** (Milestones 1-10 of 10).
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
- Host payload/safety allowlist mirrors all 203 registered tools; remote catalog cannot
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
- Wheel/sdist built from source; all 77 package modules, bootstrap, docs/tests/scripts/CI
  verified in archives. Fresh offline wheel install/imports/CLI smoke passed without bpy.
  CI now runs scripts/check_distribution.py after build; README included in wheel metadata.

## Level 7 active checkpoint
Latest verified Level 7 source/test checkpoint: 9a8446ff949c7d0441106201bf96b3059c503ec2.
CI run 37753381630 passed the Linux/Windows Python 3.11/3.12/3.13 matrix with lint,
format, **864 tests**, package build, distribution audit and clean install/import without bpy.
The distribution audit verified **84 package modules**.

Level 7 Advanced Animation is now **80% source complete** (Milestones 1-8 of 10).

Milestone 1 adds:
- `animation.inspect`: one bounded read-only Action/FCurve/keyframe inspection surface using a
  current-session object ID.
- exact supported Action state including Action API/name/users/session ownership, up to 64
  FCurves, up to 1024 keyframe points, unique sorted frames, frame range and interpolation counts.
- deterministic `animation_revision` over the exact bounded animation state.
- bounded diagnostics for drivers/NLA and mutation blockers covering non-local/read-only state,
  object constraints, non-Object mode, drivers, NLA tracks, foreign Actions and shared Actions.
- truncated or unsupported layered Action structures fail closed instead of producing a partial
  revision suitable for later mutation.
- no new keyframe overwrite/remove/edit, FCurve handle/easing mutation, pose animation, NLA
  mutation or arbitrary Python/bpy operation is exposed.
- Milestone 1 raises the registry/client cap from 203 to **204** and adds one read-only tool,
  taking the factory from 203 to **204 tools**.

Milestone 2 adds:
- three bounded public mutation surfaces: `animation.edit_keyframe`,
  `animation.remove_keyframe` and `animation.replace_keyframe`.
- all M2 mutations require a fresh ObjectTarget plus exact current `animation_revision`.
- mutation is restricted to one session-created unshared Action containing exactly the nine
  managed transform FCurves (location/rotation_euler/scale XYZ).
- single-channel edit changes only value/interpolation at one exact existing frame.
- remove requires all nine transform points at a frame and proves exact frame absence plus a
  nine-point count reduction.
- replace requires all nine points and changes only values/interpolation at the existing frame.
- stale animation revisions fail closed even with a newly refreshed ObjectTarget.
- forced verification mismatch is tested to restore the complete pre-mutation keyframe snapshot,
  recover the original `animation_revision` and report verified rollback.
- generic FCurve scripting, arbitrary data paths, handles/easing controls, pose animation and NLA
  mutation remain out of scope for M2.
- Milestone 2 raises the registry/client cap from 204 to **207** and adds three typed mutation
  tools, taking the factory from 204 to **207 tools**.

Milestone 3 adds:
- `animation.keyframe_style_set`: one bounded mutation surface for an exact existing managed
  transform-channel point.
- M1 inspection/revision now includes easing, handle types and left/right handle coordinates.
- interpolation support expands to CONSTANT, LINEAR, BEZIER plus bounded easing families SINE,
  QUAD, CUBIC, QUART, QUINT, EXPO, CIRC, BACK, BOUNCE and ELASTIC.
- easing is allowlisted to AUTO/EASE_IN/EASE_OUT/EASE_IN_OUT and irrelevant easing is rejected.
- Bezier handle types are bounded to FREE/VECTOR/AUTO/AUTO_CLAMPED; exact coordinates are accepted
  only for FREE handles with side/frame/value bounds.
- non-Bezier styles reject manual handles.
- M2 recovery snapshots now preserve M3 style state so rollback cannot silently lose handles or
  easing.
- stale animation revisions fail closed and forced verification mismatch is tested to recover the
  exact previous style-aware animation revision.
- M3 raises the registry/client cap from 207 to **208** and adds one typed mutation tool.
- generic FCurve modifiers/extrapolation, arbitrary data paths, pose animation and NLA mutation
  remain out of scope.

Milestone 4 adds:
- `animation.retime_preview` and `animation.retime_apply` for bounded multi-key timeline
  workflows over complete managed transform keys.
- each request accepts 1..32 explicit source→target integer frame mappings with unique sources and
  unique targets.
- target collisions fail closed unless the occupied target frame is itself included in the same
  move set as a source, allowing simultaneous swaps/chains without unrelated overwrite.
- preview performs the same completeness/collision checks as apply and reports the exact resulting
  frame set without mutation.
- apply moves all nine managed transform points per key and preserves values, interpolation,
  easing and handle types; handle X coordinates shift by the same frame delta.
- post-mutation verification requires unchanged point count, exact resulting frames and exact
  moved-point style/value readback.
- forced verification mismatch is tested to restore the complete pre-retime snapshot and original
  animation revision.
- M4 raises the registry/client cap from 208 to **210** and adds two typed tools.
- fractional remapping, evaluated motion, pose animation, NLA editing and generic FCurve scripting
  remain out of scope.

Milestone 5 adds:
- `animation.pose_bone_inspect` for one exact named bone's raw animation channels, current
  rig revision, full animation revision, channel completeness and pose-animation revision.
- `animation.pose_bone_keyframe_insert` for one complete raw pose key using XYZ Euler or
  normalized Quaternion rotation plus location/scale.
- pose insertion requires a fresh ObjectTarget, exact rig revision and exact animation revision.
- the first pose key may create a Shuvi-owned Action; subsequent pose keys may extend only an
  unshared session-owned pose-only Action.
- non-pose Action channels, foreign Actions, mixed alternate rotation channels, partial channel
  sets and same-bone frame collisions fail closed.
- existing global 64-FCurve / 1024-point limits remain authoritative.
- source verification checks every inserted point, requested interpolation, Action ownership and
  raw pose state.
- forced verification failure is tested to remove the inserted key, restore pose state and recover
  both the prior rig revision and prior animation revision, including clearing a newly-created
  Action when the operation began with no Action.
- M5 raises the registry/client cap from 210 to **212** and adds two typed tools.
- evaluated pose/constraints/IK, pose-key edit/remove/retime, baking and NLA remain out of scope.

Level 7 real Blender runtime verification remains 0%. Production readiness remains No.

Milestone 5 — pose-bone animation channels — is complete.

Milestone 6 adds:
- `camera.optics_animation_inspect` and `camera.optics_keyframe_insert` over the separate camera
  datablock lens and DOF focus-distance Action; object movement Action remains untouched.
- fresh ObjectTarget plus exact `camera_animation_revision` (including unkeyed lens/focus and keyed
  Action state); no foreign/shared/slotted camera Actions or unauthorized channel adoption.
- DOF enabled, no focus object, perspective camera, local unshared camera data, Object mode and
  no object constraints required before mutation.
- bounded simultaneous lens/focus key insertion, interpolation readback, no overwrite and
  recoverable new/old camera-data Actions.
- verification mismatch restores both lens/focus values and previous camera animation revision.
- M6 raises typed tools and registry cap from 212 to **214**.

Level 7 runtime verification remains 0%; production readiness remains No.
Milestone 6 — camera lens and focus animation — is complete.

Milestone 7 adds:
- `animation.control_inspect` and `animation.control_keyframe_insert` for bounded
  object visibility and pose-constraint influence keyframes.
- visibility mode keys `hide_render` and `hide_viewport` as a pair; does not attempt to
  animate per-view-layer hide state.
- constraint mode targets one exact named bounded LIMIT_ROTATION or same-armature IK
  influence, with fresh `rig_revision` plus full `animation_revision`.
- only session-created, unshared control Action ownership; foreign/slotted/driver/NLA
  and unmanaged paths fail closed.
- exact keyframe readback, no overwrite, 64-FCurve and 1024-point limits,
  failure rollback and verified animation/rig revision recovery.
- M7 raises typed tools and registry cap from 214 to **216**.

Level 7 runtime verification remains 0%; production readiness remains No.
Milestone 7 — constraint influence and visibility animation — is complete.

Milestone 8 adds:
- `animation.nla_inspect` to inspect bounded NLA tracks and strips, Action keyframe fingerprints,
  managed status and `nla_revision` through the same current-session object ID.
- `animation.nla_strip_create` for one named NLA track and strip pushed down from a complete
  session-owned nine-channel legacy transform Action (at least two common integer frames).
- fresh ObjectTarget + exact NLA revision, no adoption of foreign/shared/layered Actions or
  existing NLA tracks, and a strict 1..100000 strip timeline bound.
- REPLACE blending, influence/scale/repeat=1, unmuted clip and exact Action-fingerprint readback.
- verification mismatch removes the new NLA track, restores the exact original active Action
  and checks the prior NLA revision; negative-path tests cover failures.
- M8 adds two typed tools, raising factory/cap from 216 to **218**.
- no arbitrary NLA editing, layer/slot handling, multi-strip blending or runtime playback claim.

Level 7 real Blender runtime verification remains 0%; production ready remains No.
Milestone 8 — managed NLA clip/strip push-down — is complete. Do not begin Milestone 9
without explicit user permission.

## Status
Source: 218 typed host contracts/tools at the bounded 218-tool cap. Level 1 source: **100%**.
Level 2 modeling source: **100%**. Level 3 sculpting/character-modeling source: **100%**.
Level 4 UV/texture/materials source: **100%**. Level 5 Geometry Nodes source: **100%**.
Level 6 Rigging source: **100%** (Milestones 1-10 of 10). Verified Level 6 source/test checkpoint:
8b1f76baebcb02bd285e95dd8754df4fb9e787d4. CI run 37657039445 passed all six
Linux/Windows Python 3.11/3.12/3.13 jobs with 807 tests, lint/format, package build,
77-module distribution audit and clean install/import without bpy.
Level 7 Advanced Animation source: **80%** (Milestones 1-8 of 10). Verified Level 7 source/test
checkpoint: 9a8446ff949c7d0441106201bf96b3059c503ec2. CI run 37753381630 passed all six
Linux/Windows Python 3.11/3.12/3.13 jobs with 864 tests, lint/format, package build,
84-module distribution audit and clean install/import without bpy.
Real Blender runtime verification: none (0%). Production ready: no.

## Active work
Level 7 Milestones 1-8 are complete at 80%. Stop here. Do not begin Milestone 9 without explicit
user permission. Keep source/fake evidence separate from real Blender runtime verification.

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
None for the completed Level 7 80% source checkpoint. The registry/client is exactly at the
218-tool cap, so Milestone 9 must deliberately reconcile capacity before adding any new tool.
Heavy Blender runtime actions still require separate user authorization.

## Exact next task
Wait for explicit user permission. If the user asks to continue Level 7, start only Milestone 9:
versioned animation recipe library. First reconcile the current 218/218 registry cap,
preserve exact revision/readback/recovery evidence, keep real Blender runtime acceptance at 0%
unless separately authorized, and do not begin Milestone 10 automatically.
