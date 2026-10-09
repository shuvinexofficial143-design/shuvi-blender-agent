# Level 9 — Lighting & Look Development

Current source progress: **50%** (Milestones 1–5 of 10).
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
Level 9 M1–M5 source progress is **50%**.
Real Blender runtime acceptance is **0%**.
Production ready: **No**.

**STOP** before Level 9 M6, Blender launch/render/live evaluation,
Level 10, and merging this repo into the master `shuvi-agent`
without fresh explicit user authorization.


## M2 — Professional multi-light studio presets (10% → 20%)

One additional strict, read-only typed host tool:

- `lighting.preset_catalog`: accepts only an empty payload and returns
  five source-defined presets, their named roles, fixture count,
  azimuth/elevation, initial Watts, RGB and emitter-size multipliers.
  It creates or modifies no objects.

The existing `lighting.studio_preview`, `lighting.studio_apply`
and `lighting.studio_release` now support two real, separately
placed and aimed arrangements in addition to all three M1 presets:

- `BEAUTY_CLAMSHELL`: four actual AREA light objects/datablocks,
  Key + low frontal Fill + Rim + small Catchlight.
- `PRODUCT_FIVE_POINT`: five AREA lights, Key + Fill + Rim + Top + Edge.

Each rig has independently calculated poses, light power, color,
disk-emitter size and unique role-based names. Full scene and subject
revision safeguards, preflight name-collision checks, exact readback,
bounded scene-object ceiling, creation-failure rollback and same-session
owned release now cover every fixture in the selected 3–5 light layout.
Pre-existing foreign lights, objects, materials and cameras are not
changed or adopted.

Preset light energies are starting settings, not calibrated lux, exposure,
lighting aesthetics, Blender runtime compatibility or rendered results.
Partial light *release* cannot be guaranteed atomic if Blender removal
itself fails; affected state must be inspected manually.

M2 raises the typed tool cap from **252 to 253**; source progress
is **20% of Level 9 only**. Runtime/render acceptance remains **0%**.
Production ready: **No**. M3 was subsequently explicitly authorized.


## M3 — Cinematic Color & Mood (20% → 30%)

The existing strict `lighting.studio_preview` and `lighting.studio_apply`
accept optional `mood`: NEUTRAL (backward-compatible default),
GOLDEN_HOUR, MOONLIT_BLUE or TEAL_AMBER. Each non-neutral mood applies
actual role-specific RGB and energy multipliers to all 3–5 AREA
light datablocks at initial creation, including Catchlight/Top/Edge.
Positions and pre-existing foreign lights remain unchanged.

Exact revisioned previews include mood and all resulting values.
Changing mood after preview fails stale-state verification. Creation
readback checks actual color and energy; partial creation or corruption
removes only the newly created rig and verifies original scene state.
Same-session release remains the original checked owned-only workflow.

These are RGB/power authoring presets, *not* color grading, compositor,
scene view transform changes, calibrated color temperature, or evidence
that a rendered frame achieved the requested visual mood.
Tool count remains **253**; Level 9 source **30%**.
Real Blender runtime/render acceptance **0%**, production ready No.
The user has authorized M4 alongside M3 in the same `next`; M4
requires separate implementation/CI verification.


## M4 — Shadow Casting & Area-Light Quality (30% → 40%)

Existing revisioned `lighting.studio_preview` / `lighting.studio_apply`
accept optional `shadow_profile`: STANDARD (backward-compatible),
SOFT_CINEMATIC, CRISP_DIRECTIONAL and NO_SHADOWS. These presets
write real AREA `size`, `spread` and Blender 4.2+ Light
`use_shadow` fields for every selected 3–5 fixture light.
SOFT_CINEMATIC increases the disk diameter 2.25x, yielding a
larger area source capable of a softer penumbra; CRISP_DIRECTIONAL
reduces the disk size to 0.35x and restricts cone spread to pi/2,
and NO_SHADOWS disables shadow casting on this rig's lights.

Exact preview revisions include the profile and intended emitter
values, while apply readback and mismatch rollback verify every lamp's
shadow enablement, disk size and spread. Existing foreign lights
retain all fields; same-session release still refuses modified lights
and removes only owned datablocks. The fake-bpy fixture now models
these Blender fields strictly for source testing.

These source-level controls are **not** proof of rendering-engine
compatibility, light sampling quality, noise/alias suppression,
visually clean contact shadows, or final shadow softness. Actual
Blender evaluated and rendered acceptance remains **0%**.
Public typed tools stay at **253**, Level 9 source milestone roadmap
**40%**. Production ready No. M5 was subsequently explicitly authorized.


## M5 — Owned World Environment & Preloaded HDRI (40% → 50%)

Adds `lighting.world_preview` (read-only), `lighting.world_apply`
(approved mutation) and `lighting.world_release` (approved mutation).
The typed plan chooses COLOR (fixed Background RGB, strength 0–10)
or HDRI (strict name of a *previously loaded*, local 2:1
equirectangular Blender image with real pixel data; no file reads,
network access, or arbitrary Python/paths). Applying creates a
**new World datablock**, enables shader nodes, configures a World Output
and Background with optional Environment Texture node, and connects
the exact links through bpy. The previous foreign World is preserved
as-is, not adopted or edited. The newly created World is assigned to
the scene only after the node graph is set up. Typed revision includes
scene revision, original World identity and HDRI identity/metadata.
Readback compares the exact created node graph (node names, types,
links, Background color/strength and HDRI identity/projection).

On setup failure/mismatch, the scene's original World is restored and
only the newly-created World removed, requiring scene-revision recovery.
Same-session release refuses changed world nodes, missing HDRI,
swapped scene World, changed scene, or foreign ownership.
It restores the original World and deletes only the untouched owned one.
An interrupted removal may require manual scene inspection.

M5 host cap **256** (+3 world tools), source roadmap **50%**.
No Blender executable was launched, no HDRI sourced or downloaded,
no real lighting/render/exposure acceptance; runtime remains **0%**.
Stop before M6 unless separately authorized (the current user
authorized M5+M6 in one instruction).
