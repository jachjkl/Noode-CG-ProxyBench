# Benchmark methodology

Default sites are Google gstatic generate_204 (204), Cloudflare cp.cloudflare.com (200-399), and GitHub (200-399). If Cloudflare preflight fails at cp but succeeds at the permitted trace endpoint, the whole run consistently uses trace (200) and records the selected URL.

Every round completes the three sites across the batch before the next round starts. The default is three rounds, giving nine candidate-specific probes. Records include each observation, site means, round means, the final mean, jitter, and variance. Request loss is failed probes divided by the total probe count. Failed observations contribute the configured timeout to means when relaxed loss rules are used.

Default ordinary gates are zero loss and a final mean no greater than 200 ms. Passing candidates receive three complete 2 MiB transfers from `https://speed.cloudflare.com/__down`. HTTP status, full byte count, and candidate routing evidence are mandatory. The arithmetic mean must be at least 16 Mbps, equal to 2 MB/s. MiB describes transfer size; MB/s is decimal throughput. Payload time excludes time to first byte. Failed or partial transfers cannot qualify.

Ranking considers request loss, successful probes, mean response time, round jitter, bandwidth, and stable IP/port tie breakers. Current shortlisted nodes and all old ordinary TOP100 nodes are measured again before ranking. Failed competition measurements revoke stale qualification.

The bandwidth selector is serial to avoid cross-candidate routing races and test-generated bandwidth competition. Production thresholds remain user-controlled. Runtime acceptance records explicitly looser diagnostic thresholds and does not modify production rules or manufacture passing measurements.

The Chinese interface shows eight summary columns and 300 rows per page. The detail dialog preserves the full site-by-round and bandwidth observations.
