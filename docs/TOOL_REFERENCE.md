# Tool reference (protocol 1)

The factory registers 84 typed tools. Main Shuvi sends a `Request` through `BlenderController`;
it never needs bpy names, operators or Python expressions. All inputs are JSON objects,
unknown fields fail, and each result carries the exact request and command IDs.

## Shared contracts

`Request`: `protocol_version=1`, nonempty `request_id` and `command_id` (128 characters
maximum each), `operation` (80 maximum), `payload`, and `timeout_ms` (1..120000).
Messages have a 1 MiB byte ceiling, 32 nesting levels, 65536 JSON nodes (including keys),
finite numbers and integers with at most 64 bits. Unicode must be valid; NUL is rejected.

`Transform`: `location`, `rotation_euler`, `scale`, each exactly three finite components.
Absolute component limits are 1000000 Blender units, 1000 radians and 10000 respectively.
Euler rotation is local XYZ; this does not assert evaluated world pose.

`ObjectTarget`: `object_id`, `expected_name`, `expected_revision` from a recent snapshot.
IDs are opaque and session-scoped. Revisions are 64-character SHA-256 fingerprints.
Names used to create data are nonempty and at most 63 UTF-8 bytes. Existing names fail;
automatic Blender suffix renaming is not accepted as success.

`PageQuery`: optional `offset` (0..10000), `limit` (1..100, default 25), `name_prefix`
(0..256 characters), `object_type` (optional, 32 characters), `expected_revision`
(optional, 64 characters). A nonzero offset requires `expected_revision`. Collection
queries reject the object_type filter. Changing filters starts a new pagination query;
clients should retain the filter, session ID and revision while continuing a page.

## Operations

