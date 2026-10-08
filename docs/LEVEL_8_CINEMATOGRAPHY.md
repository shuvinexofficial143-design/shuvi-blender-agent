# Level 8 — Cinematography

Level 8 follows completed Level 1–7 **source-only** roadmaps. None of the
camera framing functionality is certified by a real Blender session yet.

Current Level 8 source progress: **80%** (Milestones 1–8 of 10).
Real Blender runtime acceptance: **0%**.
Production ready: **No**.

## Milestone 1 — Subject-centered cinematic framing

Two bounded public tools:

- `cinema.shot_preview` (READ_ONLY): compute an explicit perspective shot
  from a current-session camera ObjectTarget and a distinct subject ObjectTarget.
  Inputs are azimuth -180..180°, elevation -75..75°, framing margin 1.05..2.5
  and an explicit `make_active` boolean. Output includes computed camera position,
  XYZ Euler orientation, subject dimensions/center, lens/sensor, horizontal and
  vertical FOV, conservative camera distance, clipping blockers and a deterministic
  `plan_revision`. This operation does not modify the Blender scene.
- `cinema.shot_frame` (MUTATION): accept the same typed fields plus the **exact**
  `expected_plan_revision`, re-evaluate the camera/subject and render settings,
  refuse stale or blocked plans, move/rotate the camera to the calculated shot,
  optionally set it as the scene camera, read back all changes and restore the
  original pose/active camera on mismatch or interruption. No render is started.

### Geometric calculation

- Uses the subject object's origin as the shot center and its reported XYZ
  dimensions as a conservative *world-axis-aligned*, origin-centered enclosing
  sphere. This does **not** prove that an off-center object's full geometry
  is framed. Origin recentering and evaluated bounding-box support remain future work.
- Computes horizontal FOV from camera lens and sensor width and vertical FOV
  from pixel-corrected render aspect ratio. The narrower half-FOV governs the
  framing distance, inflated by the requested margin.
- Builds a camera pose aimed toward the subject: Blender cameras look along
  local -Z with +Y up. No arbitrary Python scripting or unrestricted camera
  operators are exposed.

### Safety and verification

- Only distinct current-session objects. The camera must be local, editable,
  parentless, unconstrained, unanimated, unshared, perspective, XYZ-rotated,
  unit-scaled, and in Object Mode, without transform locks.
- Camera data must be local, used by one object, and have no animation.
- Sensor-fit is HORIZONTAL or AUTO for landscape images. AUTO for portrait
  is deliberately blocked until explicit vertical-sensor interpretation exists.
- The conservative subject sphere must be entirely between camera near/far clip
  distances. Invalid bounds, stale target revisions, modified scene aspect,
  foreign/shared states, and invalid angular/margin payloads are refused.
- Shot apply verifies actual camera transform, unchanged camera lens,
  unchanged subject snapshot, active camera state and revision change.
  A mismatch rolls back the previous pose and active scene camera; rollback
  is only marked verified if the original camera revision is recovered.
- No real Blender execution, render, camera tracking, evaluated animated
  geometry or motion path is included in this milestone.

Factory public typed tools: **227** (M1 adds two to the former 225).
Source/fake-bpy tests cover a real camera-pose mutation through the adapter,
look-direction geometry, landscape/portrait FOV, blockers, stale plans,
readback mismatch rollback and interrupted execution recovery.

## Milestone 2 — Rule-of-Thirds camera composition (20% source-side)

Two new public tools:

- `cinema.composition_preview`: read-only camera shot composition preview
  for **nine fixed image-space anchors**: CENTER, LEFT_THIRD, RIGHT_THIRD,
  TOP_THIRD, BOTTOM_THIRD, UPPER_LEFT_THIRD, UPPER_RIGHT_THIRD,
  LOWER_LEFT_THIRD and LOWER_RIGHT_THIRD.
- `cinema.composition_apply`: apply the current exact composition revision,
  reposition the actual camera sideways/upwards in its image plane, optionally
  activate it, and verify actual camera pose and unchanged subject/focal
  length with the same atomic readback/rollback implementation as M1.

### Composition geometry

- Reuses M1's exact fresh ObjectTarget, sensor, render aspect and camera safety
  checks; no dynamic arbitrary anchor inputs are permitted.
- Each anchor is a normalized image coordinate with the bottom-left corner
  as (0,0), x right and y up; e.g. upper-right is (2/3, 2/3).
