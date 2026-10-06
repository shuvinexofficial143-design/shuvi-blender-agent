# Level 3 — Sculpting + Character Modeling

Level 3 starts after the completed Level 1 control and Level 2 professional-modeling source
roadmaps. It is intentionally split into ten source milestones so source implementation,
fake-bpy/CI evidence and real Blender runtime behavior remain separate.

Current Level 3 source progress: **30%**.

Real Blender runtime verification for Level 3: **0%**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Sculpt mesh diagnostics + radial displace/smooth foundation | complete |
| 2 | Expanded brush deformation set: inflate/flatten/pinch/grab/crease foundations | complete |
| 3 | Mask/region weighting, symmetry and side-aware sculpt controls | complete |
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
Level 3 source: **30%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 2 is complete. Milestone 3 is complete. Milestone 4 is next: Multires/subdivision sculpt workflow and level controls.


## Milestone 2 — 20% complete

Milestone 2 expands the deterministic base-mesh sculpt surface with five additional bounded
brush foundations. These remain source-side geometry operations rather than calls into
Blender's interactive Sculpt Mode brush engine.

### `sculpt.brush_inflate`

Uses the same bounded radial selection and area-weighted base-mesh vertex normals as the
Milestone 1 displacement foundation, but treats strength as a normalized brush amount in
-1..1. The actual local-space normal displacement scale is
`radius × 0.25 × strength`, then multiplied by per-vertex falloff.

Positive strength inflates; negative strength deflates.

### `sculpt.brush_flatten`

Builds one deterministic local tangent plane from the selected base-mesh region:

- brush normal = normalized falloff-weighted sum of valid selected vertex normals
- plane origin = falloff-weighted centroid of selected vertices

Each selected vertex moves toward that plane along the resolved brush normal by
`signed_distance × strength × falloff_weight`. Strength is bounded to 0.001..1.0.

If a stable regional normal cannot be resolved, the request is rejected without mutation.

### `sculpt.brush_pinch`

Resolves the same deterministic local brush normal, projects each selected vertex's radial
vector into the local tangent plane, then moves it toward or away from the brush center.

Strength is signed and bounded to -1..1:

- positive = pinch inward
- negative = expand outward

This is a tangent-plane source foundation; it does not claim equivalence to Blender's
interactive Pinch brush implementation.

### `sculpt.brush_grab`

Moves every positively weighted selected vertex by an explicit local-space `delta` multiplied
by radial falloff. Delta components are bounded to ±1000 Blender units and zero delta is
rejected.

Grab does not require a valid surface normal, but it retains the same fresh target/geometry
guards, 512-vertex brush cap, complete readback and rollback behavior.

### `sculpt.brush_crease`

Combines two deterministic components around the resolved regional brush normal:

- tangent-plane pinch toward the brush center, `pinch` 0..1
- indentation opposite the resolved brush normal, `depth` 0..100 Blender units

At least one component must be nonzero. Both components are multiplied by per-vertex radial
falloff.

### Shared Milestone 2 safety/verification boundary

All five tools:

- use explicit fresh ObjectTarget + geometry revision
- require Object mode and editable local unshared base mesh
- reject shape keys and modifier stacks
- use LINEAR or SMOOTH radial falloff
- affect at most 512 vertices
- preserve topology
- verify the complete bounded indexed geometry after mutation
- restore all changed vertex coordinates on verification mismatch
- expose no arbitrary Python and no unrestricted Blender operators

The regional normal/plane math is deterministic source-side geometry math. It does not prove
PBVH, Dyntopo, Multires, mask, face-set or interactive Sculpt Mode behavior.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **30%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 3 is next: mask/region weighting, symmetry and side-aware sculpt controls.


## Milestone 3 — 30% complete

Milestone 3 adds stateless bounded mask weighting, side filtering and deterministic local-axis
symmetry controls that can be previewed before mutation.

### `sculpt.region_preview`

Builds a no-mutation radial sculpt region from:

- local-space center/radius
- LINEAR or SMOOTH falloff
- axis: NONE/X/Y/Z
- side: BOTH/POSITIVE/NEGATIVE
- optional symmetry
- symmetry-plane/matching epsilon
- optional strict symmetry-pair requirement
- sparse explicit per-vertex mask weights

Mask semantics are conservative and explicit: 0 means unmasked/full influence, 1 means fully
masked/no influence. Missing mask entries default to 0.

With symmetry enabled, callers must choose X/Y/Z plus a single source side
(POSITIVE or NEGATIVE). The source stroke is mirrored to the opposite side. The preview
reports source indices, partner indices, radial/mask/final weights, symmetry-plane membership,
missing partners, total changed vertices and bounded candidate-check evidence.

Symmetry matching uses a local-space spatial grid and is capped at 1,000,000 candidate checks.
The complete source+mirror changed set may not exceed the existing 512-vertex sculpt cap.

If both vertices of a symmetry pair have mask values, the stronger protection
(`max(source_mask, partner_mask)`) is used on both sides so one stroke cannot violate the
requested pair protection.

### `sculpt.brush_displace_controlled`

Combines Milestone 1 normal displacement with Milestone 3 region/mask/side/symmetry controls.

For a symmetric stroke:

- only the selected source side drives the stroke
- the source vertex moves along its base-mesh area-weighted normal
- the resulting local deformation delta is mirrored across the selected axis
- paired opposite-side vertices receive the mirrored delta
- a vertex classified on the symmetry plane is kept exactly on that plane

Vertices with unresolved normals are skipped; if no valid influenced vertex remains, the
request fails without mutation.

### `sculpt.brush_grab_controlled`

Applies an explicit local-space grab delta through the same mask/region/side/symmetry layer.

Without symmetry it acts only on the requested side. With symmetry, the axis component of the
source deformation is mirrored while non-axis components keep the same sign. This supports
common left/right character blockout moves while preserving the requested local symmetry.

Like the basic Grab foundation, this controlled version does not require valid surface normals.

### Shared Milestone 3 safety/verification boundary

- symmetry works in base-mesh **local object space**, not world space
- symmetry uses X/Y/Z planes through local origin only
- symmetry must have a single source side; BOTH is rejected when symmetry is enabled
- strict `require_symmetry_pairs` fails closed if any influenced source vertex lacks a match
- sparse masks are request-local control data; no Blender Sculpt Mask layer is created yet
- mask lists are capped at 512 unique explicit vertex entries
- spatial symmetry candidate checks are capped at 1,000,000
- complete source+mirrored changed vertices are capped at 512
- mutations retain fresh ObjectTarget/geometry revision, editable local unshared mesh,
  no-shape-key/no-modifier guards, full geometry readback and rollback
- no arbitrary Python and no unrestricted Blender operators are exposed

These controls are deterministic source-side foundations. They do not yet claim Blender
Sculpt Mask, Face Set, X/Y/Z Sculpt symmetry, radial symmetry, PBVH, Dyntopo or Multires
runtime equivalence.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **30%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 4 is next: Multires/subdivision sculpt workflow and level controls.