| Tool | Payload fields | Safety | Readback / result |
| --- | --- | --- | --- |
| system.ping | none | read_only | `ready=true` after a roundtrip |
| system.capabilities | none | read_only | protocol/session/Blender version and operation catalog |
| scene.inspect | none | read_only | scene/file/render/frames, context, cursor, units, pivot, type counts, world presence, revision |
| objects.list | PageQuery | read_only | sorted object snapshots, total, offset, next_offset, session_id, revision |
| collections.list | PageQuery without object_type | read_only | sorted names and object/child counts, total, offset, next_offset, session_id, revision |
| object.inspect | object_id | read_only | current-scene object snapshot and revision |
| mode.set | target, mode, expected_scene_revision | mutation | verified compatible Object/Edit/Sculpt/Pose/Paint context transition |
| shape.inspect | object_id | read_only | bounded CURVE/FONT data summary and shape readback |
| curve.create | name, points, cyclic, bevel_depth, transform, expected_scene_revision | mutation | one bounded 3D POLY spline, transform/membership and point readback |
| text.create | name, body, align_x, size, extrude, transform, expected_scene_revision | mutation | FONT body/alignment/size/extrusion and transform/membership readback |
| object.create | name, kind, transform, expected_scene_revision | mutation | bounded primitive; actual geometry counts/fingerprint, name/type/transform/membership |
| object.set_transform | target, transform | mutation | actual local transform and unchanged object identity/name |
| object.duplicate | target, name, transform | mutation | distinct identity/mesh, copied geometry/material slots, transform/membership |
| object.duplicate_linked | target, name, transform | mutation | distinct object identity with verified shared bounded mesh data |
| object.delete | target, expected_scene_revision | destructive | verifies target object absent from scene/data after guarded deletion |
| material.create_assign | target, name, base_color, metallic, roughness | mutation | actual Principled shader inputs, material slot and properties |
| device.create | name, kind, transform, expected_scene_revision, settings | mutation | actual camera/light properties, transform/membership and active-camera state |
| device.update | target, settings | mutation | bounded camera/light setting patch and active-camera readback |
| modifier.add | target, name, kind, settings | mutation | actual newly added modifier settings |
| collection.create | name, expected_scene_revision, target (or null) | mutation | new collection's root link and optional object link |
| asset.mark | target, description | mutation | new asset mark and actual description |
| animation.set_range | start, end, expected_scene_revision | mutation | actual frame bounds |
| animation.set_frame | frame, expected_scene_revision | mutation | actual current frame |
| animation.insert_keyframe | target, frame, transform, interpolation | mutation | actual nine keyed transform values, frame and interpolation |
| render.configure | width, height, samples, expected_scene_revision | mutation | actual CPU Cycles/PNG/RGBA/8-bit/single-thread settings |
| render.execute | name (.png), expected_scene_revision | render | output size/hash, bounded PNG structure, dimensions and pixels decoded for structural validation |
| file.checkpoint | name (.blend), expected_scene_revision | file_write | output size/hash/uncompressed header and unchanged active source path |
| file.open_checkpoint | name (.blend), expected_scene_revision | destructive | opens only verified workspace checkpoint, rotates session/object identities, verifies loaded filepath |
| mesh.inspect | object_id | read_only | indexed vertices/faces and separate geometry_revision |
| mesh.topology_inspect | object_id | read_only | bounded derived edges, boundary/non-manifold edges and face adjacency |
| mesh.create | name, geometry, transform, expected_scene_revision | mutation | actual indexed geometry and object transform/membership |
| mesh.translate_vertices | target, expected_geometry_revision, indices, delta | mutation | actual complete bounded geometry; untouched indices/faces compared too |
| mesh.extrude_face | target, expected_geometry_revision, face_index, offset | mutation | exact rebuilt vertices/faces for one bounded single-face extrusion |
| mesh.transform_elements | target, expected_geometry_revision, domain, indices, translation, rotation_euler, scale, pivot | mutation | exact full-geometry readback plus affected vertex set |
| mesh.merge_vertices | target, expected_geometry_revision, indices, mode | mutation | compacted vertices/faces plus deterministic merged vertex index |
| mesh.dissolve_edge | target, expected_geometry_revision, edge_index | mutation | two-face edge dissolve into one verified simple polygon |
| mesh.extrude_region | target, expected_geometry_revision, face_indices, offset | mutation | connected-region cap/side-wall rebuild with full geometry readback |
| mesh.inset_face | target, expected_geometry_revision, face_index, factor | mutation | one inner cap plus verified quad ring |
| mesh.bevel_boundary_edge | target, expected_geometry_revision, edge_index, factor | mutation | conservative boundary-edge chamfer strip and rebuilt source polygon |
| mesh.subdivide_edge | target, expected_geometry_revision, edge_index, factor | mutation | one interpolated edge vertex inserted into all bounded edge-user polygon cycles |
| mesh.loop_cut_quad_strip | target, expected_geometry_revision, edge_index, factor | mutation | bounded all-quad strip discovery, one split vertex per ring edge and verified quad split |
| mesh.bridge_boundary_loops | target, expected_geometry_revision, loop_a, loop_b | mutation | equal explicit boundary loops connected by one verified quad per segment |
| mesh.fill_boundary_loop | target, expected_geometry_revision, vertex_indices | mutation | one verified polygon face across an explicit existing boundary loop |
| mesh.shading_inspect | object_id | read_only | bounded source face normals/areas, smoothing state and topology/shading diagnostics |
| mesh.set_face_smoothing | target, expected_geometry_revision, expected_shading_revision, face_indices, smooth | mutation | exact per-face smooth flags with unchanged bounded geometry |
| mesh.orient_faces_consistently | target, expected_geometry_revision, expected_shading_revision | mutation | manifold-connected winding consistency with preserved smooth flags |
| mesh.repair_inspect | object_id, distance, area_epsilon | read_only | bounded near-duplicate/duplicate/degenerate/loose/component repair diagnostics |
| mesh.merge_by_distance | target, expected_geometry_revision, distance | mutation | deterministic proximity merge, index compaction and collapsed/duplicate face cleanup |
| mesh.cleanup_faces | target, expected_geometry_revision, area_epsilon, remove_duplicate_faces | mutation | bounded degenerate/duplicate face removal with smooth-state preservation |
| mesh.remove_loose_vertices | target, expected_geometry_revision | mutation | compact unreferenced vertices while preserving polygon order and smoothing |
| mesh.retopology_inspect | object_id | read_only | bounded valence, pole, boundary, tri/quad/ngon and quad-ratio diagnostics |
| mesh.retopology_projection_inspect | source_id, target_id, vertex_indices, max_distance | read_only | bounded nearest target triangle points/normals/distances for explicit source vertices |
| mesh.retopology_project | source, target, expected_source_geometry_revision, expected_target_geometry_revision, vertex_indices, max_distance, offset | mutation | verified nearest-surface base-mesh projection with normal offset and coordinate rollback |
| mesh.retopology_relax | target, expected_geometry_revision, vertex_indices, factor, iterations, preserve_boundary | mutation | bounded synchronous one-ring relax with optional boundary preservation |
| modifier.shrinkwrap_add | source, target, expected_stack_revision, name, wrap_method, wrap_mode, offset | mutation | verified typed non-destructive Shrinkwrap modifier with explicit target identity |
| mesh.apply_object_transform | target, expected_geometry_revision | mutation | complete local scale/XYZ rotation/location baked into mesh; object channels reset |
| origin.to_centroid | target, expected_geometry_revision | mutation | arithmetic local vertex centroid becomes origin with verified geometry/object offset |

