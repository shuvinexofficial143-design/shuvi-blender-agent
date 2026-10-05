# Scene and object inspection

Registered read-only operations:
- `scene.inspect`: empty payload; file, Blender version, scene, object/collection counts,
  camera, frames and render configuration.
- `objects.list`: optional offset (0..10000), limit (1..100, default 25), name_prefix,
  object_type and expected_revision. Returns items, total, revision and next_offset.
- `object.inspect`: required object_id; returns one current-scene object snapshot.
- `collections.list`: PageQuery without object_type; sorted names/object/child counts,
  total, session_id, revision and next_offset. Nonzero offsets require expected_revision.

Object snapshots include local transform channels and rotation mode, dimensions, world
matrix, visibility, parent ID, collection membership, bounded material/modifier summaries,
animation/action metadata, linked-data status, camera/light properties, identity and revision.
No Blender custom properties are written by inspection. bpy is injected into the adapter;
importing inspection.py outside Blender is safe.

IDs are opaque and session-scoped, tied to the current Blender object reference. Rename
keeps identity; removal/replacement cannot be resolved through a name. IDs from another
session fail. Mutation contracts additionally require expected_name and expected_revision.
Revisions are SHA-256 fingerprints of inspected metadata, not persistent Blender IDs or
complete hashes of mesh/material/animation data. They do not cover every nested property.

Object responses cap modifier/material/collection details at 64 and report truncation.
Inspection limits work to 10000 objects, 10000 collections, 10000 allocated session
identities and 100000 nested work units. Animation snapshots cap total points at 1024.
Revisions stream one snapshot at a time and include bounded collection relationships;
computing a revision still scans the current scene. Page content is capped at 512 KiB;
request a smaller limit when denied. Truncated snapshots cannot authorize mutations.
Scene text is bounded. Scalable indexed inspection and nested-detail pagination remain
future work. Snapshot revision prevents stale pagination when the inspected metadata changes.

Target: Blender 4.2+ / bundled Python 3.11+. The direct bpy adapter has only fake-data unit
coverage so far. Actual API behavior, float precision, dependency graph evaluation, linked
data, undo/replacement identity, and multiple Blender versions require authorized runtime
acceptance testing. No production compatibility claim is made.
