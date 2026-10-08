# Level 7 — Advanced Animation

Level 7 begins after the completed Level 1-6 source roadmaps. The same evidence boundary remains:
source/fake-bpy/CI evidence is not real Blender runtime verification.

Goal: give Shuvi precise, bounded animation-state understanding and later verified advanced
keyframe, curve, pose, camera and NLA workflows without exposing arbitrary Python, unrestricted
bpy operators or generic animation data mutation.

Current Level 7 source progress: **100%**.

Real Blender runtime verification for Level 7: **0%**.

Production ready: **No**.

## Ten-milestone roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| 1 | Action / FCurve / keyframe inspection foundation | complete |
| 2 | Revision-gated keyframe edit / remove / replace | complete |
| 3 | Interpolation, easing and handle controls | complete |
| 4 | Bounded multi-key / timeline animation workflows | complete |
| 5 | Pose-bone animation channels | complete |
| 6 | Camera / lens / focus animation workflows | complete |
| 7 | Constraint influence / visibility animation controls | complete |
| 8 | Managed NLA clip / strip workflows | complete |
| 9 | Versioned animation recipe library | complete |
| 10 | Animation QA / recovery / acceptance | complete |

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

## Milestone 5 — 50% complete

Milestone 5 adds two bounded pose-animation surfaces:

- `animation.pose_bone_inspect`
- `animation.pose_bone_keyframe_insert`

These surfaces operate on raw pose-bone transform channels only. They do not claim evaluated
constraint/IK/dependency-graph motion.

### `animation.pose_bone_inspect`

Input: current-session armature `object_id` plus one explicit `bone_name`.

The read-only result combines current rig and animation evidence:

- current `rig_revision` and full `animation_revision`;
- Action name/users and live-session ownership;
- current pose rotation mode;
- exact bounded channels for that bone;
- expected channel count: **9** for XYZ or **10** for Quaternion;
- exact per-bone keyframe point count and unique frames;
- pose-bone constraint count;
- deterministic `pose_animation_revision`;
- explicit `raw_pose_channels_only=true` and runtime-unverified metadata.

Inspection reports blockers for foreign/shared/unsafe Actions, any non-pose channels in the Action,
alternate Euler/Quaternion channel remnants, or a partial channel set.

### `animation.pose_bone_keyframe_insert`

Mutation requires all three freshness guards:

- a fresh `ObjectTarget`;
- exact current `rig_revision`;
- exact current `animation_revision`.

The payload supplies one bone, frame, location, scale, interpolation and either:

- XYZ Euler rotation (3 components); or
- normalized Quaternion rotation (4 components, normalized by the existing rig contract).

The first pose key may create a new Action; Shuvi marks that Action as session-owned. Later pose
keys may extend only the same unshared, session-owned **pose-only** Action. An Action containing
object-transform or other non-pose channels is not adopted.

Existing pose animation cannot silently switch rotation representation after channels exist.
A requested frame is rejected if that bone already has any keyed pose channel at the frame;
overwrite remains disabled.

The M1 global animation bounds remain authoritative:

- at most **64 FCurves**;
- at most **1024 keyframe points**.

### Verification and recovery

After insertion Shuvi reads the Action back and verifies every inserted location/rotation/scale
point, requested interpolation, session ownership, changed animation revision and the bone's raw
pose state.

If verification fails, Shuvi removes the newly inserted frame, restores the previous raw pose
state, clears a newly-created Action when the operation started from no Action, and verifies that
both the original `rig_revision` and original `animation_revision` are recovered.

Source tests cover empty inspection, XYZ insertion, normalized Quaternion insertion, duplicate
frame rejection, foreign Action rejection, stale animation revision rejection, and forced
verification-failure rollback.

M5 does not yet add pose-key edit/remove/retime, evaluated pose verification, baking, constraint
evaluation, NLA editing or arbitrary RNA/FCurve scripting.

### Milestone 5 source checkpoint

Verified source/test checkpoint: `0b7150b08caf19aea1671c7949adb2b2fcacdca9`.

