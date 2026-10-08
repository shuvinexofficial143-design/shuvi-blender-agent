# Level 9 — Lighting & Look Development

Current source progress: **10%** (Milestone 1 of 10).
Real Blender runtime/render acceptance: **0%**.
Production ready: **No**.

## M1 — Three-point AREA-light studio rig (0% → 10%)

Three new typed host-controlled operations:

- `lighting.studio_preview` (READ_ONLY): requires a fresh `subject`
  ObjectTarget, 1..40-character `name_prefix`, one of
  `SOFT_STUDIO`, `DRAMATIC`, `WARM_PORTRAIT`, a `distance_scale`
  in 2.5–6.0 and `intensity_scale` in 0.25–3.0.
  Uses a nonzero, finite mesh-object bounding sphere and XYZ-oriented,
  unparented, unanimated, unscaled, unconstrained subject in OBJECT mode.
  Returns three planned real Blender light objects, exact names,
  location/rotation, power (Watts), RGB, disk emitter size, scene and
  subject revisions, ready/blockers and deterministic `lighting_revision`.
  No scene data is changed by preview.
- `lighting.studio_apply` (MUTATION): rechecks the entire plan and
  exact `expected_lighting_revision`. Uses actual bpy datablock APIs:
  `bpy.data.lights.new(name, "AREA")`,
  `bpy.data.objects.new(name, light_data)` and
  `scene.collection.objects.link(light_object)`.
  Each light's emitter has `shape="DISK"`, bounded nonzero `size`,
  exact RGB color and energy, independently computed world location
  and XYZ Euler rotation aiming local -Z toward the current subject.
  Creates Key, Fill and Rim in that order, with independent azimuth,
  elevation, power and emitter size. Verifies all three actual objects,
  datablock identity/membership, users count, light properties, pose,
  unchanged subject and scene expected membership. Partial creation
  and corrupted readback remove only the new objects/datablocks and
  require original scene revision before reporting recovery.
- `lighting.studio_release` (MUTATION): needs successful current-session
  `expected_lighting_token`; rejects changed scene state, edited
  lights, replaced data or foreign session ownership. If still
  untouched, removes the three owned objects and their unique light
  datablocks, verifying the original scene revision and no survivors.
  Release cleanup cannot be assumed atomic if Blender removal itself
  fails; an interrupted release may require manual scene inspection.
  It must never adopt/remove other lights or foreign objects.

Preset descriptions:

| Preset | Key | Fill | Rim | Intent |
|---|---:|---:|---:|---|
| SOFT_STUDIO | 1200 W | 500 W | 850 W | Balanced neutral/warm key, cool fill, white rim |
| DRAMATIC | 1500 W | 170 W | 1300 W | High contrast, low-power cool fill, warm backlight |
| WARM_PORTRAIT | 1000 W | 410 W | 800 W | Warm key/rim, neutral-cool fill |

Energy scales linearly with the caller's `intensity_scale`; emitter
placement scales from the current subject dimensions, and emitter
diameter scales with the subject size. All power/size values are starting
rig settings, **not measured visual illuminance**, guaranteed exposure
or real Blender render acceptance.

## Limitations and stop boundary

The M1 studio rig targets one **static, axis-aligned local mesh object**.
It intentionally does not chase future animated motion, solve shadow
occlusion, edit Render Engine/world nodes, guarantee Blender scene
color management, or verify final brightness, speculars or shadows.
Any scene-level mutation not owned by the current adapter should
cause a stale-state denial before new setup/release.

Previously completed Level 8 remains **100% source-side** only.
Level 9 M1 source progress is **10%**.
Real Blender runtime acceptance is **0%**.
Production ready: **No**.

**STOP** before Level 9 M2, Blender launch/render/live evaluation,
Level 10, and merging this repo into the master `shuvi-agent`
without fresh explicit user authorization.
