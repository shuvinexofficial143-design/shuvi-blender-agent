# Level 5 — Geometry Nodes

Level 5 begins after the completed Level 1-4 source roadmaps. It follows the same hard
boundary: source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi bounded procedural modeling and Geometry Nodes workflows without exposing
arbitrary Python, unrestricted node creation or a generic bpy execution surface.

Current Level 5 source progress: **60%**.

Real Blender runtime verification for Level 5: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Geometry Nodes tree inspection | complete |
| 2 | Typed node creation | complete |
| 3 | Typed node linking | complete |
| 4 | Modifier + node-group binding | complete |
| 5 | Procedural modeling primitives | complete |
| 6 | Attribute / field workflows | complete |
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

## Milestone 4 — 40% complete

Milestone 4 attaches bounded GeometryNodeTree groups to editable mesh objects through typed
NODES modifier operations.

### `geometry_nodes.modifier_inspect`

This read-only operation resolves one current-session mesh object and reports only NODES
modifiers from the existing bounded modifier stack. Each binding includes:

- modifier name/type
- viewport/render visibility
- bound node-group name when present
- whether the group is local
- node-tree type
- fresh group revision for a bounded local GeometryNodeTree

Broken NODES modifiers with no group are reported explicitly rather than treated as valid.
The response also contains the object's current revision and a deterministic binding revision.

Object snapshots now include `node_group_name` for NODES modifiers, so binding changes
participate in the ordinary object revision and stale ObjectTarget protection.

### `geometry_nodes.modifier_bind`

Binding requires:

- fresh ObjectTarget
- fresh expected GeometryNodeTree revision
- OBJECT mode
- editable local mesh object
- local mesh data without shape keys
- mesh geometry inside existing modifier work limits
- modifier stack below the 16-entry bound
- unique modifier name
- bounded local GeometryNodeTree

The operation creates exactly one `NODES` modifier and assigns exactly the requested node
group. Existing modifiers are preserved.

Successful readback verifies:

- exact modifier-count increment
- exact NODES modifier name/type
- exact bound group name
- object snapshot reports the same group
- node-group revision is unchanged by binding

Known verification failure removes the created modifier, updates the view layer and verifies
restoration of both the original object revision and the original group revision.

### `geometry_nodes.modifier_remove`

Removal requires a fresh ObjectTarget, fresh group revision and an exact NODES modifier that is
currently bound to the requested group.

Successful readback verifies:

- exact modifier-count decrement
- requested modifier is absent
- requested binding is absent
- node-group revision is unchanged

Before removal, recovery state records the modifier stack index plus viewport/render flags and
the exact group object. If verification fails, the modifier is recreated, rebound, restored to
its original stack position and visibility flags, then the original object/group revisions are
verified before recovery is claimed.

### Bounds

Milestone 4 adds three typed operations, taking the factory from 162 to **165 typed tools**.
The centralized registry/client maximum remains **168**.

## Milestone 5 — 50% complete

Milestone 5 adds deterministic procedural primitive recipes that can create a complete
source-side Geometry Nodes graph with an explicit Geometry output interface.

### `geometry_nodes.primitive_preview`

Preview is read-only and supports exactly three recipes:

- `CUBE`
- `ICO_SPHERE`
- `TWIN_CUBE`

Every preview returns:

- normalized bounded parameters
- deterministic node names and editor locations
- exact typed default values
- exact link topology
- one Geometry output interface specification
- one internal Group Output target
- deterministic `primitive_revision`
- `source_only=true`
- `real_runtime_verified=false`

`CUBE` exposes bounded size plus a uniform vertex count 2..64.
`ICO_SPHERE` exposes radius and subdivisions 1..5.
`TWIN_CUBE` exposes bounded size, vertex count and a ±1000 translation offset for the
second cube.

### `geometry_nodes.primitive_apply`

Apply requires:

- existing local GeometryNodeTree
- fresh `expected_group_revision`
- an entirely empty node tree
- no existing links or interface sockets
- at most one current node-group user
- one supported recipe/prefix/parameter set

The empty-tree requirement prevents recipe application from silently overwriting or merging
with foreign graphs.

Apply creates:

- one Geometry output interface socket through the bounded Blender node-group interface API
- one internal `NodeGroupOutput` node
- only existing allowlisted Geometry Nodes for the selected recipe
- deterministic node names, locations and typed defaults
- exact source-side links ending at Group Output → Geometry

The internal Group Output is not added to the public generic node-type allowlist, so callers
cannot request arbitrary Group Output creation through `geometry_nodes.node_add`.

Verification compares the complete bounded source intent:

- interface name/direction/socket type
- exact node names/types/locations
- exact non-null input defaults
- exact link endpoints/socket names

Known verification failure removes all created recipe nodes plus the output interface and
verifies restoration of the original empty group revision.

### `geometry_nodes.primitive_clear`