- For the camera's local +X right and local +Y up vectors, move the camera by
  an opposite lateral offset proportional to the requested subject frame
  displacement. **Keep the optical orientation unchanged**.
- Select a *conservatively increased distance* when necessary, so the
  origin-centered subject bounding sphere plus margin stays inside the
  horizontal and vertical image boundaries with depth allowance.
- Verify new frame clearance against near/far clipping and 1,000,000-unit
  coordinate bounds. Reject unsupported existing lens shift (`shift_x/y`).

The projection is a **source-side mathematical model**, not real Blender
rendered visual verification. The subject origin and simple dimensions are
still an approximation of geometric bounds; deformed, off-center, evaluated
mesh and occluded subjects are not certified.

### Safety, rollback and limits

- Mutation requires strict typed fields, the same fresh camera/subject
  targets plus the exact `expected_composition_revision`.
- The composition revision incorporates the M1 plan revision, fixed anchor,
  camera lens, render aspect, scene camera selection, framing distance and
  target pose. Stale inputs fail before mutation.
- M1 and M2 share the same verified camera-pose mutation and rollback path
  rather than duplicating unguarded write logic.
- Existing animated, parented, constrained, linked, shared, locked or
  non-perspective camera restrictions remain in effect.
- Nine-anchor projection, center equivalence, safe framing, landscape/
  portrait, stale plans, invalid inputs, blockers, deliberate readback
  mismatch and interrupted-write recovery are fake-bpy regression-tested.

M2 increases factory and host typed tools from **227** to **229**.
Blender runtime acceptance: **0%**. Production ready: **No**.

## Milestone 3 — Bounded Orbit and Dolly Camera Animation (30% source-side)

M3 adds two typed tools for **real keyframe authoring in source-controlled
Blender adapters**, rather than merely motion recipes or proposal registries:

- `cinema.motion_preview` is nonmutating. Given an exact fresh camera and
  subject ObjectTarget, 4..720-frame duration, bounded start/end azimuth and
  elevation, framing margin, mode and optional active-camera choice, it returns
  three world-space camera poses at start/middle/end frames, expected clip
  clearance, and a deterministic `motion_revision`.
- `cinema.motion_apply` rechecks the complete plan and exact revision,
  creates a **new current-session camera Action** with 6 object transform
  FCurves (XYZ location and XYZ Euler rotation) and three distinct frame
  keys per curve (**18 keyframes**), sets LINEAR interpolation, performs
  readback, and either verifies or removes its newly created Action and
  restores the original camera pose.

Modes:
- `ORBIT`: subject-centered camera azimuth and elevation sweep, with
  0.5..60° maximum azimuth movement and up to 35° elevation change.
  Three planned camera orientations follow the target across start/mid/end.
- `DOLLY_IN`: camera moves from a farther point to the M1 safe baseline,
  at unchanged angle, with factor 1.1..2.0.
- `DOLLY_OUT`: inverse of DOLLY_IN, same angular orientation.

### Exact source-side boundaries

- Camera requires the exact M1 source safety rules: an editable, local,
  single-user, parentless, unconstrained, unanimated perspective camera in
  Object Mode, without transform locks or nonunit scale. Nonzero lens shifts
  are denied. Existing camera object Action/data animation are **never
  adopted or overwritten**.
- Three poses are calculated using existing M1 camera/subject optics and
  clipping checks, with a conservative bounding sphere at subject origin.
  Absolute pose and frame bounds are enforced; seam-crossing Euler yaw
  angles are unwrapped to prevent a spurious full turn.
- Only newly created **legacy/non-slotted** Action structures with six
  expected FCurves, three expected points per curve and single-user
  ownership are accepted for verified mutation. Unsupported/slotted
  structures fail closed. Modern layered Blender behavior needs separate
  runtime compatibility work.
- Mutation verifies every inserted key's frame/value/interpolation,
  unchanged subject revision, unchanged camera lens, end pose, active-camera
  selection, unchanged timeline frame and existence of the created Action.
  Failed verification or partial authoring attempts to clear only the new
  Action and restore the original pose and active camera. Recovery must be
  checked against the original object revision before being called verified.
- **Evaluated interpolation, intermediate actual Blender frames, ease
  curves, rendered camera motion and production compatibility remain
  untested**. Three keys represent a basic motion foundation, not a
  full tracking/cinematic-rail rig.

