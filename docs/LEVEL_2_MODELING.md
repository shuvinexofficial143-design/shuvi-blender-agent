# Level 2 — Professional Modeling

Level 2 moves the Blender agent from broad scene/object control into professional mesh
modeling. This level is intentionally split into ten source milestones so progress can be
measured without pretending fake-bpy tests prove real Blender runtime behavior.

Current Level 2 source progress: **100%**.

Real Blender runtime verification for Level 2: **0%**.

## Roadmap

| Milestone | Scope | Source status |
|---|---|---|
| 1 | Topology foundation + bounded single-face extrusion | complete |
| 2 | Explicit vertex/edge/face transforms, merge and dissolve foundations | complete |
| 3 | Region extrusion, inset and bevel modeling | complete |
| 4 | Loop-cut/subdivide/bridge/fill workflows | complete |
| 5 | Normals, smoothing and shading/topology diagnostics | complete |
| 6 | Hard-surface boolean workflow and stronger modifier modeling controls | complete |
| 7 | Topology cleanup and repair helpers | complete |
| 8 | Retopology and shrinkwrap-oriented helpers | complete |
| 9 | Advanced modeling modifier stack workflows | complete |
| 10 | Modeling QA, recovery, acceptance and workflow composition | complete |

## Milestone 1 — 10% complete

The first Level 2 slice adds two typed tools:

### `mesh.topology_inspect`

Read-only bounded topology analysis built from the indexed mesh snapshot.

It returns:

- vertices and polygon faces from the existing bounded mesh snapshot
- canonical undirected edge list
- edge count
- boundary edges/count
- non-manifold edges/count
- face adjacency derived from shared two-face edges
- geometry revision and object identity

Bounds remain conservative:

- at most 4096 vertices
- at most 4096 faces
- at most 32768 polygon loops
- at most 8192 derived unique edges

This is deterministic source-side analysis. It does not depend on Edit Mode selection state,
screen areas or arbitrary Blender operators.

### `mesh.extrude_face`

A first professional modeling mutation for one explicitly indexed polygon face.

Request:

- fresh ObjectTarget
- fresh geometry revision
- one face index
- bounded local-space offset vector

Behavior:

1. inspect and validate the exact current mesh
2. require Object mode
3. require local, editable, unshared mesh data
4. reject shape keys and existing modifiers
5. preflight resulting vertex/face/loop counts
6. duplicate the source face vertices at the requested offset
7. replace the source polygon with the new cap
8. add one connecting quad per source edge
9. rebuild the bounded mesh through direct data APIs
10. read back the entire resulting geometry
11. verify exact vertices/faces
12. restore the captured geometry if verification fails

The tool does not expose an arbitrary operator or arbitrary bmesh/Python execution channel.
It deliberately handles one face per request so topology cost and mutation evidence remain
predictable.

## Important modeling semantics

`mesh.extrude_face` represents a bounded single-face extrusion foundation. It is not yet a
replacement for every Blender Extrude menu variant. Region extrusion, individual multi-face
extrusion, extrusion along normals, manifold extrusion, edge-only extrusion and vertex-only
extrusion remain future Level 2 milestones.

The topology analysis calls an edge non-manifold whenever it does not have exactly two polygon
users, so boundary edges are also present in the non-manifold list. This is deliberate and
explicit.

## Source/runtime boundary

Milestone 1 is unit/CI-testable without Blender installed, but direct mesh replacement and
Blender validation/dependency-graph behavior remain runtime-unverified. No Blender install,
launch, render or runtime test was performed for this Level 2 work.

Level 1 remains source-complete at 100%. Level 2 currently stands at **100% source completion**.


## Milestone 2 — 20% complete

Milestone 2 adds three more typed professional-modeling tools.

### `mesh.transform_elements`

Transforms an explicit bounded selection in one of three domains:

- `VERTEX`: indices address mesh vertices directly
- `EDGE`: indices address the canonical sorted edge list returned by
  `mesh.topology_inspect`
- `FACE`: indices address polygon faces directly

