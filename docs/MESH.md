# Bounded indexed mesh workflow

`mesh.inspect` accepts object_id and returns base mesh vertex coordinates, polygon indices
and a separate geometry revision. It does not evaluate modifiers or extract UV/material
layers. At most 4096 vertices, 4096 faces and 32768 polygon loops.

`mesh.create` accepts unique name, geometry, transform and fresh scene revision. Geometry
requires 3..4096 vertices, 1..4096 faces, 3..32 unique indices per face and finite bounded
coordinates. Blender's mesh validation runs on the new allocation, then actual vertex and
face readback is compared. Geometry changed by validation fails verification and the new
allocation is removed. These checks do not guarantee manifold topology, planar polygons,
non-intersection or artistic quality.

`mesh.translate_vertices` requires a fresh target, expected_geometry_revision from
`mesh.inspect`, 1..256 unique indices and delta. It checks both object and geometry
revisions, validates all resulting coordinates before changing any vertex, then compares
actual coordinates and unchanged polygon indices.

`mesh.apply_object_transform` requires a fresh target and expected_geometry_revision.
For an unparented editable mesh with local unshared data, XYZ Euler rotation mode, no shape
keys/modifiers, and the normal Object-mode/no-animation/no-constraint mutation guard, it
bakes the complete local scale, XYZ Euler rotation and location into every mesh vertex,
then resets object location/rotation/scale to identity. This is a bounded direct-data
operation, not a general wrapper around Blender's context-sensitive Apply operator, and it
does not offer partial location-only/rotation-only/scale-only apply modes.

`origin.to_centroid` uses the same target and geometry guards. It computes the arithmetic
mean of all bounded mesh vertex coordinates, shifts mesh vertices by the negative centroid,
and adjusts object location by the transformed centroid so world-space geometry is preserved
for the supported unparented XYZ-Euler transform model. It intentionally names the exact
operation it performs; it is not claimed to be identical to every Blender "Origin to
Geometry" mode or surface-based center calculation.

Both transform-bake and origin-to-centroid precompute bounded resulting coordinates, verify
complete mesh geometry plus object state after the write, and restore the captured vertices
and transform when readback verification fails. Their source math and fake-bpy behavior are
tested; real Blender matrix/dependency-graph semantics remain runtime-unverified.

Shared/linked meshes, shape keys, modifiers, animation and constraints are rejected for the
mesh editing mutations above as applicable. Coordinates are base local mesh coordinates.
Use explicit `file.checkpoint` before valuable edits once real runtime acceptance is enabled.

Booleans, remeshing, UVs, sculpting, topology repair and large geometry pagination remain
outside this bounded Level 1 slice. Source tests are fake-data tests; actual Blender geometry
validation, matrix behavior and dependency graph behavior remain unverified.
