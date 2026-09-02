$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $repo 'src\threadsnap\tencent_captcha\js'
$packageLock = Join-Path $runtime 'package-lock.json'

if (-not (Test-Path $packageLock -PathType Leaf)) {
    throw "腾讯验证码运行时缺少 package-lock.json：$packageLock"
}

Push-Location $runtime
try {
    & npm.cmd ci --ignore-scripts
    if ($LASTEXITCODE -ne 0) { throw 'Tencent captcha npm ci failed' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Tencent captcha runtime build failed' }
}
finally {
    Pop-Location
}

$required = @(
    'normalize-tdc-payload.js',
    'deobfuscate-tdc-interpreter.js',
    'catalog-tdc-primitives.js',
    'extend-tdc-handler-ir.js',
    'build-tdc-ir-runtime.js',
    'run-node-tdc-standalone.js'
)
foreach ($name in $required) {
    $path = Join-Path $runtime "dist\$name"
    if (-not (Test-Path $path -PathType Leaf)) {
        throw "腾讯验证码运行时构建缺少产物：$name"
    }
}

Write-Output "tencent_captcha_runtime=$runtime\dist"
