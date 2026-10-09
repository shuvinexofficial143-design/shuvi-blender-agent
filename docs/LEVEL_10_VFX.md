# Level 10 — VFX & Simulation

Current source progress: **70%** (M1–M7 of 10).
Real Blender runtime/frame evaluation/render acceptance: **0%**.
Production ready: **No**.

## M1 — Real non-destructive WAVE ripples (0% → 10%)

Adds `vfx.wave_preview`, `vfx.wave_apply`, and
`vfx.wave_release` as typed safe host commands.

- Preview uses fresh ObjectTarget, local editable MESH, unoccupied
  name and small modifier stack. It validates finite bounded height,
  width, speed, narrowness, time_offset, start_position_x/y and
  Boolean cyclic flag. Planning is strictly read-only and revisioned.
- Apply invokes Blender's actual `obj.modifiers.new(name,"WAVE")`
  API and sets all eleven WAVE properties. It checks type, mesh
  membership, modifier order, viewport/render flags and every numeric
  setting against actual readback. Failure restores only the owned
  modifier and verifies the original scene revision.
- Release requires an issued current-session token, unchanged scene,
  same modifier instance, correct properties and original object.
  Removes only that modifier, never foreign modifiers or objects.
  Fails closed when foreign changes are detected.

This is **actual modifier configuration** with source/fake-bpy test
evidence, not proof of simulated movement or a rendered effect.
**STOP before Level 10 M3** unless the user explicitly authorizes it.


## M2 — Real OCEAN Generate water surface (10% → 20%)

New typed `vfx.ocean_preview`, `vfx.ocean_apply`, and `vfx.ocean_release` on a local editable mesh. Read-only preview strictly validates bounded OCEAN resolution, simulation time, spatial size, wave scale/alignment/direction, choppiness, wind velocity and random seed, with fresh ObjectTarget and scene revision. On apply, `obj.modifiers.new(name, "OCEAN")` uses `geometry_mode="GENERATE"` to add actual Blender water geometry and writes all nine settings; exact direct readback verifies type, index and every numeric property. Modifier ownership is current-session-only, with fail-closed foreign edit detection. Error/readback mismatch removes only the new modifier and verifies prior scene state. Release requires valid one-use token and unmodified scene before removing only owned modifier. Other objects/modifiers/materials/camera/world stay intact.

M2 creates **source-level Ocean simulation configuration**: no Blender time stepping, animated time keyframes, ocean cache bake, fluid physics test or render was run. Level 10 source **20%** (M1–M2), real Blender runtime/render acceptance **0%**, production ready No. M3 is authorized and implemented.


## M3 — Actual Ocean foam and spray attribute generation (20% → 30%)

Extends the existing typed `vfx.ocean_preview/apply/release` with
**optional** nested `settings.foam`: required bounded
`foam_layer_name` and `foam_coverage`, optional
`use_spray`, `spray_layer_name` and `invert_spray`. Foam is
enabled, and Blender's actual OceanModifier `use_foam`,
`foam_layer_name`, `foam_coverage`, `use_spray`,
`spray_layer_name`, and `invert_spray` are written and
read back on the generated ocean surface. All layer names use
bounded ASCII identifier characters; no filesystem I/O, caching,
material generation or arbitrary Python is accepted.

The complete foam/spray readback is part of the same owned
Ocean modifier release guard. A corrupted readback removes
only the newly created modifier. Changed or stale settings
refuse apply; foreign changes refuse release. Original M2
requests without foam remain compatible. This generates Ocean
foam/spray **attribute configuration**, not an actual evaluated
ocean image, shader mask hookup, foam geometry measurement or
rendered visual evidence.

Registered typed tools stay **274**, Level 10 source **30%**.
Runtime/evaluated-frame/render acceptance **0%**.
M4 remains user-authorized under the same `next`.


## M4 — Animated OceanModifier.time timeline keyframes (30% → 40%)