CI run `37746328460` passed all six Linux/Windows Python 3.11/3.12/3.13 jobs with:

- Ruff lint
- Ruff format check
- **836 tests**
- package build
- distribution audit
- clean offline install/import without bpy
- **81 package modules**

Factory typed tools: **212**.
Current registry/catalog hard maximum: **212**.

Real Blender runtime verification remains **0%**.
Production ready: **No**.

## Milestone 6 — 60% source complete

M6 adds two typed camera optics surfaces:

- `camera.optics_animation_inspect`
- `camera.optics_keyframe_insert`

A camera's lens and depth-of-field focus distance are stored on the camera **data-block**,
not the camera object's transform Action. M6 therefore creates and inspects a separate
camera-data Action. Existing object transform/rig animation is not modified by M6.

The read-only inspection reports lens and focus distance, DOF enablement, data-block users,
Action ownership/users, exact bounded FCurve/keyframe details, blockers and a deterministic
`camera_animation_revision`. That revision tracks both unkeyed optics values and keyed
Action state, so edits outside Shuvi invalidate stale requests.

The mutation takes a fresh ObjectTarget, exact camera animation revision, integer frame,
bounded lens (1–500 mm), focus distance (0.01–10,000 Blender units), and an allowlisted
LINEAR/BEZIER/CONSTANT interpolation. Both channels are inserted at the same frame and
verified via exact channel readback; existing frames are never overwritten.

Safety guards deny:
- non-camera or non-perspective data, nonlocal/read-only/shared camera data;
- camera object constraints, non-Object mode, disabled DOF or focus-object override;
- foreign/shared/slotted camera-data Actions, drivers, NLA tracks or unrecognized channels;
- partial lens/focus channel sets, incomplete frame pairs or duplicate channel structures;
- duplicate key frames, stale revisions and work bounds (64 FCurves/1024 points).

A newly-created camera Action is owned by this adapter session; only that unshared Action
may be extended. Verification mismatch restores previous lens/focus values and removes the
inserted frame, clearing a newly-created Action when necessary. Recovery is marked verified
only when the original `camera_animation_revision` returns.

Source/fake-bpy tests cover initial inspection, first/second key insertion, duplicate frames,
foreign Actions, DOF/focus-object/shared-data blockers, stale revisions, and rollback both
with and without a pre-existing Action.

M6 **does not** claim evaluated depth-of-field appearance, tracking/focus targeting,
camera movement path animation, NLA, or real Blender runtime testing.

### Milestone 6 source checkpoint

Source/test commit `1ca771d464944fdf7c06baa3e15c87b9d4f1afc6`:
**845 passed tests**, **82 package modules**, Ruff lint/format, package build and offline
distribution/import validation.

Factory typed tools: **214**. Current registry/client cap: **214**.
Real Blender runtime verification: **0%**. Production ready: **No**.

## Milestone 7 — 70% complete

M7 adds two typed tools:

- `animation.control_inspect`: read the current object's full bounded animation state,
  Action ownership and safety blockers, and `rig_revision` when the target is an armature.
- `animation.control_keyframe_insert`: insert a bounded keyframe in one of two explicit modes.

### Mode 1 — Object visibility

The `VISIBILITY` request inserts a paired boolean keyframe for `hide_render` and
`hide_viewport` at one requested integer frame. Both visibility values are explicit booleans.
This allows source-side animation of rendering/viewport visibility rather than manipulating
the non-keyable per-view-layer `hide_set` state.

### Mode 2 — Pose-constraint influence

The `POSE_CONSTRAINT_INFLUENCE` request targets one named pose bone and named
`LIMIT_ROTATION` or safely bounded same-armature `IK` constraint. It inserts one
bounded 0..1 influence keyframe using the constraint's Blender RNA data path.
The caller must present the exact current `rig_revision` and full
`animation_revision`, as well as a fresh ObjectTarget.

### Safety, verification and recovery

