# Level 6 — Rigging

Level 6 begins after the completed Level 1-5 source roadmaps. It keeps the same hard boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi bounded armature, bone, posing, constraint, skinning and rig-workflow control
without exposing arbitrary Python, unrestricted bpy operators or a generic rig mutation surface.

Current Level 6 source progress: **80%**.

Real Blender runtime verification for Level 6: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Armature + bone hierarchy inspection | complete |
| 2 | Armature creation + bounded edit-bone creation | complete |
| 3 | Bone parenting / connect / rename / symmetry-safe editing | complete |
| 4 | Pose transforms + bounded pose controls | complete |
| 5 | Rig constraints + IK foundations | complete |
| 6 | Mesh-to-armature binding + Armature modifier | complete |
| 7 | Vertex groups + bounded weight workflows | complete |
| 8 | IK/FK control-rig helpers | complete |
| 9 | Versioned rig recipe library | pending |
| 10 | Rigging QA / recovery / acceptance | pending |

## Milestone 1 — 10% complete

Milestone 1 adds one bounded read-only armature inspection surface.

### `rig.armature_inspect`

The tool accepts one current-session object ID and requires the resolved object to be an
ARMATURE with armature data.

It reports:

- armature object and datablock names
- current object revision
- linked-object and linked-armature-data flags
- deterministic bone count and pose-bone count
- sorted root-bone names
- parent relationship for every bone
- local bone head and tail coordinates
- local 4x4 bone matrix when exposed by the adapter
- connect/deform flags and inherit-scale mode
- pose-bone location, Euler rotation, quaternion rotation and scale
- bounded pose-constraint name/type/mute/influence metadata
- missing/extra pose-bone names compared with armature data
- hierarchy-cycle diagnostic
- deterministic `rig_revision`
- explicit `source_only=true`
- explicit `real_runtime_verified=false`

### Bounds

Milestone 1 fails closed when:

- the target is not an armature object
- armature bone count exceeds **256**
- pose-bone count exceeds **256**
- one pose bone has more than **64 constraints**
- total pose constraints exceed **512**
- inspected coordinates/matrices/constraint influence contain non-finite values
- required text or vector/matrix dimensions exceed the typed inspection bounds

The inspection is exact within these bounds; it does not silently truncate bone or pose data.

### Safety boundary

Milestone 1 does not:

- create an armature
- create, rename, delete, parent or move bones
- enter Edit/Pose mode
- apply pose transforms
- add constraints
- create IK
- bind a mesh
- add an Armature modifier
- create or edit vertex groups/weights
- execute arbitrary Python or unrestricted Blender operators

The factory now exposes **184 typed tools**. Level 6 raises the centralized registry/client
hard maximum from **184 to 192** so later bounded Level 6 milestones have explicit capacity.

Real Blender armature API behavior, edit-bone lifetime rules, pose evaluation, dependency-graph
updates, constraints, deformation, skinning, weight normalization and viewport behavior remain
runtime-unverified.


## Milestone 2 — 20% complete

Milestone 2 adds two bounded mutation tools over the Milestone 1 inspection/revision surface.

### `rig.armature_create`

Armature creation accepts:

- unique object name
- bounded object transform
- fresh scene revision

It requires Object mode and creates one local armature datablock named from the object plus one
scene-linked ARMATURE object. Successful verification checks:

- exact requested object name/type/transform
- scene membership
- exact armature datablock name
- zero initial bones and pose bones
- local/unlinked object and armature data

Known verification mismatch removes the created object and armature datablock.

### `rig.bone_create`

Bone creation accepts:

- fresh ObjectTarget
- fresh `expected_rig_revision`
- unique bone name
- bounded head and tail coordinates
- optional `use_deform` boolean

The target must be an editable local ARMATURE in Object mode and must already be selected and
active. Shuvi then performs only the bounded internal mode transition required by Blender:

Object → Edit Armature → create one edit bone → Object.

Milestone 2 intentionally creates only a standalone root bone:

- parent = null
- use_connect = false
- no rename
- no mirror
- no hierarchy edit
- no constraints or IK

These remain Milestone 3+ scope.

Head and tail coordinates are each bounded to ±100000 Blender units and must differ.

Successful readback verifies:

- exact +1 bone count
- exact bone name
- exact local head/tail
- root parent state
- fixed disconnected state
- requested deform flag
- same armature object identity
- final Object mode

Known verification mismatch re-enters bounded armature Edit mode, removes only the just-created
bone, returns to Object mode and verifies recovery to the original `rig_revision`.

### Milestone 2 source checkpoint

Code/test checkpoint: `2bdef6e4f3d20f59bad97191a677878a97eff7a8`.

CI run `37582553780` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **729 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **186**.
Current registry/catalog hard maximum: **192**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.


