# Modifiers, collections and local assets

All tools require mutation-enabled policy and fresh object or scene preconditions.

- modifier.add: target, unique name, kind, settings. BEVEL accepts width 0..100 and segments
  1..8. SUBSURF accepts levels/render_levels 0..2.
  SOLIDIFY accepts thickness -100..100. Mesh only, no existing modifier stack; input
  capped at 4096 vertices, 4096 polygons and 32768 polygon indices before evaluation.
  Reads actual settings, compares, and removes only the new modifier on mismatch.
- collection.create: unique name, expected_scene_revision and target (fresh ObjectTarget
  or null). Links a new collection to the scene root, optionally links the target object
  without removing its existing memberships. Verifies root and object links. Root child
  count is capped at 64; object memberships at 64 and total collections at 10000.
  Existing collection names fail.
- asset.mark: target and description (up to 1000 characters). Marks a currently unmarked
  editable object as an asset and verifies the mark/description. Existing asset metadata
  is preserved by rejecting replacement. Does not generate previews or load external files.

These are bounded initial capabilities. Applying/removing modifiers, nested collection
reorganization, library append/link, asset catalogs, import/export and external asset
management are deferred. Subdivision evaluation can be costly even within bounds; actual
runtime use still requires user authorization and workload assessment. Unit tests use fake
data only, and do not establish Blender runtime compatibility.