Only a session-created unshared Action owned by the M7 adapter may be extended.
Foreign/shared/slotted Actions, drivers/NLA, object constraints, non-Object mode and
unrecognized animation channels fail closed. Existing channel/frame keys cannot be
overwritten. M7 enforces the existing **64 FCurve** and **1024 keyframe-point** bounds.

New keys are checked through exact channel/frame/value/interpolation readback, changed
animation revision and Action ownership. Verification mismatch removes the inserted
frame(s) or clears an Action created by the operation, restores visibility/influence
values and verifies the previous animation revision. Constraint operations also verify
the previous `rig_revision` on recovery.

M7 does not assert evaluated constraint influence, IK solving, viewport playback
behaviour or real Blender runtime compatibility. Tests use fake-bpy and CI only.

### Milestone 7 source checkpoint

Verified source/test checkpoint: `000957eec6270c04342967ea88e0af0d8951aa27`.
Source CI run `37751435514` passed six Linux/Windows Python 3.11/3.12/3.13 jobs
with Ruff lint/format, **855 tests**, package build, offline distribution audit
and **83 package modules**.

Factory typed tools: **216**. Registry/client cap: **216**.
Real Blender runtime verification: **0%**. Production ready: **No**.

## Milestone 8 — 80% complete

M8 adds two bounded managed NLA tools:

- `animation.nla_inspect`: read-only inspection of current-object NLA tracks and strips,
  current active Action, exact Action fingerprint, names, timing, playback properties, ownership,
  and a deterministic `nla_revision`.
- `animation.nla_strip_create`: revision-gated conversion of one managed Action into a
  named NLA track containing one named strip at an explicitly requested start frame.

### First managed clip

M8 only accepts an unshared **legacy** session-owned Action created by Shuvi's
`animation.insert_keyframe` implementation, with exactly the nine complete
location/rotation_euler/scale channels and at least two common integer frames.
The source Action is detached from the active Action slot and reused in a new
track/strip. Original Action keys are not rewritten.

The resulting strip uses normal REPLACE blending, scale=1, repeat=1,
influence=1 and mute=false. The requested strip start frame is integer
1..100000 and the computed strip end must also stay within 100000.

### Safety and recovery

- Mutation requires a fresh ObjectTarget and the exact current `nla_revision`.
- Foreign, shared, slotted/layered, structurally incomplete, driver/NLA-bearing,
  constrained-object and non-editable target states fail closed.
- M8 does **not** adopt or mutate any preexisting NLA tracks or strips.
- Inspection bounds: at most 64 tracks, 64 strips total, 64 Action FCurves and 1024
  Action keyframe points, with bounded per-curve reads.
- Post-mutation verification compares strip identity, timing, playback properties
  and the complete original Action FCurve fingerprint; the source Action must
  no longer be the active Action.
- On mismatch, the new NLA track is removed, the original active Action restored,
  and the exact former `nla_revision` must be recovered before reporting verified rollback.

M8 is deliberately a **single managed clip push-down** capability, not arbitrary
NLA arrangement: multi-track editing, blending, retiming, strip removal and repeat
scheduling are out of scope. It does not verify evaluated NLA playback.

### Milestone 8 source checkpoint

Verified source/test checkpoint: `9a8446ff949c7d0441106201bf96b3059c503ec2`.
Source CI run `37753381630`: **864 tests**, **84 package modules**,
Ruff lint/format, package build and offline wheel import without bpy.
Factory typed tools: **218**; bounded registry/client cap **218**.
Real Blender runtime verification: **0%**. Production ready: **No**.

## Milestone 9 — 90% source-side complete

M9 adds a real, versioned animation recipe library with three typed public tools:

- `animation.recipe_catalog`: read-only deterministic version-1 catalog with fixed
  recipe IDs, exact parameter schemas, Blender minimum-version metadata and catalog revision.
- `animation.recipe_preview`: validate a fixed versioned recipe and inspect its
  resulting bounded retime plan without changing any keyframe.
