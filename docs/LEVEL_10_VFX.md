# Level 10 — VFX & Simulation

Current source progress: **10%** (M1 of 10).
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
**STOP before Level 10 M2** unless the user has explicitly authorized
it (the present `next` authorizes M1 and M2).
