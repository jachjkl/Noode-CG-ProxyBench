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
