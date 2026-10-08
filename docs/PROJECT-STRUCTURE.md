# Project and maintenance structure

The cloud and Windows roles share one codebase and version. The combined maintenance package stores their deliverables separately and includes the code and build inputs needed to repair either role.

```text
Noode-CG-ProxyBench/
  .github/workflows/
    proxybench.yml               Cloud discovery and trusted mirror metadata
    proxybench-publish.yml       Validate public result blob and publish on Ubuntu
    ci.yml                       Windows and Ubuntu checks
  core/proxybench/
    __init__.py                  Common VERSION
    benchmark.py                 Candidate site and network-speed measurements
    controller.py                Explicit proxy transport and routing evidence
    pipeline.py                  Ranking, retesting, replenishment
    export.py                    output/nodes.txt and other result files
    desktop_cloud.py             Cloud control around locally owned measurements
    cloud_network.py             Read-only VPN detection and cloud process environment
    cloud.py                     Shared commands and optional legacy runner lifecycle
  sources/                       Candidate feeds and official edge sampling
  windows-controller/dashboard/
    proxybench.html              Chinese application page
    proxybench.js                Paging, controls and original visual effects
    proxybench.css               Selected-state light and responsive layout
    app.css                      Original particles, ripples and card light
  scripts/
    proxybench_channel.py        Exact output validation and cloud handoff
    package_sources.py           Public source enumeration with Git-free fallback
    package_proxybench.py        Cloud source ZIP
    build_windows_package.py     Windows ZIP with portable dependencies
    build_windows_installer.py   Windows EXE
    build_delivery_bundle.py     Combined maintenance ZIP and inventory
    windows/Rebuild-Bundle.ps1   Prepare and rebuild separate repair workspace
  output/
    README.md                    Result format and publication behavior
    nodes.txt                    Actual published IPs, initially empty
  config/
    proxy-profile.local.yaml     Owner's local profile, excluded from public code
  runtime/                       Local tools and transient state, excluded from Git
  dist/                          Generated packages, excluded from Git
```

The local profile is included only when an explicit personal package is built. Cloud code packages always omit it. Build-cache entries are allowlisted and never include runner registration, authentication files, logs, or live results.

Preparing the repair workspace again leaves existing source edits intact. Rebuilding writes new packages inside that workspace's `dist/` folder, allowing fixes to be tested without replacing the existing desktop installation.
