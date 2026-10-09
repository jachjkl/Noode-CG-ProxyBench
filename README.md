# Noode-CG-ProxyBench

A standalone Windows IP optimizer with two selectable measurement methods: authenticated proxy website tests and direct TCP/TLS tests adapted from the original local package. The application interface and operating instructions are Chinese; this README and development documentation are English.

## Run on Windows

Double-click the Windows EXE, or extract the Windows ZIP and run its launcher. The EXE installs `Noode-CG-ProxyBench` beside itself. Python, dependencies, GitHub CLI, curl, and Mihomo are included. Existing saved rules, profiles, results, and logs survive upgrades. The owner's private package stays local; public source contains no proxy credentials.

Choose a method at the top, save its rules and publication counts, then start optimization. Each method has its own five-step workflow, live measurements and rejection table, publication competition table, timer, and checkpoint. Tables paginate at 300 records. The unified cloud table displays both methods with their original ranks, location, measured latency, loss, jitter, speed, and per-IP copy actions. Chinese event logs remain in `logs/` after closure. Original rising particles, green completion gradients, bottom fluorescence, and button ripples remain; reduced-motion preferences are respected.

## Two measurement methods

| Method | Measurement | Default preset | Output |
| --- | --- | --- | --- |
| Authenticated proxy | Five requests each to Google, Cloudflare and GitHub; remove one highest and one lowest per site, average the remaining samples, then average the three site means. Candidate-specific small-sample download. | Entry and composite limits 300 ms, failed requests 0%, response jitter at most 500 ms, download at least 3.01 Mbps. Defaults preserve the owner's latest proxy preset. | `output/nodes.txt` |
| Direct TCP/TLS | Three consecutive TCP connections per IP; arithmetic mean of successes, failures divided by all three attempts, population standard deviation. Optional three TLS handshakes. Original pinned-IP HTTPS download probe. | TCP mean 200 ms, loss at most 20%, jitter at most 200 ms, download at least 3 Mbps. Independent TLS probes are off, matching the original saved preset; when enabled their mean limit is 300 ms. | `output/Nodes-TCP/nodes.txt` |

Both presets use a 512 KiB download sample, at least 95% response-body completion, an 8-second I/O timeout and a 7-second body-time limit. Download timing begins after headers. All limits are configurable with Chinese help and persist independently. A failed or above-limit measurement cannot qualify. Direct mode requires no proxy profile or application-owned proxy core; existing operating-system/VPN routes remain in effect.

Proxy mode uses one isolated, loopback-only Mihomo core in rule mode, with at most 100 independent candidate nodes per batch. It preserves the user's existing Clash, VPN, TUN and system proxy. Public Cloudflare trace is the default website probe because the legacy `cp.cloudflare.com` target can fail through EdgeTunnel. Adaptive concurrency reduces local congestion without changing thresholds. Full-pool TCP screening runs before expensive proxy requests, failed requests finish early when the configured loss limit becomes impossible, geography uses one successful provider during screening, and early competition begins after the saved quotas plus a retest margin are reached. Final competition rechecks geography and every saved quality rule.

Direct mode uses the original `core/tcp_scan.py`, `core/tls_check.py` and `core/speed_test.py` probes. TLS measurements include connection and handshake time. Edge location comes from the trace `colo` mapped to a bundled location table; trace `loc` identifies the requesting client and is not used as candidate geography. Unknown ordinary locations are `XX`; Japanese append entries require verified JP geography.

## Configurable publication counts

Each method separately saves the ordinary TOP count (1–1000) and additional Japanese count (0–300). Examples include 100, 200 or 300 ordinary entries. Defaults are proxy 100 + 10 and direct 300 + 10. Japanese entries receive a separate quota and obey the same measurement rules. There are no duplicate IPs across the two lanes of a published method.

Before publication, current winners and the previous cloud list for that method undergo fresh competition tests. Results are ranked using current measurements, ordinary winners come first, and Japanese append winners follow. Rule changes restart final competition. Automatic publication requires the complete configured quotas; insufficient results trigger new candidates and preserve last-good output. Stop-and-save preserves completed results and checkpoints without pushing. Manual push retests only already measured candidates and may publish the actual qualified count up to the saved limits. A running manual request waits for the current batch. Pending uploads survive network errors and can be retried.