## Operation limits and policy

- Read-only operations are enabled by default. Mutation requires `allow_mutations`.
  Destructive operations require both `allow_mutations` and `allow_destructive`.
  Checkpoints require `allow_file_writes` and an output workspace. Rendering requires
  mutations, file writes, rendering permission, an output workspace and prior CPU settings.
  `file.open_checkpoint` additionally requires a configured OutputWorkspace and accepts only
  a verified regular `.blend` inside that confined root. The host checks its own safety
  allowlist and rejects catalog classifications that disagree with it.
- Scene work: at most 10000 objects, 10000 collections, 10000 allocated session identities,
  and 100000 nested inspection work units per scene request. Revisions scan current bounded
  scene metadata and collection relationships; snapshots stream rather than accumulate.
  Object pages have a 512 KiB content budget; reduce limit when denied. No persistent cache.
- Object snapshots expose at most 64 modifiers, material slots and collection memberships;
  animation exposes at most 64 channels, 256 points per channel and 1024 total points.
  Truncation is explicit and truncated snapshots cannot authorize mutation. Names are
  bounded to 256 characters; metadata strings to 1000; file/render paths to 4096.
  Revisions cover inspected metadata, not every Blender property or all mesh geometry.
- Mesh operations and duplicate input: 4096 vertices, 4096 faces, 32768 total face indices.
  Created faces have 3..32 distinct valid vertex indices. Translation selects 1..256 unique
  indices and delta components in -1000..1000; every result coordinate stays within
  -1000000..1000000. Translation requires unshared editable mesh without shapes/modifiers.
  Complete transform baking and origin-to-centroid require a fresh geometry revision,
  unparented local unshared mesh data, XYZ Euler rotation mode, no shape keys/modifiers,
  and the normal Object-mode/no-animation/no-constraint guard. Duplicates reject shape keys
  and modifiers and require an unparented mesh or empty.
- Modifiers require no existing modifier stack and the bounded mesh above. BEVEL has width
  0..100 and segments 1..8; SUBSURF has levels/render_levels 0..2; SOLIDIFY thickness -100..100.
  These source bounds do not establish a hard Blender CPU/memory ceiling.
