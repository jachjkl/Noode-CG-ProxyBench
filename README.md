# Noode-CG-ProxyBench

An independent Cloudflare IP optimizer that measures real authenticated proxy traffic with an isolated Mihomo core. Surviving candidates become distinct proxy nodes using the owner's actual Worker or EdgeTunnel configuration.

The Windows interface is Chinese. This README and the development documentation are English.

## Windows application

Run the Windows EXE to install and open the local application, then click the primary start button. Alternatively, extract the Windows ZIP and double-click `Start-ProxyBench.vbs`. Python, PyYAML, psutil, GitHub CLI, curl, and Mihomo are included.

The application automatically connects these stages:

1. Request a GitHub Actions run using the owner's local GitHub login.
2. Fetch both configured feeds in full and sample 10,000 additional official Cloudflare IPv4 candidates.
3. Download the immutable handoff through multiple public mirrors and verify its trusted SHA-256.
4. Measure candidate-specific proxy access, response times, request success, and the original package's small-sample network speed on Windows.
5. Retest current candidates against the previously published ordinary TOP100, select the best 100, and append 10 independently verified Japanese exits.
6. Upload the allowlisted results to Ubuntu for final validation and publication.

[Open the cloud automation workflow](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/workflows/proxybench.yml). A manual run from GitHub defaults to cloud discovery only. Starting optimization in the Windows application explicitly requests the complete local benchmark and publication workflow.

The desktop controller runs local measurements independently of GitHub Actions. Cloud discovery and final publication run on Ubuntu; no Windows Runner heartbeat owns the local benchmark. GitHub authentication comes from the owner's local `jachjkl` login. Public files use mirror downloads; authenticated operations use official GitHub endpoints with bounded retries and do not automatically adopt the local HTTP proxy. Each start checks for a running proxy client and a reachable local proxy listener, while preserving the current VPN and system routes. The public package contains no personal proxy credentials. The separately prepared owner-only package includes the real local profile at the owner's request and is never uploaded to GitHub Releases.

The compact Chinese dashboard shows five actual workflow steps: cloud acquisition, candidate download, local selection, final retest, and GitHub publication. Completed steps use the original package's stable completion colors, bottom fluorescence, and rising particles. The publication step completes only after cloud push succeeds. The candidate list and live benchmark occupy separate panes, each with independent 300-IP paging. A separate cloud panel displays the published total, ordinary count, Japanese count, and the exact original ranking. Detailed observations remain available in a dialog. Work starts after the user clicks the primary start button.

## Discovery and replenishment

- Each application window has its own session identity. Starting after reopening the window fetches both complete feeds again for the new session.
- Within one session, the two fixed feeds are fetched only once. Subsequent automatic replenishment or manual continuation requests a fresh 10,000-address official edge sample.
- Cloud history excludes every previously handed-off IP, including untested candidates and optional-source candidates. No later round reintroduces an earlier candidate IP.
- Downloaded candidates are accumulated locally before proxy validation. Failed validation does not discard the first complete pool when another handoff arrives.
- Replenishment continues until 100 ordinary candidates and 10 additional Japanese exits pass final retesting, unless stopped or the sources are exhausted. `max_cycles: 0` enables this default behavior; a positive value sets an explicit limit.
- Normal window closure clears transient candidate pools and checkpoints. Errors, unexpected interruption, and the explicit stop-and-save action preserve checkpoints. A newly opened window starts a new discovery session; resume explicitly restores an interrupted session. Continue fetching requests fresh candidates while retaining completed measurements and the current session's exclusion history. Five consecutive fetches, and later fetches in that same session, exclude all previously handed-off IPs.

## Measurement and publication rules

Each batch loads at most 100 distinct proxies into one isolated Mihomo core. The core uses rule mode, loopback-only listeners, and no TUN interface. The application does not change the system proxy or terminate the user's existing Clash or Mihomo processes.

