[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Application,
    [string]$OutputDirectory = $env:OMNIDECK_DESKTOP_SMOKE_OUTPUT_DIR,
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 45,
    [switch]$RequireReady
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopRoot = (Resolve-Path (Join-Path $ScriptRoot "..\..")).Path
$ApplicationPath = (Resolve-Path -LiteralPath $Application).Path
if (-not $OutputDirectory) {
    $RunId = if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { "local-$PID" }
    $OutputDirectory = Join-Path $DesktopRoot "..\artifacts\desktop-hardware\windows-$RunId"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$ProofPath = Join-Path $OutputDirectory "smoke-proof.json"
$ReportPath = Join-Path $OutputDirectory "report.json"
$StdoutPath = Join-Path $OutputDirectory "host.stdout.log"
$StderrPath = Join-Path $OutputDirectory "host.stderr.log"
$UserDataPath = Join-Path $OutputDirectory "user-data"
New-Item -ItemType Directory -Path $UserDataPath -Force | Out-Null
Remove-Item -LiteralPath $ProofPath -Force -ErrorAction SilentlyContinue

if (Get-Process -Name "omnideck" -ErrorAction SilentlyContinue) {
    throw "Close every existing omnideck process before running packaged smoke."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required to validate the packaged smoke proof."
}

$EnvironmentNames = @("OMNIDECK_DESKTOP_SMOKE_FILE", "OMNIDECK_DESKTOP_USER_DATA")
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

$Process = $null
try {
    [Environment]::SetEnvironmentVariable("OMNIDECK_DESKTOP_SMOKE_FILE", $ProofPath, "Process")
    [Environment]::SetEnvironmentVariable("OMNIDECK_DESKTOP_USER_DATA", $UserDataPath, "Process")
    $Process = Start-Process `
        -FilePath $ApplicationPath `
        -PassThru `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not (Test-Path -LiteralPath $ProofPath)) {
        if ($Process.HasExited) {
            throw "The desktop host exited before writing a packaged smoke proof (exit $($Process.ExitCode))."
        }
        if ([DateTime]::UtcNow -ge $Deadline) {
            throw "The desktop host did not write a packaged smoke proof within $TimeoutSeconds seconds."
        }
        Start-Sleep -Milliseconds 250
    }

    $Arguments = @(
        (Join-Path $ScriptRoot "validate-proof.mjs"),
        "--proof", $ProofPath,
        "--application", $ApplicationPath,
        "--report", $ReportPath
    )
    if ($RequireReady) { $Arguments += "--require-ready" }
    & node @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "The packaged smoke proof was invalid."
    }
}
finally {
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(5000) | Out-Null
    }
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], "Process")
    }
}

Write-Host "Evidence: $ReportPath"
