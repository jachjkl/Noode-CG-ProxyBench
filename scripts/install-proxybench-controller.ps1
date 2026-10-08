param([string]$InstallRoot = $(Join-Path $PSScriptRoot 'Noode-CG-ProxyBench-Local'))
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetRoot = [IO.Path]::GetFullPath($InstallRoot)
if ((Split-Path $targetRoot -Leaf) -notmatch 'ProxyBench') { throw 'Use an independent ProxyBench installation directory.' }
$appRoot = Join-Path $targetRoot 'app'
New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
$python = (Get-Command python.exe -ErrorAction Stop).Source
$runtime = Join-Path $targetRoot 'runtime\python'
if (-not (Test-Path -LiteralPath (Join-Path $runtime 'Scripts\python.exe'))) {
    & $python -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Unable to prepare isolated Python runtime.' }
}
$runtimePython = Join-Path $runtime 'Scripts\python.exe'
& $runtimePython -m pip install --disable-pip-version-check -r (Join-Path $sourceRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependency installation failed.' }
# Explicit source roots, no runtime, credentials, browser profiles or result caches.
foreach ($name in @('core','sources','api','functions','config','docs','scripts','windows-controller')) {
    $source = Join-Path $sourceRoot $name
    Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
        $_.FullName -notmatch '(__pycache__|\.local\.|\.pyc$|\.log$)'
    } | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\')
        $target = Join-Path $appRoot $relative
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
}
foreach ($name in @('main.py','config.yaml','VERSION','requirements.txt')) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $appRoot $name) -Force
}
$profile = Join-Path $appRoot 'config\proxy-profile.local.yaml'
if (-not (Test-Path -LiteralPath $profile)) {
    & $runtimePython -c "import sys;sys.path.insert(0,r'$appRoot');from core.proxybench.profile import discover_profiles,import_discovered;from pathlib import Path;r=[x for x in discover_profiles('jackoyu.dpdns.org') if x['matches_worker'] and x['port']==443];print('Profile imported' if r and import_discovered(r[0],Path(r'$profile')) else 'Use Dashboard import')"
}
$launcher = Join-Path $targetRoot 'Start-ProxyBench.cmd'
$content = '@echo off' + "`r`n" + '"' + $runtimePython + '" "' + (Join-Path $appRoot 'main.py') + '" --config "' + (Join-Path $appRoot 'config.yaml') + '" dashboard' + "`r`n"
[IO.File]::WriteAllText($launcher,$content,[Text.UTF8Encoding]::new($false))
Write-Host "Installed: $launcher"
