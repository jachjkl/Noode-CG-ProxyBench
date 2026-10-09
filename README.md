# Noode-CG-ProxyBench

A standalone Windows IP optimizer with three explicit measurement choices: authenticated proxy website tests, direct TCPing, or direct TLS. The two direct latency methods are mutually exclusive and follow the original local package's probes, with the owner's latest fixed 100-IP batches. The application interface and operating instructions are Chinese; this README and development documentation are English.

## Run on Windows

Double-click the Windows EXE, or extract the Windows ZIP and run its launcher. The EXE installs `Noode-CG-ProxyBench` beside itself. Python, dependencies, GitHub CLI, curl, and Mihomo are included. Existing saved rules, profiles, results, and logs survive upgrades. The owner's private package stays local; public source contains no proxy credentials.

Choose a method at the top, save its rules and publication counts, then start optimization. Each method has its own five-step workflow, live measurements and rejection table, publication competition table, timer, and checkpoint. Tables paginate at 300 records. Each 100-IP batch has a progress bar and individually labelled IP status cells. Cleanup displays its own phase, then resets the batch visualization before the next group. The unified cloud table displays both methods with their original ranks, location, measured latency, loss, jitter, speed, and per-IP copy actions. Chinese event logs remain in `logs/` after closure. Original rising particles, green completion gradients, bottom fluorescence, and button ripples remain; reduced-motion preferences are respected.

## Three measurement choices

| Method | Measurement | Default preset | Output |
| --- | --- | --- | --- |
| Authenticated proxy | One request each to Google, Cloudflare and GitHub; arithmetic mean of the three response-header latencies, without warmup, repeats or discarded extremes. Candidate-specific small-sample download. | Composite limit 300 ms, failed requests 0%, download at least 3.01 Mbps. Defaults preserve the owner's latest proxy preset. | `output/nodes.txt` |
| Direct TCPing or TLS | Select exactly one latency probe. Three consecutive connections OR three verified TLS handshakes; arithmetic mean of successes, failures divided by all three attempts, population standard deviation. Finish the original pinned-IP download test within each batch before testing more candidates. | Selected mean at most 200 ms, loss at most 20%, jitter at most 200 ms, download at least 3 Mbps. Previously saved limits remain authoritative. | [`output/Npdex-Tcp/Tls.txt`](output/Npdex-Tcp/Tls.txt) |

Both presets use a 512 KiB download sample, at least 95% response-body completion, an 8-second I/O timeout and a 7-second body-time limit. Download timing begins after headers. All limits are configurable with Chinese help and persist independently. A failed or above-limit measurement cannot qualify. Direct mode requires no proxy profile or application-owned proxy core; existing operating-system/VPN routes remain in effect.

Proxy mode uses one isolated, loopback-only Mihomo core in rule mode, with 100 independent candidate nodes per full batch. It preserves the user's existing Clash, VPN, TUN and system proxy. Public Cloudflare trace is the default website probe because the legacy `cp.cloudflare.com` target can fail through EdgeTunnel. Adaptive concurrency reduces local congestion without changing thresholds. Every acquired candidate enters actual proxy website testing; there is no direct TCP admission gate. Every candidate attempts all three sites once, including candidates that fail the first site. Ordinary measurement uses one successful geography provider. Automatic competition starts only after the entire acquired pool has been measured, even when publication quotas were reached earlier. Final competition rechecks geography and every saved quality rule.

Direct mode uses the original `core/tcp_scan.py`, `core/tls_check.py` and `core/speed_test.py` probes. TLS measurements include connection and handshake time, using the configured project target domain as the reference package does. TCPing does not run independent TLS latency checks; HTTPS downloads still use TLS transport. TLS selection does not run a TCP latency gate. The application never starts its proxy core for either direct choice; existing operating-system routes remain in effect. Edge location comes from the trace `colo` mapped to a bundled location table; trace `loc` identifies the requesting client and is not used as candidate geography. Unknown ordinary locations are `XX`; Japanese append entries require verified JP geography.

