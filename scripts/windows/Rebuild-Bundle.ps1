param([switch]$PrepareOnly, [switch]$Public)
$ErrorActionPreference = "Stop"
$bundleRoot = $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
[void][System.Reflection.Assembly]::LoadWithPartialName("System.IO.Compression.FileSystem")

# Verify distributed build inputs before extracting or executing them.
foreach ($entry in $manifest.files) {
    $file = Join-Path $bundleRoot $entry.path
    $stream = [System.IO.File]::OpenRead($file)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $actual = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace("-", "").ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
    if ($actual -ne $entry.sha256) {
        throw "维护包校验失败：$($entry.path)"
    }
}
$work = Join-Path $bundleRoot "修复工作区"
$project = Join-Path $work "Noode-CG-ProxyBench"
if (-not (Test-Path -LiteralPath (Join-Path $project "config.yaml"))) {
    [void][System.IO.Directory]::CreateDirectory($work)
    [System.IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $bundleRoot $manifest.roles.cloud_source), $work)
}
$bootstrap = Join-Path $bundleRoot "本地构建环境"
$portable = Join-Path $bootstrap "Noode-CG-ProxyBench-Windows"
$python = Join-Path $portable "runtime/python/python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    [void][System.IO.Directory]::CreateDirectory($bootstrap)
    [System.IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $bundleRoot $manifest.roles.windows_zip), $bootstrap)
}
$cache = Join-Path $bundleRoot "构建缓存"
foreach ($file in Get-ChildItem -LiteralPath $cache -File -Recurse) {
    $relative = $file.FullName.Substring($cache.Length).TrimStart([char[]]"\/")
    $target = Join-Path (Join-Path $project "runtime") $relative
    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target
    }
}
$personal = $manifest.contains_local_profile -and -not $Public
if ($personal) {
    $profile = Join-Path $project "config/proxy-profile.local.yaml"
    if (-not (Test-Path -LiteralPath $profile)) {
        Copy-Item -LiteralPath (Join-Path $portable "app/config/proxy-profile.local.yaml") -Destination $profile
    }
}
Write-Host "修复工作区已就绪：$project"
if ($PrepareOnly) { exit 0 }
$arguments = @("-X", "utf8", (Join-Path $project "scripts/build_delivery_bundle.py"))
if ($personal) { $arguments += "--personal" }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "重新打包失败" }
Write-Host "重新打包完成，新文件位于：$(Join-Path $project 'dist')"
