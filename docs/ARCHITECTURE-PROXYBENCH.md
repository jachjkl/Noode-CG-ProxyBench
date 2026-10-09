# Architecture

Ubuntu prepares session-scoped candidates; the Windows desktop owns measurement; Ubuntu validates and publishes the result blob. Local measurement is independent of GitHub Runner heartbeats. Public immutable downloads use multiple mirrors and trusted SHA-256 metadata. Authenticated operations use official GitHub APIs without sending credentials to mirrors.

`MultiModeDashboard` routes proxy and direct controllers in one window. It serializes task starts so there is one active local workflow. Mode selection persists; each method has separate rule files, state directories, outputs and Chinese event logs. A shared window identity and cumulative candidate handoff prevent fixed-feed refetch when switching methods.

`Pipeline` manages screening, local batches, incumbent competition, ranking, replenishment and transactional output. `Benchmark` runs isolated authenticated candidate outbounds. `DirectBenchmark` adapts original TCP, TLS and speed probes without a profile or proxy core. Three direct samples are refreshed during final competition. Both pipelines execute current saved limits and configurable quotas; no above-limit result can pass.

Digest-verified checkpoint generations and partial-batch snapshots preserve measurements after stop/error/interruption. Normal closure removes only known transient state, retaining saved rules, profiles, outputs, tools and logs. `EventLog` writes bounded Chinese JSON-lines files with rotation. `RunClock` tracks optimization time separately from window lifetime.

Manual publication queues a request until the current batch completes, or starts one owned publisher when idle. Stop-and-save never queues publication. Explicit manual results may be partial; automatic publication requires full quotas. `proxybench_channel` rejects mixed namespaces and validates the entire allowlisted archive before writing any files. Proxy and direct output transactions preserve each other's last-good output. Failed cloud writes leave a mode-specific pending archive for retry.
