param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$RuntimeConfig,
    [string]$InputFile,
    [string]$ConnectivityInputFile
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$artifactRoot = Join-Path $repo 'artifacts\poc\packages\linux-dual-runner'
$runtimeRoot = Join-Path $repo 'artifacts\runtime\linux-package-build'
$packageName = "threadsnap-poc-dual-runner-$Version-linux"
$staging = Join-Path $runtimeRoot $packageName
$archive = Join-Path $artifactRoot "$packageName.tar.gz"

function Assert-SafePath([string]$Path, [string]$AllowedRoot) {
    $full = [IO.Path]::GetFullPath($Path)
    $allowed = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\') + '\'
    if (-not $full.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) {
        throw "路径越出允许目录: $full"
    }
}

New-Item -ItemType Directory -Force -Path $artifactRoot, $runtimeRoot | Out-Null
$sourceCommit = (git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceCommit) { throw '读取 Git 提交失败' }
$trackedChanges = @(git -C $repo status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw '读取 Git 状态失败' }
if ($trackedChanges.Count -ne 0) { throw '存在未提交的跟踪文件修改，停止生成可追溯测试包' }
Assert-SafePath $staging $runtimeRoot
if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$files = @(
    'poc/linux/README.md',
    'poc/linux/config.example.json',
    'poc/linux/preflight.sh',
    'poc/linux/install.sh',
    'poc/linux/start.sh',
    'poc/linux/healthcheck.sh',
    'poc/linux/monitor-resources.sh',
    'poc/linux/process-control.sh',
    'poc/linux/run-poc.sh',
    'poc/linux/run-all.sh',
    'poc/linux/test-connectivity.sh',
    'poc/linux/test-access-transition.sh',
    'poc/linux/test-single-concurrency.sh',
    'poc/linux/bootstrap-sms-session.sh',
    'poc/candidate-a/requirements.lock',
    'poc/candidate-a/src/throughput.py',
    'poc/candidate-b/package.json',
    'poc/candidate-b/package-lock.json',
    'poc/candidate-b/tsconfig.json',
    'poc/candidate-b/src/contract.ts',
    'poc/candidate-b/src/access-diagnostic.ts',
    'poc/candidate-b/src/throughput.ts',
    'poc/shared/access_diagnostic.py',
    'poc/shared/contract.py',
    'poc/shared/network_probe.py',
    'poc/shared/prepare_connectivity_config.py',
    'poc/shared/prepare_single_concurrency_config.py',
    'poc/shared/validate_single_concurrency_probe.py',
    'poc/shared/finalize_connectivity.py',
    'poc/shared/validate_results.py',
    'poc/shared/finalize_run.py'
)

foreach ($relative in $files) {
    $source = Join-Path $repo $relative
    if (-not (Test-Path $source -PathType Leaf)) { throw "缺少打包文件: $relative" }
    $destination = Join-Path $staging $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}

$manifest = [ordered]@{
    schema_version = '1.0'
    package = $packageName
    version = $Version
    source_commit = $sourceCommit
    candidate_a = 'Scrapling 0.4.12'
    candidate_b = 'Crawlee 3.18.0 + Playwright 1.62.1'
    target = 'CentOS Stream 10 x86_64 glibc 2.39'
    dependency_mode = 'locked-online-install'
    contains_credentials = $false
    file_count = $files.Count
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $staging 'PACKAGE-MANIFEST.json') -Encoding UTF8

$hashLines = Get-ChildItem -LiteralPath $staging -Recurse -File |
    Where-Object Name -ne 'SHA256SUMS' |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($staging.Length + 1).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
[IO.File]::WriteAllText(
    (Join-Path $staging 'SHA256SUMS'),
    ($hashLines -join "`n") + "`n",
    [Text.UTF8Encoding]::new($false)
)

if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
tar.exe -czf $archive -C $runtimeRoot $packageName
if ($LASTEXITCODE -ne 0) { throw 'tar 打包失败' }
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$archive.sha256", "$archiveHash  $([IO.Path]::GetFileName($archive))`n", [Text.UTF8Encoding]::new($false))
$entries = tar.exe -tzf $archive
if ($LASTEXITCODE -ne 0 -or -not ($entries -contains "$packageName/SHA256SUMS")) { throw '压缩包结构校验失败' }

if ($RuntimeConfig -or $InputFile -or $ConnectivityInputFile) {
    if (-not $RuntimeConfig -or -not $InputFile -or -not $ConnectivityInputFile) {
        throw 'RuntimeConfig、InputFile 与 ConnectivityInputFile 必须同时提供'
    }
    $configSource = (Resolve-Path $RuntimeConfig).Path
    $inputSource = (Resolve-Path $InputFile).Path
    $connectivityInputSource = (Resolve-Path $ConnectivityInputFile).Path
    $operator = Join-Path $artifactRoot 'copy-to-linux'
    Assert-SafePath $operator $artifactRoot
    if (Test-Path $operator) { Remove-Item -LiteralPath $operator -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $operator | Out-Null
    Copy-Item -LiteralPath $archive, "$archive.sha256" -Destination $operator
    Copy-Item -LiteralPath $configSource -Destination (Join-Path $operator 'config.json')
    Copy-Item -LiteralPath $inputSource -Destination (Join-Path $operator 'input-urls.txt')
    Copy-Item -LiteralPath $connectivityInputSource -Destination (Join-Path $operator 'connectivity-urls.txt')
    $deploy = @"
#!/usr/bin/env bash
set -euo pipefail
archive="$([IO.Path]::GetFileName($archive))"
expected="$archiveHash"
actual="`$(sha256sum "`$archive" | awk '{print `$1}')"
[[ "`$actual" == "`$expected" ]] || { echo "ERROR: archive checksum mismatch" >&2; exit 2; }
tar -xzf "`$archive"
runner="$packageName"
cp config.json input-urls.txt connectivity-urls.txt "`$runner/"
chmod 600 "`$runner/config.json"
chmod +x "`$runner"/poc/linux/*.sh
echo "deployed: `$runner"
echo "next: cd `$runner && ./poc/linux/install.sh && ./poc/linux/start.sh && ./poc/linux/test-connectivity.sh"
"@
    [IO.File]::WriteAllText((Join-Path $operator 'deploy.sh'), $deploy.Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText(
        (Join-Path $operator 'README.txt'),
        "将本目录完整复制到 Linux，执行: chmod +x deploy.sh && ./deploy.sh`n部署后先运行 test-connectivity.sh，把 connectivity-results 中的 tar.gz 和 sha256 复制回来。`n配置文件为明文，仅保留在受控测试目录。`n",
        [Text.UTF8Encoding]::new($false)
    )
}

Write-Output "archive=$archive"
Write-Output "sha256=$archiveHash"