Each output namespace contains `nodes.txt`, `nodes.json`, `nodes.csv`, `api.json`, `ip.zip`, and `health.json`. Text lines use `IP:port#COUNTRY`, for example `82.139.242.5:443#DE`. JSON persists matching ranks and measurement methods. Cloud decoding checks quotas, uniqueness, order, exact text/JSON consistency and the complete allowlisted file set before any writes. Publishing one method cannot overwrite the other.

## Cloud discovery and publication

1. The application requests [the owner's GitHub workflow](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/workflows/proxybench.yml).
2. Ubuntu fetches both configured feeds in full once per open application session, plus 10,000 official Cloudflare candidates and available Japanese hints.
3. Immutable handoffs are downloaded through multiple public mirrors and checked against a trusted SHA-256. Both local methods reuse this session's candidate pool.
4. Windows measures locally. Later automatic replenishment or manual continuation requests 10,000 new edge addresses, excluding every earlier session address, including untested addresses. Fixed feeds are not fetched again during that session.
5. Ubuntu validates the result blob and commits the selected output namespace. Successful completion is displayed only after cloud confirmation.

Mirror downloads never carry GitHub or proxy credentials. Authenticated operations use official GitHub APIs with retries; ordinary download mirrors cannot receive GitHub writes. Local measurement continues independently of GitHub Runner heartbeat failures. Proxy mode checks local protocol updates and official core updates at start. Normal closure removes transient pools and checkpoints; explicit stop, errors and interruption preserve recovery state. Saved rules, profiles, tools, published files and Chinese logs remain. Reopening starts a new discovery session unless interrupted work is explicitly resumed.

## Build and repair

```powershell
python -m pip install -r requirements-dev.txt
python main.py validate
python main.py dashboard
python main.py auto-cloud --measurement-mode tcp_tls
python -X utf8 -m unittest discover -s tests -v
python -m ruff check .
python scripts/build_delivery_bundle.py
```

`--personal` builds the explicitly authorized private local-profile bundle. The maintenance ZIP in `dist/` combines Windows EXE/ZIP, cloud source ZIP, directory listing, SHA-256 inventory, repair-workspace preparation/rebuild scripts, and verified build caches. Extract and repair inside its workspace; embedded Python supports rebuilding without a Git checkout. A single `VERSION` in `core/proxybench/__init__.py` controls file names.

## Verification

Version 1.2.0 passes 319 deterministic tests and browser replay of both methods, custom saved quotas, all result tabs, independent 300-row paging, competition views, unified cloud rows, clipboard, Chinese logs and responsive layout. Real network checks are distinct from fixtures: the final optimized 100-candidate proxy batch passed 88 three-site/download checks in 126.45 seconds without geography or publication. A fresh mixed-source run excluded published addresses, screened 1,000 candidates in 5.67 seconds and qualified 15 of 100 tested candidates under strict 200 ms entry and response limits. A direct 100-candidate pipeline initially qualified 27 and retained 25 after competition. The 1.1.4 real proxy publication contains 110 addresses confirmed by cloud run [37791275236](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37791275236). See [validation evidence](docs/VALIDATION.md) for limitations and subsequent publication evidence.

Baseline: original `jachjkl/Noode-CG` commit `3bc8598b1b9e77cc38f7a54c9d75f5e3796fc058`, recovery tag `baseline-noode-cg-v13.6.2`. Development and generated writes target only this independent repository. The public repository permits owner-only write access and owner-authorized Actions output.

## Development documentation

- [Architecture](docs/ARCHITECTURE-PROXYBENCH.md)
- [Measurement methodology](docs/BENCHMARK-METHODOLOGY.md)
- [Japanese quota](docs/JP-SELECTION.md)
- [Sources](docs/CANDIDATE-SOURCES.md), [profiles](docs/PROXY-PROFILE.md), [Mihomo](docs/MIHOMO.md)
- [Deployment](docs/DEPLOYMENT.md), [recovery](docs/RECOVERY.md)
- [Windows packages](docs/WINDOWS-PACKAGE.md), [project structure](docs/PROJECT-STRUCTURE.md)
- [Interface design](docs/UI-DESIGN.md), [validation](docs/VALIDATION.md)
