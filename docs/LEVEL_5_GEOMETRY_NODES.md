# Level 5 — Geometry Nodes

Level 5 begins after the completed Level 1-4 source roadmaps. It follows the same hard
boundary: source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi bounded procedural modeling and Geometry Nodes workflows without exposing
arbitrary Python, unrestricted node creation or a generic bpy execution surface.

Current Level 5 source progress: **30%**.

Real Blender runtime verification for Level 5: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Geometry Nodes tree inspection | complete |
| 2 | Typed node creation | complete |
| 3 | Typed node linking | complete |
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

Requires a fresh group revision and an existing allowlisted node. Milestone 3 extends this
operation so linked nodes are now handled with bounded typed recovery. Before deletion, source
state captures the node's prior name, label, location, readable input defaults and every
bounded incident link identity.

Removal verifies node absence, exact node-count decrement and exact incident-link removal.
Verification failure recreates the node, restores every captured incident link and only claims
recovery after the original group revision is read back.

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

## Milestone 3 — 30% complete

Milestone 3 adds two explicit typed link mutations and upgrades linked-node recovery.

### `geometry_nodes.link_add`

A link request requires:

- existing local GeometryNodeTree
- fresh `expected_group_revision`
- source allowlisted node name
- source output socket identifier
- destination allowlisted node name
- destination input socket identifier

Socket identifiers come from `geometry_nodes.tree_inspect`, so callers do not rely only on
display names.

The source operation validates:

- both nodes exist and are different nodes
- both nodes are in the Shuvi Geometry Nodes allowlist
- exactly one requested output/input socket identifier resolves at each endpoint
- both socket types are known and exactly equal
- exact duplicate link does not already exist
- a non-multi-input destination has no existing incoming link
- the bounded 128-link work limit is not exhausted
- adding the directed edge would not create a dependency cycle

No implicit socket-type conversion is performed.

Successful creation reads the tree back and verifies both exact link presence and an exact
link-count increment of one. Known verification mismatch removes the new link and verifies the
original group revision before reporting a recovered failure.

### `geometry_nodes.link_remove`

Removal uses the same explicit node/socket identifiers plus a fresh group revision. The exact
existing link must be present. It verifies exact absence and an exact link-count decrement of
one.

Known verification failure recreates the original link and verifies restoration of the original
group revision.

### Linked-node removal recovery

`geometry_nodes.node_remove` now captures all bounded incident links before an allowlisted
node is removed. A successful node removal accounts for the exact number of links Blender
removes with that node.

If node-removal verification fails, recovery recreates the node and restores all captured
incident links using their node names and socket identifiers. Recovery success is not claimed
until the original group revision is restored.

### Bounded registry-cap increase

Milestones 1-2 reached the previous 160-tool hard limit. Milestone 3 deliberately changes the
shared registry/client maximum from **160 to 168** and adds only two new typed operations.
The factory therefore contains **162 typed tools** at this checkpoint. The extra capacity is
bounded and does not introduce a generic executor.

## Safety boundary

Milestones 1-3 do **not** expose:

- arbitrary Python
- arbitrary node idnames
- generic node property mutation
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

## Verified 30% source checkpoint

Source/test checkpoint: `492d4c91f2712a8d0eda83a72b81fb474633db8d`.

CI run `37452665272` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **567 tests**
- package build
- distribution audit
- clean install/import without bpy
- **67 package modules**

Factory typed tools: **162**.
Current registry/catalog hard maximum: **168**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **100%**.
Level 5 source: **30%** (Milestones 1-3 of 10).

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestone 4 — modifier + node-group binding — is the next source task, but it must not start
without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real Geometry Nodes runtime
acceptance without separate explicit runtime authorization.
