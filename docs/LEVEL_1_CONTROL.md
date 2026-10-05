# Level 1 control

Level 1 broad source-side Blender control is now substantially implemented. Real Blender
runtime verification remains **0%** because Blender is not installed/authorized on the
current machine. Source tests use explicit fake-bpy fixtures and do not claim runtime
compatibility.

| Capability | Implemented | Unit tested | CI tested | Runtime tested | Deferred / note |
|---|---|---|---|---|---|
| Cube/plane/empty | yes | yes | yes | no | |
| UV sphere/icosphere/cylinder/cone/circle/grid/torus | yes | yes | yes | no | fixed bounded geometry |
| Object rename + allowlisted display properties | yes | yes | yes | no | no generic property setter |
| Full + partial local transforms | yes | yes | yes | no | XYZ Euler + unit quaternion |
| World transform/origin inspection | yes | yes | yes | no | mutation deferred |
| Independent + linked mesh duplication | yes | yes | yes | no | bounded unparented mesh rules |
| Visibility controls | yes | yes | yes | no | viewport/render/view-layer separated |
| Selection + active object | yes | yes | yes | no | bounded Object-mode state |
| Parent/unparent + children inspection | yes | yes | yes | no | cycle rejection; keep-world option |
| Collection inspect/rename/link/unlink/move | yes | yes | pending latest checkpoint | no | orphan prevention |
| Child collection creation | yes | yes | pending latest checkpoint | no | bounded hierarchy |
| Cursor inspect/set | yes | yes | yes | no | location only |
| Scene rename + unit settings | yes | yes | yes | no | active context scene only |
| Scene type counts/world presence | yes | yes | yes | no | bounded scene summary |
| Transform pivot inspect/set | yes | yes | yes | no | allowlisted pivot enum |
| Mode inspection | yes | yes | yes | no | mode mutation requires runtime validation |
| Data-block + constraint summaries | yes | yes | yes | no | read-only and bounded |
| Apply transforms / origin mutation | no | no | no | no | deferred: context/operator-sensitive |
| Edit/Sculpt/Pose/Paint mode mutation | no | no | no | no | deferred: runtime/context-sensitive |
| Curve/Text primitive creation | no | no | no | no | deferred from Level 1 source pass |
| Destructive deletion | no | no | no | no | deferred until recovery is runtime-verified |

## Source design

All Level 1 mutations remain typed and allowlisted:

```text
Typed request
→ validation
→ expected-state / revision guard
→ mutation
→ bpy-shaped readback
→ verification
→ structured result
```

No Level 1 tool accepts arbitrary Python, a bpy path, an operator identifier, an arbitrary
property name, eval, or shell execution. Mutation targets use session-scoped object IDs and
fresh revisions rather than names alone.

Primitive creation uses direct mesh data rather than operators. Current fixed meshes are:
unit-radius spheres, cylinder/cone height 2, 16 radial segments, sphere 8 latitude divisions,
unsubdivided icosphere, filled 16-sided circle, 8x8 grid over [-1,1], and a torus with major
radius 1/minor radius .25 using 16x8 segments. Geometry is bounded and fingerprinted for
readback verification.

Object transforms support complete local XYZ transforms plus nonempty partial patches for
location, scale, XYZ Euler, or unit WXYZ quaternion. Omitted channels are preserved.
The object snapshot exposes the world matrix; `origin.inspect` reports local and world origin
locations. Applying transforms and moving the origin are intentionally deferred because those
operations are context-sensitive in Blender and have not been runtime-tested.

Hierarchy controls support parent, unparent, child inspection, self/cycle rejection and an
optional keep-world request. Collection controls support inspection, rename, link, unlink,
move, and bounded child creation. Unlinking the last collection is denied so a controlled
operation cannot orphan an object. Linked/overridden collections are denied for mutation.

Scene-state controls cover 3D cursor location, scene naming, units, transform pivot,
current mode, world presence, active/selected context, object counts by type, camera/render
state and file metadata. Mode mutation remains deferred until real Blender acceptance because
safe mode changes depend on actual Blender context.

## Runtime boundary

Source-side completion is not production readiness. Blender 4.2+ runtime behavior still
requires the opt-in acceptance suite in `docs/RUNTIME_ACCEPTANCE.md`. Until explicit
authorization, do not install, probe, launch or render Blender.
