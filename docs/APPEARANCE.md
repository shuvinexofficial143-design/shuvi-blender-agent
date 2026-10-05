# Materials, cameras and lights

`device.create` requires name, kind, transform, expected_scene_revision and settings.
CAMERA settings: lens (1..500 mm), clip_start, clip_end, make_active (boolean). Creates a
perspective camera, optionally sets scene.camera, and verifies actual lens/clipping, active
camera status, transform and membership. Light kind: POINT/SUN/SPOT/AREA; settings: energy
(0..1000000) and RGB color (0..1). Energy uses Blender's native units for that light type.
No rendering or GPU work occurs merely by defining a tool; tests only use fake data.

`material.create_assign` requires a fresh target, unique material name, RGBA base_color,
metallic and roughness (all components 0..1). It creates a node material with the default
Principled shader, configures those explicit sockets, appends a slot and verifies socket
values plus assignment. Existing materials/slots are preserved. Only editable meshes
with unshared, unlinked mesh data are accepted to prevent accidental cross-object edits.
Alpha is a shader input; this tool does not configure transparency/render modes.

Verification failures remove newly created data; camera failures restore the previous
active camera, and material failures remove the newly appended slot. These operations
are not general transactions. Unexpected Blender exceptions can leave partial state and
require inspection. Texture networks, editing existing materials, advanced camera models,
light shape/spot controls and render appearance verification remain future extensions.

Source and fake-data tests are complete for this initial bounded capability slice.
No Blender runtime or production readiness is claimed.
