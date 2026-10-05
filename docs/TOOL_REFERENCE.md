# Tool reference (protocol 1)

The factory registers 23 tools. Main Shuvi sends a `Request` through `BlenderController`;
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
| scene.inspect | none | read_only | scene/file/render/frames, counts, up to 64 collection summaries, revision |
| objects.list | PageQuery | read_only | sorted object snapshots, total, offset, next_offset, session_id, revision |
| collections.list | PageQuery without object_type | read_only | sorted names and object/child counts, total, offset, next_offset, session_id, revision |
| object.inspect | object_id | read_only | current-scene object snapshot and revision |
| object.create | name, kind, transform, expected_scene_revision | mutation | CUBE/PLANE/EMPTY; actual geometry counts/fingerprint, name/type/transform/membership |
| object.set_transform | target, transform | mutation | actual local transform and unchanged object identity/name |
| object.duplicate | target, name, transform | mutation | distinct identity/mesh, copied geometry/material slots, transform/membership |
| material.create_assign | target, name, base_color, metallic, roughness | mutation | actual Principled shader inputs, material slot and properties |
| device.create | name, kind, transform, expected_scene_revision, settings | mutation | actual camera/light properties, transform/membership and active-camera state |
| modifier.add | target, name, kind, settings | mutation | actual newly added modifier settings |
| collection.create | name, expected_scene_revision, target (or null) | mutation | new collection's root link and optional object link |
| asset.mark | target, description | mutation | new asset mark and actual description |
| animation.set_range | start, end, expected_scene_revision | mutation | actual frame bounds |
| animation.set_frame | frame, expected_scene_revision | mutation | actual current frame |
| animation.insert_keyframe | target, frame, transform, interpolation | mutation | actual nine keyed transform values, frame and interpolation |
| render.configure | width, height, samples, expected_scene_revision | mutation | actual CPU Cycles/PNG/RGBA/8-bit/single-thread settings |
| render.execute | name (.png), expected_scene_revision | render | output size/hash, bounded PNG structure, dimensions and pixels decoded for structural validation |
| file.checkpoint | name (.blend), expected_scene_revision | file_write | output size/hash/uncompressed header and unchanged active source path |
| mesh.inspect | object_id | read_only | indexed vertices/faces and separate geometry_revision |
| mesh.create | name, geometry, transform, expected_scene_revision | mutation | actual indexed geometry and object transform/membership |
| mesh.translate_vertices | target, expected_geometry_revision, indices, delta | mutation | actual complete bounded geometry; untouched indices/faces compared too |

## Operation limits and policy

- Read-only operations are enabled by default. Mutation requires `allow_mutations`.
  Checkpoints require `allow_file_writes` and an output workspace. Rendering requires
  mutations, file writes, rendering permission, an output workspace and prior CPU settings.
  Destructive operations have no registered tool. The host checks its own safety allowlist
  and rejects catalog classifications that disagree with it.
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
  Duplicates reject shape keys and modifiers and require an unparented mesh or empty.
- Modifiers require no existing modifier stack and the bounded mesh above. BEVEL has width
  0..100 and segments 1..8; SUBSURF has levels/render_levels 0..2; SOLIDIFY thickness -100..100.
  These source bounds do not establish a hard Blender CPU/memory ceiling.
- Material color is RGBA in 0..1; metallic/roughness are 0..1. Material assignment requires
  local unshared mesh data and fewer than 64 slots. Camera settings are lens 1..500,
  clip_start 0.0001..1000, clip_end 0.001..1000000 greater than start, boolean make_active.
  Light kinds POINT/SUN/SPOT/AREA accept energy 0..1000000 and RGB in 0..1.
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
