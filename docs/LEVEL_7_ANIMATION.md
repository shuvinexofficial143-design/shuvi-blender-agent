# Level 7 — Advanced Animation

Level 7 begins after the completed Level 1-6 source roadmaps. The same evidence boundary remains:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi precise, bounded animation-state understanding and later verified advanced
keyframe, curve, pose, camera and NLA workflows without exposing arbitrary Python, unrestricted
bpy operators or generic animation data mutation.

Current Level 7 source progress: **40%**.

Real Blender runtime verification for Level 7: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Action / FCurve / keyframe inspection foundation | complete |
| 2 | Revision-gated keyframe edit / remove / replace | complete |
| 3 | Interpolation, easing and handle controls | complete |
| 4 | Bounded multi-key / timeline animation workflows | complete |
| 5 | Pose-bone animation channels | pending |
| 6 | Camera / lens / focus animation workflows | pending |
| 7 | Constraint influence / visibility animation controls | pending |
| 8 | Managed NLA clip / strip workflows | pending |
| 9 | Versioned animation recipe library | pending |
| 10 | Animation QA / recovery / acceptance | pending |

## Milestone 1 — 10% complete

Milestone 1 adds one read-only foundation surface: `animation.inspect`.

### `animation.inspect`

Input: one current-session `object_id`.

The tool resolves only the current scene/session identity and returns an exact bounded animation
state for supported Action structures. It does not mutate the timeline, object transform, Action,
FCurves or keyframes.

The readback includes:

- current object ID and object revision;
- Action name, API form (`NONE`, `LEGACY`, or supported `SLOTTED`), Action user count and
  whether the Action was created by this live Shuvi animation adapter session;
- exact FCurve/channel count and bounded channel list;
- exact keyframe point count, unique sorted frames and first/last keyed frame;
- per-point frame/value/interpolation readback and deterministic interpolation counts;
- current driver count and NLA-track count;
- deterministic `animation_revision` over the managed animation state;
- explicit `source_only=true` and `real_runtime_verified=false`.

### Safety and bounds

Exact inspection fails closed when the existing animation snapshot is truncated or uses an
unsupported layered Action structure.

Current source bounds:

- at most **64 FCurves**;
- at most **1024 inspected keyframe points**;
- at most **64 drivers** and **64 NLA tracks** before inspection refuses the structure;
- keyframe coordinates must be finite;
- channel paths and interpolation strings are bounded Unicode text.

The tool also reports deterministic blockers for later managed mutation:

- non-local/read-only object;
- existing object constraints;
- non-Object mode;
- drivers present;
- NLA tracks present;
- foreign Action not created by this adapter session;
- shared Action with user count other than one.

An unanimated safe local object can therefore report `managed_mutation_ready=true`, while an
existing foreign/shared/driver/NLA animation remains inspectable but is not silently adopted for
mutation.

### Existing animation controls retained

The earlier bounded controls remain available:

- `animation.set_range`
- `animation.set_frame`
- `animation.insert_keyframe`

Milestone 1 does not broaden those mutation surfaces or add overwrite/removal behavior.

### Milestone 1 source checkpoint

Verified source/test checkpoint: `e1ecabf4b6d8a15dd7b0891fa3c36cd066f71b89`.

CI run `37725756781` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **812 tests**
- package build
- distribution audit
- clean offline install/import without bpy
- **77 package modules**

Factory typed tools: **204**.
Current registry/catalog hard maximum: **204**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Milestone 2 — 20% complete

Milestone 2 adds three bounded mutation surfaces over the M1 inspection/revision foundation:

- `animation.edit_keyframe`
- `animation.remove_keyframe`
- `animation.replace_keyframe`

All three require a fresh `ObjectTarget` plus the exact current `animation_revision`.
They operate only on a session-created, unshared, mutation-ready Action with exactly the nine
managed transform curves: location XYZ, rotation_euler XYZ and scale XYZ.

### `animation.edit_keyframe`

Edits one exact transform channel point at one integer frame. The caller supplies
`data_path`, `array_index`, `frame`, bounded value and one allowlisted interpolation mode
(`LINEAR`, `BEZIER`, `CONSTANT`). Missing or non-unique points fail closed. No-op edits are
rejected.

### `animation.remove_keyframe`

Removes one complete managed transform key at an exact frame. All nine transform-channel points
must exist exactly once at that frame. Readback must prove the frame is absent, point count drops
by exactly nine and the animation revision changes.

### `animation.replace_keyframe`

Replaces all nine values/interpolations for one existing complete transform keyframe at the same
frame. It does not create a new frame and does not rewrite unrelated frames.

### Freshness, safety and recovery

M2 keeps M1 blockers authoritative: linked/read-only objects, constraints, non-Object mode,
drivers, NLA, foreign Actions and shared Actions are not adopted for mutation.

Before every mutation the exact `animation_revision` is rechecked. A stale revision returns
`STALE_STATE` even when the caller refreshed the ObjectTarget.

Mutation readback is compared against the requested exact state. On mismatch Shuvi restores the
pre-mutation keyframe snapshot, recomputes animation state and only reports
`recovery_verified=true` when the original `animation_revision` is restored.

The M2 source tests force a verification mismatch during replacement and prove rollback to the
exact previous animation revision and keyframe value.

M2 deliberately remains transform-keyframe-only. It does not yet expose Bezier handle geometry,
easing parameters, arbitrary data paths, pose-bone channels, evaluated animation, NLA mutation or
generic FCurve scripting.

### Milestone 2 source checkpoint

Verified source/test checkpoint: `5f6bb906b2c344c7b15dd4da44a3e359098ba70e`.

