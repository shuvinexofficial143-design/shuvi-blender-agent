# Future Blender acceptance (not performed)

## Current evidence

| Level | Status |
| --- | --- |
| Source implemented | 91 bounded typed tools; Level 1 and current Level 2 source roadmaps complete, host client, declarative plans and acceptance harness |
| Unit tested | Source contracts, fake bpy adapters, Python sockets and injected owned process handles |
| CI tested | Linux/Windows, Python 3.11/3.12/3.13; status recorded in CODEX_HANDOFF.md |
| Real Blender runtime tested | No; 0% |
| Production ready | No |

The acceptance module is prepared and tested only with injected fake sessions. No Blender
installation, --version probe, background/GUI launch, bpy runtime or real render has been
performed. Passing fake tests does not establish Blender API compatibility.

## Authorization and isolation

Only run these commands after the user explicitly authorizes real runtime testing.
No-argument invocation is safe preparation: it prints a prepared status and exits without
executing Blender. The actual suite requires both --authorize-runtime and an executable.
Rendering is a separate --allow-render opt-in. Destructive delete/checkpoint-reopen cases are a separate --allow-destructive opt-in. Level 2 professional-modeling acceptance cases are a separate --allow-level2-modeling opt-in. Do not install Blender automatically.

```powershell
# Safe preparation only; no Blender execution.
python -m shuvi_blender_agent.runtime_acceptance

# Future command: run only after explicit runtime authorization.
python -m shuvi_blender_agent.runtime_acceptance --authorize-runtime `
  --executable "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" `
  --report acceptance-4.2.json

# Future render acceptance: requires explicit render authorization too.
python -m shuvi_blender_agent.runtime_acceptance --authorize-runtime --allow-render `
  --executable "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" `
  --report acceptance-4.2-render.json

# Future Level 2 modeling acceptance: separately opt into modeling mutation cases.
python -m shuvi_blender_agent.runtime_acceptance --authorize-runtime --allow-level2-modeling `
  --executable "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" `
  --report acceptance-4.2-level2.json
```

The suite uses factory startup, no existing .blend input, disabled auto-execution and a
new temporary output workspace. Names are prefixed Acceptance. Outputs are disposable
and removed after the owned child is closed; JSON evidence goes to a separate explicitly
chosen new report file, never overwriting one. No GUI attachment or user project is used.
The suite has a 120-second execution budget and bounded per-command deadlines; cleanup
has its own bounded waits. Running bpy calls are not interruptible and can outlive a client
deadline; stop only the owned child, retain/report failure, and inspect cleanup before retry.

## Automatic acceptance cases

- [ ] Filesystem discovery selects the explicit executable; --version identifies Blender 4.2+.
- [ ] Factory background launch, ephemeral loopback authentication and readiness ping succeed.
- [ ] Running version agrees with minimum requirement; capabilities match host allowlist.
- [ ] Scene, object and collection inspection provide bounded correlated data and fresh revisions.
- [ ] Cube, plane and empty creation verify geometry/membership; duplicate has separate mesh.
- [ ] Transform channels read back within tolerance; material properties/assignment match.
- [ ] Perspective camera and POINT/SUN/SPOT/AREA lights verify requested properties.
- [ ] Single bounded BEVEL modifier verifies settings; collection adds membership safely.
- [ ] Local asset mark, frame range/selection and nine transform keyframes verify.
- [ ] Curve/Text creation and bounded shape readback verify.
- [ ] Selected/active mesh enters Edit mode and returns to Object mode with verified context.
- [ ] Camera/light bounded update readback verifies.
- [ ] Triangle creation, inspection and explicit vertex translation verify geometry.
- [ ] Origin-to-centroid and complete object-transform bake verify resulting geometry/object state.
- [ ] CPU render configuration is 16x16, one sample, one thread, PNG/RGBA/8-bit.
- [ ] Checkpoint file has bounded size/hash/header and does not change active source path.
- [ ] When separately authorized for destructive cases, object deletion verifies absence and
  reopening the confined checkpoint replaces the project and rotates the session identity.
- [ ] When separately authorized, one tiny render verifies PNG structure/dimensions/hash.
- [ ] When separately authorized for Level 2 modeling, a disposable repair mesh exercises
  topology/shading/retopology inspection, aggregate modeling QA, workflow preview/apply,
  modifier recipe preview/apply and final stack diagnostics with verified readback.
- [ ] A small declarative plan succeeds with correlated results.
- [ ] Session closes; owned child has exited; temporary workspace is removed.

## Additional manual acceptance before production

- [ ] Execute Linux/Windows builds with Blender 4.2 LTS and each additional supported release;
  record exact Blender/Python versions, executable source, OS and tested Git commit.
- [ ] Check legacy and slotted actions, evaluated transforms, parented objects, shared mesh
  and material behavior, linked/overridden data and readback after dependency graph update.
- [ ] Confirm stale revisions and renamed/removed/replaced IDs fail on real Blender objects,
  including undo/replacement and independent edits in an owned test scene.
- [ ] Exercise bounded large scenes, animation/detail truncation, byte/work denial and filtered
  continuation pages. Same-size collection membership changes must invalidate pages.
- [ ] Test malformed/version-mismatched/duplicate packets, slow/truncated/disconnected frames,
  expired replay entries, delayed readback and unknown outcomes without mutation replay.
- [ ] Test output refusal for existing files, Windows device/UNC/traversal names, junctions,
  hard links and replaced directories, including cleanup after partial write failures.
- [ ] Reopen the produced checkpoint in a second owned background test session and independently
  verify expected scene content. Header/hash checks alone do not establish recoverability.
- [ ] Visually inspect the tiny render in the isolated project; structural validity does not
  prove image content. Collect bounded timing/memory observations on authorized workloads.
- [ ] Verify source/wheel/sdist imports and bootstrap from a clean install without host bpy.
- [ ] Confirm startup errors, worker/child cleanup and exit state under real OS process behavior.
- [ ] Define supported-version policy and pass all required cases before changing readiness.

Keep raw sanitized JSON reports outside the disposable workspace. Record each case as
pass/fail/skipped with reason; a skipped case is not a pass. The harness marks real_runtime_verified
only for its real default launcher/probe with completed suite and confirmed cleanup; injected
unit sessions cannot mark it true. A successful smoke suite does not grant production readiness.


## Level 2 acceptance boundary

The `--allow-level2-modeling` path is prepared in source and covered by injected fake-session
tests only. It creates a disposable bounded mesh with controlled repair candidates, inspects
Level 2 topology/shading/retopology state, runs `modeling.qa_inspect`, previews and applies
`CLEAN_BASE_MESH`, then applies a small typed modifier recipe and diagnoses the resulting
stack.

Until that exact path is run using the real launcher and real Blender 4.2+ executable after
explicit authorization, Level 2 real-runtime verification remains 0%. Fake sessions, CI and
source readback algorithms are not substitutes for Blender dependency-graph, modifier,
Shrinkwrap or mesh-runtime acceptance.
