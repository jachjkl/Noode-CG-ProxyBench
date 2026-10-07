param([string]$Destination = "")
$ErrorActionPreference = "Stop"
if ($Destination) {
    & python (Join-Path $PSScriptRoot "package_proxybench.py") --destination $Destination
} else {
    & python (Join-Path $PSScriptRoot "package_proxybench.py")
}
if ($LASTEXITCODE -ne 0) { throw "Package failed" }
