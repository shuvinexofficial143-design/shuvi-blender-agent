# Level 1 control

Source work in progress. Real Blender runtime verification: **0%**.

| Capability | Implemented | Unit tested | CI tested | Runtime tested | Deferred |
|---|---|---|---|---|---|
| Cube/plane/empty | yes | yes | yes (prior baseline) | no | |
| UV sphere/icosphere/cylinder/cone/circle/grid/torus | yes | yes | pending | no | configurable resolution |
| Remaining Level 1 controls | in progress | pending | pending | no | see future checkpoints |

Primitives use direct mesh data, no operators. Unit radius spheres, cylinder/cone
height 2, 16 radial segments, sphere 8 latitude divisions, unsubdivided icosphere,
filled 16-sided circle, 8x8 grid over [-1,1], torus major radius 1/minor .25
with 16x8 segments. Mesh coordinates are float32 before fingerprint comparison.
All use object.create with unchanged typed transform and expected_scene_revision.
Creation mismatch removes only newly created object and unused mesh.

Implemented and unit-tested (CI pending, runtime no): rename; allowlisted display/color/locks;
partial location/scale/XYZ Euler or unit WXYZ quaternion; separate visibility flags;
selection/active inspection and mutation. Data and constraint summaries join object inspection.
Selection writes require expected_scene_revision and Object mode, at most 256 selected IDs.
Null target with selected=false and active=false clears selection and active object.
Partial transform omitted channels are preserved and verified. Clear channels by explicitly
setting location/Euler to [0,0,0], quaternion to [1,0,0,0], scale to [1,1,1].