New typed `vfx.ocean_timeline_preview` (READ_ONLY),
`vfx.ocean_timeline_apply` (MUTATION) and
`vfx.ocean_timeline_restore` (MUTATION) accept a currently
owned Ocean token plus 2–8 strictly increasing frame/time pairs.
The frames must lie in the scene's original range, and the
Ocean times must be finite, bounded and strictly increasing.
Existing animation-data objects are refused.

Apply writes the **real Blender OceanModifier.time** for every
specified pair and invokes `OceanModifier.keyframe_insert(
data_path="time", frame=...)`. It reads back actual time
F-Curve keyframe coordinates from the object's current Blender
Action using Blender's legacy/slotted action compatibility reader
and verifies every frame/time coordinate plus the final current
modifier time. The resulting same-session token guards ownership,
frame curve identity, and the exact post-write scene revision.

Restore refuses changed Ocean modifiers, altered keyframe
coordinates, a replaced action, or foreign changes to the scene.
It clears only animation data created on a previously unanimated
object, removes the newly-owned orphan action when safe, restores
the original Ocean.time and verifies the exact prior snapshot,
then re-enables normal owned `vfx.ocean_release`. The
source-side tests include interrupted key insertion and cleanup.
No user-created Action or foreign keyframes are adopted/deleted.

This enables Blender timeline **keyframe data**, but does not
evaluate time between keys, play an animation, bake ocean
simulation caches, prove animated geometry or render frames.
**Level 10 source 40%**, 277 registered typed tools.
Real Blender runtime/frame/render acceptance **0%**.
Production-ready **No**. Stop before Level 10 M5 without user
authorization.


## M5 — Blender Cloth physical simulation setup (40% → 50%)

Adds `vfx.cloth_preview/apply/release` typed commands. Creates an actual bpy `CLOTH` modifier on a local editable mesh. Sets `ClothModifier.settings` quality (2–20), per-vertex mass, air damping, tension/bending stiffness, and `ClothModifier.collision_settings` self collision and minimum collision distance. Enforces bounds, unique modifier name/type, fresh mesh and scene revisions and maximum stack size. All seven fields and the modifier's instance/index/type/render flags are read back and compared; corrupted writes roll back the owned modifier, while edited foreign or managed content is never adopted or silently deleted. Release consumes a session-only token and verifies original scene state. No evaluated cloth solver frames, bake or visuals have been run. **Level 10 50% source, 280 tools; Blender runtime 0%.** M6 follows under this authorized `next`.


## M6 — Collision Surface for Cloth/Particle obstacles (50% → 60%)

Adds typed `vfx.collision_preview/apply/release` for a separate existing local MESH. Applies a real bpy `COLLISION` modifier and edits Blender `CollisionModifier.settings`: `use=True`, bounded `thickness_outer` (0.001–1), `cloth_friction` (0–80), `damping` (0–1), Boolean `use_culling` and `use_normal`. Read-only preview binds a fresh target, scene, modifier index and collision geometry options. Apply directly writes nested Blender RNA properties and verifies the exact readback; failures delete only the owned modifier with verified rollback. Release requires session ownership and an unmodified scene/owned collider; foreign meshes/modifiers remain unchanged. M5 Cloth and M6 Collision can coexist on different mesh objects, and the tests verify reverse-order safe release. This configures a collider for subsequent physics execution but does **not** prove that cloth actually collides with it in a rendered or evaluated frame. Source Level10 **70%** (M1–M7); **283** public typed tools; real Blender runtime/frame/render acceptance **0%**; production ready No. Stop before M7 without user authorization.

### M7 — Cloth Pinning (60% → 70%)
Existing vfx.cloth_preview/apply/release accepts optional paired settings.pin_group (existing weighted vertex group) and settings.pin_stiffness (0..50). Writes real ClothSettings.vertex_group_mass and pin_stiffness, fingerprints existing vertex weights in preview, refuses weight edits during release, and never creates or removes foreign vertex groups. Source-only; real frame/bake/render testing remains outstanding.