Registry/host cap: **231 typed tools** (two more than M2).
Tests cover ORBIT/DOLLY creation, 18 distinct actual source keyframes,
yaw continuity, stale plans, unsafe/foreign Actions, invalid requests,
post-mutation readback failure and partial insertion cleanup.
Real Blender runtime acceptance: **0%**. Production ready: **No**.

## Milestone 4 — Bounded cubic Bézier camera rail (40% source-side)

M4 adds two typed tools that use **one five-pose smooth-path approximation**,
without opening Blender or running arbitrary bpy scripts:

- `cinema.rail_preview` (READ_ONLY) receives fresh camera and distinct subject
  ObjectTargets, camera azimuth/elevation, margin, 8..720 frame duration, three
  2D image-plane handle offsets (`control_a`, `control_b`, `end_offset`)
  in [-0.25,0.25], and optional active-camera selection. Generates a cubic
  Bézier path with five samples at 0, .25, .5, .75, 1, deterministic pose
  data and exact `rail_revision` without mutation.
- `cinema.rail_apply` (MUTATION) requires the exact current
  `expected_rail_revision`, refuses unsafe/occupied camera Actions and calls
  the shared M3 verified, guarded Action authoring operation. Writes
  **six FCurves (XYZ location/rotation), five keyframes per channel, 30
  LINEAR keys**, with full readback and rollback on failure.

The path is generated in the camera's image plane and uses bounded control
points, a fixed camera orientation, pixel-corrected render aspect and
margin-adjusted distance to maintain approximate origin-centered
subject-sphere clearance. The planned subject screen position moves along
the Bézier curve; it is not a real rendered visual proof.

The final keyed motion is **piecewise LINEAR between five calculated samples**,
not a Blender native Curve modifier, not a true continuously evaluated cubic
Bézier animation. Additional path smoothing/easing, occlusion checks,
evaluated mesh bounding-box coverage and visual acceptance require later
separately authorized work.

Safety continues to require local, unanimated, single-user, parentless,
unconstrained, unlocked perspective camera without pre-existing Action
or nonzero lens shift. An Action is never adopted or overwritten. Failed
keyframe insertions, inconsistent Action identity/slotted behavior and
readback mismatch trigger best-effort cleanup of only the newly created
Action and exact pre-mutation object-revision recovery verification.
Runtime Blender compatibility has not been established.

Tests include 5 sample positions, projected subject screen offsets, 30
actual source/fake-bpy keypoints, strict validation, stale plan/lens/render
checks, shared/linked/animated Action refusal, partial-write failure and
verification rollback. Factory/public host cap: **233 typed tools**.
Real Blender runtime verification: **0%**; production ready: **No**.

## Milestone 5 — Eased camera motion and Bézier FCurve handles

M5 adds real source-side keyframe interpolation and handle authoring to the
existing bounded five-pose M4 rail, rather than another animation registry.

- `cinema.easing_preview` (READ_ONLY): accepts a validated M4 rail with
  style `EASE_IN`, `EASE_OUT` or `EASE_IN_OUT` and strength 0.25..1.
  Reparameterizes the cubic image-plane path at five bounded samples,
  computes analytic path and timing derivatives, and previews the target
  camera positions and **explicit LEFT/RIGHT BEZIER keyframe handles**.
- `cinema.easing_apply` (MUTATION): requires an exact current
  `expected_easing_revision`, fresh object targets and M4 camera safety
  checks, creates one new Action with six camera XYZ location/rotation FCurves,
  five keys per channel, **BEZIER interpolation and FREE handles** at all
  30 points. Verifies the exact frame/value/interpolation/handle types and
  coordinates against readback; restores original camera pose and removes
  only the newly created Action if any verification or authoring fails.

The three timing profiles blend with linear timing by `strength`:
EASE_IN progressively accelerates; EASE_OUT decelerates; EASE_IN_OUT does
both. At full strength, endpoint motion speed becomes zero on the
applicable endpoints. An analytic derivative of the planned image-plane
cubic path supplies the y slopes of Blender's FCurve handles, while
neighboring frame separations constrain the handle x coordinates.

M3 remains 18 LINEAR transform keys; M4 remains 30 LINEAR keys. M5
creates 30 BEZIER keys with separately verified handles. A camera must
have **no existing Action or animation**; linked/shared, constrained,
parented, locked, non-perspective or unsafe-camera cases remain blocked.
Subject framing bounds are still the M1-origin-centered approximation.
Interpolation **between** samples, evaluated frames, actual Blender
API compatibility, render output and visual smoothness remain untested.
No user-supplied Python or arbitrary bpy operators are introduced.

