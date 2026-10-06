# Level 2 — Professional Modeling

Level 2 moves the Blender agent from broad scene/object control into professional mesh
modeling. This level is intentionally split into ten source milestones so progress can be
measured without pretending fake-bpy tests prove real Blender runtime behavior.

Current Level 2 source progress: **50%**.

Real Blender runtime verification for Level 2: **0%**.

## Roadmap

| Milestone | Scope | Source status |
|---|---|---|
| 1 | Topology foundation + bounded single-face extrusion | complete |
| 2 | Explicit vertex/edge/face transforms, merge and dissolve foundations | complete |
| 3 | Region extrusion, inset and bevel modeling | complete |
| 4 | Loop-cut/subdivide/bridge/fill workflows | complete |
| 5 | Normals, smoothing and shading/topology diagnostics | complete |
| 6 | Hard-surface boolean workflow and stronger modifier modeling controls | pending |
| 7 | Topology cleanup and repair helpers | pending |
| 8 | Retopology and shrinkwrap-oriented helpers | pending |
| 9 | Advanced modeling modifier stack workflows | pending |
| 10 | Modeling QA, recovery, acceptance and workflow composition | pending |

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

Level 1 remains source-complete at 100%. Level 2 currently stands at **50% source completion**.


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

Milestone 5 is complete. Milestone 6 is next: hard-surface boolean workflow and stronger modifier modeling controls.


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
