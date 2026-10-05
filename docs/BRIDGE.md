# Controlled background bridge

The host explicitly calls launch(LaunchConfig(...)); import and discovery never launch
Blender. Startup uses factory settings, disables file auto-execution, and runs only our
packaged bootstrap. An optional existing .blend file is opened before bootstrap. Paths
are separate subprocess arguments, never a shell command. See the official
[command-line manual](https://docs.blender.org/manual/en/5.1/advanced/command_line/arguments.html).

The host binds a loopback ephemeral port. The child connects and authenticates with a
random 256-bit session token passed in its environment. No listening Blender port is
exposed to the network. Treat the local OS user and launched executable as trusted;
this is not a security sandbox against malicious local processes or malicious .blend
parser inputs. Disabling auto-exec blocks normal embedded scripts, not all Blender bugs.
All bridge peers are checked for loopback addresses. Bootstrap consumes secrets/settings
before importing bpy, including configuration validation failures.

Frames have a 4-byte big-endian length and a 1 MiB limit. Send/receive enforce one monotonic
deadline even with fragmented or trickled messages. Responses must match both IDs. A
readiness ping roundtrip is required before the launch function returns. Startup failure
cleans up only the owned child handle. Closing a session disconnects, waits briefly, then
terminates/kills only that child if necessary. stdout/stderr are discarded to avoid pipe
deadlocks; richer bounded diagnostics remain future work.

The background bootstrap executes dispatch on Blender's main thread. No thread touches
bpy; see [Blender threading guidance](https://docs.blender.org/api/main/info_gotchas_threading.html).
GUI attachment and timer integration are not implemented. Connections have a 120-second
idle deadline and should be kept alive with explicit ping calls when needed. One client
owner, one in-flight request; do not share the client concurrently.
Concurrent calls are explicitly denied without corrupting the existing request.

Session command IDs are guarded against changed payloads and repeat execution. A bounded
cache can return the original result; expired IDs fail closed. The session stops accepting
new commands after 4096 unique IDs. Restart loses that history, so never blindly retry a
mutation after disconnect or timeout. A timeout may mean the operation completed; inspect
actual state in a new session before recovery. bpy calls cannot be safely interrupted mid
execution; deadlines bound the client's wait, not Blender CPU use. No long-running tools
are enabled at this layer.
The serialized cache is capped at 4 MiB and 256 responses; both request and command IDs
are guarded against inappropriate reuse. Deadline failure responses are cached consistently
with the first delivered result. Structured cleanup failure means owned-child exit could
not be confirmed and must be inspected before recovery.

Source tests use real ordinary Python sockets and fake Popen handles. They do not launch
Blender and do not establish runtime compatibility. All real Blender launches remain
subject to later explicit user authorization.
