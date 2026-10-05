# Rendering and file checkpoints

Render execution requires allow_mutations, allow_file_writes AND allow_rendering explicitly
enabled by the host. All default false. No tool request can elevate these permissions.
LaunchConfig.output_directory must identify an existing directory for file writes.
Do not enable rendering or launch Blender until later user authorization.

render.configure: width/height 16..512, samples 1..16, expected_scene_revision. Sets Cycles
CPU, one fixed CPU thread, 100% resolution, RGBA8 PNG, then verifies actual settings.
render.execute: plain PNG name and fresh scene revision. Rejects non-CPU/unbounded settings
and missing camera. Temporarily sets output filepath, executes one still, then restores it.
No animation renders or GPU paths. Client deadlines cannot interrupt bpy mid-render; scene
complexity can still make a small render expensive. Closing the owned session can terminate
its process. No real render was run during development.

Outputs cannot overwrite existing files and stay directly inside the configured directory.
Names reject paths, traversal, Windows reserved names and invalid characters. Exclusive
reservation prevents ordinary overwrite races. Trusted local OS processes are outside this
boundary; this is not a filesystem security sandbox. Empty abandoned reservations are
removed; nonempty partial outputs are preserved for inspection. Verification reads at most
128 MiB. PNG checks signature, chunk lengths/CRCs, IHDR, IEND, bounded decompression,
pixel row lengths/filter tags, dimensions, RGBA8 format and SHA-256. It proves a structurally
valid bounded image was produced, not artistic correctness or intended scene appearance.

file.checkpoint: plain .blend name and fresh scene revision. Saves an uncompressed copy
using Blender's native save API, checks FINISHED, header/size/hash and preserved active
filepath. No overwrite, backup rotation or automatic checkpoint deletion. Header verification
is not proof that a saved scene can reopen; reopening and content acceptance remain runtime
tests. Restore by launching a new controlled session with LaunchConfig.blend_file set to a
checkpoint. No in-session file-open tool invalidates existing identities.

Unit tests use fixture PNG bytes and fake save/render operators, not Blender. Destructive
object deletion remains disabled pending runtime-verified recovery, even though source
checkpoint tooling now exists.