CI run `37726818467` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **818 tests**
- package build
- distribution audit
- clean offline install/import without bpy
- **78 package modules**

Factory typed tools: **207**.
Current registry/catalog hard maximum: **207**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Milestone 3 — 30% complete

Milestone 3 adds one bounded style mutation surface:

- `animation.keyframe_style_set`

It addresses one exact managed transform-channel keyframe using a fresh `ObjectTarget` plus the
exact current `animation_revision`.

### Style controls

The tool can set:

- interpolation: `CONSTANT`, `LINEAR`, `BEZIER`, `SINE`, `QUAD`, `CUBIC`, `QUART`,
  `QUINT`, `EXPO`, `CIRC`, `BACK`, `BOUNCE`, or `ELASTIC`;
- easing: `AUTO`, `EASE_IN`, `EASE_OUT`, or `EASE_IN_OUT` where the interpolation family
  actually uses easing;
- bounded Bezier handle types: `FREE`, `VECTOR`, `AUTO`, or `AUTO_CLAMPED`;
- exact left/right handle coordinates only when that side is explicitly `FREE`.

`CONSTANT`, `LINEAR` and `BEZIER` require `easing=AUTO`. Non-Bezier interpolation rejects
manual handle coordinates and requires automatic handle types. FREE Bezier handles must stay on
their respective side of the keyframe and within the bounded frame/value work limits.

### Style-aware inspection and revisions

M1 inspection now includes per-key:

- easing;
- left/right handle type;
- left/right handle coordinates.

Those fields are included in `animation_revision`. A handle/easing-only change therefore makes
old animation revisions stale instead of silently bypassing the M2 freshness gate.

M2 recovery snapshots were also extended to preserve these style fields, so later keyframe
edit/remove/replace rollback does not discard M3 curve style.

### Verification and recovery

The M3 mutation is restricted to the same session-owned, local, editable, unshared nine-transform
curve Action accepted by M2. It does not adopt arbitrary foreign FCurves.

After mutation Shuvi reads the exact point back and verifies requested interpolation/easing,
handle types and any explicit FREE handle coordinates. Verification mismatch restores the complete
pre-mutation Action snapshot and only reports recovery success when the original
`animation_revision` is reproduced.

Source tests cover exact FREE Bezier handle readback, eased non-Bezier interpolation, invalid
style combinations, stale revision rejection, and forced verification-failure rollback.

M3 does not expose FCurve modifiers, extrapolation, arbitrary data paths, evaluated motion,
pose-bone animation, NLA mutation, or unrestricted bpy/Python.

### Milestone 3 source checkpoint

Verified source/test checkpoint: `c4b2e0865f5909546f1281762a34f5736c44a466`.

CI run `37741672615` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **823 tests**
- package build
- distribution audit
- clean offline install/import without bpy
- **79 package modules**

Factory typed tools: **208**.
Current registry/catalog hard maximum: **208**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Milestone 4 — 40% complete

Milestone 4 adds two bounded timeline workflow surfaces:

- `animation.retime_preview`
- `animation.retime_apply`

Both take the same fresh `ObjectTarget`, exact current `animation_revision`, and an explicit list
of source→target frame mappings.

### Bounded multi-key retiming

A single request may retime **1..32 complete transform keys**. Every source frame must contain
exactly one key on all nine managed transform channels.

Mappings are canonicalized by source frame and require:

- unique source frames;
- unique target frames;
- source and target to differ;
- integer frames in the existing bounded animation frame range;
- no target collision with an unrelated existing key.

A target frame may already be occupied only when that frame is itself included in the same move
set as a source. This permits simultaneous swaps/chains without overwriting unrelated timeline
keys.

### `animation.retime_preview`

The preview is read-only. It proves the requested source frames are complete, performs the same
collision checks as apply, and reports:

- canonical mapping list;
- source/target frame sets;
- mapping count;
- exact moved-point count (9 per key);
- resulting unique-frame set;
- explicit value/style preservation guarantees;
- deterministic workflow revision.

Preview never mutates the Action.

### `animation.retime_apply`

Apply moves the nine point coordinates for every selected transform key as one bounded workflow.
Each key's value, interpolation, easing and handle types are preserved.

Bezier handle X coordinates move by the same frame delta as the owning key while handle Y values
are preserved. This keeps M3 FREE-handle geometry attached to the moved key in source/fake-bpy
evidence.

After mutation Shuvi verifies:

- total point count is unchanged;
- the resulting unique-frame set exactly matches the previewed plan;
- every moved channel reaches its requested target frame;
- value/interpolation/easing/handle state matches the source key with the expected frame delta;
- `animation_revision` changes.

Verification mismatch restores the full pre-retime Action snapshot and requires the original
animation revision to be recovered before rollback is reported as verified.

Source tests cover preview no-mutation, multi-key style-preserving apply, simultaneous swaps,
occupied-target rejection, stale revision rejection, duplicate mapping rejection and forced
verification-failure rollback.

M4 does not yet expose arbitrary time scaling curves, fractional frame remapping, evaluated motion,
pose-bone channels, NLA editing or generic FCurve scripting.

### Milestone 4 source checkpoint

Verified source/test checkpoint: `6bd1384583bc1b1255e62799314c18de04965275`.

CI run `37743968296` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **830 tests**
- package build
- distribution audit
- clean offline install/import without bpy
- **80 package modules**

Factory typed tools: **210**.
Current registry/catalog hard maximum: **210**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Stop boundary

Milestones 1-4 are complete at 40%. Do not begin Milestone 5 without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real animation runtime
acceptance without separate explicit runtime authorization.
