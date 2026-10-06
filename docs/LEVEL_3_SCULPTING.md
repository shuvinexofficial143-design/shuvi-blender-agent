# Level 3 — Sculpting + Character Modeling

Level 3 starts after the completed Level 1 control and Level 2 professional-modeling source
roadmaps. It is intentionally split into ten source milestones so source implementation,
fake-bpy/CI evidence and real Blender runtime behavior remain separate.

Current Level 3 source progress: **90%**.

Real Blender runtime verification for Level 3: **0%**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Sculpt mesh diagnostics + radial displace/smooth foundation | complete |
| 2 | Expanded brush deformation set: inflate/flatten/pinch/grab/crease foundations | complete |
| 3 | Mask/region weighting, symmetry and side-aware sculpt controls | complete |
| 4 | Multires/subdivision sculpt workflow and level controls | complete |
| 5 | Remesh/voxel-density planning and surface-preservation helpers | complete |
| 6 | Character blockout and proportion/landmark guides | complete |
| 7 | Head/face character-modeling helpers and facial landmark workflows | complete |
| 8 | Torso/limb/hands/feet character-modeling helpers and symmetry workflows | complete |
| 9 | Character sculpt QA, recovery and reusable sculpt workflow recipes | complete |
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
Level 3 source: **90%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 2 is complete. Milestone 3 is complete. Milestones 4 and 5 are complete. Milestones 6 and 7 are complete. Milestones 8 and 9 are complete. Milestone 10 is next: Level 3 acceptance, end-to-end character workflow composition and handoff.


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
Level 3 source: **90%**.
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
Level 3 source: **90%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 4 is next: Multires/subdivision sculpt workflow and level controls.


## Milestone 4 — 40% complete

Milestone 4 adds bounded sculpt-detail planning plus a non-destructive SUBSURF preview/control
workflow while explicitly refusing to pretend real Blender Multires subdivision has been
executed.

### `sculpt.detail_plan`

Reports:

- base face count
- requested viewport/render detail levels, each 0..3
- conservative face estimate using `base_faces × 4^level`
- current modifier stack revision
- existing SUBSURF entries
- explicit `multires_runtime_required=true`
- source status `PLANNING_ONLY` for real Multires behavior

The estimated face count is capped at 250,000 for this source workflow.

### `sculpt.subdivision_setup`

Creates one verified non-destructive SUBSURF preview modifier on an empty modifier stack.

It requires:

- fresh ObjectTarget
- fresh stack revision
- local mesh without shape keys
- empty stack
- explicit modifier name
- viewport/render levels 0..3
- estimate under the sculpt-detail work cap

The resulting ordered modifier stack is read back through the Level 2 typed modifier surface.
This is a sculpt-detail preview/control foundation, not a Multires sculpt replacement.

### `sculpt.subdivision_set_levels`

Updates a named SUBSURF preview modifier's viewport/render levels using fresh stack state,
complete stack readback and existing rollback behavior.

The named entry must still be SUBSURF; type drift or stale stack state is rejected.

## Milestone 5 — 50% complete

Milestone 5 adds bounded voxel/remesh planning plus surface-preservation baselines and anchors.
No source tool executes Blender voxel remesh yet.

### `sculpt.voxel_plan`

Given an explicit voxel size, reports:

- mesh bounds and extents
- padded per-axis voxel-grid dimensions
- estimated total cell count
- explicit per-axis/total work limits
- `runtime_remesh_required=true`
- `execution_status=PLANNING_ONLY`

Each axis is capped at 512 planned cells and total cells at 16,777,216.

### `sculpt.voxel_target_density`

Accepts a desired 8..512 voxel count along the mesh's longest local-space axis and derives a
recommended voxel size plus the resulting bounded grid/cell estimate.

Zero-size bounds are rejected.

### `sculpt.surface_snapshot`

Captures a deterministic source-side preservation baseline:

- geometry revision
- local bounds
- vertex centroid
- polygon surface-area estimate
- average unique-edge length
- vertex/face counts

This gives later remesh acceptance a compact before/after comparison target without claiming
shape equivalence.

### `sculpt.surface_anchor_plan`

Selects 4..32 deterministic base-mesh anchors for later post-remesh comparison.

The helper begins with local X/Y/Z extrema, fills remaining slots with vertices nearest the
mesh centroid, and records base position, area-weighted normal and centroid distance.

These anchors are planning evidence only; topology-changing remesh cannot preserve vertex IDs,
so future runtime acceptance must compare spatial/surface proximity rather than index identity.

