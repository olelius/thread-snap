[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$root = (& git rev-parse --show-toplevel 2>$null).Trim()
if (-not $root) {
    throw '当前目录不在 Git 仓库中。'
}

$hook = Join-Path $root '.githooks/pre-commit'
if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
    throw "缺少版本化 hook：$hook"
}

& git -C $root config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw '设置 core.hooksPath 失败。'
}

$actual = (& git -C $root config --get core.hooksPath).Trim()
if ($actual -ne '.githooks') {
    throw "core.hooksPath 校验失败，实际值：$actual"
}

Write-Host "已为当前仓库启用 Git hooks：$actual"
