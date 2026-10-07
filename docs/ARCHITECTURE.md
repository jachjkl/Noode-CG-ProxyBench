# Historical V13 architecture

This file describes the baseline's historical direct-network design. It is not the active ProxyBench architecture. See [the current architecture](ARCHITECTURE-PROXYBENCH.md).

The baseline used GitHub-hosted candidate discovery and Windows direct-network selection, including TCP, TLS, HTTP, download, and location gates. Its quotas and direct-network checks are preserved only as migration references and regression fixtures. They do not define the active authenticated-proxy benchmark.

The complete historical source and documentation are recoverable from `baseline-noode-cg-v13.6.2`, based on original commit `3bc8598b1b9e77cc38f7a54c9d75f5e3796fc058`. The retired workflow is stored at `docs/legacy/update.yml`. No migration command writes to the original repository.
