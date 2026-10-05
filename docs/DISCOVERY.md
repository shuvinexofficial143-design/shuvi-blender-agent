# Installation discovery

Discovery checks explicitly configured paths (file or installation directory), PATH,
and shallow standard installation directories. Windows roots come from ProgramFiles,
ProgramW6432 and ProgramFiles(x86), under Blender Foundation. macOS bundles and Linux
PATH plus /opt are also supported; platform coverage still requires actual acceptance tests.

```powershell
shuvi-blender-agent discover
shuvi-blender-agent discover --path "C:\Custom Blender\blender.exe"
```

These commands inspect the filesystem only. `--probe-versions` explicitly executes each
candidate with `--version`, a bounded timeout, and no shell. No probe was run during
development. Unit tests inject mock probes. Failed probes are reported and excluded;
unknown versions are permitted in a path-only report but cannot satisfy a minimum-version
selection. Directory names are never trusted as proof of a version.

Selection order: configured path order, then PATH, then standard installations ordered
by detected semantic version descending and canonical path ascending. Duplicate paths
are removed; candidates and root children are capped, with a truncation flag. Missing
configured paths and probe errors are returned as structured issues. Installed=true means
an executable file candidate exists; it is not proof that Blender can launch.

Each root enumerates at most 4097 entries before sorting. Roots exceeding the configured
directory work limit (default/maximum 4096) are skipped with directory_work_limit and
truncated=true, avoiding nondeterministic partial selection. Version capture is capped
at 64 KiB and oversized output stops only the owned probe child. No runtime probe was
run during source hardening; tests inject fake process pipes.

Portable paths need --path or --root. Registry, Microsoft Store, Steam libraries, remote
machines, and running-process attachment are not implemented. No unrelated Blender
process is controlled or terminated by discovery.