- Material color is RGBA in 0..1; metallic/roughness are 0..1. Material assignment requires
  local unshared mesh data and fewer than 64 slots. Camera settings are lens 1..500,
  clip_start 0.0001..1000, clip_end 0.001..1000000 greater than start, boolean make_active.
  Light kinds POINT/SUN/SPOT/AREA accept energy 0..1000000 and RGB in 0..1. device.update
  accepts only the fields appropriate to the target kind and verifies the resulting state.
- Curves create exactly one 3D POLY spline with 2..256 points, coordinates within
  -1000000..1000000, boolean cyclic state and bevel depth 0..100. Text body is 1..1000
  characters; align_x is LEFT/CENTER/RIGHT/JUSTIFY/FLUSH, size .0001..1000 and extrude
  0..100. Curve/Text creation uses direct data APIs, not editor operators.
- Collections have at most 64 root children; adding an object membership requires fewer
  than 64 existing memberships. Asset descriptions are 0..1000 characters; replacement
  metadata is denied. Objects must be editable/local, in object mode, and unconstrained;
  generic object tools reject animation. Keyframes permit only session-owned unshared
  actions, at most 64 unique frames, no frame overwrite, and LINEAR/BEZIER/CONSTANT.
- Timeline frames are 1..100000; configured range span at most 10000. Frame selection must
  fall inside that range. Rendering is single-frame CPU only, 16..512 pixels each dimension,
  1..16 samples, one thread. A deadline cannot interrupt a running bpy call.
- Outputs use plain filenames at most 128 characters, exact .png/.blend suffixes, exclusive
  reservation and no overwrite. Traversal, absolute/UNC paths, alternate streams, reserved
  Windows device names, reparse points and hard links are denied. Roots are pinned to
  filesystem identity. PNG files are at most 4 MiB; BLEND files 128 MiB with streamed hashing.
  Header validation does not prove that a .blend file can be reopened or recovered.

## Results and catalog

Read-only success is `succeeded`; mutations are `verified` only with nonempty expected
state matching actual readback. Numeric comparisons use absolute tolerance 1e-5 and
relative tolerance 1e-6; copied geometry fingerprints require identical stored coordinates.
Adapter mutation results include before/after where available and verification evidence.
Creation mismatches remove newly allocated data; generic edits are not transactions.
Errors/exceptions can leave partial state. Failed verification never authorizes retry.

`Result` includes `protocol_version`, `request_id`, `command_id`, `status`, `data`, `error`,
`verification`. An error has `code`, sanitized public `message`, and boolean `retryable`.
Codes: invalid_request, unsupported_operation, protocol_mismatch, not_found,
ambiguous_target, stale_state, safety_denied, timeout, transport_error, execution_error,
verification_failed, blender_not_found. No traceback or arbitrary exception text is sent.
Error messages are nonempty, valid Unicode and at most 512 characters. Mutation exceptions
after dispatch report outcome=unknown and require inspection before retry.

Catalog entries expose name, classification, enabled, payload_fields (null for custom
parsers), verification_required, runtime_required, file_write_permission_required and
render_permission_required. Enabled reports session policy, not scene compatibility or
runtime verification. All factory tools except the generic ping adapter require Blender
state at execution. Normal host imports have no bpy dependency.

See [client contract](CLIENT.md), [source audit](SOURCE_AUDIT.md) and
[future runtime acceptance](RUNTIME_ACCEPTANCE.md). Runtime verification remains **0%**;
production ready: **no**.

Level 1 primitive expansion: `object.create.kind` also accepts `UV_SPHERE`,
`ICOSPHERE`, `CYLINDER`, `CONE`, `CIRCLE` (filled), `GRID`, `TORUS`.
See [Level 1 control](LEVEL_1_CONTROL.md) for fixed geometry bounds.

