# Level 2 — Professional Modeling

Level 2 moves the Blender agent from broad scene/object control into professional mesh
modeling. This level is intentionally split into ten source milestones so progress can be
measured without pretending fake-bpy tests prove real Blender runtime behavior.

Current Level 2 source progress: **10%**.

Real Blender runtime verification for Level 2: **0%**.

## Roadmap

| Milestone | Scope | Source status |
|---|---|---|
| 1 | Topology foundation + bounded single-face extrusion | complete |
| 2 | Explicit vertex/edge/face transforms, merge and dissolve foundations | pending |
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

Level 1 remains source-complete at 100%. Level 2 currently stands at **10% source completion**.
