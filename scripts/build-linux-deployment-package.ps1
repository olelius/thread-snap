param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)*$')]
    [string]$Version,
    [switch]$AllowDirty
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.vevn\Scripts\python.exe'
$artifactRoot = Join-Path $repo 'artifacts\releases'
$runtimeRoot = Join-Path $repo 'artifacts\runtime\linux-deployment-build'
$packageName = "threadsnap-$Version-linux-builder"
$staging = Join-Path $runtimeRoot $packageName
$archive = Join-Path $artifactRoot "$packageName.tar.gz"

function Assert-SafePath([string]$Path, [string]$AllowedRoot) {
    $full = [IO.Path]::GetFullPath($Path)
    $allowed = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\') + '\'
    if (-not $full.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes allowed root: $full"
    }
}

if (-not (Test-Path $python -PathType Leaf)) {
    throw "Project virtualenv Python is missing: $python"
}

$sourceCommit = (git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceCommit) { throw 'Failed to read Git commit' }
$status = @(git -C $repo status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw 'Failed to read Git status' }
$isDirty = $status.Count -ne 0
if ($isDirty -and -not $AllowDirty) {
    throw 'A formal builder input must come from a clean commit. Use -AllowDirty only for development verification.'
}

New-Item -ItemType Directory -Force -Path $artifactRoot, $runtimeRoot | Out-Null
Assert-SafePath $staging $runtimeRoot
if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$frontendBuildRoot = Join-Path $runtimeRoot 'frontend-build'
Assert-SafePath $frontendBuildRoot $runtimeRoot
if (Test-Path $frontendBuildRoot) { Remove-Item -LiteralPath $frontendBuildRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $frontendBuildRoot | Out-Null
& robocopy.exe (Join-Path $repo 'frontend') $frontendBuildRoot /E /XD node_modules dist /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Frontend copy failed, robocopy=$LASTEXITCODE" }

& npm.cmd --prefix $frontendBuildRoot ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend npm ci failed' }
& npm.cmd --prefix $frontendBuildRoot run check
if ($LASTEXITCODE -ne 0) { throw 'Frontend type check failed' }
& npm.cmd --prefix $frontendBuildRoot run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed' }

$wheelOutput = Join-Path $runtimeRoot 'wheel-output'
Assert-SafePath $wheelOutput $runtimeRoot
if (Test-Path $wheelOutput) { Remove-Item -LiteralPath $wheelOutput -Recurse -Force }
New-Item -ItemType Directory -Force -Path $wheelOutput | Out-Null
& $python -m pip wheel --no-deps --wheel-dir $wheelOutput $repo
if ($LASTEXITCODE -ne 0) { throw 'Backend wheel build failed' }
$wheels = @(Get-ChildItem -LiteralPath $wheelOutput -Filter 'threadsnap-*.whl' -File)
if ($wheels.Count -ne 1) { throw "Unexpected backend wheel count: $($wheels.Count)" }
$wheel = $wheels[0]
if ($wheel.Name -notlike "threadsnap-$Version-*.whl") {
    throw "Requested version $Version does not match wheel $($wheel.Name)"
}

$stagingDirectories = @(
    (Join-Path $staging 'backend')
    (Join-Path $staging 'frontend')
    (Join-Path $staging 'deploy')
    (Join-Path $staging 'licenses')
    (Join-Path $staging 'metadata')
)
New-Item -ItemType Directory -Force -Path $stagingDirectories | Out-Null
Copy-Item -LiteralPath $wheel.FullName -Destination (Join-Path $staging 'backend')
Copy-Item -Path (Join-Path $frontendBuildRoot 'dist\*') -Destination (Join-Path $staging 'frontend') -Recurse
Copy-Item -Path (Join-Path $repo 'deploy\linux\*') -Destination (Join-Path $staging 'deploy') -Recurse
Copy-Item -LiteralPath (Join-Path $repo 'THIRD_PARTY_NOTICES.md') -Destination (Join-Path $staging 'licenses')
Copy-Item -LiteralPath (Join-Path $repo 'frontend\THIRD_PARTY_NOTICES.md') -Destination (Join-Path $staging 'licenses\FRONTEND_THIRD_PARTY_NOTICES.md')
Copy-Item -LiteralPath (Join-Path $repo 'frontend\LICENSE') -Destination (Join-Path $staging 'licenses\FRONTEND_LICENSE')
Copy-Item -LiteralPath (Join-Path $repo 'pyproject.toml') -Destination (Join-Path $staging 'metadata')
Copy-Item -LiteralPath (Join-Path $repo 'docs\deployment\linux-v1.md') -Destination (Join-Path $staging 'README.md')

$manifest = [ordered]@{
    schema_version = '1.0'
    package = $packageName
    version = $Version
    source_commit = $sourceCommit
    source_dirty = $isDirty
    target = 'CentOS Stream 10 x86_64 glibc 2.39'
    package_role = 'offline-builder-input'
    dependency_mode = 'pending-linux-assembly'
    installable = $false
    contains_credentials = $false
    backend_wheel = $wheel.Name
    frontend_entry = 'frontend/index.html'
}
$manifestJson = ($manifest | ConvertTo-Json -Depth 4) + "`n"
[IO.File]::WriteAllText(
    (Join-Path $staging 'PACKAGE-MANIFEST.json'),
    $manifestJson,
    [Text.UTF8Encoding]::new($false)
)

$forbidden = Get-ChildItem -LiteralPath $staging -Recurse -Force | Where-Object {
    $_.Name -in @('.env', 'threadsnap.db', 'session.key', 'storage-state.json') -or
    $_.FullName -match '[\\/]node_modules[\\/]'
}
if ($forbidden) {
    throw "Deployment package contains forbidden files: $($forbidden.FullName -join ', ')"
}

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
if ($LASTEXITCODE -ne 0) { throw 'tar archive build failed' }
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    "$archive.sha256",
    "$archiveHash  $([IO.Path]::GetFileName($archive))`n",
    [Text.UTF8Encoding]::new($false)
)

$entries = @(tar.exe -tzf $archive)
if ($LASTEXITCODE -ne 0) { throw 'Failed to inspect archive' }
foreach ($required in @(
    "$packageName/PACKAGE-MANIFEST.json",
    "$packageName/SHA256SUMS",
    "$packageName/backend/$($wheel.Name)",
    "$packageName/frontend/index.html",
    "$packageName/deploy/assemble-offline-package.sh",
    "$packageName/deploy/install.sh"
)) {
    if ($entries -notcontains $required) { throw "Archive entry missing: $required" }
}

Write-Output "builder_archive=$archive"
Write-Output "builder_sha256=$archiveHash"
Write-Output "source_commit=$sourceCommit"
Write-Output "source_dirty=$isDirty"
Write-Output 'next=Run deploy/assemble-offline-package.sh on a matching CentOS Stream 10 x86_64 builder'
