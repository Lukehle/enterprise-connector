# Runs one explicit sync. No scheduling, credential storage, or setup changes.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $ConfigPath,

    [ValidateNotNullOrEmpty()]
    [string] $Python = 'python',

    [ValidatePattern('^TASK-[0-9]{3,}$')]
    [string] $Task = 'TASK-001'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Preserve the CLI's exit code even when a PowerShell 7 profile enables native errors.
$PSNativeCommandUseErrorActionPreference = $false

try {
    $launcher = Join-Path -Path (Split-Path -Parent $PSScriptRoot) -ChildPath 'work-context.py'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "The kit launcher was not found at '$launcher'. Keep this script in the kit's scripts directory."
    }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "ConfigPath must name an existing configuration file: '$ConfigPath'."
    }
    $resolvedConfigPath = (Resolve-Path -LiteralPath $ConfigPath).ProviderPath
    $pythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pythonCommand) {
        throw "Python was not found. Use -Python with the path to an approved Python 3.11 or newer executable."
    }

    $syncArguments = @($launcher, '--config', $resolvedConfigPath, 'sync', '--task', $Task)
    & $pythonCommand.Source @syncArguments
    $syncExitCode = $LASTEXITCODE
    exit $syncExitCode
}
catch {
    [Console]::Error.WriteLine("Work Context sync failed: $($_.Exception.Message)")
    exit 1
}