Each request includes a translation vector, XYZ Euler rotation, scale and explicit local-space
pivot. The transform order is scale around pivot, then XYZ rotation, then translation.
At most 256 elements can be selected in one request. Edge/face domains expand deterministically
to the unique affected vertex indices, and the entire mesh geometry is read back afterward.
A no-op transform is rejected.

### `mesh.merge_vertices`

Merges 2..64 explicit vertex indices with one of three deterministic placement modes:

- `CENTER`: arithmetic mean of selected vertex coordinates
- `FIRST`: coordinate of the first requested vertex
- `LAST`: coordinate of the last requested vertex

The operation compacts vertex indices, rewrites polygon indices, removes polygons collapsed
below three unique vertices, and rejects merges that would create a self-repeating polygon.
The complete rebuilt mesh is verified. Topology rebuilds are conservatively denied when the
object contains material slots, vertex groups, UV layers or color attributes because this
foundation does not yet preserve those data layers.

### `mesh.dissolve_edge`

Dissolves one canonical topology edge by edge index. This first dissolve foundation accepts
only an edge shared by exactly two polygon faces. It joins the non-shared polygon boundary
paths into one simple polygon, requires the resulting face to stay within the 32-vertex face
bound, and rejects boundary/non-manifold edges or a merge that would create repeated vertices.

### Shared Milestone 2 safety/verification

All three tools require:

- a fresh ObjectTarget
- a fresh geometry revision
- Object mode
- editable local unshared mesh data
- no shape keys
- no modifier stack
- the existing object animation/constraint mutation guard

Element transforms edit coordinates in place and restore captured coordinates if verification
fails. Merge/dissolve rebuild topology through bounded direct data APIs and restore the full
captured vertices/faces if verification fails.

This milestone still does not expose arbitrary bmesh, Python or Blender operator execution.
Region extrusion, inset, bevel, loop cut/subdivide/bridge/fill, normals and repair workflows
remain later Level 2 milestones.


## Milestone 3 — 30% complete

Milestone 3 adds three bounded topology-rebuild modeling tools:

### `mesh.extrude_region`

Extrudes 1..64 explicit edge-connected faces as one region using a bounded local-space offset.

- selected faces must form one edge-connected region
- selected non-manifold edges are rejected
- a closed selected shell with no boundary is rejected
- all unique selected vertices are duplicated once
- selected faces are replaced by offset cap faces
- side quads are created only on the selected-region boundary
- internal selected edges do not receive duplicate side walls
- complete resulting vertices/faces are read back and verified

### `mesh.inset_face`

Insets one explicit polygon face by a bounded factor in `0.001..0.95`.

The operation computes the arithmetic face-vertex center, creates one inner vertex for each
source vertex using linear interpolation toward that center, replaces the source face with
the inner cap, and creates a quad ring between the original boundary and inner cap. This is a
deterministic planar/topological inset foundation; it does not yet claim Blender's complete
Inset Faces operator semantics such as even offset, boundary modes, relative offset or depth.

### `mesh.bevel_boundary_edge`

Adds a first conservative bevel/chamfer foundation for one canonical boundary edge.

- the edge must have exactly one polygon user
- factor is bounded to `0.001..0.49`
- each edge endpoint is moved inward along its neighboring polygon edge to create two new
  vertices
- the source polygon is rebuilt with the inner edge
- one quad strip preserves the original outer boundary edge
- shared/manifold edges are rejected in this foundation

### Shared Milestone 3 guards

All three tools require fresh object/geometry state, Object mode, editable local unshared
mesh data, no shape keys/modifiers and the normal object animation/constraint guard.
Topology rebuild is denied when material slots, vertex groups, UV layers or color attributes
are present because this source milestone does not yet preserve those data layers.

Every operation preflights the existing 4096-vertex, 4096-face, 32768-loop and 32-vertices-per-
face limits, reads the complete resulting geometry back, verifies it, and restores the prior
captured vertices/faces if verification fails.

Milestone 4 is complete. Milestone 5 is next: normals, smoothing and shading/topology diagnostics.


