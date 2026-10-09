# Level 11 — Tracking, Matchmove & Green Screen

Source milestone: **10%** (M1/10). Blender runtime verification: **0%**. Production: No.

## M1 — Existing MovieClip tracking inspection
The allowlisted read-only `tracking.clip_inspect` takes an exact, already-loaded Blender MovieClip name, its tracking object name, and 1–16 sorted unique sample frames. It inspects the actual Blender MovieTrackingObject tracks and uses `MovieTrackingMarkers.find_frame(frame, exact=True)` to read real coordinates, keyed/mute status and lock flags (max 64 tracks). It also reports clip pixel dimensions/duration, without file paths. It never loads a clip, runs Blender tracking, solves camera movement, touches external files, changes any tracking data, or renders. Full runtime acceptance is not demonstrated. M2 will add reversible manual marker placement to an existing track; green screen and actual matchmove solve remain future milestones.
