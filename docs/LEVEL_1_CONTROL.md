# Level 1 control

Level 1 broad source-side Blender control is now **100% implemented** against the current
Level 1 roadmap. Real Blender runtime verification remains **0%** because Blender has
not been installed, probed, launched or rendered in this source-only pass. Source tests use
explicit fake-bpy fixtures and do not claim runtime compatibility.

| Capability | Implemented | Unit tested | CI tested | Runtime tested | Deferred / note |
|---|---|---|---|---|---|
| Cube/plane/empty | yes | yes | yes | no | |
| UV sphere/icosphere/cylinder/cone/circle/grid/torus | yes | yes | yes | no | fixed bounded geometry |
| Curve/Text creation + shape inspection | yes | yes | yes | no | direct CURVE/FONT data APIs |
| Object rename + allowlisted display properties | yes | yes | yes | no | no generic property setter |
| Full + partial local transforms | yes | yes | yes | no | XYZ Euler + unit quaternion |
| Apply complete mesh object transform | yes | yes | yes | no | bounded direct-data mesh bake |
| World transform/origin inspection | yes | yes | yes | no | |
| Origin to arithmetic mesh centroid | yes | yes | yes | no | bounded direct-data mesh operation |
| Independent + linked mesh duplication | yes | yes | yes | no | bounded unparented mesh rules |
| Visibility controls | yes | yes | yes | no | viewport/render/view-layer separated |
| Selection + active object | yes | yes | yes | no | bounded Object-mode state |
| Parent/unparent + children inspection | yes | yes | yes | no | cycle rejection; keep-world option |
| Collection inspect/rename/link/unlink/move | yes | yes | yes | no | orphan + scene-reachability protection |
| Child collection creation | yes | yes | yes | no | bounded hierarchy depth |
| Cursor inspect/set | yes | yes | yes | no | location only |
| Scene rename + unit settings | yes | yes | yes | no | active context scene only |
| Scene type counts/world presence | yes | yes | yes | no | bounded scene summary |
| Transform pivot inspect/set | yes | yes | yes | no | allowlisted pivot enum |
| Camera/light create + bounded update | yes | yes | yes | no | type-specific settings |
| Mode inspection | yes | yes | yes | no | |
| Bounded mode mutation | yes | yes | yes | no | typed Object/Edit/Sculpt/Pose/Paint transitions |
| Data-block + constraint summaries | yes | yes | yes | no | read-only and bounded |
| Edit/Sculpt/Pose/Paint mode mutation | yes | yes | yes | no | active/selected compatible target required |
| Destructive object deletion | yes | yes | yes | no | separate destructive policy required |
| Confined checkpoint reopening/project switch | yes | yes | yes | no | workspace-only, destructive policy required |

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

Primitive mesh creation uses direct mesh data rather than operators. Current fixed meshes are:
unit-radius spheres, cylinder/cone height 2, 16 radial segments, sphere 8 latitude divisions,
unsubdivided icosphere, filled 16-sided circle, 8x8 grid over [-1,1], and a torus with major
radius 1/minor radius .25 using 16x8 segments. Geometry is bounded and fingerprinted for
readback verification.

Curve and text creation also use direct data APIs. Curves create one bounded 3D POLY spline
with 2..256 points, optional cyclic closure and bevel depth 0..100. Text creates a FONT
datablock with a body of at most 1000 characters, allowlisted horizontal alignment, bounded
size and extrusion. `shape.inspect` returns bounded readback for these data types.

Object transforms support complete local XYZ transforms plus nonempty partial patches for
location, scale, XYZ Euler, or unit WXYZ quaternion. Omitted channels are preserved.
`mesh.apply_object_transform` is deliberately narrower than Blender's general Apply menu:
for an unparented, local, unshared mesh in XYZ Euler Object mode, with no shape keys,
modifiers, animation or constraints, it bakes the complete local location + rotation + scale
into the mesh vertices and resets those object channels. It does not claim arbitrary partial
apply semantics.

The object snapshot exposes the world matrix and `origin.inspect` reports local/world
origin locations. `origin.to_centroid` moves the origin to the arithmetic centroid of the
bounded mesh vertices while offsetting vertices/object location so supported world geometry
is preserved. This is an explicit centroid operation; it does not claim every semantic of
Blender's context-sensitive "Origin to Geometry" operator.

Hierarchy controls support parent, unparent, child inspection, self/cycle rejection and an
optional keep-world request. Collection controls support inspection, rename, link, unlink,
move, and bounded child creation. Unlinking an object's final scene-reachable collection is
denied. Linked/overridden collections are denied for mutation.

Scene-state controls cover 3D cursor location, scene naming, units, transform pivot,
current mode, world presence, active/selected context, object counts by type, camera/render
state and file metadata. Cameras/lights can be created and updated through bounded,
type-specific settings with readback verification and rollback on verification failure.

## Final Level 1 source boundary

`mode.set` now provides an allowlisted subset of Blender context transitions. It requires
a fresh scene revision plus a fresh target, and the target must already be selected, active,
editable and compatible with the requested mode. Non-Object modes are entered only from
Object mode; returning to Object mode is supported from the Level 1 mode set. The operation
uses Blender's mode operator only behind this typed allowlist and verifies the resulting
context mode/active object.

`object.delete` is explicitly classified destructive, requires both mutation and destructive
policy permission, requires Object mode plus a fresh scene/object state, rejects linked,
overridden, read-only objects and parents with children, clears active-camera/active-object
references when applicable, and verifies that the object is absent from both the data table
and active scene.

`file.open_checkpoint` is also destructive. It can open only a verified regular `.blend`
inside the configured confined OutputWorkspace; arbitrary paths are not accepted. After a
successful project replacement the inspector rotates the session ID and invalidates all old
object IDs before fresh scene readback. This completes the source-side project switching and
recovery surface without claiming that fake-bpy tests prove real Blender reopening semantics.

**Level 1 source implementation is complete at 100% for the current roadmap.** This does not
mean Blender runtime verification or production readiness is complete. Blender 4.2+ runtime
behavior still requires the opt-in acceptance suite in `docs/RUNTIME_ACCEPTANCE.md`.
Until explicit authorization, do not install, probe, launch or render Blender.