## Milestone 4 — 40% complete

Milestone 4 adds four typed topology construction tools.

### `mesh.subdivide_edge`

Splits one canonical boundary/manifold edge at a bounded factor in `0.001..0.999`.

- edge index comes from the deterministic canonical topology edge list
- the edge must have one or two polygon users
- one new vertex is linearly interpolated between the edge endpoints
- every polygon using that edge receives the new vertex in its polygon cycle
- resulting polygon size must remain within the 32-vertex face bound

This is an explicit one-edge subdivision foundation, not Blender's complete Subdivide operator.

### `mesh.loop_cut_quad_strip`

Performs one deterministic cut through an all-quad strip.

Starting from one canonical seed edge, the tool walks through each incident quad to the
opposite edge and continues that topology component. Every ring edge receives one interpolated
cut vertex at the requested factor, and every affected quad is split into two quads connecting
the cut points.

Safety limits:

- only quads may participate in the discovered strip
- seed/crossed edges with more than two face users are rejected
- at most 256 ring edges are traversed
- complete geometry limits are preflighted before committing

This is a bounded quad-strip loop-cut foundation. It does not claim Blender's complete loop-cut
behavior across poles, triangles/ngons, multi-cut counts, edge slide or proportional controls.

### `mesh.bridge_boundary_loops`

Bridges two explicit, disjoint boundary loops with equal vertex counts.

- each loop has 3..64 unique vertices
- every consecutive loop pair, including loop closure, must be an existing edge with exactly
  one polygon user
- loops must have equal counts and share no vertices
- corresponding loop segments are connected with one new quad each

Loop ordering and correspondence are explicit inputs; this foundation does not automatically
solve loop alignment, twist minimization or unequal-count resampling.

### `mesh.fill_boundary_loop`

Adds one polygon face across an explicit boundary loop.

- loop contains 3..32 unique vertices
- every loop segment must be an existing boundary edge with one polygon user
- a face containing the same vertex set is rejected as already filled
- the supplied vertex order becomes the new polygon cycle

This is a direct bounded face-fill foundation, not triangulate/grid-fill/beautify-fill.

### Shared Milestone 4 guards

Milestone 4 inherits the topology-rebuild safety boundary from Milestones 2-3:

- fresh ObjectTarget and geometry revision
- editable local unshared mesh data
- Object mode and normal object mutation guards
- no shape keys or modifier stack
- no material slots, vertex groups, UV layers or color attributes during topology rebuild
- existing 4096-vertex, 4096-face, 32768-loop and per-face bounds
- complete geometry readback verification
- restoration of captured vertices/faces on verification failure

No arbitrary bmesh, Python or unrestricted Blender operator execution is exposed.

Milestone 5 is complete. Milestone 6 is complete. Milestone 7 is next: topology cleanup and repair helpers.


## Milestone 5 — 50% complete

Milestone 5 adds bounded source-side shading/normal diagnostics plus conservative smoothing and
face-orientation controls.

### `mesh.shading_inspect`

Read-only diagnostics derived from the bounded base mesh.

For every face it returns:

- a unit face normal computed from the summed triangle-fan area vector
- triangle-fan surface area
- flat/smooth shading state

It also reports:

- smooth and flat face indices
- degenerate face indices
- faces whose accumulated normal vector is ambiguous
- isolated vertices not referenced by any polygon
- boundary edges
- non-manifold edges
- manifold edges whose two polygon users traverse the edge in the same direction
  (`winding_conflict_edges`)
- a separate `shading_revision` derived from geometry revision + per-face smoothing flags

The diagnostic normals are deterministic source-geometry calculations. They are not claimed to
be identical to Blender's evaluated split normals after modifiers, custom normals, sharp edges
or render-time shading.

### `mesh.set_face_smoothing`

Sets `use_smooth` on 1..256 explicit face indices.

The request requires both a fresh geometry revision and a fresh shading revision. The tool
requires editable local unshared mesh data and conservatively denies shape keys/modifiers.
Geometry must remain byte-for-byte equivalent at the bounded indexed-mesh level. Complete
smoothing state is read back and verified; verification failure restores the prior face flags.

