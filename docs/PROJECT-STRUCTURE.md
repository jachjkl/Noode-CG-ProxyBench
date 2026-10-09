# Project and maintenance structure

```text
Noode-CG-ProxyBench/
  main.py                           CLI and desktop entry
  config.yaml                       Public defaults and source settings
  config/proxy-profile.local.yaml   Private local authentication (excluded)
  core/proxybench/
    modes.py                        Independent paths and publication quotas
    multi_dashboard.py              One window, two methods, one active task
    pipeline.py                     Screening, competition, replenishment
    benchmark.py                    Authenticated proxy website tests
    direct_benchmark.py              Original TCP/TLS/speed adapters
    colo-locations.json             Public edge location mapping
    events.py                       Persistent Chinese JSON-lines logs
    export.py                       Transactional ranked output
    desktop_cloud.py                Discovery and cloud publication controller
  windows-controller/dashboard/     Chinese HTML, CSS and JavaScript
  data/proxybench-rules.json         Saved proxy rules (local)
  data/tcpbench-rules.json           Saved direct rules (local)
  data/proxybench-ui.json            Saved selected mode (local)
  data/proxy-bench/                  Proxy checkpoint and measurements
  data/tcp-bench/                    Direct checkpoint and measurements
  data/window-candidates.json.gz     Shared window candidate pool
  output/nodes.txt                  Ranked proxy addresses
  output/Nodes-TCP/nodes.txt         Ranked direct addresses
  logs/proxy-events.jsonl            Chinese proxy events
  logs/tcp_tls-events.jsonl          Chinese direct events
  runtime/pending-publish/           Retryable proxy archive
  runtime/pending-publish-tcp/       Retryable direct archive
  scripts/                          Cloud validation and package recipes
  .github/workflows/                Owner-authorized Ubuntu tasks and CI
  tests/                            Deterministic regression coverage
  dist/                             Local packages and verification evidence
```

Each output namespace also contains JSON, CSV, API, ZIP and health metadata after publication. ZIP source placeholders are empty; live installation output survives replacement. Maintenance bundles include Windows and cloud packages, cache inventory, directory listing, repair-workspace preparation and rebuild scripts. Private profile packages remain local; logs, checkpoints, runner registration and credentials are excluded from public source.
