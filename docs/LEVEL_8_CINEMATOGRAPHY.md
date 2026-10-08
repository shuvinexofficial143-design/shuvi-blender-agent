# Level 8 — Cinematography

Level 8 follows completed Level 1–7 **source-only** roadmaps. None of the
camera framing functionality is certified by a real Blender session yet.

Current Level 8 source progress: **10%** (Milestone 1 of 10).
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

## Stop boundary

Level 8 M1 is the only authorized source expansion. Do not start M2,
real Blender runtime tests, rendering, or merge this into the main Shuvi
repository without explicit user permission.
