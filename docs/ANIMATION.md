# Timeline and keyframes

animation.set_range accepts start/end (1..100000, span at most 10000) and a fresh scene
revision. animation.set_frame accepts frame and a fresh scene revision; the frame must
be inside the configured range. Both compare actual scene readback after mutation.

animation.insert_keyframe accepts target, frame, transform and interpolation (LINEAR,
BEZIER or CONSTANT). It inserts nine local transform channel keys and verifies their
stored coordinates/interpolation. New actions become owned by the session. Further keys
are allowed only on that session-created, unshared action; existing foreign actions,
drivers, NLA, constraints, linked/overridden targets and key overwrites are rejected.
At most 64 distinct keyed frames per action. Key insertion may alter current transform
channels; stored keys are verified separately from evaluated current-frame world pose.
Partial insertion failures require inspection; no transaction or automatic retry is promised.

Action readback uses legacy fcurves or the object's assigned slot/channelbag. The slotted
API was checked against Blender's [upgrade guide](https://developer.blender.org/docs/release_notes/4.4/upgrading/slotted_actions/)
and [5.0 API notes](https://developer.blender.org/docs/release_notes/5.0/python_api/).
Unsupported multi-layer/strip structures are reported as truncated metadata during
inspection, and are not edited. Bounded channel/key coordinates participate in revision
fingerprints. Real Blender action creation, interpolation and evaluation remain unverified.
