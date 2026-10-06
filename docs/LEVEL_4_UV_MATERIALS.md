# Level 4 — UV / Texture / Materials

Level 4 begins after the completed Level 1-3 source roadmaps. It follows the same boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Current Level 4 source progress: **40%**.

Real Blender runtime verification for Level 4: **0%**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | UV diagnostics foundation | complete |
| 2 | Explicit seam controls and safe seam verification | complete |
| 3 | Bounded UV unwrap foundation | complete |
| 4 | UV island editing | complete |
| 5 | UV packing and texel-density planning | pending |
| 6 | Material slot management | pending |
| 7 | Shader / material node foundation | pending |
| 8 | PBR texture assignment | pending |
| 9 | Advanced texture workflow | pending |
| 10 | Level 4 QA / recovery / acceptance | pending |

## Milestone 1 — 10% complete

Milestone 1 adds a bounded read-only UV inspection surface through `uv.inspect`.

### `uv.inspect`

The tool requires one typed `object_id` and reads only bounded base-mesh data. It reports:

- fresh `geometry_revision`
- dedicated `uv_revision`
- UV-layer count and active layer
- explicit missing-UV detection
- per-layer coordinate revision
- UV loop count
- total UV area
- degenerate UV face indices
- positive-area UV overlap face pairs
- overlap result truncation evidence
- UV island count based on shared geometry plus UV continuity
- relative UV-to-surface-area stretch outlier diagnostics
- complete bounded seam flags, seam edge indices and seam vertex pairs

The source diagnostic limits are intentionally conservative:

- at most 256 mesh faces
- at most 8,192 UV loops
- at most 8 UV layers
- at most 8,192 mesh edges
- overlap evidence retains at most 256 positive-area face pairs

Overlap detection triangulates each bounded UV polygon and checks for positive-area triangle
intersection. Touching only at an edge or point is not reported as overlap. Stretch diagnostics
compare per-face UV/surface area ratios against the layer median and flag a face only when its
relative factor exceeds the bounded source threshold.

UV island counting is source-side topology/UV continuity analysis. It does not invoke Blender's
unwrap, pack, stitch or island operators.

## Milestone 2 — 20% complete

Milestone 2 adds explicit edge-based seam mutation through `uv.seam_set`.

### Seam preview

`uv.inspect` is also the bounded seam-preview surface. It exposes every bounded edge's current
seam flag plus the marked seam indices and vertex pairs without mutating anything. No separate
preview mutation or generic operator surface is required.

### `uv.seam_set`

Inputs:

- fresh `ObjectTarget`
- fresh `expected_geometry_revision`
- fresh `expected_uv_revision`
- 1..512 unique explicit mesh edge indices
- boolean `seam`

Safety and verification:

- object mode is required
- the target must be an editable local mesh
- mesh data must be unshared and local
- edge indices are prevalidated against bounded readback
- only explicit requested edge `use_seam` flags are changed
- geometry revision must remain unchanged
- UV-layer coordinate revisions must remain unchanged
- the complete bounded seam-flag vector is read back
- verification failure restores the prior complete seam-flag vector
- rollback is claimed only after recovery readback matches the initial seam state

No arbitrary Python execution and no unrestricted `bpy.ops`/operator execution is exposed.

## Milestone 3 — 30% complete

Milestone 3 adds a bounded source-side planar unwrap foundation without exposing generic
Blender UV operators.

### `uv.unwrap_plan`

This read-only tool accepts an object ID plus one explicit projection: `XY`, `XZ` or `YZ`.
It validates the bounded mesh and returns:

- current geometry revision
- selected planar projection
- projected source min/max/extents
- face and loop counts
- deterministic target coordinate revision
- explicit `SOURCE_PLANAR_PROJECTION_PREVIEW_ONLY` status
- `runtime_unwrap_equivalent=false`

Zero-extent projections fail closed instead of fabricating UV coordinates.

### `uv.unwrap_apply`

This mutation requires:

- fresh ObjectTarget
- fresh geometry revision
- fresh UV revision
- explicit UV layer name
- explicit XY/XZ/YZ projection

It normalizes the selected two object-local coordinate axes into a deterministic 0..1 UV
square. It may create one named UV layer when below the eight-layer cap, or replace that
named layer's loop coordinates when it already exists.

Verification checks:

- geometry revision unchanged
- seam flags unchanged
- UV layer count and names
- active UV layer
- every UV layer coordinate revision
- exact intended target-layer coordinate revision

A newly created layer is removed on verification failure. An existing layer restores all prior
loop coordinates and prior active-layer index. Recovery is claimed only after readback matches
the complete initial bounded UV state.

This is deterministic planar source projection. It is not Blender Angle Based, Conformal,
Smart UV Project, cube/sphere/cylinder projection or artistic unwrap-quality acceptance.

## Milestone 4 — 40% complete

Milestone 4 adds bounded UV-island membership readback and exact-island coordinate editing.

### Island membership

Each `uv.inspect` layer summary now exposes deterministic `islands` as face-index groups in
addition to `island_count`. Connectivity requires both a shared geometry edge and matching UV
coordinates on that edge.

### `uv.island_transform`

Inputs:

- fresh ObjectTarget
- fresh geometry revision
- fresh UV revision
- existing UV layer name
- 1..256 unique face indices
- 2D translation bounded to ±16
- scale 0.01..100

The requested face set must exactly match one currently detected UV island; arbitrary partial
island edits fail closed.

The transform scales around the island UV bounding-box center and then translates it. Resulting
UV coordinates must stay within the ±16 source bound.

Verification preserves:

- geometry revision
- seam flags
- active layer
- UV layer count/order
- every non-target layer coordinate revision
- exact intended target-layer coordinate revision

Verification mismatch restores every prior target-layer loop coordinate and verifies recovery.

### Registry bound

Milestones 3-4 add three typed operations, taking the factory from 128 to **131** tools. The
registry/catalog remains explicitly bounded; the centralized maximum is now **160** and is
covered by the same constructor/registration and host-catalog tests. This is a bounded capacity
increase only; it does not permit arbitrary operations.

## Source/runtime boundary

Milestones 1-4 are source-side typed UV infrastructure only.

They do **not** claim:

- real Blender UV Editor behavior
- unwrap quality
- packing quality
- Blender operator compatibility
- texture/material runtime behavior
- production readiness

No Blender install, version probe, launch, bpy runtime execution, render, real Blender unwrap or
GPU-heavy operation was performed for this 40% source checkpoint.

## Verified 40% source checkpoint

Source/test checkpoint: `8059ec61e60a0056e7e2ec3b107153934c9a1f5e`.

CI run `37440606175` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **468 tests**
- package build
- distribution audit
- clean install/import without bpy
- **62 package modules**

Factory typed tools: **131**.
Registry/catalog maximum: **160**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **40%**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestone 5 — UV packing and texel-density planning — is the next source task, but it must not
start without explicit user permission.
