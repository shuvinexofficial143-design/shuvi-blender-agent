# Level 8 — Cinematography

Level 8 follows completed Level 1–7 **source-only** roadmaps. None of the
camera framing functionality is certified by a real Blender session yet.

Current Level 8 source progress: **40%** (Milestones 1–4 of 10).
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

## Stop boundary

Levels 1–7 remain source-side complete. Level 8 M1–M4 are source-side
complete at **40%** only. Do not begin Level 8 M5, launch Blender, render,
run live Blender compatibility checks or integrate the main Shuvi repository
without separate explicit user permission.
