# Noode-CG-ProxyBench

An independent Cloudflare IP optimizer that measures real authenticated proxy traffic with an isolated Mihomo core. Every candidate becomes a distinct proxy node using the owner's actual Worker or EdgeTunnel configuration.

The Windows interface is Chinese. This README and the development documentation are English.

## Windows application

Run the Windows EXE to install and open the local application, then click the primary start button. Alternatively, extract the Windows ZIP and double-click `Start-ProxyBench.vbs`. Python, PyYAML, psutil, GitHub CLI, curl, and Mihomo are included.

The application automatically connects these stages:

1. Request a GitHub Actions run using the owner's local GitHub login.
2. Fetch both configured feeds in full and sample 10,000 additional official Cloudflare IPv4 candidates.
3. Download the immutable handoff through verified mirrors or the authenticated runner channel.
4. Measure candidate-specific proxy access, response times, request success, and actual bandwidth on Windows.
5. Retest current candidates against the previously published ordinary TOP100, select the best 100, and append 10 independently verified Japanese exits.
6. Upload the allowlisted results to Ubuntu for final validation and publication.

[Open the cloud automation workflow](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/workflows/proxybench.yml). A manual run from GitHub defaults to cloud discovery only. Starting optimization in the Windows application explicitly requests the complete local benchmark and publication workflow.

The first launch downloads and registers a separate application-owned Windows runner. GitHub authentication comes from the owner's local `jachjkl` login. The public package contains no personal proxy credentials. The separately prepared owner-only package includes the real local profile at the owner's request and is never uploaded to GitHub Releases.

The main list shows 300 IPs per page and eight summary columns. Detailed measurements are available in a dialog. The application starts work after the user clicks the start button.

## Discovery and replenishment

- Each application window has its own session identity. Starting after reopening the window fetches both complete feeds again for the new session.
- Within one session, the two fixed feeds are fetched only once. Subsequent automatic replenishment or manual continuation requests a fresh 10,000-address official edge sample.
- Cloud history excludes every previously handed-off IP, including untested candidates and optional-source candidates. No later round reintroduces an earlier candidate IP.
- Downloaded candidates are accumulated locally before proxy validation. Failed validation does not discard the first complete pool when another handoff arrives.
- Replenishment continues until 100 ordinary candidates and 10 additional Japanese exits pass final retesting, unless stopped or the sources are exhausted. `max_cycles: 0` enables this default behavior; a positive value sets an explicit limit.
- Resume uses saved batches. Continue fetching requests fresh candidates while retaining completed measurements and the current session's exclusion history.

## Measurement and publication rules

Each batch loads at most 100 distinct proxies into one isolated Mihomo core. The core uses rule mode, loopback-only listeners, and no TUN interface. The application does not change the system proxy or terminate the user's existing Clash or Mihomo processes.

Google, Cloudflare, and GitHub are tested for three rounds by default, producing nine candidate-specific probes. The defaults require zero failed requests and an average response time of at most 200 ms. Candidates passing these checks receive three complete 2 MiB proxy transfers from the Cloudflare bandwidth endpoint, with an average of at least 16 Mbps, equivalent to 2 MB/s. Response and bandwidth thresholds are editable.

Cloudflare uses `cp.cloudflare.com` first. If preflight fails there and succeeds at `www.cloudflare.com/cdn-cgi/trace`, the entire measurement run consistently uses the trace endpoint and records that choice.

The current ordinary shortlist and all previously published ordinary TOP100 nodes compete in a fresh retest. Failed retests revoke stale qualification, allowing newly measured candidates into later competitions. Japanese append candidates are independently retested and must have verified Japanese exit geography. Source labels alone never establish Japanese eligibility.

Publication requires exactly 100 ordinary nodes followed by 10 additional Japanese nodes, with 110 unique IPs. Every publication uses the same ranking policy and retested measurements. Insufficient results preserve the previous successful files and trigger replenishment.

Outputs: `nodes.txt`, `nodes.json`, `nodes.csv`, `api.json`, `ip.zip`, and `health.json`. The text format is `IP:port#country`, with the Japanese append lane occupying the final ten lines.

## Validation status

Automated checks pass, including candidate paging, independent batch probes, checkpoint recovery, incumbent competition, failed-retest replacement, and continuous replenishment. Real cloud discovery produced 21,537 candidates in the first round and 10,000 new IPs in each of the next two rounds, with no overlap.

Real authenticated proxy traffic has been exercised, including 100 independently loaded nodes and 900 site probes. The available Worker profile has **not passed the required bandwidth acceptance test**, so the formal large-pool scan and a real 100+10 publication remain gated. The package includes the actual local configuration, but configuration syntax validity does not guarantee that its upstream proxy can complete the bandwidth transfer. See [validation evidence and limitations](docs/VALIDATION.md).

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

Cloud preparation uses `prepare-handoff`; downloaded pools are persisted with `stage-handoff`; the runner executes `local-select`. CI uses deterministic fixtures and does not substitute mocked measurements for real network acceptance.

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
- [Validation evidence](docs/VALIDATION.md)