Registry/host cap: **235 typed tools**; Level 8 M1–M5 source-side 50%.
Real Blender runtime acceptance: **0%**. Production ready: **No**.

## Milestone 6 — Dynamic subject tracking via managed TRACK_TO constraint

M6 adds three typed public tools that connect a camera to a target Blender
object with a **real object-level constraint**, rather than calculating a
single static look-at rotation.

- `cinema.track_preview` (READ_ONLY): validates current-session camera and
  subject ObjectTargets, M1 azimuth/elevation framing/margin/activation,
  safe perspective lens/clip distance, empty camera constraint stack and
  unanimated local single-user camera. Also rejects subject-parent or direct
  constraint dependencies that would create a camera-target cycle. Reports
  exact deterministic tracking revision and blockers, without mutation.
- `cinema.track_apply` (MUTATION): requires exact
  `expected_tracking_revision`; sets the camera to the planned initial pose,
  creates **one object TRACK_TO constraint** targeting the subject, with
  `track_axis=TRACK_NEGATIVE_Z`, `up_axis=UP_Y`, influence=1, mute=False;
  optionally activates the scene camera. Verifies the new constraint's
  identity, target pointer, track axes, count, initial camera pose,
  unchanged subject and focal length. Rollback removes only the newly
  created constraint and restores the old pose/active camera, checking the
  original camera snapshot revision before declaring recovery.
- `cinema.track_release` (MUTATION): requires a fresh camera ObjectTarget
  and exact successful tracking token. It can only release the same
  constraint instance created by **this agent adapter in this runtime
  session**; it refuses nonowned, modified, stale or foreign constraints,
  verifies constraint removal and preserves the camera's current pose and
  active camera setting. If release is interrupted after removal, it
  recreates only the owned TRACK_TO constraint and verifies the original
  camera snapshot revision before reporting recovery.

When Blender evaluates the new TRACK_TO constraint, it is expected to
update the camera's *orientation* as the subject moves (including a
subject with existing animation). **It does not translate/physically chase
the target, keyframe its motion or guarantee the subject stays fully
within frame if it moves toward/away from the camera.** Continuous
depsgraph evaluation, rotation damping, focus/lens adjustments,
occlusion handling, animated render playback and actual visual
subject-follow performance remain **untested in real Blender**.

Safety: no existing camera constraint, camera animation or foreign
Action is modified; linked/shared/nonperspective/locked/parented camera,
lens-shift, invalid clipping and dependency cycles fail closed. The
release capability is deliberately **session-local**: if the adapter or
Blender project restarts, it cannot safely claim ownership of a saved
constraint and will not remove it. Restoration of manual edits made by
other tools is not attempted.

Source tests cover deterministic nonmutating planning; real fake-bpy
constraint new/remove; animated target pointers; current-camera pose;
stale changes, safety guards, target dependency loops; corrupted readback
rollback; interrupted updates and same-session release ownership.

Public typed tools / host cap: **238** (235 + 3).
Source-side Level 8 roadmap: **60%**.
Real Blender runtime acceptance: **0%**. Production ready: **No**.

## Milestone 7 — Camera translation follow and target aim (70% source-side)

Three new typed public operations, all grounded in exact current-session
camera/subject revisions and M6 safe initial framing:

- `cinema.follow_preview` (READ_ONLY): plans the world-space camera
  position for a subject-centered shot, then derives the camera's local
  offset vector `planned_world_camera - initial_subject_location`.
  Validates parent/constraint dependency cycles, safe perspective camera,
  no existing Action/constraint, clipping, lens shift and current scene
  state. Returns exact `follow_revision` and explicit safety blockers.
- `cinema.follow_apply` (MUTATION): rechecks the exact plan, places the
  camera object's stored location at the **relative offset**, then
  creates exactly two object constraints **in order**:
  `COPY_LOCATION` of subject with `use_offset=True`, all XYZ axes,
  no inversions, owner/target in WORLD space, followed by `TRACK_TO`
  the same subject with camera's local -Z and +Y up. Both use influence 1,
  mute=False. Verifies every constraint property and target identity,
  original subject revision, unchanged lens, camera raw position/rotation
  and optional scene-camera activation. On partial creation or a failed
  readback, removes only the new constraints and restores the original
  unmodified camera pose and activation with revision-confirmed rollback.