- `animation.recipe_apply`: run that exact type of fixed recipe through the existing
  atomic M4 retime operation with fresh ObjectTarget, animation revision,
  channel completeness/ownership checks, readback and verified rollback.

The three managed recipes are:

- `timeline.shift`: shift 1..32 explicitly selected complete transform keys
  by a nonzero signed frame offset of -10000..10000.
- `timeline.reverse`: reverse the times of 2..32 selected complete transform keys,
  preserving values and the motion styling of each moved key. A center key may stay put.
- `timeline.stretch`: stretch 2..32 selected complete transform keys
  by an integer factor of 2..4 around their earliest selected frame.

Only version 1 and the exact allowlisted parameter schemas are accepted. Source frames
must be unique integers in 1..100000. All computed destination frames are bounded.
Destinations occupied by non-moving keys are rejected. The existing M4 delegate
protects session-owned, unshared, complete legacy transform Actions (nine channels),
checks the exact animation revision and preserves keyframe values, interpolation,
easing and Bezier handle geometry. Its verification failure path restores the original
snapshot and checks the original revision before claiming recovery.

M9 does not run user scripts, adopt foreign/shared Actions, dynamically register recipes,
edit arbitrary NLA strips, perform Blender runtime acceptance or claim evaluated playback.
The catalog/preview tools are read-only; apply is a MUTATION-classified operation.

New fake-bpy source tests cover catalog determinism, preview purity, shift, reverse, stretch,
unknown/versioned/invalid inputs, occupied targets, stale-state rejection and forced
verification-mismatch rollback. Runtime verification: **0%**; production ready: **No**.

Factory typed tool count and registry/client cap: **221**.

## Milestone 10 — 100% source-side complete

M10 adds four public typed operations for scoped, recoverable managed transform
Actions. This does **not** claim all Blender animation types have passed acceptance.

- `animation.qa_inspect(object_id)`: nonmutating bounded QA for session Action
  ownership and sharing, exact nine-channel topology, complete unique frame keys,
  integer frame bounds, mutation blockers and the source-vs-runtime boundary.
  Reports deterministic checks, READY/BLOCKED status and a `qa_revision`.
- `animation.recovery_capture(target, expected_animation_revision)`:
  capture an exact bounded snapshot of **one current-session, session-owned
  unshared nine-channel Action**. The capture stays in adapter memory and
  does not modify Blender. At most 16 object captures are retained, replacing
  older captures for the same object.
- `animation.recovery_restore(target, expected_animation_revision,
  recovery_revision)`: revision-gated, verified restore to a previous captured
  managed Action state. The exact Action identity must still match, and
  the target must remain safe, local and owned. The restore compares complete
  keyframe values/interpolation/easing/handle state and previous revision.
  On verification failure or interruption it attempts to restore the *immediately
  preceding* Action snapshot; it reports recovery verified only when exact
  revision and complete readback match. A successfully restored capture is consumed.
- `animation.level7_acceptance(recipe_id, recipe_version, target,
  expected_animation_revision, parameters)`: nonmutating, scoped source
  acceptance combining the transform QA, version-1 managed recipe catalog,
  fresh atomic recipe preview, NLA check and source/runtime evidence boundary.
  It explicitly does not certify pose-bone playback, camera optics playback,
  visibility/constraint influence evaluation or NLA evaluated playback.
  READY refers only to this source/managed-transform recipe pathway.

Tests use injected fake-bpy only. Negative cases cover incomplete keyframes,
wrong recovery tokens, stale animation revisions, foreign Action ownership,
recipe collision, forced restore-readback mismatch, interrupted restore and
rollback to the actual pre-restore state.

M10 raises the public typed registry/client cap from 221 to **225**.
Level 7 source roadmap: **100%**. Real Blender runtime acceptance:
**0%**. Production ready: **No**.

## Stop boundary

Levels 1–7 are complete against their **source-side roadmaps only**.
Do not begin Level 8 Cinematography or merge into the main Shuvi repository
without explicit authorization. No real Blender launch, render or runtime test
has been performed.