TCPing and TLS share one public subscription, `output/Npdex-Tcp/Tls.txt`, as requested by the owner. Every successful direct publication replaces it with the latest competition-tested ranking and saved counts. It matches the compatibility text at `output/Nodes-TCP/nodes.txt` exactly; metrics and health stay in that compatibility directory. The proxy subscription remains `output/nodes.txt`.

## Configurable publication counts

Each method separately saves the ordinary TOP count (1–1000) and additional Japanese count (0–300). Examples include 100, 200 or 300 ordinary entries. Defaults are proxy 100 + 10 and direct 300 + 10. Japanese entries receive a separate quota and obey the same measurement rules. There are no duplicate IPs across the two lanes of a published method.

Before publication, current winners and the previous cloud list undergo fresh competition tests. Automatic publication requires the configured quotas; insufficient results trigger new candidates and preserve last-good output. Stop-and-save stores measured qualified IPs separately without pushing. After normal closure, the next opening fetches a full new pool; only abnormal exits or failed tests preserve a resumable checkpoint. Start automatically resumes such a failure. Manual push freshly retests saved measured IPs and may publish their actual count up to the saved limits. Network-failed pending uploads survive for retry.

Each output namespace contains `nodes.txt`, `nodes.json`, `nodes.csv`, `api.json`, `ip.zip`, and `health.json`. Text lines use `IP:port#COUNTRY`, for example `82.139.242.5:443#DE`. JSON persists matching ranks and measurement methods. Cloud decoding checks quotas, uniqueness, order, exact text/JSON consistency and the complete allowlisted file set before any writes. Publishing one method cannot overwrite the other.

## Cloud discovery and publication

