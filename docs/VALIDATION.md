# Validation evidence and current limits

## Automated validation

The version 1.0.1 suite contains 219 passing tests. Windows and Ubuntu GitHub CI pass. Coverage includes immutable authenticated profiles, 100 independently named proxy nodes, 900 fixture-based site probes, source diversity and exclusions, checkpoint recovery, 300-row paging, incumbent admission, removal of failed retest qualification, continuous replenishment, candidate queue preservation, strict 100+10 publication, digest-checked control-channel payloads, and last-successful-output protection.

Windows installation smoke tests verify public packages contain no real profile, private packages contain the authorized local profile, embedded Python validates configuration, reinstallation preserves that profile, and active run locks refuse replacement. Browser tests verify 21,537 real cloud candidates across 72 pages, 300 rows per full page, 237 rows on the last page, eight summary columns, a Chinese detail dialog, and no JavaScript errors or page overflow.

## Real cloud discovery

- [First cloud-to-Windows run](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37592642410): 11,374 first-feed IPs, 184 second-feed IPs, 10,000 official samples, and 19 Japanese hints; 21,537 unique merged candidates. Cloud preparation and trusted download passed. Local bandwidth acceptance failed.
- [Second discovery-only round](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37594439125): 10,000 new official IPs, no fixed-feed fetch, zero overlap with all prior IPs.
- [Third discovery-only round](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37594482456): another 10,000 new official IPs, no fixed-feed fetch, zero overlap with all prior IPs.

The three rounds total 41,537 unique IPs. The second and third runs deliberately exercised cloud discovery only; they are not evidence of successful local bandwidth measurement or publication.

## Real proxy measurements

Official Mihomo v1.19.32 was exercised in isolated rule mode with the actual locally imported VLESS/WebSocket/TLS configuration. A real batch loaded 100 independent nodes and completed 900 site probes across three rounds; nine candidates completed all nine site requests. Named-outbound and connection-chain evidence was collected. This did not unlock the formal bandwidth gate.

The available current profile can complete some site traffic but fails the required Cloudflare bandwidth transfers. Another discovered configuration and bounded relay-path trials did not resolve that failure. No fictitious bandwidth, direct-network substitution, or simulated passing IP set was published.

