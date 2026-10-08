# Level 7 — Advanced Animation

Level 7 begins after the completed Level 1-6 source roadmaps. The same evidence boundary remains:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi precise, bounded animation-state understanding and later verified advanced
keyframe, curve, pose, camera and NLA workflows without exposing arbitrary Python, unrestricted
bpy operators or generic animation data mutation.

Current Level 7 source progress: **20%**.

Real Blender runtime verification for Level 7: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Action / FCurve / keyframe inspection foundation | complete |
| 2 | Revision-gated keyframe edit / remove / replace | complete |
| 3 | Interpolation, easing and handle controls | pending |
| 4 | Bounded multi-key / timeline animation workflows | pending |
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

## Stop boundary

Milestones 1-2 are complete at 20%. Do not begin Milestone 3 without explicit user permission.

Do not install, probe, launch or render Blender and do not execute real animation runtime
acceptance without separate explicit runtime authorization.
