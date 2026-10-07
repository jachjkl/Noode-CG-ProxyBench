# Deployment

For the active project, use the [Windows package](WINDOWS-PACKAGE.md) and the [cloud automation workflow](https://github.com/jachjkl/Noode-CG-ProxyBench/actions/workflows/proxybench.yml). Manual Windows-service installation is unnecessary; the application owns its separate runner lifecycle.

The public repository contains source and public candidate metadata. Authenticate GitHub CLI locally as `jachjkl`. The owner-only package already includes the imported real proxy configuration. The public package can import an existing local client configuration.

Open the installed window and start optimization. Ubuntu prepares candidates, Windows downloads and measures them, and Ubuntu validates and publishes the allowed result files. Subsequent rounds exclude all earlier session IPs. Final output remains unchanged until exactly 100 ordinary nodes plus ten verified Japanese exits pass.

Historical V13 service deployment instructions are recoverable from the baseline tag. Their direct-network proxy restrictions and TOP300 quotas do not apply to ProxyBench.
