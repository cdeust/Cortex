# Issue #689 owner decision (2026-10-13): exercise manifest hooks without bash.
# Runs only on the hosted Windows environment leg; never changes the machine PATH.
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Root
)
$ErrorActionPreference = 'Stop'
$originalPath = $env:PATH
try {
    $env:PATH = (($originalPath -split ';') | Where-Object {
        $_ -and -not (Test-Path -LiteralPath (Join-Path $_ 'bash.exe')) -and
        -not (Test-Path -LiteralPath (Join-Path $_ 'git.exe'))
    }) -join ';'
    if (Get-Command bash -ErrorAction SilentlyContinue) {
        throw 'The no-bash probe still resolves bash'
    }

    # Removing git.exe also prevents resolve_bash from finding bin/bash.exe beside it.
    $resolverProbe = @'
from mcp_server.shared.platform import BashNotFoundError, resolve_bash
try:
    resolve_bash()
except BashNotFoundError as exc:
    if "Git for Windows" not in str(exc):
        raise AssertionError(str(exc))
    print(str(exc))
else:
    raise AssertionError("resolve_bash accepted a PATH without Git Bash")
'@
    & $Python -c $resolverProbe
    if ($LASTEXITCODE -ne 0) {
        throw 'Missing-bash resolver contract failed'
    }

    $manifest = Get-Content -LiteralPath (Join-Path $Root '.claude-plugin/plugin.json') -Raw |
        ConvertFrom-Json
    $commands = @(
        foreach ($event in $manifest.hooks.PSObject.Properties) {
            foreach ($group in $event.Value) {
                foreach ($hook in $group.hooks) {
                    if ($hook.type -eq 'command') { $hook.command }
                }
            }
        }
    )
    if ($commands.Count -eq 0) { throw 'No manifest hook commands were exercised' }
    foreach ($command in $commands) {
        $missing = $false
        try {
            Invoke-Expression $command
        } catch [System.Management.Automation.CommandNotFoundException] {
            if ($_.TargetObject -ne 'bash') { throw }
            $missing = $true
        }
        if (-not $missing) {
            throw "Hook did not fail at missing bash: $command"
        }
        Write-Output "Verified missing bash for hook: $command"
    }
    Write-Output "Verified $($commands.Count) manifest hook commands under PowerShell without bash"
} finally {
    $env:PATH = $originalPath
}
