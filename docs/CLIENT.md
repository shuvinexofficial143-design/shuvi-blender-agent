# Host client and declarative plans

BlenderController accepts a transport with call(Request)->Result. BlenderClient is the
authenticated socket implementation. The controller fetches system.capabilities, checks
advertised operation/policy, correlates both IDs and independently compares mutation
verification evidence. Typed action dataclasses can be sent with submit(operation, action);
convenience methods cover scene/object inspection, creation and transforms. Execution
parsers always revalidate. Capability enabled means policy permission, not production
runtime verification, scene compatibility or output workspace availability.

```python
from shuvi_blender_agent.client import BlenderController
from shuvi_blender_agent.models import ObjectTarget, Transform

# session comes from an explicitly authorized controlled launch.
controller = BlenderController(session.client)
snapshot = controller.list_objects().data["items"][0]
result = controller.set_transform(
    ObjectTarget.from_snapshot(snapshot),
    Transform((1, 2, 3), (0, 0, 0), (1, 1, 1)),
)
assert result.status.value == "verified"
```

PlanRunner runs 1..32 named requests under one bounded total deadline. Bindings can copy
JSON values from earlier step result paths into existing payload fields. Paths have at
most 8 string/index components; each step has at most 16 bindings. No eval, templates,
Python callbacks, arbitrary attribute resolution or policy elevation. Operation/policy
preflight happens before any step, and each bound request undergoes normal tool validation.
Forward references, duplicate step names/command IDs and unknown references fail. Request
and command IDs remain separate. Plan input is capped by the normal 1 MiB JSON ceiling.

Plans stop on first failure and never automatically retry. They are sequential workflows,
not transactions: completed mutations remain applied if a later step fails. A timeout may
leave the last command's outcome unknown. Inspect/recover; do not blindly replay a plan.
Provider-specific AI planning remains in main Shuvi. This repository contains deterministic
execution/orchestration only; no frontend, provider SDK, auth or billing is duplicated.

## Stable external interface

| Main Shuvi action | Interface | Behavior |
| --- | --- | --- |
| discover | discovery.discover(DiscoveryConfig) | filesystem only by default; candidates/issues/truncated |
| optional version probe | discovery.probe_version(path, timeout_ms) | explicitly executes --version; only after authorization |
| start session | process.launch(LaunchConfig) | owned background child, loopback auth/ping; BlenderSession/context manager |
| capabilities | BlenderController(session.client).capabilities() | validated catalog keyed by name; safety/policy/stable metadata |
| execute tool | controller.execute(Request) or submit(operation, action) | validates payload/safety, correlates response, compares mutation evidence |
| execute plan | PlanRunner(controller).run(Plan) | bounded sequential declarative execution with bindings |
| shutdown | session.close() or context-manager exit | closes transport; confirms/terminates only owned child |
| errors | AgentError / failed Result | stable ErrorCode, sanitized message, no automatic mutation retry |

Normal imports require no Blender installation or bpy. Main Shuvi stores model/provider/user
authorization state and calls startup explicitly. LaunchConfig fixes the session policy and
optional output workspace. Construct a new controller for each session; cached capabilities
are session-local and cannot elevate policy.

Catalog classification must agree with the host's local 23-tool allowlist. Stable boolean
metadata (verification/runtime/file/render requirements) is validated and exposed, along
with payload_fields where available. Custom parser fields may be null. Missing optional
metadata derives from local contracts; unknown tools/safety disagreement fail closed.
Consult TOOL_REFERENCE.md for field constraints and structured result shapes.

Operation/policy and capability failures during preflight raise AgentError before step
execution. Invalid unbound plan payloads and invalid/overlapping destination paths also
fail before any step. Bound values are validated when available, before that step dispatch;
future Blender result values and scene preconditions cannot all be checked during preflight.
Completed mutations remain applied if a later step fails.

Transport failures after dispatch return failed correlated results with outcome=unknown
and inspect_before_retry=true. PlanReport preserves earlier results, lists unexecuted_steps
and exposes outcome_unknown. A deadline exceeded after a complete response reports
outcome=known and completed_status and stops the plan. No new request is sent after a
pre-dispatch deadline or result-budget failure.

Plan limits additionally include unique request IDs, 256 total bindings and 4 MiB aggregate
serialized result bytes. A full 1 MiB response slot is reserved before every dispatch;
the runner can stop conservatively before that budget is exhausted. Reports are host-side
data, not bridge frames. Input retains the 1 MiB/65536-node aggregate ceiling. Binding paths
index JSON dict/list values only; no attributes, methods, expressions, loops or parallelism.
Runtime acceptance remains outstanding.