Google, Cloudflare, and GitHub each receive at least five unified-delay observations, with five as the default. Each site discards one highest and one lowest observation and averages the remaining samples; five observations retain the middle three. The final response value is the mean of the three site means. Its default limit is 300 ms, and zero failed requests are allowed by default. Entry TCP latency has its own strict 300 ms default limit and a 1.2-second connection timeout. Every saved threshold remains authoritative. Network speed follows the original local installation package: one 512 KiB sample through the selected candidate, at least 95% body completion, an 8-second I/O timeout, a 7-second body-time limit, and a default minimum of 3.01 Mbps. Timing begins after response headers. Up to four dedicated candidate listeners perform speed requests concurrently. All rules have Chinese explanations and persist across normal closure and restart.

Cloudflare uses `cp.cloudflare.com` first. If preflight fails there and succeeds at `www.cloudflare.com/cdn-cgi/trace`, the entire measurement run consistently uses the trace endpoint and records that choice.

The new ordinary TOP100 and all previously published ordinary TOP100 nodes compete in a fresh retest. New Japanese TOP10 candidates and the previous Japanese TOP10 are independently retested. Exactly 100 ordinary winners and 10 additional Japanese winners are retained. Japanese nodes receive a separate quota and must meet the same saved measurement rules, with verified Japanese exit geography. Failed retests revoke stale qualification. A rule edit before publication restarts final competition under the latest saved rules.

Publication requires exactly 100 ordinary nodes followed by 10 additional Japanese nodes, with 110 unique IPs. Every publication uses the same ranking policy and retested measurements. Insufficient results preserve the previous successful files and trigger replenishment.

Outputs are stored in the repository's `output/` directory: `nodes.txt`, `nodes.json`, `nodes.csv`, `api.json`, `ip.zip`, and `health.json`. [The plain-text IP file](output/nodes.txt) uses one `IP:port#COUNTRY` per line, such as `82.139.242.5:443#DE`, with the Japanese append lane occupying the final ten lines. It starts empty before the first successful publication. Both local packaging and cloud decoding require the complete output set and verify that the text exactly matches the final ranked JSON; missing or inconsistent text cannot overwrite the last successful result.

## Combined maintenance bundle

Run `python scripts/build_delivery_bundle.py` for a public maintenance ZIP, or add `--personal` for the explicitly authorized local profile package. The result is created under this project's `dist/` directory. It combines the Windows EXE and ZIP, cloud source ZIP, directory listing, SHA-256 inventory, repair-workspace preparation script, rebuild script, and an explicit set of Python, wheel, GitHub CLI, and Mihomo build inputs. Runner registration and runtime measurements are excluded.

After extraction, prepare the repair workspace, edit its source, and run the rebuild script. Existing source edits and local profiles are preserved. The embedded Python can rebuild an extracted source tree without requiring a Git checkout. Both cloud and Windows code packages contain these build recipes. Version numbers come from `core/proxybench/__init__.py`.

The original rising background particles, card lighting, button ripples, and fluorescent selected-state animation are preserved in the Chinese Windows interface. Hidden or offscreen decorations pause, and reduced-motion preferences are respected.

## Validation status

Automated checks pass, including candidate paging, independent batch probes, checkpoint recovery, incumbent competition, failed-retest replacement, and continuous replenishment. Real cloud discovery produced 21,537 candidates in the first round and 10,000 new IPs in each of the next two rounds, with no overlap.

Real authenticated proxy traffic has been exercised, including 100 independently loaded nodes and 900 site probes. Version 1.0.1 replaces the earlier three-transfer bandwidth gate with the original package's small-sample speed method. Core initialization checks node loading and rule routing; endpoint failures are handled per candidate during selection. A real 100+10 publication has not yet been verified. See [validation evidence and limitations](docs/VALIDATION.md).

## Development

```powershell
python -m pip install -r requirements-dev.txt
python main.py validate
python main.py validate-profile
python main.py validate-runtime
python main.py dashboard
python main.py auto-cloud
python main.py resume
python -m unittest discover -s tests -v
python -m ruff check .
python scripts/build_windows_package.py
python scripts/build_windows_installer.py
```

Cloud preparation uses `prepare-handoff`; downloaded pools are persisted with `stage-handoff`; the desktop controller executes the local pipeline. The publication workflow validates an allowlisted, SHA-256-verified public result blob before committing output. CI uses deterministic fixtures and does not substitute mocked measurements for real network acceptance.

