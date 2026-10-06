# Level 3 — Sculpting + Character Modeling

Level 3 starts after the completed Level 1 control and Level 2 professional-modeling source
roadmaps. It is intentionally split into ten source milestones so source implementation,
fake-bpy/CI evidence and real Blender runtime behavior remain separate.

Current Level 3 source progress: **10%**.

Real Blender runtime verification for Level 3: **0%**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Sculpt mesh diagnostics + radial displace/smooth foundation | complete |
| 2 | Expanded brush deformation set: inflate/flatten/pinch/grab/crease foundations | pending |
| 3 | Mask/region weighting, symmetry and side-aware sculpt controls | pending |
| 4 | Multires/subdivision sculpt workflow and level controls | pending |
| 5 | Remesh/voxel-density planning and surface-preservation helpers | pending |
| 6 | Character blockout and proportion/landmark guides | pending |
| 7 | Head/face character-modeling helpers and facial landmark workflows | pending |
| 8 | Torso/limb/hands/feet character-modeling helpers and symmetry workflows | pending |
| 9 | Character sculpt QA, recovery and reusable sculpt workflow recipes | pending |
| 10 | Level 3 acceptance, end-to-end character workflow composition and handoff | pending |

## Milestone 1 — 10% complete

Milestone 1 establishes a bounded, provider-independent sculpt foundation without exposing
arbitrary Python, unrestricted operators or Blender brush internals.

### `sculpt.inspect`

Read-only base-mesh sculpt diagnostics return:

- bounded vertex/face/edge counts
- geometry revision
- boundary vertex indices/count
- non-manifold edge count
- degenerate face indices/count
- vertices whose accumulated area-weighted normal cannot be resolved
- minimum/maximum/average vertex valence
- conservative `sculpt_ready` flag

The normal diagnostic is derived directly from bounded indexed base geometry. It is not a claim
about Blender evaluated split normals, multires data, Dyntopo data or Sculpt Mode PBVH state.

### `sculpt.brush_displace`

Applies one deterministic radial normal-displacement brush to the base mesh.

Inputs:

- fresh ObjectTarget
- fresh geometry revision
- local-space brush center
- radius
- signed strength
- LINEAR or SMOOTH falloff

The tool scans the bounded base mesh, affects at most 512 vertices, computes deterministic
area-weighted vertex normals from polygon winding and moves each valid selected vertex along its
normal by `strength × falloff_weight`.

Negative strength lowers the surface; positive strength raises it.

The mutation requires:

- Object mode
- editable local mesh object
- unshared mesh data
- no shape keys
- no modifier stack

Full bounded geometry is read back after mutation. Verification mismatch restores all changed
vertex coordinates.

### `sculpt.brush_smooth`

Applies bounded radial synchronous one-ring smoothing.

Inputs:

- fresh ObjectTarget + geometry revision
- local-space brush center/radius
- strength 0.001..1.0
- LINEAR or SMOOTH radial falloff
- 1..8 iterations
- optional boundary preservation

Each iteration uses the previous iteration's coordinates for every selected vertex, preventing
order-dependent in-place smoothing. A selected vertex moves toward the average of its one-ring
neighbors by `strength × radial_weight`.

With boundary preservation enabled, selected boundary vertices are held fixed. The brush is
capped at 512 affected vertices. Full geometry readback and coordinate rollback are required.

## Important source/runtime boundary

These Milestone 1 brushes are deliberate **source-side base-mesh deformation foundations**.
They do not yet call Blender's interactive Sculpt Mode brush engine, PBVH, Dyntopo, Multires,
mask or face-set systems.

This is intentional while no usable real Blender runtime/server is available. The typed
contracts, bounded math, state guards, readback verification and fake-bpy tests can be completed
without pretending they prove Blender's real sculpt runtime behavior.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **10%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 2 is next: expanded bounded sculpt brush deformation foundations.
