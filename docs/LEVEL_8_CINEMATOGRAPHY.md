# Level 8 — Cinematography

Level 8 follows completed Level 1–7 **source-only** roadmaps. None of the
camera framing functionality is certified by a real Blender session yet.

Current Level 8 source progress: **20%** (Milestones 1–2 of 10).
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

## Stop boundary

Levels 1–7 remain source-only complete. Level 8 M1–M2 are source-side complete
at **20%**. Do not begin Level 8 M3, launch Blender, render, perform real runtime
acceptance or integrate the master Shuvi repo without separate user approval.