## Milestone 3 — 30% complete

Milestone 3 adds two bounded mutation tools over the fresh `rig_revision` surface.

### `rig.bone_hierarchy_edit`

Hierarchy editing accepts:

- fresh ObjectTarget
- fresh `expected_rig_revision`
- current bone name
- requested final bone name
- explicit parent name or null
- explicit `use_connect`

The target must be an editable local armature in Object mode, selected and active. The edit is
rejected before mutation if the requested parent is missing, the final name collides, a connected
bone has no parent, or the requested relationship would create a hierarchy cycle.

Connected edits deterministically place the child head at the requested parent's tail before
enabling `use_connect`. Successful readback verifies unchanged bone count, final name/parent,
connect state, expected head/tail/deform state, the same armature object, Object mode and no
hierarchy cycle.

Known verification mismatch restores the original name, parent, head, tail and connect state,
returns to Object mode and verifies the original `rig_revision`.

### `rig.bone_symmetry_edit`

Symmetry editing accepts one explicit matching `.L` / `.R` bone pair plus bounded left-side
head/tail coordinates. It mirrors the left coordinates across local X onto the right bone.

The operation requires both bones to exist and be disconnected. It never guesses a counterpart,
never scans by fuzzy name and never applies global mirror operators. Head/tail values remain
bounded to ±100000 Blender units and must define a non-zero bone.

Successful readback verifies unchanged bone count, exact left coordinates, exact X-mirrored right
coordinates, preserved parent/deform state, the same armature object and final Object mode.
Known verification mismatch restores both bones' original coordinates and verifies the original
`rig_revision`.

Milestone 3 does not add pose transforms, constraints, IK, mesh binding, Armature modifiers,
vertex groups or weight editing. Those remain Milestones 4+.

### Milestone 3 source checkpoint

Code/test checkpoint: `ce4734eac961fc03bf081739de49ca99fc46390f`.

CI run `37602106158` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **737 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **188**.
Current registry/catalog hard maximum: **192**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.


## Milestone 4 — 40% complete

Milestone 4 adds two bounded pose-channel mutation tools over the fresh `rig_revision` surface.

### `rig.pose_bone_transform`

Pose transforms accept:

- fresh ObjectTarget
- fresh `expected_rig_revision`
- explicit pose-bone name
- bounded location
- rotation mode `XYZ` or `QUATERNION`
- bounded rotation payload
- bounded positive scale

The target must be an editable local armature in Object mode, selected and active. The pose bone
must already exist in the inspected pose map. Milestone 4 writes only the explicit raw pose
channels; it does not add constraints, IK, drivers or a generic pose operator surface.

Location components are bounded to ±100000 Blender units. XYZ Euler components are bounded to
±1000 radians. Quaternion payloads contain exactly four finite components in [-1, 1], must be
non-zero, and are deterministically normalized before write/readback verification. Scale has
exactly three finite components in [0.001, 1000].

Successful readback verifies the same armature object, Object mode, exact requested location and
scale, requested rotation mode, and the corresponding Euler or normalized quaternion channel.
Known verification mismatch restores the original rotation mode, location, Euler rotation,
quaternion rotation and scale, updates the view layer and verifies recovery to the original
`rig_revision`.

### `rig.pose_bone_reset`

Pose reset accepts a fresh ObjectTarget, fresh `expected_rig_revision` and one explicit pose-bone
name. It restores only that bone to deterministic identity pose channels:

- rotation mode = `QUATERNION`
- location = [0, 0, 0]
- Euler rotation = [0, 0, 0]
- quaternion rotation = [1, 0, 0, 0]
- scale = [1, 1, 1]

Successful readback verifies the exact identity state, same armature object and Object mode.
Known verification mismatch restores the complete pre-call pose state and verifies recovery to
the original `rig_revision`.

Pre-existing pose constraints are inspected but not created, changed or removed by Milestone 4.
Constraint authoring and IK remain Milestone 5 scope.

### Milestone 4 source checkpoint

Code/test checkpoint: `38dddb6a8282a7be487fe3bc62522823bc02da2d`.

CI run `37605704490` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **748 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **190**.
Current registry/catalog hard maximum: **192**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.


## Milestone 5 — 50% complete

Milestone 5 adds two bounded mutation tools for pose constraints and same-armature IK foundations.

### `rig.pose_constraint_create`

Constraint creation requires:

- fresh ObjectTarget
- fresh `expected_rig_revision`
- one explicit existing pose-bone owner
- a unique bounded constraint name
- constraint type `LIMIT_ROTATION` or `IK`
- influence in [0, 1]
- explicit mute state

The target must remain an editable local armature in Object mode, selected and active. Creation
fails closed at the existing bounds of **64 constraints per pose bone** and **512 total pose
constraints**.