### Milestones 4–5 source/runtime boundary

- no real Multires subdivision is executed
- no Voxel Remesh/Dyntopo operation is executed
- SUBSURF is used only as a verified non-destructive detail preview/control foundation
- real Multires and remesh remain explicitly marked runtime-required
- all planning calculations are bounded and deterministic
- no arbitrary Python or unrestricted Blender operator execution is exposed

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **90%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 6 is next: character blockout and proportion/landmark guides.


## Milestone 6 — 60% complete

Milestone 6 adds bounded character-proportion references, blockout planning and mesh-to-guide
landmark candidate fitting. These helpers are intentionally read-only planning surfaces; they do
not create anatomy automatically or claim artistic/anatomical correctness.

### `character.proportion_guide`

Returns one deterministic local-space human proportion reference for:

- `ADULT_NEUTRAL`
- `HEROIC`
- `STYLIZED`

Inputs are preset, total height and local origin. The guide reports head-unit count,
head height, shoulder/hip widths, centerline landmark heights and paired left/right landmark
positions.

The convention is explicit: local X = left/right, local Y = depth, local Z = up.

These presets are modeling references, not medical/anatomical ground truth.

### `character.blockout_plan`

Expands the same proportion preset into a bounded planning-only primitive layout for:

- head
- torso
- pelvis
- left/right upper arms
- left/right forearms
- left/right thighs
- left/right lower legs

Each part has a deterministic center, approximate dimensions and shape class
(`ELLIPSOID` or `CAPSULE`). The plan is symmetric around local X and does not create Blender
objects.

### `character.landmark_fit`

Fits the proportion guide to an existing bounded mesh using its local-space bounds.

The mesh height is taken from local Z. Guide targets are generated inside those bounds, then
each target is mapped to the nearest base-mesh vertex with deterministic distance/tie-breaking.

The result reports:

- geometry revision
- mesh bounds/height
- target landmark position
- candidate vertex index and position
- absolute and height-normalized distance
- explicit `CANDIDATE_MAPPING_ONLY` status

The fit is capped by the existing 4096-vertex bounded mesh surface and never mutates the mesh.

## Milestone 7 — 70% complete

Milestone 7 adds bounded head/face landmark, brush-region and symmetry-audit helpers.

### `character.face_guide`

Builds a normalized facial reference from one bounded head mesh.

The caller explicitly chooses `POSITIVE_Y` or `NEGATIVE_Y` as the local-space front
direction. Nonzero X/Y/Z head bounds are required.

The guide contains 14 reference landmarks:

- left/right brow
- left/right eye
- nose bridge
- nose tip
- left/right mouth corner
- philtrum
- chin
- left/right jaw
- left/right ear

The guide is positioned slightly inside the selected local front surface and reports centerline
landmarks plus left/right symmetry pairs.

### `character.face_landmark_fit`

Maps each facial guide target to the nearest bounded base-mesh vertex and reports normalized
distance relative to max(head width, head height).

The request includes an explicit maximum normalized distance. Candidates outside that threshold
are reported as rejected, producing `REVIEW` rather than silently claiming a good facial fit.

### `character.face_region_plan`

Converts the face guide into six deterministic sculpt planning regions:

- left eye socket
- right eye socket
- nose
- mouth
- chin/jaw
- brow

Each region has a local-space center and bounded radius derived from head width/height. The
result is `SCULPT_BRUSH_PLANNING_ONLY`; it does not invoke brushes automatically.

### `character.face_symmetry_audit`

Uses the same fitted facial candidates to inspect local-X facial symmetry.

For each paired landmark it reports:

- mirrored X error around head center
- combined Y/Z alignment error
- tolerance pass/fail

Centerline landmarks are separately checked for local-X drift. The aggregate result is
`PASS` or `REVIEW`.

This is a candidate-vertex audit only; it is not a perceptual face-symmetry score.

### Milestones 6–7 source/runtime boundary

- all seven new character tools are read-only
- no mesh/object creation is performed
- no unrestricted Blender operators are used
- proportion presets are modeling references, not anatomical truth
- blockout plans describe intended primitive layout only
- landmark fitting uses bounded base-mesh nearest-vertex candidates
- head/face guides require explicit local front direction
- face symmetry is local X only and based on candidate vertices, not evaluated geometry
- character fit workflows are capped by the bounded 4096-vertex mesh snapshot
- no real Blender Sculpt Mode/PBVH/Multires/Dyntopo behavior is implied

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **90%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 8 is next: torso/limb/hands/feet character-modeling helpers and symmetry workflows.


