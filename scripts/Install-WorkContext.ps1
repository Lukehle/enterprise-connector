# Creates a vault using an already-approved local Python runtime.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $VaultPath,

    [ValidatePattern('^[a-z0-9]+(?:-[a-z0-9]+)*$')]
    [string] $Project = 'forecast-automation',

    [ValidatePattern('^PRJ-[0-9]{3,}$')]
    [string] $ProjectId = 'PRJ-001',

    [string] $StateDir,

    [ValidateNotNullOrEmpty()]
    [string] $Python = 'python',

    [switch] $Demo,

    [switch] $SelfTest,

    [switch] $PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Preserve the CLI's exit code even when a PowerShell 7 profile enables native errors.
$PSNativeCommandUseErrorActionPreference = $false

try {
    $kitRoot = Split-Path -Parent $PSScriptRoot
    $launcher = Join-Path -Path $kitRoot -ChildPath 'work-context.py'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "The kit launcher was not found at '$launcher'. Keep this script in the kit's scripts directory."
    }

    $pythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pythonCommand) {
        throw "Python was not found. Use -Python with the path to an approved Python 3.11 or newer executable. This script does not install Python."
    }
    $pythonExecutable = $pythonCommand.Source
    $versionArguments = @('-c', "import sys; print('.'.join(map(str, sys.version_info[:3]))); sys.exit(0 if sys.version_info >= (3, 11) else 1)")
    $versionOutput = & $pythonExecutable @versionArguments 2>&1
    $versionExitCode = $LASTEXITCODE
    if ($versionExitCode -ne 0) {
        throw "Python 3.11 or newer is required. The selected executable did not pass the version check: $($versionOutput -join ' ')"
    }

    $resolvedVaultPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($VaultPath)
    if ((Test-Path -LiteralPath $resolvedVaultPath) -and -not (Test-Path -LiteralPath $resolvedVaultPath -PathType Container)) {
        throw "VaultPath must name a directory, not a file: '$resolvedVaultPath'."
    }
    if ($resolvedVaultPath.TrimEnd('\', '/') -eq [System.IO.Path]::GetPathRoot($resolvedVaultPath).TrimEnd('\', '/')) {
        throw 'Choose a dedicated vault directory, not a drive or share root.'
    }

    $initArguments = @($launcher, 'init', '--vault', $resolvedVaultPath, '--project', $Project, '--project-id', $ProjectId)
    if (-not [string]::IsNullOrWhiteSpace($StateDir)) {
        $resolvedStateDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($StateDir)
        if ((Test-Path -LiteralPath $resolvedStateDir) -and -not (Test-Path -LiteralPath $resolvedStateDir -PathType Container)) {
            throw "StateDir must name a directory, not a file: '$resolvedStateDir'."
        }
        if ($resolvedStateDir.TrimEnd('\', '/') -eq [System.IO.Path]::GetPathRoot($resolvedStateDir).TrimEnd('\', '/')) {
            throw 'Choose a dedicated state directory, not a drive or share root.'
        }
        $vaultPrefix = $resolvedVaultPath.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
        $statePrefix = $resolvedStateDir.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
        if ($vaultPrefix.StartsWith($statePrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
            $statePrefix.StartsWith($vaultPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'Vault and state must be separate non-overlapping directories.'
        }
        $initArguments += @('--state-dir', $resolvedStateDir)
    }
    if ($Demo) {
        $initArguments += '--demo'
    }

    if (Test-Path -LiteralPath (Join-Path $kitRoot 'FILE_MANIFEST.json') -PathType Leaf) {
        & $pythonExecutable (Join-Path $PSScriptRoot 'verify_kit.py') $kitRoot
        if ($LASTEXITCODE -ne 0) { throw 'Kit manifest verification failed.' }
    }
    if ($SelfTest) {
        & $pythonExecutable $launcher self-test
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic installation self-test failed.' }
    }
    if ($PreflightOnly) {
        Write-Host 'Preflight passed. No target vault or state directory was created.'
        exit 0
    }
    Write-Host "Using Python $($versionOutput -join ' ') to initialize '$resolvedVaultPath'."
    & $pythonExecutable @initArguments
    $initExitCode = $LASTEXITCODE
    exit $initExitCode
}
catch {
    [Console]::Error.WriteLine("Work Context setup failed: $($_.Exception.Message)")
    exit 1
}
