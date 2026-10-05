# Bounded indexed mesh workflow

mesh.inspect accepts object_id and returns base mesh vertex coordinates, polygon indices
and a separate geometry revision. It does not evaluate modifiers or extract UV/material
layers. At most 4096 vertices, 4096 faces and 32768 polygon loops.

mesh.create accepts unique name, geometry, transform and fresh scene revision. Geometry
requires 3..4096 vertices, 1..4096 faces, 3..32 unique indices per face and finite bounded
coordinates. Blender's mesh validation runs on the new allocation, then actual vertex and
face readback is compared. Geometry changed by validation fails verification and the new
allocation is removed. These checks do not guarantee manifold topology, planar polygons,
non-intersection or artistic quality.

mesh.translate_vertices requires a fresh target, expected_geometry_revision from mesh.inspect,
1..256 unique indices and delta. Checks both object and geometry revisions, validates all
resulting coordinates before changing any vertex, then compares actual coordinates and
unchanged polygon indices. Shared/linked meshes, shape keys, modifiers, animation and
constraints are rejected. Coordinates are local mesh space. Failures can leave partial
state; inspect before recovery. Use explicit file.checkpoint before valuable edits.

This is the first useful mesh editing slice, not the complete future advanced mesh suite.
Booleans, remeshing, UVs, sculpting, topology repair and large geometry pagination are
deferred. Source tests are fake-data tests; actual Blender geometry validation and
dependency graph behavior remain unverified.