### `mesh.orient_faces_consistently`

Makes each manifold-connected polygon component internally winding-consistent.

The tool builds constraints across edges with exactly two polygon users. Neighboring faces are
assigned flip states so their shared edge directions become opposite. Boundary edges are
allowed. Edges with more than two polygon users are rejected, as are contradictory orientation
constraints. Each disconnected face component is anchored independently, so this operation
guarantees local consistency but does **not** claim outward-facing normals.

Because face winding is rebuilt, this tool inherits the topology metadata guard: material
slots, vertex groups, UV layers and color attributes are denied until those layers can be
preserved intentionally. Existing per-face smooth flags are explicitly restored after the
rebuild and included in verification.

### Shared Milestone 5 boundary

- fresh object + geometry state for mutations
- fresh shading state where shading can change or must be preserved
- bounded base mesh only
- no evaluated modifier-stack normal claims
- no custom split-normal editing
- no arbitrary Python, bmesh or unrestricted operator execution
- verification mismatch triggers bounded rollback for smoothing/winding mutations

Milestone 6 is next: hard-surface boolean workflow and stronger modifier modeling controls.


## Milestone 6 — 60% complete

Milestone 6 adds a typed, bounded hard-surface modifier-stack workflow without exposing arbitrary
modifier properties or Python/operator execution.

### `modifier.stack_inspect`

Returns a bounded ordered modifier stack plus a separate `stack_revision`.

For supported hard-surface modifiers it reads back:

- BEVEL: width and segments
- SUBSURF: viewport/render levels
- SOLIDIFY: thickness
- BOOLEAN: operation, solver and referenced cutter object identity/name
- viewport/render visibility for every stack entry

The stack is capped at 16 modifiers. Unknown modifier types may be listed conservatively but
their arbitrary settings are not exposed.

### `modifier.stack_add`

Appends one typed BEVEL, SUBSURF or SOLIDIFY modifier to an existing bounded stack.

Unlike the older Level 1 `modifier.add` safety slice, this tool intentionally permits a
multi-modifier hard-surface stack. It requires a fresh ObjectTarget plus fresh
`stack_revision`, rejects duplicate names/full stacks, and verifies the complete ordered
stack after addition. Verification failure removes the created modifier.

### `modifier.boolean_add`

Creates a non-destructive BOOLEAN modifier referencing an explicit fresh cutter ObjectTarget.

Supported operations:

- DIFFERENCE
- UNION
- INTERSECT

Supported solvers:

- EXACT
- FAST

Target and cutter must be distinct editable local mesh objects inside normal bounded geometry
limits. The tool verifies the cutter object identity/name, operation, solver and ordered stack
readback. This milestone creates/configures Boolean modifiers but deliberately does **not**
apply/evaluate the Boolean into permanent topology, because real Blender solver output still
requires runtime acceptance.

### `modifier.update`

Applies a nonempty typed patch to one existing supported modifier.

Allowlisted patches:

- BEVEL: width, segments
- SUBSURF: levels, render_levels
- SOLIDIFY: thickness
- BOOLEAN: operation, solver
- all supported kinds: show_viewport, show_render

The request includes expected modifier type and fresh stack revision. A type change/stale stack
fails before mutation. Verification mismatch restores the captured patched properties.

### `modifier.move`

Moves one named modifier to an explicit index inside the current bounded stack.

The complete ordered stack is read back and compared after the move. Verification failure
moves the modifier back to its prior index.

### Shared Milestone 6 boundary

- maximum 16 stack entries
- fresh object + stack state for mutations
- editable local mesh targets with bounded base geometry
- shape-key meshes are denied for new hard-surface modifier work
- Boolean cutter must be a different explicit mesh object
- no arbitrary modifier type/property paths
- no generic modifier-apply operator
- no claim that fake-bpy/CI verifies Blender Boolean solver geometry
- failed source-level readback verification performs bounded rollback of the changed stack state