For `LIMIT_ROTATION`, all X/Y/Z enable flags and min/max values are explicit. Limits are finite,
bounded to ±1000 radians, and each minimum must not exceed its maximum.

For `IK`, the target is restricted to one explicit pose bone in the same armature. The target
bone must exist in both armature and pose data, must differ from the owner bone, and chain count
is bounded to **1..64**. No arbitrary target object, pole target, solver settings, Python, driver
or unrestricted constraint payload is exposed.

Successful readback verifies the full managed constraint state, per-bone and total constraint
counts, the same armature object and final Object mode. Known verification mismatch removes the
exact created constraint object and verifies recovery to the original `rig_revision`.

### `rig.pose_constraint_remove`

Constraint removal requires the same fresh target/revision gates plus an explicit constraint name
and expected type. Only managed `LIMIT_ROTATION` / same-armature `IK` state within the same
bounds is removable.

Removal is intentionally limited to the **final constraint on that pose bone**. This preserves
constraint ordering during append-based recovery. Successful readback verifies exact absence and
the decremented per-bone/total counts. Known verification mismatch recreates the removed
constraint from the bounded snapshot and verifies recovery to the original `rig_revision`.

Milestone 5 does not bind meshes, add Armature modifiers, edit vertex groups/weights, or expose
general IK/FK control-rig generation. Those remain Milestones 6+.

### Milestone 5 source checkpoint

Code/test checkpoint: `7732e365f7259cc9dfb951ac25517b6f439ecfda`.

CI run `37607776888` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **759 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **192**.
Current registry/catalog hard maximum: **192**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.


## Milestone 6 — 60% complete

Milestone 6 adds two bounded mutation tools for establishing and removing a mesh-to-armature
binding through one explicit Blender `ARMATURE` modifier.

### `rig.mesh_armature_bind`

Binding requires:

- fresh mesh ObjectTarget
- fresh armature ObjectTarget
- fresh `expected_rig_revision`
- explicit unique modifier name
- editable local mesh and armature objects/data
- Object mode
- unparented mesh
- no shape keys
- no pre-existing vertex groups
- empty modifier stack
- bounded mesh work: at most 4096 vertices, 4096 polygons and 32768 polygon indices

The tool creates exactly one `ARMATURE` modifier and fixes the managed settings to:

- target = the explicit armature object
- `use_vertex_groups=true`
- `use_bone_envelopes=false`
- viewport/render enabled

Milestone 6 deliberately does **not** parent the mesh, create vertex groups, assign weights,
invoke automatic weights, use bone envelopes, or expose a generic modifier-settings surface.

Successful readback verifies:

- same mesh object identity
- same explicit armature identity
- mesh remains unparented
- modifier count becomes exactly one
- exact modifier name/type/settings
- modifier target resolves to the expected armature object ID
- armature `rig_revision` remains unchanged
- final Object mode

Known verification mismatch removes the exact created modifier and verifies both the original mesh
object revision and original armature `rig_revision`.

### `rig.mesh_armature_unbind`

Unbind uses the same fresh mesh/armature/rig gates and only accepts the narrow M6-managed state:

- unparented mesh
- no vertex groups
- exactly one modifier
- explicit modifier is `ARMATURE`
- modifier target is the explicit armature
- managed viewport/render and vertex-group/envelope flags are unchanged

Successful readback verifies exact modifier absence, zero remaining modifiers, unchanged
armature `rig_revision`, same object identities and Object mode. Known verification mismatch
recreates the exact managed Armature modifier and verifies recovery to the original mesh and rig
revisions.

This zero-vertex-group unbind restriction is intentional for the Milestone 6 source boundary.
Milestone 7 owns vertex-group and weight workflows and may extend later integration behavior.

### Milestone 6 source checkpoint

Code/test checkpoint: `3777267dc806f6aab550c3c103f9b380fcaa6095`.

CI run `37623998540` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **767 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **194**.
Current registry/catalog hard maximum: **200**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.


## Milestone 7 — 70% complete

Milestone 7 adds one bounded read-only skin-weight inspection surface plus two explicit
vertex-group mutation tools over the Milestone 6 managed Armature binding.

### `rig.mesh_weights_inspect`

Weight inspection accepts one current-session mesh object ID and one current-session armature
object ID. The pair must already use the exact managed Milestone 6 `ARMATURE` modifier state.

The inspection reports:

- mesh object ID and armature object ID
- managed Armature modifier name
- mesh vertex count
- vertex-group count
- total sparse weight-assignment count
- each vertex group in exact contiguous Blender group-index order
- each group's explicit sparse `vertex_index + weight` assignments
- group names that do not match armature bones
- group names that match non-deform bones
- deterministic `weight_revision`
- current armature `rig_revision`
- `source_only=true`
- `real_runtime_verified=false`