Level 1 additions (mutations require normal policy and fresh state):
- `scene.rename`: name, expected_scene_revision.
- `scene.set_units`: bounded system/scale_length/length_unit patch plus scene revision.
- `cursor.inspect` / `cursor.set`: read or verify the 3D cursor location.
- `mode.inspect`: bounded current mode + active-object summary.
- `pivot.inspect` / `pivot.set`: transform pivot with an allowlisted Blender enum.
- `object.rename`: target, name.
- `object.set_properties`: allowlisted display/color/pass-index/transform-lock/empty-display
  group only; no arbitrary property setter.
- `object.patch_transform`: nonempty partial location/scale/XYZ Euler or unit WXYZ
  quaternion; omitted channels are preserved.
- `object.set_visibility`: hide_viewport, hide_render and view-layer hidden state.
- `selection.inspect` / `selection.set`: bounded selected IDs and active object.
- `hierarchy.inspect` / `hierarchy.set_parent`: parent/children readback, cycle rejection,
  unparent via null parent, and optional keep-world.
- `origin.inspect`: local and world object-origin locations.
- `collection.inspect`, `collection.rename`, `collection.link_object`,
  `collection.unlink_object`, `collection.move_object`, `collection.create_child`:
  bounded collection management with stale-state guards and orphan prevention.
- `object.duplicate_linked`: independent object sharing the source mesh datablock, with
  geometry/material/readback checks and conservative mesh limits.
- `shape.inspect`, `curve.create`, `text.create`: bounded direct-data Curve/Text
  inspection and creation; no arbitrary bpy/operator execution.
- `device.update`: bounded camera lens/clip/active-state or light energy/color updates.
- `mesh.apply_object_transform`: bake the complete supported local object transform into
  bounded mesh vertices, then verify reset object transform plus resulting geometry.
- `origin.to_centroid`: move the origin to the arithmetic mesh-vertex centroid while
  preserving supported world geometry through a verified vertex/object offset.


## Level 1 completion additions

- `mode.set` supports the current Level 1 allowlist: OBJECT for supported targets; EDIT for
  mesh/curve/font/surface/meta/lattice/armature; SCULPT/VERTEX_PAINT/WEIGHT_PAINT/
  TEXTURE_PAINT for mesh; POSE for armature. The target must already be selected and active.
  Non-Object entry is only from Object mode. Actual Blender context semantics remain subject
  to runtime acceptance.
- `object.delete` is destructive and source-verified by absence readback. It refuses linked,
  overridden/read-only objects and refuses deleting a parent while scene children still
  reference it. It does not automatically remove orphan data blocks.
- `file.open_checkpoint` is a confined destructive project replacement. Before opening, the
  file is structurally verified as a bounded regular BLEND output in the configured workspace.
  A successful open invalidates all prior session object IDs by rotating the inspector session.
- With these additions the current Level 1 **source roadmap is 100% implemented**. Real Blender
  runtime verification remains a separate acceptance phase and is not implied by source CI.


## Level 2 modeling additions

Current Level 2 source progress: **80%**.

- `mesh.topology_inspect` derives a deterministic canonical edge set from bounded polygon
  loops, reports boundary edges, non-manifold edges and two-face adjacency. Derived topology
  is capped at 8192 unique edges in addition to the existing 4096-vertex/4096-face/32768-loop
  geometry bounds.
- `mesh.extrude_face` performs one explicitly indexed face extrusion using a bounded local
  offset. It requires Object mode, fresh object + geometry revisions, editable local unshared
  mesh data, no shape keys and no modifier stack. The resulting vertex/face/loop counts are
  preflighted before mutation. The tool rebuilds the bounded mesh through direct data APIs,
  reads the entire geometry back, verifies the new cap and side quads, and restores captured
  geometry if verification fails.
- This is the first professional-modeling milestone, not Blender's complete extrusion family.
  Multi-face region extrusion, inset, bevel, loop cut, bridge, merge/dissolve, normals and
  topology-repair workflows remain later Level 2 milestones.

