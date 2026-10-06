# Level 4 — UV / Texture / Materials

Level 4 begins after the completed Level 1-3 source roadmaps. It follows the same boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Current Level 4 source progress: **60%**.

Real Blender runtime verification for Level 4: **0%**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | UV diagnostics foundation | complete |
| 2 | Explicit seam controls and safe seam verification | complete |
| 3 | Bounded UV unwrap foundation | complete |
| 4 | UV island editing | complete |
| 5 | UV packing and texel-density planning | complete |
| 6 | Material slot management | complete |
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

## Milestone 5 — 50% complete

Milestone 5 adds deterministic bounded UV packing plus read-only texel-density inspection and
target planning. It does not expose Blender's generic UV packing operators.

### `uv.pack_plan`

Inputs:

- object ID
- existing UV layer name
- UV margin 0..0.1

The tool detects the current bounded UV islands and assigns them deterministically to a
near-square row-major grid inside 0..1 UV space. Each island is uniformly scaled to fit its cell
while preserving its current shape and aspect ratio. Degenerate island bounds or a margin that
leaves no usable cell area fail closed.

The result includes island count, grid rows/columns, per-island source/target centers and scale,
a deterministic target coordinate revision, and explicit
`SOURCE_GRID_PACK_PREVIEW_ONLY` / `runtime_pack_equivalent=false` boundaries.

### `uv.pack_apply`

This mutation additionally requires fresh ObjectTarget, geometry revision and UV revision.
It writes only the requested UV layer. Verification requires:

- unchanged geometry revision
- unchanged seam state
- unchanged active UV layer
- unchanged UV layer count/order
- unchanged non-target UV layer revisions
- exact intended target-layer coordinate revision

Verification failure restores every prior target-layer loop UV and claims recovery only after
readback matches the initial bounded state.

### Texel-density inspection and planning

`uv.texel_density_inspect` accepts an existing UV layer plus texture size 16..32768. For each
bounded face it reports surface area, UV area and source-side pixels-per-unit estimate:

`texture_size × sqrt(uv_area / surface_area)`.

It also reports valid-face count and min/median/max density.

`uv.texel_density_plan` accepts a positive target density and returns the uniform UV scale
needed to move the current median density toward that target. This remains planning-only and
explicitly does not claim Blender/runtime texel-density equivalence.

## Milestone 6 — 60% complete

Milestone 6 adds bounded material-slot inspection and management for editable local unshared
mesh data.

### `material.slots_inspect`

The read-only snapshot is capped at 64 material slots and 256 faces. It reports:

- slot count and ordered material names
- face-user count per slot
- face material index for every bounded face
- dedicated `material_revision`

The material revision covers both ordered slot names and complete bounded face-slot assignment.

### Slot and face mutation tools

- `material.slot_link` appends an existing material datablock as a new slot.
- `material.slot_reassign` replaces one existing slot with another existing material.
- `material.slot_duplicate` duplicates a source slot's material datablock, requires a fresh
  unused name, and appends the duplicate as a new slot.
- `material.slot_remove` removes only the final slot and only when no bounded face currently
  uses it. This conservative rule avoids silent face-index shifting.
- `material.face_assign` assigns 1..256 unique explicit face indices to one existing slot.

Every mutation requires a fresh ObjectTarget plus fresh `expected_material_revision`.
Slot/face readback is compared against the exact intended state. Supported recovery restores
the prior slot reference or prior face material indices and only reports recovery after complete
bounded readback matches.

These tools do not expose arbitrary Python, unrestricted material operators or shader-node
editing. Shader/node work remains Milestone 7.

### Tool-count boundary

Milestones 5-6 add ten typed operations, taking the factory from 131 to **141** tools. The
centralized registry/catalog maximum remains **160**.

## Source/runtime boundary

Milestones 1-6 are source-side typed UV/material infrastructure only.

They do **not** claim:

- real Blender UV Editor behavior
- unwrap quality
- packing quality
- Blender operator compatibility
- texture/material runtime behavior
- production readiness

No Blender install, version probe, launch, bpy runtime execution, render, real Blender UV pack,
material runtime mutation or GPU-heavy operation was performed for this 60% source checkpoint.

## Verified 60% source checkpoint

Source/test checkpoint: `f095e4ec6ea8f6e9a5072faa026583bcb63e21b7`.

CI run `37444522045` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **489 tests**
- package build
- distribution audit
- clean install/import without bpy
- **64 package modules**

Factory typed tools: **141**.
Registry/catalog maximum: **160**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **60%**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestone 7 — shader / material node foundation — is the next source task, but it must not start
without explicit user permission.
