# Level 6 — Rigging

Level 6 begins after the completed Level 1-5 source roadmaps. It keeps the same hard boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi bounded armature, bone, posing, constraint, skinning and rig-workflow control
without exposing arbitrary Python, unrestricted bpy operators or a generic rig mutation surface.

Current Level 6 source progress: **30%**.

Real Blender runtime verification for Level 6: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Armature + bone hierarchy inspection | complete |
| 2 | Armature creation + bounded edit-bone creation | complete |
| 3 | Bone parenting / connect / rename / symmetry-safe editing | complete |
| 4 | Pose transforms + bounded pose controls | pending |
| 5 | Rig constraints + IK foundations | pending |
| 6 | Mesh-to-armature binding + Armature modifier | pending |
| 7 | Vertex groups + bounded weight workflows | pending |
| 8 | IK/FK control-rig helpers | pending |
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

## Stop boundary

Milestones 1-3 are complete at 30%. Do not begin Milestone 4 without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real rigging runtime
acceptance without separate explicit runtime authorization.