Baseline: `jachjkl/Noode-CG` main commit `3bc8598b1b9e77cc38f7a54c9d75f5e3796fc058`. Recovery tag: `baseline-noode-cg-v13.6.2`. This project writes only to the independent `Noode-CG-ProxyBench` repository. The original repository's source and published outputs remain unchanged.

The repository is public for source and candidate mirrors. Only the owner has repository write access; owner-authorized Actions publish generated data. Local profiles, controller secrets, runner registration, and private packages are excluded from public artifacts.

## Documentation

- [Architecture](docs/ARCHITECTURE-PROXYBENCH.md)
- [Candidate sources](docs/CANDIDATE-SOURCES.md)
- [Mihomo lifecycle](docs/MIHOMO.md)
- [Proxy profiles](docs/PROXY-PROFILE.md)
- [Benchmark methodology](docs/BENCHMARK-METHODOLOGY.md)
- [Japanese append selection](docs/JP-SELECTION.md)
- [Recovery and checkpoints](docs/RECOVERY.md)
- [Windows packaging](docs/WINDOWS-PACKAGE.md)
- [Project and maintenance structure](docs/PROJECT-STRUCTURE.md)
- [Validation evidence](docs/VALIDATION.md)

## EdgeTunnel fast-selection notes

Entry TCP timing and unified proxy website response timing are separate observations. Version 1.1.3 enforces both saved latency limits strictly and uses per-site trimmed means from at least five observations. Both fixed feeds remain complete; non-Cloudflare entries are labeled reverse-proxy candidates rather than official Cloudflare edges. Entry-only results cannot qualify for publication.

The pinned upstream [cmliu/edgetunnel source](https://github.com/cmliu/edgetunnel/blob/af4f9837e1843e34159018713bc8749ccec3004d/_worker.js) treats `speed.cloudflare.com` and `cp.cloudflare.com` as special local-response domains in some paths. Worker [TCP restrictions](https://developers.cloudflare.com/workers/runtime-apis/tcp-sockets/) also block direct outgoing sockets to Cloudflare ranges. The speed probe therefore uses a bounded 512 KiB HTTP range from Google's download service, through the candidate proxy, retaining body timing and route evidence. It does not accept a local 204 as a bandwidth result.

The Windows EXE creates its `Noode-CG-ProxyBench` runtime folder next to the EXE. `--install-adjacent` exercises the same location without opening a window; explicit `--install-only PATH` remains available for packaging checks.


## Runtime synchronization and updates

Cloud dispatch uses a unique request identifier in the workflow title, independent of the Windows clock. Temporary monitoring failures retry without terminating the owned runner. The dashboard checks ownership of a live local core, so a child that outlives its monitor remains visible and cannot trigger a duplicate start. Local phase information advances the five-step display even when cloud job metadata is delayed.

Each operation checks the official stable Mihomo release and downloads a verified update when necessary. The actual active local Clash configuration is checked at startup and periodically between batches. Changed protocol parameters synchronize locally, archive prior measurements, and restart measurement of the saved pool under the new fingerprint. Fixed-source session history remains intact; different configurations never compete using mixed old measurements.

Version 1.1.4 adds a manual publication button and separate optimization/software timers. Stop-and-save only stops measurements and saves the checkpoint; it does not publish. Manual publication retests existing measurements without fetching new IPs. During a scan it is queued until the current batch finishes. It publishes the actual qualified selection, capped at 100 ordinary records plus ten additional verified Japanese exits, even when fewer are available; automatic publication still requires the complete 100+10 quota. Japanese append candidates are reserved before the ordinary shortlist to avoid consuming their separate quota. Failed uploads retain the exact pending archive for retry. Active optimization time excludes pauses, resumes from saved timing, freezes on completion, and resets on a new start. Software lifetime continues while the window is open. Defaults match the owner's latest saved 17-rule preset; individually saved choices always take precedence.

The candidate pane always shows the complete paginated pool. The live/completed/published buttons switch the right pane only; the selected button uses the same green gradient, bottom light, and rising particles as completed workflow steps.