Milestone 7 is complete. Milestone 8 is complete. Milestone 9 is complete. Milestone 10 is complete. The current Level 2 source roadmap is complete at 100%.


## Milestone 7 — 70% complete

Milestone 7 adds one bounded repair diagnostic and three conservative topology-cleanup tools.

### `mesh.repair_inspect`

Read-only repair analysis accepts an explicit near-duplicate distance and face-area epsilon.

It reports:

- near-duplicate vertex groups
- bounded proximity pair-check count
- duplicate face groups using rotation/reversal-insensitive polygon keys
- degenerate face indices by triangle-fan area
- loose/unreferenced vertices
- zero-length/near-zero edges at the requested distance
- boundary and non-manifold edges
- winding-conflict edges
- face-connected components
- a separate `repair_revision` tied to geometry + diagnostic thresholds

Near-duplicate clustering uses a bounded spatial grid/union-find pass rather than exposing an
arbitrary nearest-neighbor routine. Proximity comparisons are capped at 1,000,000 and
diagnostic groups are capped at 512.

### `mesh.merge_by_distance`

Merges all source vertices connected within a bounded distance threshold.

- deterministic cluster representative is the smallest source vertex index
- vertex indices are compacted after merging
- consecutive duplicate polygon vertices are collapsed
- faces reduced below three unique vertices are removed
- self-repeating collapsed polygons are removed as degenerate
- duplicate polygons created by the merge are removed deterministically
- removed/merged source indices are returned as mutation evidence
- source per-face smooth flags are preserved for surviving faces

If no vertex group is within the requested distance, the mutation is rejected as a no-op.

### `mesh.cleanup_faces`

Removes explicit repair candidates without touching vertex coordinates.

- faces at or below the requested area epsilon are removed
- optional duplicate-face cleanup keeps the earliest deterministic face and removes later
  rotation/reversal-equivalent duplicates
- source face smoothing is preserved for surviving faces
- removing every polygon is denied

If no requested cleanup candidate exists, the mutation is rejected as a no-op.

### `mesh.remove_loose_vertices`

Removes vertices not referenced by any polygon and compacts all surviving polygon indices.

- polygon topology/order is otherwise preserved
- per-face smoothing state is preserved
- no-op requests are rejected when no loose vertices exist

### Shared Milestone 7 repair boundary

All repair mutations reuse the conservative topology-rebuild boundary:

- fresh ObjectTarget + fresh geometry revision
- editable local unshared mesh
- Object mode
- no shape keys or modifier stack
- no material slots, UV layers, color attributes or vertex groups during rebuild
- bounded geometry and topology work
- complete indexed geometry readback
- per-face smoothing readback for repair rebuilds
- rollback to captured geometry/smoothing on verification failure

The repair diagnostic is source/base-mesh analysis. It does not claim evaluated modifier,
custom-data-layer or real Blender mesh-validation equivalence.

Milestone 8 is next: retopology and shrinkwrap-oriented helpers.


## Milestone 8 — 80% complete

Milestone 8 adds bounded retopology diagnostics, direct source-to-surface projection, a relax
helper and a typed non-destructive Shrinkwrap workflow.

### `mesh.retopology_inspect`

Reports base-mesh retopology indicators: complete bounded vertex valence and histogram,
boundary vertices, isolated vertices, interior non-4-valence poles, triangle/quad/ngon face
indices, quad ratio and the existing edge/boundary/non-manifold diagnostics.

### `mesh.retopology_projection_inspect`

Previews nearest-surface projection for 1..128 explicit source vertices against a different
target mesh. It converts unparented XYZ source/target base geometry into world space,
triangulates target triangles/quads, computes exact nearest triangle points, and reports target
face/triangle, point, winding normal and distance. Work is capped at 1,000,000
source-vertex × target-triangle comparisons.

Target ngons, target shape keys and target modifier stacks are rejected because this source
milestone does not claim evaluated surface equivalence.

### `mesh.retopology_project`

