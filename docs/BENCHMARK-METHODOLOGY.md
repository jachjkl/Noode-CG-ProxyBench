# Benchmark methodology

Default sites are Google gstatic generate_204 (204), Cloudflare cp.cloudflare.com (200-399), and GitHub (200-399). If Cloudflare preflight fails at cp but succeeds at the permitted trace endpoint, the whole run consistently uses trace (200) and records the selected URL.

Every round completes the three sites across the batch before the next round starts. The default is three rounds, giving nine candidate-specific probes. Records include each observation, site means, round means, the final mean, jitter, and variance. Request loss is failed probes divided by the total probe count. Failed observations contribute the configured timeout to means when relaxed loss rules are used.

Default ordinary response gates are zero loss and a final mean no greater than 200 ms. Network speed uses the original local package's algorithm and default sample: one HTTP/1.1 transfer of 524,288 bytes (512 KiB) from `https://speed.cloudflare.com/__down?bytes=524288`, with TLS certificate verification and the original host/SNI. The transfer uses HTTP CONNECT through the application-owned loopback Mihomo listener; selecting a candidate and confirming its connection chain are required before sending the speed request.

Timing starts after the HTTP 200 response headers. The received body must be at least 95% of the requested sample. Speed is the received byte count times eight, divided by body seconds and 1,000,000, rounded to three decimal places. The original 1 ms timing floor is preserved. Default I/O timeout is 8 seconds and the body deadline is 7 seconds. Timeout, non-200 status, missing candidate route proof, and bodies below 95% cannot qualify. The default minimum is 3 Mbps. This small-sample measurement is retained as network speed; it is not a separate sustained-network speed acceptance test.

Ranking considers request loss, successful probes, mean response time, round jitter, network speed, and stable IP/port tie breakers. Current shortlisted nodes and all old ordinary TOP100 nodes are measured again before ranking. Failed competition measurements revoke stale qualification.

The network speed selector is serial to avoid cross-candidate routing races and test-generated network speed competition. Production thresholds remain user-controlled. Runtime initialization checks 1/10/100 node loading and the isolated rule-mode core. Cloudflare endpoint preflight is advisory and records the permitted fallback. No separate speed acceptance result is required before the scan. Each candidate is still measured and qualified against its effective rules.

The Chinese interface shows eight summary columns and 300 rows per page. The detail dialog preserves the full site-by-round and network speed observations.

Saved rules matching the former untouched 16 Mbps / three 2 MiB transfers / 15-second preset migrate to the original-package speed defaults. Independently edited response rules and customized speed thresholds are preserved.

## Version 1.1.0 fast pipeline

Entry screening performs bounded local TCP connects with default concurrency 256, timeout 1.2 seconds, and maximum entry latency 200 ms. It is a preliminary reachability test, not authenticated proxy traffic. Failed entries are excluded before loading proxies; successful entries remain subject to real site and speed checks.

Authenticated site probes use up to 60 concurrent requests over three rounds. A candidate that can no longer satisfy its loss allowance stops making further requests; skipped observations are explicitly marked. Complete Worker website response time has a separate default limit of 2500 ms. Production ranking includes entry latency, then end-to-end response and stability. Final competitions refresh entry checks as well as proxy traffic.

Speed uses a 512 KiB range request to https://dl.google.com/chrome/install/standalonesetup64.exe, with HTTP 200 or a matching HTTP 206 byte range. Named loopback listeners and InName rules isolate each node, allowing four concurrent speed/geo checks without selector races. Successful downloads must retain exact candidate connection-chain proof and the original minimum 95% body rule.

Rule migration updates former untouched defaults while preserving other edits. Resuming a pre-1.1.0 run archives its former measurements and remeasures the same saved candidate pool under the corrected policy. Discovery-session exclusions remain unchanged. Dashboard progress writes are throttled, and repeated control checkpoints do not rewrite the full live snapshot.