See [Level 2 modeling](LEVEL_2_MODELING.md) for the ten-milestone roadmap.


### Level 2 milestone 2 limits

- `mesh.transform_elements` accepts domain VERTEX/EDGE/FACE and 1..256 unique element
  indices. EDGE indices refer to the canonical sorted edge list from
  `mesh.topology_inspect`; FACE and VERTEX indices refer to current bounded geometry.
  Translation/rotation/scale are applied around the supplied local-space pivot. Result
  coordinates must remain within the normal ±1000000 mesh coordinate bound.
- `mesh.merge_vertices` accepts 2..64 unique vertex indices and placement CENTER/FIRST/LAST.
  Rebuild is denied when material slots, vertex groups, UV layers or color attributes are
  present because those layers are not preserved by this foundation.
- `mesh.dissolve_edge` accepts one canonical edge index and only edges with exactly two face
  users. The merged face must be simple and contain at most 32 unique vertices.
- All milestone 2 mutations require editable local unshared mesh data, fresh geometry state,
  no shape keys/modifiers, Object mode and normal object mutation safety guards. Verification
  compares complete bounded geometry; failed verification triggers bounded rollback.


### Level 2 milestone 3 limits

- `mesh.extrude_region` accepts 1..64 unique face indices, requires a single edge-connected
  selected region, rejects selected non-manifold edges and rejects a closed region without a
  boundary. Unique selected vertices are duplicated once; side quads are created only for
  region boundary edges.
- `mesh.inset_face` accepts one face and factor 0.001..0.95. It is a center-interpolation
  inset foundation with one new inner vertex per source face vertex and one surrounding quad
  per source edge.
- `mesh.bevel_boundary_edge` accepts one canonical edge index and factor 0.001..0.49.
  The edge must have exactly one polygon user. This milestone intentionally does not bevel
  shared/manifold edges.
- Milestone 3 topology rebuilds keep the Milestone 2 metadata guard: material slots, vertex
  groups, UV layers and color attributes cause a safety denial until data-layer preservation
  is implemented intentionally.


### Level 2 milestone 4 limits

- `mesh.subdivide_edge` accepts one canonical edge index and factor 0.001..0.999. The edge
  must have one or two polygon users. One interpolated vertex is inserted into every polygon
  cycle using that edge; any resulting polygon above 32 vertices is denied.
- `mesh.loop_cut_quad_strip` accepts one seed edge and factor 0.001..0.999. Discovery walks
  only through quads by opposite edges, rejects non-manifold crossings, and caps the discovered
  ring at 256 edges. Every affected quad is replaced by two verified quads.
- `mesh.bridge_boundary_loops` accepts two disjoint equal-size loops of 3..64 vertices.
  Consecutive loop vertices must already form boundary edges with exactly one polygon user.
  Corresponding segments create one quad each; automatic twist/alignment solving is not part
  of this foundation.
- `mesh.fill_boundary_loop` accepts 3..32 unique vertices following an existing boundary
  cycle and adds exactly one polygon. It rejects a polygon with the same vertex set when one
  already exists.
- All Milestone 4 topology rebuilds retain the no-material/UV/color/vertex-group metadata
  guard until those data layers can be intentionally preserved.


### Level 2 milestone 5 limits

- `mesh.shading_inspect` computes source face normals from triangle-fan area vectors and
  reports triangle-fan area, degenerate/ambiguous-normal faces, isolated vertices, boundary/
  non-manifold edges, winding conflicts and per-face `use_smooth` state. These are base-mesh
  diagnostics and do not claim evaluated custom/split normals.
- `mesh.set_face_smoothing` accepts 1..256 unique face indices and a boolean smooth state.
  Both geometry and shading revisions must be fresh. The complete smooth/flat face partition
  is read back; geometry revision must stay unchanged.
