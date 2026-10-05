# Architecture and trust boundaries

`contracts` defines strict versioned request/result envelopes with separate request and
command IDs, bounded timeouts, structured errors, and finite JSON data. `tools` dispatches
only registered operations and rejects unknown payload fields using typed parsers.
`safety` supplies fail-closed policy and stale-state checks. No source-side import depends
on `bpy`. Blender-specific adapters will import it only inside Blender.

The caller chooses an operation; the executor validates its typed payload. AI planning
cannot bypass validation, policy, object identity, revision checks, or readback comparison.
Read-only success means data was obtained. Mutation success requires `verified` with
matching readback evidence. Command delivery alone is never success. A bridge must
correlate both IDs and enforce deadlines; a timeout after mutation means outcome is
unknown, so clients must inspect before deciding what to do next. Never blindly retry
mutations. Request/command IDs alone do not provide persistent exactly-once execution.

## Development layers

1. Packaging, contracts, safety, errors, tests and documentation.
2. Installation discovery with deterministic selection and injectable version probing.
3. Controlled launch and versioned local communication; no arbitrary-code endpoint.
4. Bounded scene/object inspection.
5. Object identity, stale checks, safe creation/transforms and actual readback.
6. Materials, cameras and lights.
7. Modifiers, collections and assets.
8. Animation.
9. Rendering and verified outputs.
10. Advanced meshes.
11. Planning/tool orchestration.
12. Authorized real Blender acceptance tests.
13. Main Shuvi integration contract.

Each layer must be useful and tested before expansion. Future modules are not empty
placeholders. Production runtime capability requires authorized real Blender testing.

## Testing and checkpoints

Unit tests run without Blender. CI checks supported host Python versions on Windows and
Linux, formatting, linting, tests, and distributions. Mock tests validate contracts and
algorithms but cannot establish Blender runtime compatibility. Do not install Blender,
launch sessions, or render without later explicit authorization.

Before each logical checkpoint, test, update CODEX_HANDOFF, fetch the latest remote,
and push without force. The handoff records the preceding pushed SHA because the current
commit cannot embed its own content-derived SHA; `git log -1` resolves the current tip.