1. The application requests [the owner's GitHub workflow](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/workflows/proxybench.yml).
2. Ubuntu fetches both configured feeds in full once per open application session, plus 10,000 official Cloudflare candidates and available Japanese hints.
3. Immutable handoffs are downloaded through multiple public mirrors and checked against a trusted SHA-256. Both local methods reuse this session's candidate pool.
4. Windows measures locally. Later automatic replenishment or manual continuation requests 10,000 new edge addresses, excluding every earlier session address, including untested addresses. Fixed feeds are not fetched again during that session.
5. Ubuntu validates the result blob and commits the selected output namespace. Successful completion is displayed only after cloud confirmation.

Mirror downloads never carry GitHub or proxy credentials. Authenticated operations use official GitHub APIs with retries; ordinary download mirrors cannot receive GitHub writes. Local measurement continues independently of GitHub Runner heartbeat failures. Both modes check official stable Mihomo updates when the window opens and before measuring. Updates are verified before installation; a known newer version that fails installation blocks testing until retry or an explicit rollback. Click the engine card to choose the current or previous retained version, or automatic stable updates. Explicit rollback remains selected while release checks continue. Direct mode updates the binary without starting a proxy. Only two binary versions are retained. Normal closure, including closure after stop-and-save, removes transient pools and checkpoints; only errors and abnormal interruption preserve recovery state. Saved rules, profiles, tools, published files and Chinese logs remain. Reopening starts a new discovery session unless interrupted work is explicitly resumed.

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

Version 1.2.5 uses 100-IP batches for both engines and exactly one website request per site in proxy mode. Current latency, loss, download limits and timeouts remain strict; old five-round settings normalize to one round. Proxy time jitter is unavailable from one observation and is displayed as a dash. A timeout cannot become a qualified result. Request/proof deadlines, socket-abort watchdogs and bounded direct probes prevent an unresponsive or trickling peer from keeping a worker alive indefinitely. Completion persistence remains ordered, with progress updates interleaved rather than starved. The interface aborts stalled reads, reconnects automatically, omits unused large preview payloads and reuses verified unchanged checkpoints.

Regression coverage includes all 20,000 candidates in each engine, 100-IP cleanup/reset cycles, all three website attempts for failures, no legacy warmup/repeat path, exact averages without trimming, threshold boundaries, strict slow-peer timeouts and UI reconnection/progress visualization. A bounded real proxy run tested 100 existing published addresses using the saved 300 ms / zero failed requests / 3.01 Mbps rules: all 100 were measured, 300 website probes attempted, and 63 qualified in 106.328 seconds. This is a current-network sample, not a whole-pool acceptance test or promised success rate. The owner's supplied installation is read-only; repaired source and packages remain under this project's directory.

Version 1.2.4 removes proxy entry screening and all automatic quota cutoffs. Both modes complete each 300-IP batch, retain qualified details, delete failed probe bodies and partial journals, and continue to the next batch. Address-only outcomes keep total measured counts correct and prevent duplicate work after an abnormal resume; normal closure clears that ledger. Deterministic tests drive all 20,000 candidates through each selected engine (66 full batches plus 200), including enough early winners to exercise the former cutoff. They also verify exclusive three-attempt direct tests, failed-detail compaction, partial-journal recovery, 300 isolated proxy listeners, two-version update rotation, rollback validation and persistent manual version selection. These fixtures verify scheduling and recovery, not Internet success rates.

Version 1.2.3 separates UI/checkpoint I/O from network measurement, restores reference direct parallelism, and fixes normal-exit versus error-resume behavior. Regression coverage includes blocked UI writes during concurrent probes, partial-journal recovery, normal stop/reopen, automatic failure resume, saved-result manual publication, and preservation of quality limits during legacy-preset migration. In a bounded sequential comparison of the same 100 candidates and 200 ms / 20% loss / 200 ms jitter / 3 Mbps gates, the reference probe pipeline qualified 8 in 11.11 seconds; the new TCPing pipeline qualified 10 in 11.58 seconds. New TLS qualified 3 in 13.51 seconds. These are current-network samples, not a guaranteed success rate.

Version 1.2.2 passes 337 automated tests. The shared TCPing/TLS subscription is checked against ranked metadata before cloud writes and included in local transaction rollback. Completed workflow rectangles and selected controls share the emerald gradient, silver-yellow bottom glow and 32 rising particles. The application links directly to the shared cloud text.

Version 1.2.1 passes 334 automated tests and browser checks for exclusive TCPing/TLS selection, persisted settings, real particle motion and hover feedback. A bounded test of 100 candidates from the interrupted local run qualified 7 with TCPing and 1 with TLS under unchanged 200 ms / 20% loss / 200 ms jitter / 3 Mbps limits; neither method measured the other latency probe. See the version 1.2.1 section in the [validation evidence](docs/VALIDATION.md). Earlier version 1.2.0 results below are historical comparisons.

Version 1.2.0 passes 329 deterministic tests and browser replay of both methods, custom saved quotas, all result tabs, independent 300-row paging, competition views, unified cloud rows, clipboard, Chinese logs and responsive layout. The final proxy test excluded published addresses, screened 1,000 candidates in 5.31 seconds, and measured 98 admitted candidates. Twenty-two passed strict 200 ms entry and response limits, zero failed requests and 3.01 Mbps in 111.20 seconds total, including the saved pauses and geographic requests. Cloudflare used actual GET and trace-body validation. A direct 100-candidate pipeline initially qualified 27 and retained 25 after competition; these were confirmed by [cloud publication 37885554940](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/runs/37885554940). The earlier saved proxy publication remains available for fresh competition under the new policy. See [validation evidence](docs/VALIDATION.md) for the distinction between preliminary API-only observations, current verified measurements, and publication.

Baseline: original `jachjkl/Noode-CG` commit `3bc8598b1b9e77cc38f7a54c9d75f5e3796fc058`, recovery tag `baseline-noode-cg-v13.6.2`. Development and generated writes target only this independent repository. The public repository permits owner-only write access and owner-authorized Actions output.

## Development documentation

- [Architecture](docs/ARCHITECTURE-PROXYBENCH.md)
- [Measurement methodology](docs/BENCHMARK-METHODOLOGY.md)
- [Japanese quota](docs/JP-SELECTION.md)
- [Sources](docs/CANDIDATE-SOURCES.md), [profiles](docs/PROXY-PROFILE.md), [Mihomo](docs/MIHOMO.md)
- [Deployment](docs/DEPLOYMENT.md), [recovery](docs/RECOVERY.md)
- [Windows packages](docs/WINDOWS-PACKAGE.md), [project structure](docs/PROJECT-STRUCTURE.md)
- [Interface design](docs/UI-DESIGN.md), [validation](docs/VALIDATION.md)
