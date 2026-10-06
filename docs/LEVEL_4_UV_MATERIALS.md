# Level 4 — UV / Texture / Materials

Level 4 begins after the completed Level 1-3 source roadmaps. It follows the same boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Current Level 4 source progress: **100%**.

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
| 7 | Shader / material node foundation | complete |
| 8 | PBR texture assignment | complete |
| 9 | Advanced texture workflow | complete |
| 10 | Level 4 QA / recovery / acceptance | complete |

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

## Milestone 7 — 70% complete

Milestone 7 adds a bounded typed Principled-BSDF material node surface. It does not expose
generic node creation, arbitrary Python or unrestricted shader graph editing.

### `material.shader_inspect`

This read-only operation targets one existing local node-enabled material by name and reports:

- material name
- node/link counts
- bounded node type/name/image summaries
- complete bounded link topology
- supported Principled values for Base Color, Metallic, Roughness, Transmission Weight,
  Emission Color, Emission Strength and Alpha
- managed Normal Map / Bump strengths and distance
- all managed PBR channel bindings
- dedicated `shader_revision`

Shader inspection is capped at 32 nodes and 64 links and requires exactly one Principled BSDF.

### `material.principled_set`

This mutation requires a fresh `expected_shader_revision` and accepts only typed bounded
settings:

- base color
- metallic
- roughness
- transmission
- emission color
- emission strength
- alpha
- normal strength
- height/bump strength
- height/bump distance

Normal and height controls may create only Shuvi-managed Normal Map / Bump helper nodes. The
managed normal chain is deterministic:

- Normal Map → Principled Normal when no managed Bump node is present
- Normal Map → Bump Normal → Principled Normal when both are present
- Bump → Principled Normal when only Bump is present

The tool refuses to overwrite an unmanaged incoming shader link. Verification compares the
requested Principled/auxiliary values against actual node readback. Recovery restores direct
Principled values plus the complete prior Shuvi-managed node/link state and only claims success
after the initial shader revision is restored.

## Milestone 8 — 80% complete

Milestone 8 adds typed PBR image-texture binding for seven channels:

- Base Color
- Roughness
- Metallic
- Normal
- Height
- Ambient Occlusion (AO)
- Alpha

### `material.pbr_texture_assign`

The operation requires:

- existing local material
- fresh shader revision
- allowlisted channel
- existing local image datablock

No filesystem path or image-loading surface is exposed here. The image must already exist in
Blender's data and must already use the required color space:

- Base Color → `sRGB`
- Roughness / Metallic / Normal / Height / AO / Alpha → `Non-Color`

The tool fails closed instead of silently changing the shared image datablock's global
colorspace.

Direct shader wiring is bounded:

- Base Color texture Color → Principled Base Color
- Roughness texture Color → Principled Roughness
- Metallic texture Color → Principled Metallic
- Alpha texture Alpha → Principled Alpha
- Normal texture Color → Shuvi Normal Map → managed normal chain
- Height texture Color → Shuvi Bump Height → managed normal chain

Principled BSDF has no native AO socket, so AO is intentionally retained as a managed
Non-Color auxiliary texture node and reported with `ao_auxiliary_only=true`; it is not falsely
claimed as a direct shader connection.

### `material.pbr_texture_clear`

This removes only the requested Shuvi-managed texture-channel node and its links. It does not
delete the image datablock or touch unmanaged nodes. Normal/height clearing re-evaluates only
the bounded managed normal chain.

Both assignment and clear preserve a full pre-mutation snapshot of supported Principled values
and Shuvi-managed nodes/links. Verification mismatch restores that state and verifies the
original shader revision.

### Tool-count boundary

Milestones 7-8 add four typed operations, taking the factory from 141 to **145** tools. The
centralized registry/catalog maximum remains **160**.

## Milestone 9 — 90% complete

Milestone 9 adds bounded advanced texture planning and QA surfaces without introducing
filesystem texture loading, arbitrary node editing or real baking execution.

### `texture.image_inspect`

This read-only operation inspects one existing local image datablock and reports bounded
metadata only:

- image name
- width/height
- color space
- source kind
- whether the source is tiled
- up to 256 discovered tile numbers
- packed-state boolean
- filepath-presence boolean without exposing the path
- dedicated image revision

### `texture.udim_plan`

The tool reads one existing UV layer and maps each bounded face to a source-side UDIM tile.
Supported tiles use the standard 10-column numbering model starting at 1001. Exact face
boundaries such as 0..1 remain in one deterministic tile; faces spanning multiple tiles are
reported explicitly rather than silently assigned. Negative/out-of-range UVs are also reported.

The result is planning-only and always states `runtime_udim_verified=false`.

### `texture.channel_qa`

This operation audits all seven managed PBR channels and detects:

- missing image datablocks
- wrong color spaces
- broken Base Color/Roughness/Metallic/Alpha links
- broken Normal/Height helper links
- broken managed Normal Map → Bump → Principled normal chain
- unexpected AO outgoing links

Absent optional channels are reported as ABSENT instead of false failures. A material with no
managed textures receives a REVIEW advisory rather than a false PASS claim.