- `mesh.orient_faces_consistently` solves pairwise orientation constraints across edges with
  exactly two face users. More-than-two-user edges and contradictory constraints are denied.
  Components are made internally consistent but are not automatically oriented "outside".
  Smooth flags are preserved across the bounded topology rebuild.
- The orientation rebuild keeps the existing no-material/UV/color/vertex-group metadata guard.
  No custom normal layer editing, sharp-edge system, modifier-evaluated normal control or
  arbitrary normal operator is exposed in this milestone.


### Level 2 milestone 6 limits

- `modifier.stack_inspect` caps stack inspection at 16 entries and returns an ordered
  `stack_revision`. Supported typed readback covers BEVEL, SUBSURF, SOLIDIFY and BOOLEAN;
  arbitrary settings on unknown modifier types are not surfaced.
- `modifier.stack_add` appends BEVEL/SUBSURF/SOLIDIFY to an existing bounded stack using
  the allowlisted settings for that kind. Duplicate names and full stacks are denied.
- `modifier.boolean_add` requires distinct fresh mesh target/cutter objects, accepts
  DIFFERENCE/UNION/INTERSECT and EXACT/FAST, and verifies cutter identity/name plus ordered
  modifier state. It does not apply the Boolean result to permanent mesh topology.
- `modifier.update` accepts only allowlisted fields for the declared current modifier type,
  plus viewport/render visibility. Verification failure restores the captured patched values.
- `modifier.move` reorders one named stack entry to an existing index and verifies the
  complete ordered stack; verification failure restores the prior order.
- Hard-surface source CI verifies contracts/state transitions only. Actual Blender modifier
  evaluation and Boolean solver geometry remain runtime-unverified.


### Level 2 milestone 7 limits

- `mesh.repair_inspect` accepts distance 1e-9..100 and area epsilon 0..1000000. Spatial
  near-duplicate work is capped at 1,000,000 pair checks and 512 reported diagnostic groups.
  Duplicate polygons are matched independent of cycle rotation/reversal.
- `mesh.merge_by_distance` uses deterministic proximity clusters, compacts surviving
  vertices, removes faces collapsed below three unique vertices, and deduplicates polygons
  created by the merge. Surviving source face smoothing flags are preserved.
- `mesh.cleanup_faces` removes triangle-fan-area-degenerate faces and, when explicitly
  requested, later duplicate faces. It refuses to remove every polygon and rejects a no-op.
- `mesh.remove_loose_vertices` removes only vertices unused by every polygon, remaps all
  polygon indices, preserves per-face smooth state and rejects a no-op.
- All Milestone 7 mutations retain the no-material/UV/color/vertex-group metadata guard and
  deny shape keys/modifiers; failed verification restores captured geometry and smoothing.


### Level 2 milestone 8 limits

- `mesh.retopology_inspect` reports vertex valence, boundary vertices, isolated vertices,
  interior non-4-valence poles, tri/quad/ngon face partitions and quad ratio.
- Projection preview/mutation accepts 1..128 unique source vertices and caps
  source-vertex × target-triangle checks at 1,000,000. Projection targets currently require
  base triangle/quad faces and no shape keys/modifiers.
- Direct projection supports unparented XYZ source/target transforms with nonzero scale,
  computes nearest world-space triangle points, and converts them back to source local space.
  If any requested vertex exceeds max_distance, the mutation is denied before changing source
  coordinates.
- `mesh.retopology_relax` accepts factor 0.001..1 and 1..8 iterations. It performs synchronous
  one-ring averaging on the explicit selection and can hold boundary vertices fixed.
- `modifier.shrinkwrap_add` supports NEAREST_SURFACEPOINT/NEAREST_VERTEX and
  ON_SURFACE/ABOVE_SURFACE with offset -100..100. Existing `modifier.update` can patch typed
  Shrinkwrap method/mode/offset/visibility but cannot arbitrarily retarget the modifier.
- Real Blender evaluated Shrinkwrap/depsgraph behavior remains runtime-unverified.
