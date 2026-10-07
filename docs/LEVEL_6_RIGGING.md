# Level 6 — Rigging

Level 6 begins after the completed Level 1-5 source roadmaps. It keeps the same hard boundary:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi bounded armature, bone, posing, constraint, skinning and rig-workflow control
without exposing arbitrary Python, unrestricted bpy operators or a generic rig mutation surface.

Current Level 6 source progress: **10%**.

Real Blender runtime verification for Level 6: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Armature + bone hierarchy inspection | complete |
| 2 | Armature creation + bounded edit-bone creation | pending |
| 3 | Bone parenting / connect / rename / symmetry-safe editing | pending |
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

## Stop boundary

Milestone 1 is complete at 10%. Do not begin Milestone 2 without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real rigging runtime
acceptance without separate explicit runtime authorization.
