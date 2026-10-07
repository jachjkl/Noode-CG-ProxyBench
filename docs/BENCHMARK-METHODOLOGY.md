# Benchmark methodology

Default sites are Google gstatic generate_204 (204), Cloudflare cp.cloudflare.com (200-399), and GitHub (200-399). If Cloudflare preflight fails at cp but succeeds at the permitted trace endpoint, the whole run consistently uses trace (200) and records the selected URL.

Every round completes the three sites across the batch before the next round starts. The default is three rounds, giving nine candidate-specific probes. Records include each observation, site means, round means, the final mean, jitter, and variance. Request loss is failed probes divided by the total probe count. Failed observations contribute the configured timeout to means when relaxed loss rules are used.

Default ordinary response gates are zero loss and a final mean no greater than 200 ms. Network speed uses the original local package's algorithm and default sample: one HTTP/1.1 transfer of 524,288 bytes (512 KiB) from `https://speed.cloudflare.com/__down?bytes=524288`, with TLS certificate verification and the original host/SNI. The transfer uses HTTP CONNECT through the application-owned loopback Mihomo listener; selecting a candidate and confirming its connection chain are required before sending the speed request.

Timing starts after the HTTP 200 response headers. The received body must be at least 95% of the requested sample. Speed is the received byte count times eight, divided by body seconds and 1,000,000, rounded to three decimal places. The original 1 ms timing floor is preserved. Default I/O timeout is 8 seconds and the body deadline is 7 seconds. Timeout, non-200 status, missing candidate route proof, and bodies below 95% cannot qualify. The default minimum is 3 Mbps. This small-sample measurement is retained as network speed; it is not a separate sustained-network speed acceptance test.

Ranking considers request loss, successful probes, mean response time, round jitter, network speed, and stable IP/port tie breakers. Current shortlisted nodes and all old ordinary TOP100 nodes are measured again before ranking. Failed competition measurements revoke stale qualification.

The network speed selector is serial to avoid cross-candidate routing races and test-generated network speed competition. Production thresholds remain user-controlled. Runtime initialization checks 1/10/100 node loading and the isolated rule-mode core. Cloudflare endpoint preflight is advisory and records the permitted fallback. No separate speed acceptance result is required before the scan. Each candidate is still measured and qualified against its effective rules.

The Chinese interface shows eight summary columns and 300 rows per page. The detail dialog preserves the full site-by-round and network speed observations.

Saved rules matching the former untouched 16 Mbps / three 2 MiB transfers / 15-second preset migrate to the original-package speed defaults. Independently edited response rules and customized speed thresholds are preserved.
