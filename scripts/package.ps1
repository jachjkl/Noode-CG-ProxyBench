param([string]$Destination = "dist/Noode-CG-ProxyBench-1.0.0.zip")
$ErrorActionPreference = "Stop"
& python (Join-Path $PSScriptRoot "package_proxybench.py")
if ($LASTEXITCODE -ne 0) { throw "Package failed" }
