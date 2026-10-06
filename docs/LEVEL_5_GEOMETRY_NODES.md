# Level 5 — Geometry Nodes

Level 5 begins after the completed Level 1-4 source roadmaps. It follows the same hard
boundary: source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi bounded procedural modeling and Geometry Nodes workflows without exposing
arbitrary Python, unrestricted node creation or a generic bpy execution surface.

Current Level 5 source progress: **20%**.

Real Blender runtime verification for Level 5: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Geometry Nodes tree inspection | complete |
| 2 | Typed node creation | complete |
| 3 | Typed node linking | pending |
| 4 | Modifier + node-group binding | pending |
| 5 | Procedural modeling primitives | pending |
| 6 | Attribute / field workflows | pending |
| 7 | Procedural scatter systems | pending |
| 8 | Procedural architecture / environment | pending |
| 9 | Geometry Nodes recipe library | pending |
| 10 | Geometry Nodes QA / recovery / acceptance | pending |

## Milestone 1 — 10% complete

Milestone 1 adds one bounded read-only Geometry Nodes inspection surface.

### `geometry_nodes.tree_inspect`

The tool requires one existing local GeometryNodeTree group by name. It reports:

- group name and tree type
- node count and link count
- fresh deterministic `group_revision`
- bounded group-interface input/output socket metadata
- every bounded node's name, label, Blender idname and Shuvi-managed type when allowlisted
- deterministic node location
- bounded input and output socket metadata
- socket name, identifier, socket type, direction, linked state and multi-input state
- bounded JSON-safe default values when the socket exposes one
- complete bounded link topology
- nested node-group names referenced by inspected nodes

Inspection limits:

- at most 64 nodes
- at most 128 links
- at most 64 interface sockets
- at most 32 inputs per node
- at most 32 outputs per node
- at most 32 nested group names

Foreign/unmanaged nodes may be inspected inside the bounded tree but are not automatically
eligible for mutation.

The snapshot revision covers the bounded interface, node/socket state, link topology and nested
group references. This revision is required by all Milestone 2 node mutations.

## Milestone 2 — 20% complete

Milestone 2 adds a typed Geometry Nodes creation/editing foundation through four mutations.

### `geometry_nodes.group_create`

Creates exactly one new local `GeometryNodeTree` datablock with a bounded UTF-8 name.
Existing names fail closed. Creation is verified by actual readback of group name, tree type,
node count and link count. A failed verification removes the newly created group.

The source foundation deliberately creates an empty node group. Modifier binding, standard
geometry interface creation and object attachment remain later milestones.

### `geometry_nodes.node_add`

Requires:

- existing local GeometryNodeTree
- fresh `expected_group_revision`
- one allowlisted node type
- unique bounded node name
- optional bounded 2D editor location

If location is omitted, placement is deterministic on a fixed four-column grid. The current
source allowlist contains ten Blender Geometry Nodes types:

- MESH_CUBE
- MESH_ICO_SPHERE
- JOIN_GEOMETRY
- TRANSFORM_GEOMETRY
- SET_POSITION
- INPUT_POSITION
- INPUT_NORMAL
- INPUT_INDEX
- REALIZE_INSTANCES
- INSTANCE_ON_POINTS

No arbitrary Blender node idname from a caller is passed to `nodes.new`.

Verification reads back:

- requested node name
- mapped allowlisted node type
- deterministic/requested location
- exact bounded node-count increment

Known verification failure removes the created node and verifies restoration of the original
group revision.

### `geometry_nodes.node_remove`

Requires a fresh group revision and an existing allowlisted node. Removal is intentionally
conservative at this stage: a node with any incoming or outgoing link is rejected until
Milestone 3 provides typed link capture/recovery.

For an unlinked allowlisted node, source state needed for recovery is captured before mutation.
Removal verifies node absence and the exact node-count decrement. Verification failure
recreates the node with its prior name, label, location and readable input defaults, then
verifies restoration of the original group revision.

### `geometry_nodes.node_set_input`

Requires:

- fresh group revision
- existing allowlisted node
- existing input socket
- unlinked input socket
- socket name specifically allowlisted for that node type
- typed bounded value matching the socket rule

Current editable typed defaults include bounded cube size/resolution, Icosphere radius/
subdivision, transform translation/rotation/scale, Set Position field defaults and
Instance-on-Points selection/index/rotation/scale controls.

The tool never disconnects an existing link in order to set a default value. Linked inputs fail
closed. Successful mutation reads back the exact requested default value. Verification failure
restores the previous value and verifies the original group revision.

## Safety boundary

Milestones 1-2 do **not** expose:

- arbitrary Python
- arbitrary node idnames
- generic node property mutation
- typed socket linking/disconnecting
- Geometry Nodes modifier binding
- node-group interface mutation
- unrestricted object/collection/material references
- procedural recipe execution
- simulation zones
- repeat zones
- real Geometry Nodes evaluation
- render/GPU execution

Fake-bpy tests validate contracts, bounds, stale-state handling and source-side readback
algorithms only. They do not establish Blender Geometry Nodes API/runtime compatibility.

## Verified 20% source checkpoint

Source/test checkpoint: `34d57faf3c9fafd0cf27d3e724f563de6aba821b`.

CI run `37451234147` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **556 tests**
- package build
- distribution audit
- clean install/import without bpy
- **67 package modules**

Factory typed tools: **160**.
Current registry/catalog hard maximum: **160**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **100%**.
Level 5 source: **20%** (Milestones 1-2 of 10).

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestone 3 — typed node linking — is the next source task, but it must not start without
explicit user permission.

The current factory exactly reaches the existing 160-tool hard cap. Before Milestone 3 adds new
typed operations, the cap must be deliberately and boundedly increased with the existing
registry/client cap tests kept in sync. Reaching the cap is not permission to expose generic
operations or collapse multiple unsafe actions into an unrestricted executor.

Do not install, probe, launch or render Blender and do not execute real Geometry Nodes runtime
acceptance without separate explicit runtime authorization.
