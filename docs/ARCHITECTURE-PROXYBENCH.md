# Architecture

Ubuntu prepares session-scoped candidates; the Windows desktop owns measurement; Ubuntu validates and publishes the result blob. Local measurement is independent of GitHub Runner heartbeats. Public immutable downloads use multiple mirrors and trusted SHA-256 metadata. Authenticated operations use official GitHub APIs without sending credentials to mirrors.

`MultiModeDashboard` routes proxy and direct controllers in one window. It serializes task starts so there is one active local workflow. Mode selection persists; each method has separate rule files, state directories, outputs and Chinese event logs. A shared window identity and cumulative candidate handoff prevent fixed-feed refetch when switching methods.

`Pipeline` manages full-pool local batches, incumbent competition, ranking, replenishment and transactional output. `Benchmark` runs isolated authenticated candidate outbounds. `DirectBenchmark` adapts original TCP, TLS and speed probes without a profile or proxy core. Three direct samples are refreshed during final competition. Both pipelines execute current saved limits and configurable quotas; no above-limit result can pass.

Digest-verified checkpoint generations and partial-batch snapshots preserve measurements after stop/error/interruption. Normal closure removes only known transient state, retaining saved rules, profiles, outputs, tools and logs. `EventLog` writes bounded Chinese JSON-lines files with rotation. `RunClock` tracks optimization time separately from window lifetime.

Manual publication queues a request until the current batch completes, or starts one owned publisher when idle. Stop-and-save never queues publication. Explicit manual results may be partial; automatic publication requires full quotas. `proxybench_channel` rejects mixed namespaces and validates the entire allowlisted archive before writing any files. Proxy and direct output transactions preserve each other's last-good output. Failed cloud writes leave a mode-specific pending archive for retry.

## Full-pool batching and version review (1.2.4)

`Pipeline` orders acquired candidates without probing or excluding them. Its fixed 300-IP scan commits qualified records and address-only processed outcomes after each completed batch. The next batch excludes only addresses that already completed actual measurement, including journal-recovered failures. Publication quotas cannot end the scan. Failed result bodies are compacted without losing counts or resumability. The owned Mihomo core can load 300 independent loopback-only named listeners and unload them between batches; direct measurements remain independent of the core.

`MultiModeDashboard` asynchronously reviews official stable core updates on window opening and exposes a shared current/previous version menu. Both run paths recheck before measurement. `MihomoManager` verifies official downloads, retains only two binary slots, supports validated rollback and preserves a selected historical version until automatic updates are selected again. The installer preserves existing core slots and selection metadata during application upgrades.


## Single-round batches and progress (1.2.5)

`BATCH_SIZE` is now 100 for both methods. `Benchmark` visits each site exactly once through `Controller.site_probe`, averages three observations without trimming, and records failure even when earlier sites failed. The former warmup/repeated `site_samples` path is removed. `SocketDeadline` aborts stalled peer transports, while route-proof calls share the current request's deadline. Legacy jitter/cooldown options are retired rather than exposed as unenforceable one-round settings.

`Pipeline` exposes compact current-batch node states and completion counts, commits a visible cleanup phase, then resets that visualization before the next batch. `Observation` interleaves previews with its ordered durable completion queue. `BenchDashboard` caches verified immutable checkpoint views and omits unused full preview records from state responses. Browser requests have a finite abort deadline and automatically reconnect; the actual measurement process remains independent. Repair artifacts are produced within the repository; the user-supplied installed directory is used only for read-only diagnosis.

## Honeycomb and operation layout (1.2.6)

The dashboard renders the same batch state as staggered, point-up hexagons, with 20 columns on wide windows and 10 on narrow ones. Each cell has an address/status label and tooltip; completion symbols provide a cue beyond color. Unchanged previews reuse existing cells, and changed outcomes update those cells in place. Cleanup removes the current cells and resets the existing progress counter. The operation toolbar groups launch, playback and output controls without changing API actions. CSS controls responsive wrapping, active-cell motion and reduced-motion handling; backend measurement rules are unchanged.


## Continuous requests and live qualification (1.2.7)

`Benchmark.batch` queues all three site work items per candidate and refills available request slots as soon as any request finishes. The saved request concurrency is a global request limit, not a multiplied per-site limit. All three results are required before the existing calculator accepts or rejects the candidate. Download concurrency remains unchanged; successful downloads hand off to a separate bounded location executor. Pending location records are explicitly unqualified and carry no completed timestamp. Ordered persistence and cleanup still finish before the next 100-IP batch.

The `qualified-results` dashboard action filters fully finished `Qualified` records after reapplying current saved limits, then sorts them with the normal ranking key before independent 300-row pagination. Historical or in-flight passes cannot populate this view prematurely. The native core dialog renders both retained version slots while measurement is active, explains why switching is disabled, and uses `core-check` to review updates without resetting a pinned rollback choice. Explicitly selecting automatic updates still clears that choice.
