# Source hardening audit

This pass reviews every runtime module without importing bpy or executing Blender.
Regression tests verify the changed boundaries; CI and real runtime evidence remain separate.

| Modules | Reviewed boundary / resulting protection |
| --- | --- |
| validation, contracts, errors, verification | bounded finite JSON, Unicode, node/depth/byte limits, envelope fields/IDs/version, actual comparison |
| tools, safety, service, input_contracts | explicit parser/executor allowlist, initial/added registry bounds, policy checks, nonempty matching mutation evidence, host safety agreement |
| models, inspection, animation_state | session identities, stale revisions, continuation preconditions, sorted pages, streamed snapshots, collection/nested/byte/text bounds |
| operations, appearance, assets | preconditions/collisions/editability/shared data, geometry copy verification, newly created data cleanup, bounded modifier and collection work |
| animation, mesh | owned actions, prevalidated indices/frames, separate geometry revisions, loop checks before allocation, bounded readback |
| rendering, files | opt-in CPU/file policy, exclusive outputs, pinned root identities, reparse/hard-link refusal, streamed BLEND readback and bounded PNG decoding |
| client, plans | capability validation, local payload/safety contracts, destination preflight, overlap/forward/ID rejection, binding/payload/result budgets, partial/unknown outcomes |
| bridge, bootstrap, process | loopback/token/version/framing, concurrent call refusal, replay byte/command bounds, startup secret cleanup and owned process termination |
| discovery, CLI | no default execution, bounded enumeration before sorting, deterministic truncation, bounded optional version capture and process cleanup |
| runtime_acceptance | explicit authorization guard, factory startup, disposable files, injected fake testing and separate real runtime evidence |

## Limits that remain explicit

- Scene revisions cover bounded inspected metadata. They do not hash every Blender property;
  mesh edits use a separate geometry revision. Truncated object snapshots cannot authorize
  mutation. A scene scan is still required for fresh revisions; no complex cache was added.
- Blender operations may fail after partial state changes. Creation cleanup is verified where
  available; existing-object edits are not atomic transactions. Return errors/readback,
  inspect state and use fresh IDs/revisions before recovery. Never retry mutations implicitly.
- A 1 MiB protocol ceiling and 65536-node work bound can reject a theoretically valid largest
  geometry/result combination. These are aggregate ceilings in addition to per-field limits.
- Deadlines bound transport waits and sequencing. They cannot preempt bpy evaluation or set
  a strict OS/process memory ceiling. Source geometry/modifier caps are conservative gates,
  not proof that every bounded mesh can be evaluated cheaply.
- Output identity and link checks cover ordinary path replacements before/after operations.
  The local OS account and executable remain trusted; these checks are not a security sandbox
  against an adversary racing directory/file replacement during Blender's own write calls.
- BLEND verification checks uncompressed header, size and hash, not parse/reopen/recovery.
  PNG verification checks structure/decompression/dimensions, not desired visual content.
- The owned direct child handle is cleaned up. Real Blender worker/process-tree behavior
  needs OS-specific acceptance; no unrelated Blender process is located or terminated.
- Version probing remains explicitly opt-in, with bounded captured output. Filesystem probes
  can be slow on an explicitly configured remote/unresponsive filesystem; directory names
  alone never establish a Blender version.

Windows device-name handling follows Microsoft's
[file naming documentation](https://learn.microsoft.com/en-us/windows/desktop/fileio/naming-a-file),
including superscript digits in COM/LPT names. Reparse-point tests depend on account support;
the local symlink creation test can skip, while Linux CI covers that path.

Source audit completion does not establish production readiness. See
[runtime acceptance](RUNTIME_ACCEPTANCE.md) for remaining real-Blender and recovery checks.
