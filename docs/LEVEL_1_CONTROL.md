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