Cloudflare [documents restrictions on outbound TCP connections to its own IP ranges](https://developers.cloudflare.com/workers/runtime-apis/tcp-sockets/). This may be relevant to a Worker's forwarding path, but the exact deployed Worker failure cannot be established without its server-side configuration and logs.

## Remaining acceptance work

The earlier 1/10/100 bandwidth gate was removed at the owner's request in version 1.0.1. Initialization verifies the isolated rule-mode core and independent node loading. Network speed now uses the original local package's one-sample 512 KiB algorithm through the selected candidate proxy. Failure rejects that candidate rather than preventing the entire scan. A completed real 110-node publication is still unverified; candidate preservation and last-successful-output protection remain in force.

This implementation writes only to the independent repository. The owner's later README edits in the original repository are preserved. The owner's 12 repositories were audited for write collaborators, pending write invitations, and write-enabled deploy keys; no additional account had write access. Only public source and IP metadata are published here. Real profile credentials remain local.

The [installed personal-package workflow](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37608093535) also exercised the actual pythonw frontend, console-backed runner commands, owner authentication, cloud discovery, mirrored download, and queue persistence. It retained 21,538 candidates and served 300 records per page. It correctly stopped at the real bandwidth acceptance failure; no 110-node publication was claimed.

## Version 1.0.1 regression checks

Coverage verifies the original 95% completion threshold, named-proxy CONNECT and HTTP Host, body-only timing, rejection of timeouts even after receiving 95%, continued testing after an individual speed failure, old-preset migration, and successful core initialization with no separate speed request. Historical failed bandwidth acceptance above describes version 1.0.0, not a prerequisite of version 1.0.1.

A controlled TLS origin and HTTP proxy fixture exercised the real Mihomo v1.19.32 core. The speed request preserved HTTP/1.1, the Cloudflare Host and SNI, received all 524,288 bytes, and recorded the selected proxy plus the InName rule in the actual core connection chain. This fixture verifies the transport and timing implementation; it is not Internet speed or a qualified public candidate. The installed local Worker profile was also tested at three edge IPs with the new 512 KiB method; its speed endpoint connections still failed. The updated rule-mode core check nevertheless loaded 1, 10, and 100 nodes successfully, issued no separate speed request, and selected the working Cloudflare trace fallback. These upstream speed failures remain per-IP failures during selection.

A bounded real pipeline scan also completed 18 site probes for two candidates while its saved historical bandwidth acceptance flag was false. It returned an insufficient-results report after measuring both candidates, preserved successful outputs, and did not publish an unqualified set. This verifies that the former gate no longer stops candidate selection; it is not a completed large-pool or 110-node run.

## Version 1.0.2 output and maintenance checks

The suite contains 226 passing tests. Additional checks cover the exact `82.139.242.5:443#DE` text format, local-to-cloud text/order preservation, rejection of missing or inconsistent output text, Git-free source packaging, excluded private state, maintenance-archive inventory hashes, and the explicit build-cache allowlist.

Browser checks confirm 30 moving background particles, 32 decorative particles on the hovered card, a visibly changing fluorescent selected-button effect, 300-row paging, no JavaScript errors, no desktop/mobile overflow, and reduced-motion handling. Repair-workspace preparation has been exercised with embedded Python and no Git checkout, and repeated preparation preserves source edits. The combined maintenance package contains both cloud source and local Windows packages; the personal variant remains local to the project directory.

## Version 1.1.0 measured performance

The user's recorded 1.0.2 run contained 1200 measured candidates. Of these, 619 completed all nine site requests but were rejected by the former 200 ms end-to-end threshold; their best mean was approximately 685 ms. This was a threshold/model problem, not evidence that every candidate was unusable.

The corrected implementation screened 21,538 real saved candidate addresses in 128.875 seconds, retaining 1028 entries under the 200 ms local TCP limit. A separate 100-address screen took 1.218 seconds. A bounded 20-candidate authenticated proxy retest took 34.25 seconds and produced nine qualified candidates using production speed/site thresholds. Successful speed transfers retained named-candidate InName connection-chain evidence and never used DIRECT. This bounded test omitted exit-geography queries, so it is not evidence of a Japanese append set or complete 110-node publication.

One independently exercised candidate measured approximately 110 ms at entry, 682 ms for a proxied Google request, and 7.583 Mbps for the 512 KiB download sample. A Cloudflare-range candidate also completed the alternative speed sample at 4.496 Mbps. These measurements use the owner's actual VLESS/WebSocket/TLS profile.

There are 232 passing automated tests, including early rejection, separate entry/proxy response criteria, per-candidate listeners, preserved partial results, and reduced dashboard writes. The default Windows installation directory is beside the EXE; an explicit adjacent-install check is available for package verification.


## Version 1.1.1 Clash timing and workflow checks

The active Clash configuration uses unified delay and an HTTP gstatic 204 endpoint. A same-profile comparison on four screenshot nodes confirmed the difference: XX 10 measured 735 ms including connection establishment and 82 ms with unified delay. The production core now enables the same timing mode, while retaining authenticated three-site success checks. TCP entry timing above 200 ms only affects priority; reachable slower candidates are preserved.

A bounded real test screened 206 existing same-profile candidates in 1.283 seconds, retaining 191 reachable entries, including entries outside the 200 ms preference. It then measured 100 independent proxy nodes in 95.538 seconds: 85 completed all nine reported site observations and 76 passed both response and original-package speed criteria. Successful speed routes were verified from actual InName connection chains with the exact candidate and no DIRECT. Exit-geography queries were deliberately omitted, so these results do not establish ten Japanese exits or a completed 110-node publication.

All 238 automated tests pass. Workflow regressions cover stale-run isolation, verified download completion, paused retesting, GitHub confirmation before final completion, insufficient-result waiting, and retention/reset of cloud job evidence. Browser state fixtures verify the five-step fluorescent-yellow gradient, animated silver-white sweep, moving completion particles, current/pause/failure states, 12 px module spacing, responsive layout, and reduced-motion behavior. Those fixtures demonstrate interface behavior, not actual network qualification or publication.

The EXE installs beside itself. PowerShell helper defaults also stay beside their scripts, with no hard-coded Desktop installation path. The original decorative particles and selected-button animation remain enabled.


## Version 1.1.2 monitoring, live display, and lifecycle

The reported installation logged two failures to identify newly dispatched runs, while an owned local child continued measuring. Before stopping that child at a checkpoint, the actual saved run contained 21,538 candidates, 1,000 proxy-tested entries, and 441 qualified results. The orphaned child was asked to stop through the normal control checkpoint, and the duplicate queued workflow was cancelled. Existing measurements were retained. This incident is not a completed 110-node publication.

Dispatch now matches a unique request identifier rather than comparing server timestamps to the Windows clock. Monitoring retries transient API errors and retains job evidence. The local core ownership check prevents duplicate starts and allows the live phase to drive the dashboard during delayed or missing cloud metadata. Regression cases include shifted server timestamps, unrelated concurrent dispatches, monitor retry, and the exact lost-monitor/local-running condition.

The UI has independent candidate and live-result panes. In-flight site observations and partial batch results appear before full-batch checkpoint commits; TCP-only rejections remain in the candidate pane. Browser replay verifies both panes at 300 rows, independent page navigation, a 50-row last result page, live response changes, correct third-stage selection, no JavaScript errors, and no desktop/mobile page overflow. Replayed values are interface fixtures, not network acceptance data.

Lifecycle regressions verify normal-close cleanup, error/interruption checkpoint retention, five non-overlapping discovery cycles, credential-free update reporting, and archived/retested measurements after a protocol fingerprint change. Published files and the local proxy configuration are separate from transient candidate state.

## Version 1.1.3 detached measurements, trimmed latency, and cloud ranking

The reported failure was traced to the owned Actions Runner's `renewjob` connection repeatedly ending prematurely. Its diagnostic recorded a renewal exception followed by `Abandoned`, which cancelled workflow [37730190645](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37730190645) while local progress still displayed Running. The desktop now owns local measurements directly, with Ubuntu discovery and publication around that process. No Windows Runner heartbeat owns those measurements. Public downloads use mirrors; authenticated operations use official endpoints, as agreed with the owner.

A separate copy of the real saved scan ran for 781.75 seconds with every GitHub command deliberately unavailable. It preserved the owner's original checkpoint and advanced from 10,432 results and 111 qualified entries to 11,132 results and 419 qualified entries without a GitHub call. This measured continuity under the earlier policy and does not establish qualification under the subsequently requested five-observation policy.

[Cloud handoff verification 37736724664](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37736724664) reused the saved session without fetching new candidates. Its trusted metadata identified 21,421 candidates; the first public mirror returned the exact SHA-256-verified file. This is cloud discovery/download evidence, not a completed publication.

The final requested policy enforces a strict entry limit and a trimmed three-site composite. A bounded real 100-node batch took 105.625 seconds, with five observations per site, and qualified 34 candidates. Every passing candidate met both the 200 ms entry limit and 200 ms trimmed composite limit. No above-limit composite qualified. Geography checks and final 110-node publication were outside this bounded check.

The suite now has 278 passing tests, including exact five-sample arithmetic, single-instance removal of tied extremes, six-sample behavior, failed-request preservation after trimming, minimum sample validation, strict 200/240 ms rejection, saved-rule persistence, hidden-rule preservation, stale-pass revocation, cancelled-run startup recovery, detached resume without GitHub, mirror integrity, cloud ranking order, and the separate Japanese quota.

Browser replay verifies the cloud count and all 110 ordered fixture rows, 17 individual Chinese rule explanations, minimum five observations, saved values after reload, original 32-particle completed cards, stable bottom fluorescence, no sweep, no JavaScript errors, and no desktop/mobile overflow. These cloud rows are interface fixtures. Actual cloud output starts empty until the real 100+10 gate succeeds; a complete real publication remains unverified.

## Version 1.1.4 and first confirmed real publication

Before application changes, the owner requested publication of existing measured results. The installed saved preset was 300 ms entry, 300 ms composite, five observations per site, zero failed requests and 3.01 Mbps. Retesting produced 95 qualified non-Japanese exits and 19 qualified verified Japanese exits. Reserving the best ten Japanese exits left enough qualified entries for 100 ordinary slots. Cloud workflow run 37791275236 succeeded and committed 110 unique addresses to `output/nodes.txt`; the official GitHub contents API returned bytes identical to the local output. The final ten entries are Japanese append records. The original scan checkpoint was retained. Earlier statements that a complete real publication was unverified describe earlier versions.

Automated coverage additionally verifies stop without publication, queued manual publication without duplicate processes, idle publication mode, saved partial-batch recovery, publication without discovery or unmeasured scans, manual-only partial result validation, actual cloud counts, unchanged strict saved-rule boundaries, and timer pause/resume/reopen/reset behavior. UI replay verifies timer advancement and freezing, both controls, saved rules, original particle effects, and responsive layout.

The final 1.1.4 suite passes 291 tests. The obsolete all-candidates control is removed. Browser checks exercise all three result buttons, verify their distinct dataset, exclusive pressed state, matching green completion gradient and 32 moving particles, and preserve reduced-motion behavior.