Projects 1..128 explicit source vertices to the nearest target triangle and optionally offsets
them along the target triangle's world-space winding normal. It requires fresh source/target
ObjectTargets and geometry revisions. Every requested vertex must be inside max_distance before
any source coordinate changes. Complete source geometry is read back; verification failure
restores the captured coordinates.

### `mesh.retopology_relax`

Runs bounded synchronous one-ring relaxation on 1..128 explicit vertices with factor
0.001..1.0, 1..8 iterations and optional boundary preservation. Unselected vertices and faces
remain unchanged.

### `modifier.shrinkwrap_add`

Adds one typed non-destructive SHRINKWRAP modifier with explicit target identity.

Supported methods:
- NEAREST_SURFACEPOINT
- NEAREST_VERTEX

Supported wrap modes:
- ON_SURFACE
- ABOVE_SURFACE

Offset is bounded to -100..100. Existing `modifier.update` also supports typed Shrinkwrap
method, mode, offset and viewport/render visibility patches.

### Shared Milestone 8 boundary

- source/target direct projection objects must be unparented XYZ objects with nonzero scale
- direct projection uses base triangle/quad geometry, not evaluated modifier output
- source direct-projection mesh must be editable/unshared and have no shape keys/modifiers
- no unrestricted Python or operator execution
- direct geometry mutation verifies the complete bounded source mesh and rolls back on mismatch
- Shrinkwrap creation verifies complete ordered modifier-stack state
- fake-bpy/CI evidence does not count as real Blender Shrinkwrap/depsgraph verification

Milestone 9 is next: advanced modeling modifier stack workflows.


## Milestone 9 — 90% complete

Milestone 9 adds typed modifier-stack composition, deterministic presets and stronger
stack diagnostics without exposing arbitrary modifier properties.

### `modifier.stack_diagnose`

Performs read-only bounded modifier-stack diagnostics on the current ordered stack.

It reports:

- type counts
- unsupported modifier indices
- viewport-disabled indices
- render-disabled indices
- missing Boolean/Shrinkwrap object-reference indices
- SUBSURF-before-BEVEL ordering pairs as an explicit modeling warning
- reference-modifier count
- a simple bounded complexity score
- deterministic warning codes
- a separate diagnostic revision

The order warning is advisory rather than a claim that another order is universally wrong.

### `modifier.stack_compose`

Transactionally appends 1..8 explicit typed modifiers in one request.

Supported composed types:

- BEVEL
- SUBSURF
- SOLIDIFY

Each entry contains an explicit unique name plus the already allowlisted settings for its type.
The final stack may not exceed the existing 16-entry stack cap. Name collisions and stale stack
revisions are rejected before creation. The entire ordered resulting stack is read back and
verified. If verification fails, every modifier created by that composition is removed in
reverse order.

BOOLEAN and SHRINKWRAP are intentionally excluded from generic composition because they require
fresh external object references; those continue through their dedicated typed tools.

### `modifier.recipe_preview`

Builds a deterministic no-mutation preview of one allowlisted modeling recipe.

Current recipes:

- `PANEL_SHELL`: SOLIDIFY → BEVEL
- `SUBDIV_BEVEL`: BEVEL → SUBSURF
- `HARD_SURFACE_TRIPLE`: SOLIDIFY → BEVEL → SUBSURF

The request supplies a bounded prefix and exactly the typed parameters required by that recipe.
The response contains final modifier names/types/settings and a recipe revision.

### `modifier.recipe_apply`

Applies one previewable recipe transactionally to a fresh target stack.

The tool:

- validates recipe-specific parameters before mutation
- generates deterministic prefixed modifier names
- checks every generated name for collision
- checks total stack capacity before creation
- creates the complete recipe in declared order
- verifies the full ordered stack through readback
- removes every recipe-created entry if verification fails

Recipes are convenience compositions over the existing typed modifier surface, not arbitrary
scripts or opaque Blender macros.

### Shared Milestone 9 boundary