Clear requires the current tree to exactly match the requested recipe, prefix and parameters
before any mutation occurs. A changed default, extra/foreign node, altered link, interface
change or different recipe fails closed.

Successful clear removes only the exact recipe graph and its one managed Geometry output
interface, then verifies:

- zero nodes
- zero links
- empty interface

Known clear verification failure rebuilds the exact recipe and verifies the original
group revision before recovery is claimed.

### Bounds and runtime boundary

Milestone 5 adds three typed operations, taking the factory from 165 to **168 typed tools**.
This exactly reaches the current **168-tool** registry/client hard cap.

The source recipes establish deterministic graph/output intent only. Fake-bpy and CI do not
prove real Blender Geometry Nodes modifier evaluation, generated topology, dependency-graph
updates, viewport behavior or render output.

## Milestone 6 — 60% complete

Milestone 6 adds deterministic bounded field-to-attribute workflows without exposing a generic
field graph or arbitrary Store Named Attribute property editor.

### `geometry_nodes.field_preview`

Preview supports exactly three workflows:

- `INDEX_ATTRIBUTE`
- `POSITION_ATTRIBUTE`
- `NORMAL_ATTRIBUTE`

Every workflow uses one bounded Mesh Cube source, one built-in field source, one internal
Store Named Attribute node and one internal Group Output.

The workflow metadata is fixed:

- INDEX_ATTRIBUTE → Index field → INT attribute on POINT domain
- POSITION_ATTRIBUTE → Position field → FLOAT_VECTOR attribute on POINT domain
- NORMAL_ATTRIBUTE → Normal field → FLOAT_VECTOR attribute on POINT domain

Attribute names must:

- start with `shuvi_`
- contain a non-empty suffix
- use only ASCII letters, digits and underscore
- remain within 48 UTF-8 bytes

The preview returns deterministic node names/locations, exact links, exact managed attribute
metadata, one Geometry output interface intent, `source_only=true`,
`real_runtime_verified=false`, and a deterministic `field_workflow_revision`.

### `geometry_nodes.field_apply`

Apply requires:

- existing local GeometryNodeTree
- fresh `expected_group_revision`
- completely empty node tree
- no existing links or interface sockets
- at most one current node-group user
- one supported workflow and bounded parameter set

Apply creates exactly:

- one Mesh Cube node
- one allowlisted built-in field node (Index, Position, or Normal)
- one internal `GeometryNodeStoreNamedAttribute`
- one internal `NodeGroupOutput`
- one Geometry output interface socket
- three deterministic links

The Store Named Attribute node's `data_type` and `domain` are set internally from the
workflow definition. Callers cannot provide arbitrary values for those properties.

Geometry-node inspection now reports `field_settings` for Store Named Attribute nodes,
including exact `data_type` and `domain`. Those settings are included in the node-group
revision, so field-setting changes become stale-state-visible.

Apply verification compares:

- exact interface
- exact node names/types/locations
- selected typed default values
- exact Store Named Attribute data type/domain
- exact link topology

Known verification failure removes all workflow nodes/interface and verifies restoration of the
original empty group revision.

### `geometry_nodes.field_clear`

Clear first requires the current graph to exactly match the requested workflow, prefix and
parameters. Any changed attribute name, data type, domain, default value, link, interface,
extra node or foreign node fails closed.

Successful clear verifies a completely empty group. Known verification failure rebuilds the
exact workflow and verifies restoration of the original group revision.

### Bounds and runtime boundary

The centralized registry/client cap is deliberately raised from **168 to 176**. Milestone 6
adds three typed operations, taking the factory from 168 to **171 typed tools**.

The source/fake-bpy evidence proves only deterministic graph intent and readback. It does not
prove real Blender field evaluation, attribute storage on generated geometry, domain behavior,
modifier evaluation, dependency-graph updates, viewport output or rendering.

## Safety boundary

Milestones 1-6 do **not** expose:

- arbitrary Python
- arbitrary node idnames
- generic node property mutation
- unrestricted object/collection/material references
- simulation zones
- repeat zones
- real Geometry Nodes evaluation
- render/GPU execution

Fake-bpy tests validate contracts, bounds, stale-state handling and source-side readback
algorithms only. They do not establish Blender Geometry Nodes API/runtime compatibility.

## Verified 60% source checkpoint

Source/test checkpoint: `6f02087b402c6a737af80f7cae879f4d5962a956`.

CI run `37487992573` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **620 tests**
- package build
- distribution audit
- clean install/import without bpy
- **70 package modules**

Factory typed tools: **171**.
Current registry/catalog hard maximum: **176**.

Level 1 source: **100%**.
Level 2 source: **100%**.
Level 3 source: **100%**.
Level 4 source: **100%**.
Level 5 source: **60%** (Milestones 1-6 of 10).

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestone 7 — procedural scatter systems — is the next source task, but it must not start
without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real Geometry Nodes runtime
acceptance without separate explicit runtime authorization.