Inspection fails closed above **64 vertex groups**, above **16,384 total weight assignments**,
above **64 memberships per vertex**, or when group indices/memberships/weights are malformed.
Weights must be finite and remain inside [0, 1].

### `rig.vertex_group_weights_set`

Weight replacement requires:

- fresh mesh ObjectTarget
- fresh armature ObjectTarget
- fresh `expected_rig_revision`
- fresh `expected_weight_revision`
- one explicit existing deform-enabled bone name
- **1..4096** unique explicit sparse vertex assignments
- each assignment's vertex index in 0..4095 and actual mesh bounds
- each requested weight in **0.000001..1.0**

The mesh must remain local, editable, Object-mode, unparented, without shape keys, within the
existing 4096-vertex / 4096-polygon / 32768-loop bounds, and bound through exactly one managed
Milestone 6 Armature modifier targeting the explicit armature.

The operation is a **full replacement of one bone-matched vertex group's sparse weight map**.
If the group is absent it is appended, subject to the 64-group cap. It does not guess bone names,
create arbitrary groups, normalize across neighboring groups, invoke automatic weights, or expose
Weight Paint operators.

Successful readback verifies the exact group name/index/weight map, group count, assignment count,
mesh and armature identities, unchanged `rig_revision`, and Object mode. Known verification
mismatch restores the exact prior group state and verifies the original `weight_revision`.

### `rig.vertex_group_remove`

Removal uses the same fresh target/revision gates and only permits a group whose name matches an
existing deform-enabled bone. For deterministic append-based recovery, only the **final vertex
group** in Blender group-index order can be removed.

Successful readback verifies exact group absence, decremented group/assignment counts, unchanged
object identities, unchanged `rig_revision`, and Object mode. Known verification mismatch
recreates the group and exact sparse weights and verifies recovery to the original
`weight_revision`.

Milestone 7 deliberately does not add automatic skinning, envelope weighting, normalization,
weight mirroring, weight-paint brush control, weight transfer or IK/FK rig generation. Those remain
outside this milestone.

### Milestone 7 source checkpoint

Code/test checkpoint: `b5639b28bde191ad6e98036a465bf470d4e123ea`.

CI run `37634813759` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **779 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **197**.
Current registry/catalog hard maximum: **200**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.


## Milestone 8 — 80% complete

Milestone 8 adds a compact three-tool IK/FK helper surface that uses the existing bounded
pose-constraint primitives instead of introducing a generic control-rig mutation API.

### `rig.ik_fk_preview`

Preview accepts one current-session armature object ID plus four explicit distinct bone names:

- upper deform bone
- middle deform bone
- end deform bone
- non-deforming IK target/control bone
- explicit managed constraint name

The chain must be exactly upper → middle → end in the existing armature hierarchy, all three
chain bones must be deform-enabled, and the target control bone must be non-deforming. Preview
reports the current matching constraint, whether it is recognized as the managed M8 helper, and
the resulting mode (`IK`, `FK`, or null), together with the current `rig_revision`.

### `rig.ik_fk_setup`

Setup requires a fresh ObjectTarget and fresh `expected_rig_revision`, validates the same
explicit chain, and creates exactly one managed same-armature `IK` constraint on the end bone:

- constraint target = the same armature object
- target bone = explicit non-deforming control bone
- chain count = **3**
- influence = **1.0**
- initial mode `IK` => constraint unmuted
- initial mode `FK` => constraint muted

The helper does not create control bones, pole targets, drivers, custom properties, arbitrary
constraint types or automatic rig generation. Existing `rig.bone_create` can create a bounded
non-deforming control bone, and existing `rig.pose_constraint_remove` remains the cleanup path.

Successful readback verifies the exact managed constraint, object identity, requested IK/FK mode
and final Object mode. Known verification mismatch removes the exact just-created constraint and
verifies recovery to the original `rig_revision`.

### `rig.ik_fk_switch`

Switch requires the same explicit chain and fresh ObjectTarget/`rig_revision`. It only accepts
a constraint already recognized as the M8-managed helper. Switching changes one field only:

- `IK` => `mute=false`
- `FK` => `mute=true`

No pose channels, weights, bone hierarchy, target bone or constraint topology are changed by the
switch. Exact readback verifies the managed helper and requested mode; mismatch restores the
previous mute state and verifies recovery to the original `rig_revision`.

### Milestone 8 source checkpoint

Code/test checkpoint: `5dad53c97596daa131dce1ca847d819ceaf36ab1`.

CI run `37636963291` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **790 tests**
- package build
- distribution audit
- clean install/import without bpy
- **75 package modules**

Factory typed tools: **200**.
Current registry/catalog hard maximum: **200**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestones 1-8 are complete at 80%. Do not begin Milestone 9 without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real rigging runtime
acceptance without separate explicit runtime authorization.
