# Safe object operations

Enable mutations explicitly in LaunchConfig.policy. Default sessions are read-only.
Tools accept no bpy path, arbitrary property name, code, expression or operator identifier.

`object.create` requires name (at most 63 UTF-8 bytes), kind (CUBE/PLANE/EMPTY), transform,
and expected_scene_revision from scene.inspect. Cube is side length 2; plane is a 2×2 XY
quad. Uses mesh.from_pydata, objects.new and scene.collection.objects.link, avoiding
operator selection/context dependence. Existing names fail; no automatic .001 renaming.
Actual primitive geometry counts and coordinate/face fingerprints are verified.

`object.set_transform` requires target and transform. Target has object_id, expected_name,
expected_revision from a fresh snapshot. Transform requires all three local channel
vectors: location in Blender units, rotation_euler in radians (XYZ), scale. This sets local
channels, not evaluated world pose. Parented objects retain their parents. Animated,
constrained, linked, overridden, or noneditable objects are rejected. Object mode required.

`object.duplicate` requires target, new name and transform. Only unparented mesh/empty
objects are supported. Mesh data is copied; materials referenced by the copied mesh may
remain shared. Actual new identity, scene membership, name/type and transform are checked.
Copied geometry fingerprints, material slots and separate mesh identity are checked too.
Copies reject modifiers/shape keys and exceed no more than 4096 vertices, 4096 faces and
32768 total polygon indices. Truncated inspection cannot authorize a mutation.

Every successful mutation returns verified status with expected/actual comparison and
before/after snapshots. Numeric comparisons explicitly use absolute tolerance 1e-5 and
relative tolerance 1e-6 to account for Blender float storage. This verifies channels; it
does not promise bit-exact decimal storage or evaluated geometry equality.
Creation failures remove only newly allocated object/unused mesh data and verify object
absence before reporting rolled_back. Transform failures include observed state when
readback is available; they do not silently replay or overwrite later changes. Exceptions
can leave partial state; inspect and recover using a new revision.

Deletion is deferred until checkpoint reopening/recovery has real runtime verification.
No Blender runtime tests have occurred; geometry, float precision, duplication semantics,
cleanup failures and Blender version differences still require authorized acceptance tests.
