# Level 10 — VFX & Simulation

Current source progress: **20%** (M1–M2 of 10).
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

M2 creates **source-level Ocean simulation configuration**: no Blender time stepping, animated time keyframes, ocean cache bake, fluid physics test or render was run. Level 10 source **20%** (M1–M2), real Blender runtime/render acceptance **0%**, production ready No. Stop before M3.