- no arbitrary modifier classes
- no arbitrary modifier property paths
- no generic modifier apply/evaluation
- stack mutation requires a fresh ObjectTarget and fresh stack revision
- generic composition is capped at 8 new entries and 16 total entries
- recipes are closed allowlisted definitions with exact parameter schemas
- full ordered stack readback is required for successful verification
- fake-bpy/CI verifies stack state/contract behavior only, not Blender modifier evaluation

Milestone 10 is complete. The current Level 2 source roadmap is complete at 100%.


## Milestone 10 — 100% complete

Milestone 10 closes the current Level 2 source roadmap with aggregate modeling QA,
transactional repair workflows, explicit recovery evidence and opt-in Level 2 runtime
acceptance preparation.

### `modeling.qa_inspect`

Aggregates bounded base-mesh, shading, repair, retopology and modifier-stack signals into one
read-only modeling QA report.

The report includes:

- geometry/shading/stack revisions plus a combined `qa_revision`
- vertex/edge/face counts
- triangle/quad/ngon partitions and quad ratio
- interior non-4-valence poles
- near-duplicate vertex groups
- duplicate/degenerate faces
- loose vertices
- zero/near-zero edges
- high-degree non-manifold edges (>2 polygon users)
- winding conflicts
- modifier type/reference/order/visibility diagnostics
- deterministic blocker/advisory codes
- `qa_status`: `BLOCKED`, `REVIEW` or `CLEAN`

The status is a source-side structural QA classification, not an artistic-quality or
production-readiness guarantee.

### `modeling.workflow_preview`

Previews one allowlisted repair workflow without mutation.

Current workflows:

- `CLEAN_BASE_MESH`
- `CLEAN_ORIENT_BASE_MESH`

The preview reports the initial QA revision, current geometry revision, initial triggered steps
and a workflow revision. It explicitly states that repair conditions are re-evaluated after
each executed step because one topology repair can create/remove later cleanup candidates.

### `modeling.workflow_apply`

Runs a bounded transactional repair composition over the existing verified Level 2 tools.

Depending on refreshed readback state it can compose:

1. `mesh.merge_by_distance`
2. `mesh.cleanup_faces`
3. `mesh.remove_loose_vertices`
4. `mesh.orient_faces_consistently` for `CLEAN_ORIENT_BASE_MESH`

The request requires a fresh ObjectTarget, geometry revision and QA revision. A clean no-op
workflow is rejected.

The workflow captures the complete initial indexed geometry and per-face smoothing state before
the first mutation. Every child operation must itself return verified readback. Final QA must
show zero near-duplicate groups, duplicate faces, degenerate faces, loose vertices and
zero-length edges; the orienting workflow additionally requires zero winding conflicts.

If a later step fails after earlier verified mutations, the workflow restores the original
captured vertices/faces and smoothing flags, reads them back, and returns explicit
`rolled_back=true` / `recovery_verified=true` evidence when recovery succeeds. If recovery
cannot itself be verified, the operation escalates to verification failure rather than
claiming a known safe outcome.

All existing topology-rebuild metadata guards remain active: no shape keys/modifiers,
material slots, UV/color layers or vertex groups are silently discarded.

### Level 2 runtime acceptance preparation

The acceptance harness now has a separate `--allow-level2-modeling` opt-in. When enabled in
an explicitly authorized real Blender run, the disposable suite additionally exercises
representative Level 2 topology/shading/retopology inspection, aggregate QA, workflow
preview/apply, modifier recipe preview/apply and stack diagnostics.

The injected fake-session acceptance test covers that path in CI, but it does **not** count as
real Blender runtime verification.

## Level 2 completion boundary

The current Level 2 source roadmap is **100% implemented**.

This means the typed source contracts, bounded algorithms, readback verification, rollback
paths, fake-bpy tests, packaging and CI coverage for the ten defined milestones are complete.
It does **not** mean:

- real Blender 4.2+ runtime behavior is verified
- modifier/Boolean/Shrinkwrap evaluated geometry is proven
- production readiness is achieved
- Level 3 sculpting/character modeling has started

Real Blender runtime verification remains **0%** until the separately authorized acceptance
suite is actually run against Blender.