## Milestone 8 — 80% complete

Milestone 8 adds bounded torso/limb/hands/feet planning helpers plus a deterministic base-mesh
local-X symmetry audit.

### `character.body_region_plan`

Fits the selected character proportion preset to the current mesh's local bounds and emits 17
planning-only sculpt regions covering:

- chest
- abdomen
- pelvis
- left/right shoulder
- left/right upper arm
- left/right forearm
- left/right hand
- left/right thigh
- left/right calf
- left/right foot

Each region contains a local-space center and reference radius derived from the chosen preset
and fitted mesh height. The result is explicitly `CHARACTER_SCULPT_REGION_PLANNING_ONLY`.

### `character.limb_guide`

Builds one side-specific ARM or LEG guide from preset, total height and local origin.

ARM guide landmarks:
- shoulder
- elbow
- wrist
- hand center

LEG guide landmarks:
- hip
- knee
- ankle
- foot center

The result also exposes a reference thickness for downstream planning.

### `character.extremity_guide`

Builds one explicit local-space HAND or FOOT landmark guide from side, anchor and length.

HAND:
- wrist
- palm center
- thumb/index/middle/ring/pinky tips

FOOT:
- ankle
- heel
- ball
- big toe
- little toe

This is reference geometry only; it does not create bones, fingers, toes or mesh topology.

### `character.body_symmetry_audit`

Audits bounded base-mesh local-X coordinate symmetry.

Vertices are classified as positive-X, negative-X or symmetry-plane using caller-supplied
tolerance. Positive vertices search for mirrored negative partners using the existing bounded
spatial-grid symmetry matcher.

The result reports:
- paired vertex count
- unmatched positive/negative indices
- duplicate partner collisions
- symmetry-plane vertex count
- candidate-check work evidence
- PASS/REVIEW status

This is coordinate symmetry QA only. It does not claim visual, anatomical or evaluated-mesh
symmetry.

## Milestone 9 — 90% complete

Milestone 9 adds aggregate character-sculpt QA, reusable recipe previews and bounded verified
coordinate-patch recovery.

### `character.sculpt_qa`

Combines existing sculpt diagnostics with the body local-X symmetry audit.

Blockers include:
- no faces
- degenerate faces
- unresolved vertex normals
- base mesh not structurally sculpt-ready

Advisories include:
- open boundaries
- local-X symmetry review

The aggregate status is PASS, REVIEW or BLOCKED and includes a deterministic `qa_revision`.

This remains structural base-mesh QA, not an artistic quality score.

### `character.sculpt_recipe_preview`

Supports three allowlisted reusable planning recipes:

- `BODY_PRIMARY_FORMS`
- `FACE_PRIMARY_FORMS`
- `HAND_FOOT_REFINEMENT`

Each recipe expands into an ordered preview of existing typed tools plus scaled suggested
strengths. No recipe executes automatically. Each mutation still requires fresh target and
geometry state when later executed.

### `character.sculpt_recovery_snapshot`

Captures a bounded 1..512 vertex coordinate patch from an existing mesh.

The result includes:
- current geometry revision
- topology revision derived from vertex count + faces
- selected vertex indices and restore positions
- explicit bounded coordinate-patch scope

This does not persist anything to disk.

### `character.sculpt_recovery_restore`

Restores 1..512 explicit vertex coordinates with full source-side verification and rollback.

Requirements:
- fresh ObjectTarget
- fresh geometry revision
- exact matching topology revision
- editable local unshared base mesh
- no shape keys
- no modifier stack

If topology changed since the recovery snapshot, restore fails closed with stale state.
Successful recovery preserves topology and verifies the complete indexed geometry. If recovery
verification itself fails, the coordinates that existed immediately before the restore attempt
are restored by the ordinary sculpt coordinate rollback path.

### Milestones 8–9 source/runtime boundary

- body/limb/extremity tools are planning/reference helpers only
- body symmetry is local-X base-coordinate QA only
- aggregate sculpt QA is structural, not perceptual
- recipe previews never auto-execute mutations
- recovery is limited to an explicit coordinate patch of at most 512 vertices
- recovery refuses topology drift and retains all normal sculpt editability guards
- no arbitrary Python or unrestricted Blender operators are exposed
- real Blender Sculpt Mode/PBVH/Multires/Dyntopo behavior remains unverified

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **90%**.
Level 3 real Blender runtime verification: **0%**.

Milestone 10 is next: Level 3 acceptance, end-to-end character workflow composition and handoff.
