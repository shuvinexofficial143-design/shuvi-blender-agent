# Level 9 — Lighting & Look Development

Current source progress: **90%** (Milestones 1–9 of 10).
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
Level 9 M1–M9 source progress is **90%**.
Real Blender runtime acceptance is **0%**.
Production ready: **No**.

**STOP** before Level 9 M10, Blender launch/render/live evaluation,
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


## M6 — Per-light Sub-object Targeting (50% → 60%)

The existing `lighting.studio_preview`/`lighting.studio_apply`
accept a strictly parsed optional `target_offsets` dictionary:
one role (Key, Fill, Rim, Catchlight, Top or Edge **only if present**)
maps to three finite normalized X/Y/Z values in [-0.45, 0.45].
The aim target is the static, unrotated subject origin plus the
reported object dimensions multiplied by the normalized offset.
Every fixture can now aim at a distinct subject region without
relocating the subject or moving foreign lights.

M6 uses actual per-fixture XYZ Euler rotations and verified bpy
light-object transform readback. Default omitted/zero offsets retain
exact M1–M5 central aiming and pose values. The plan exposes each
computed world-space `aim_point`, original `target_offset`, and
a deterministic revision bound to every offset. Changing any target
between preview/apply is rejected as STALE_STATE; failures roll back
all owned newly-created light datablocks and objects. Same-session
release still checks all owned light poses and scene revisions.

These are object bounding-box coordinate aim points, **not**
face/vertex tracking, evaluated world-space ray tests, real-time
target following or proof of rendered highlights. Rotated, parented,
animated, constrained, or nonunit-scaled subjects are still refused.

Registered public tools remain **256**. Level 9 source **60%**
(M1–M6 of 10), Blender runtime/render verification **0%**,
production ready No. M7 subsequently explicitly authorized.


## M7 — In-place single-lamp creative tuning (60% → 70%)

Two real, typed public tools: `lighting.tune_preview` (READ_ONLY)
and `lighting.tune_apply` (approved mutation). Requires a currently
owned, unchanged lighting token and one existing fixture role. A
nonempty bounded settings patch can change energy Watts (1–100000),
RGB (three finite numbers in [0, 1]), AREA disk emitter size
(0.2–50000) and Boolean shadow casting. Unlike the original M1–M6
rig creation, **M7 changes actual existing bpy light datablocks
in place**, without deleting/recreating the rig.

The exact read-only plan contains current and proposed light
properties plus a deterministic `tuning_revision` bound to the
ownership token, full currently read-back rig and scene revision.
Apply requires this exact expected revision; stale, foreign, changed
or already-modified lights cannot be adopted. Every existing fixture
is read back, with current same-session ownership and subject
verified before mutation. On write error or mismatch, all relevant
original light settings are restored and read back, with a
fail-closed status if recovery cannot be verified. Successful tuning
updates the owned baseline so `lighting.studio_release` can still
remove only those owned lights and restore the original scene.
Foreign objects, foreign lights, world, materials and camera are
untouched.

M7 registers **258** public typed tools (M6 256 + 2).
Level 9 source progress **70%**. Real Blender runtime and
rendered appearance acceptance **0%**. Production ready: No.
The same user `next` also authorizes M8; complete its own
source and CI checks before claiming 80%.


## M8 — Reversible whole-rig cinematic look swaps (70% → 80%)

Three real host operations: `lighting.look_preview` (READ_ONLY),
`lighting.look_apply` and `lighting.look_restore` (mutations).
Strict named styles: FILM_NOIR, PRODUCT_GLOSS and NEON_SPLIT. Each
style computes bounded per-role power (Watt) multipliers and actual
RGB values for every fixture of the currently owned 3–5 light rig.
Unlike source-side recipe descriptions, `look_apply` modifies
**the existing bpy AREA light datablocks together**. It requires an
unchanged ownership token, complete preflight readback, exact fresh
look revision and no pending un-restored look. Every fixture is
independently verified after the mutation. If even one light fails
readback or write, the pre-look properties of the entire owned rig
are restored with verified readback; uncertain recovery fails closed.

Successful apply returns a same-session look token and preserves a
one-level exact before/after snapshot. `lighting.look_restore` accepts
that token only while the managed scene and every light match the
applied look. Restore writes the original per-fixture settings,
verifies them, expires the look token and preserves the regular
`studio_release` lifecycle. Individual M7 tuning after a look
explicitly expires the pending undo token so it cannot overwrite
new intentional adjustments. Neither foreign lights nor materials,
camera, environment, other objects are altered. This is not
color grading, rendered film-noir quality or visual acceptance.

Public tools **261**. Level 9 source progress **80%** (M1–M8).
Real Blender runtime/visual render acceptance remains **0%**.
Production ready: No. **STOP before M9**, Blender launch/render
and merging into the master Shuvi repo without new instruction.


## M9 — Reversible multi-property Cinematic Lighting Recipes (80% → 90%)

New strictly typed `lighting.recipe_catalog`, `lighting.recipe_preview`,
`lighting.recipe_apply`, and `lighting.recipe_restore` support
INTERVIEW_SOFTBOX, NOIR_PORTRAIT and PRODUCT_SHOWCASE. These are **functional
recipes**, not descriptions: a single recipe adjusts existing managed
3–5 AREA lights together with per-role RGB, power, emitter size,
`spread`, and `use_shadow` (not just M8's color and energy). Every
fixture's actual datablock is modified via the existing safe in-place
write method, all properties are read back, a partial or corrupted
result restores every previous owned light, and a one-use recipe token
restores all prior settings on request. The previous native scene,
camera, material, foreign lights and World remain unchanged.

Recipe preview requires current-session ownership, unchanged full
scene and each fixture readback, and no pending M8 look/previous recipe.
The deterministic expected recipe revision must still match at apply.
Individual M7 tuning after successful recipe intentionally invalidates
the old recipe undo (new user changes take precedence); M8's look
switching refuses to silently override a pending recipe undo.
Restore refuses stale, modified or foreign tokens/fixtures and checks
the complete post-restore state.

These are static initial scene-look presets only; they do not
render, inspect scene images, calibrate illuminance, or guarantee
cinematic quality. Level 9 source **90%**, public typed tools **265**.
Real Blender runtime/render acceptance **0%**. Production-ready No.
M10 is separately authorized in the same `next`, requiring separate
implementation, testing and green CI.
