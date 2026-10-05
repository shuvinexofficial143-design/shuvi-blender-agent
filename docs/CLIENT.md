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