### `texture.consistency_qa`

Consistency QA combines channel QA with bounded image metadata and reports:

- invalid image dimensions
- mixed texture resolutions
- one image reused across multiple channels
- channel/image mapping
- PASS / REVIEW / BLOCKED source status

Resolution mismatch and channel reuse are review advisories unless they accompany a structural
blocker.

### `texture.bake_prep`

Bake preparation is read-only. It requires an object, assigned material, UV layer, 1..7 target
channels and texture size 16..32768. It checks:

- requested material is actually assigned to the object
- UV degeneracy and overlap diagnostics
- supported UDIM tile placement
- current managed channel graph health
- presence/absence of existing target channel textures

It returns READY / REVIEW / BLOCKED plus explicit
`BAKE_PREP_SOURCE_ONLY` / `runtime_bake_executed=false`. It does not invoke Blender bake
operators.

## Milestone 10 — 100% complete

Milestone 10 adds bounded recovery, aggregate Level 4 QA, deterministic workflow composition,
source acceptance and a separately gated runtime-acceptance path.

### `texture.recovery_snapshot`

The recovery snapshot records only Shuvi-managed Level 4 material state:

- supported Principled values
- Normal/Bump strengths and distance
- image names for the seven managed PBR channels
- current shader revision
- deterministic recovery revision

It does not serialize arbitrary nodes or unrestricted graph data.

### `texture.recovery_restore`

Restore requires a fresh shader revision plus a recovery state whose supplied recovery revision
matches the validated state. The parser accepts only bounded supported Principled values,
managed auxiliary values and allowlisted channel image names.

Restore removes/rebuilds only Shuvi-managed nodes, verifies required image datablocks/color
spaces, recreates the bounded managed normal chain, reads back the resulting managed state and
compares its recovery revision. If the requested restore cannot be verified, the tool restores
the immediate pre-call managed state and verifies that rollback before reporting failure.

### `texture.asset_qa`

Aggregate asset QA combines:

- UV layer presence
- degenerate UV diagnostics
- UV overlap diagnostics
- UDIM face placement
- material assignment
- managed channel graph QA
- texture consistency QA
- presence of at least one managed texture

It reports PASS / REVIEW / BLOCKED, fresh geometry/UV/shader revisions, and explicitly keeps
`real_runtime_verified=false` and `production_ready=false`.

### `texture.workflow_preview`

This read-only tool composes a fixed ten-stage Level 4 workflow:

1. UV diagnostics
2. seam and unwrap review
3. UV island pack review
4. texel-density review
5. material slot assignment
6. Principled shader review
7. PBR channel QA
8. UDIM and consistency QA
9. bake preparation
10. Level 4 source acceptance

It never auto-mutates and explicitly recommends a recovery snapshot before later material
mutations.

### `texture.level4_acceptance`

The final source acceptance evaluates eight structural checks from the aggregate asset QA:
UV layer, UV degeneracy, UV overlap, UDIM placement, material assignment, channel graph,
texture consistency and managed texture presence.

Acceptance returns PASS / REVIEW / BLOCKED, blockers/advisories, deterministic acceptance
revision and explicit boundaries:

- `scope=LEVEL_4_SOURCE_AND_FAKE_ADAPTER_ACCEPTANCE_ONLY`
- `runtime_acceptance_required=true`
- `real_runtime_verified=false`
- `production_ready=false`

### Runtime acceptance preparation

The acceptance harness now has a separate `--allow-level4-textures` opt-in behind the existing
mandatory `--authorize-runtime` guard. Its injected fake-session CI path exercises disposable
UV creation/packing, texel-density planning, material slots, Principled mutation, managed
recovery, UDIM/channel/consistency/bake-prep QA, aggregate asset QA, workflow preview and final
Level 4 source acceptance.

That preparation does not count as real Blender testing and does not auto-enable render or
destructive cases.

### Tool-count boundary

Milestones 9-10 add ten typed operations, taking the factory from 145 to **155** tools. The
centralized registry/catalog maximum remains **160**.

## Source/runtime boundary

Milestones 1-10 are source-side typed UV/material infrastructure only.

They do **not** claim:

- real Blender UV Editor behavior
- unwrap quality
- packing quality
- Blender operator compatibility
- texture/material runtime behavior
- production readiness

No Blender install, version probe, launch, bpy runtime execution, render, real Blender shader/
texture/bake mutation or GPU-heavy operation was performed for this 100% source checkpoint.

## Verified 100% source checkpoint

Source/test checkpoint: `0d139c038db86a00590c15971ace2f88991e9da9`.

CI run `37449038646` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **527 tests**
- package build
- distribution audit
- clean install/import without bpy
- **66 package modules**

Factory typed tools: **155**.
Registry/catalog maximum: **160**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **100%** (Milestones 1-10 of 10).

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Completion boundary

Level 4 has no remaining required source milestone in the current roadmap. Do not silently add
Milestone 11. The next scope must be explicitly authorized as Level 5 Geometry Nodes, main-Shuvi
integration, or real Blender 4.2+ Level 4 runtime acceptance.
