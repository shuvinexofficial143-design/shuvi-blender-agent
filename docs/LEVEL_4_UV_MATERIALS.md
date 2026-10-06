# Level 4 — UV / Texture / Materials

Level 4 begins after the completed Level 1-3 source roadmaps. It follows the same boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Current Level 4 source progress: **20%**.

Real Blender runtime verification for Level 4: **0%**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | UV diagnostics foundation | complete |
| 2 | Explicit seam controls and safe seam verification | complete |
| 3 | Bounded UV unwrap foundation | pending |
| 4 | UV island editing | pending |
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

## Source/runtime boundary

Milestones 1-2 are source-side typed UV infrastructure only.

They do **not** claim:

- real Blender UV Editor behavior
- unwrap quality
- packing quality
- Blender operator compatibility
- texture/material runtime behavior
- production readiness

No Blender install, version probe, launch, bpy runtime execution, render, unwrap or GPU-heavy
operation was performed for this 20% source checkpoint.

## Verified 20% source checkpoint

Source/test checkpoint: `f6d8150d14c6f022cc281ae8dee7ed224d3390bc`.

CI run `37429688765` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **455 tests**
- package build
- distribution audit
- clean install/import without bpy
- **61 package modules**

Factory typed tools: **128**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **20%**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestone 3 — bounded UV unwrap foundation — is the next source task, but it must not start
without explicit user permission.
