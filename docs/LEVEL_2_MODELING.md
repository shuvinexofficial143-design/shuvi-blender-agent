# Level 2 — Professional Modeling

Level 2 moves the Blender agent from broad scene/object control into professional mesh
modeling. This level is intentionally split into ten source milestones so progress can be
measured without pretending fake-bpy tests prove real Blender runtime behavior.

Current Level 2 source progress: **20%**.

Real Blender runtime verification for Level 2: **0%**.

## Roadmap

| Milestone | Scope | Source status |
|---|---|---|
| 1 | Topology foundation + bounded single-face extrusion | complete |
| 2 | Explicit vertex/edge/face transforms, merge and dissolve foundations | complete |
| 3 | Region extrusion, inset and bevel modeling | pending |
| 4 | Loop-cut/subdivide/bridge/fill workflows | pending |
| 5 | Normals, smoothing and shading/topology diagnostics | pending |
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

Level 1 remains source-complete at 100%. Level 2 currently stands at **20% source completion**.


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