- `cinema.follow_release` (MUTATION): requires current camera target and
  session-specific `follow_token`; only releases the **exact two
  same-session owned constraints** if both still match their full
  readback. It restores the **pre-follow camera pose** and verifies exact
  constraint removal. If release is interrupted mid-way, it can reconstruct
  only these two original managed constraints and verify the same tracked
  revision; foreign constraints are never adopted or intentionally removed.

Under Blender's documented COPY_LOCATION offset mechanism, evaluated
position is expected to be `subject_world_location + stored_offset`.
This lets the camera **translate along with subject movement** while
TRACK_TO independently changes its direction to point at the subject.
It does **not** promise visual smoothness, collision avoidance, render
acceptance, damping, interpolation at animated frames or dynamic zoom.
M7 setup is not automatically layered on top of M6 tracking; a camera
with ANY existing constraint is deliberately refused. Parented targets
are also blocked because their local location cannot be treated as a
world-space origin for this initial-offset formulation.

IMPORTANT: This milestone is source/fake-bpy only. The fake fixture
checks exact Blender-shaped constraint properties and predicts camera
position mathematically; it does not evaluate Blender's dependency graph.
Blender version compatibility and evaluated world transforms require
actual runtime verification. Releasing after a moving subject has shifted
restores the **saved pre-follow pose**, not the camera's last evaluated
render pose, so an instantaneous jump is possible.

Factory/client tools: **241** (238 + 3).
Source completion Level 8 M1–M7: **70%**. Real Blender runtime
acceptance: **0%**. Production ready: **No**.

## Milestone 8 — Time-normalized baked camera follow damping (80% source-side)

M8 adds **real temporal smoothing of a pre-keyframed subject trajectory**,
not a fake "damping" switch on spatial constraints. Two public tools:

- `cinema.damped_preview` (READ_ONLY): accepts fresh camera/subject
  ObjectTargets, bounded M1 shot azimuth/elevation/margin, an EMA
  `damping_alpha` in [0.1, 0.9], and scene-camera activation choice.
  Reads an existing **single-user, legacy subject Action containing
  exclusively location X/Y/Z FCurves**. All three FCurves must have
  precisely matching integer frames, 5..24 keyed samples, LINEAR
  interpolation, increasing frames and maximum 60-frame gaps. Subject
  must have no parent/constraint, drivers, NLA, rotation or nonunit scale;
  scene frame and current subject pose must equal its first Action key.
  Preview computes target positions, a camera baseline offset and
  independently **time-normalized exponential moving average**:
  `alpha_eff = 1 - (1 - damping_alpha) ** elapsed_frames`;
  `filtered = filtered + alpha_eff * (target - filtered)`.
  Produces camera position from filtered target + baseline offset,
  calculates camera look-at rotation for the actual unsmoothed subject
  origin at each sample, checks clip/framing and bounds, and returns
  deterministic `damped_revision`. Preview changes no scene data.
- `cinema.damped_apply` (MUTATION): revalidates all input, current
  subject Action/scene revisions and exact preview token; if safe, uses
  the existing M3–M5 guarded Action writer to create fresh camera
  XYZ location and XYZ Euler rotation channels with **5..24
  sample poses, 30..144 LINEAR keyframes**. Verifies every keyframe
  frame/value/interpolation, active camera, unchanged subject/optics,
  created Action identity and final camera pose. On any partial write
  or readback discrepancy, clears only the new camera Action and
  checks restoration of original camera snapshot/active camera/frame.

This is **offline/baked, sampled damping**, useful for a subject with
known motion keys. It is not a runtime frame handler, physics-based
camera stabilizer, continuously re-evaluated spring, or automatic
tracking of later target edits. In-between camera frames are linearly
interpolated between baked keys; actual Blender evaluated transforms,
occlusions, render framing and visual quality remain unverified.

As in previous milestones, **real Blender runtime acceptance remains
0%, and production ready is No**. M8 adds exactly two public typed tools,
bringing the factory/host registry cap to **243**.

## Stop boundary

Levels 1–7 remain source-side complete. Level 8 M1–M8 are source-side
complete at **80%** only. Do not begin Level 8 M9, launch Blender,
render, conduct live Blender compatibility tests or integrate the main
Shuvi repository without separate explicit user permission.
