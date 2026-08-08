[CmdletBinding()]
param(
    [string]$Release = "latest",
    [ValidateSet("Keep", "FirstRun", "Resume", "Update", "Doctor", "Returning")]
    [string]$Scenario = "Keep",
    [ValidateSet("Auto", "x64", "arm64")]
    [string]$Architecture = "Auto",
    [switch]$Yes,
    [switch]$ResetOnly,
    [switch]$Smoke,
    [switch]$RequireReady
)

$ErrorActionPreference = "Stop"
$Repository = "omnideck-dev/omnideck"
$SyntheticImageRef = "ghcr.io/omnideck-dev/omnideck@sha256:" + ("0" * 64)
$MachineName = "omnideck-runtime"
$ContainerName = "omnideck-desktop"
$HomeVolumeName = "omnideck-desktop-home"
$StateVolumeName = "omnideck-desktop-state"
$ConfirmationText = "RESET OMNIDECK"
if ($RequireReady) { $Smoke = $true }

if (-not $ResetOnly) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI (gh) is required."
    }
    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run: gh auth login"
    }
}

function Select-ReleaseTag {
    param([string]$Requested)

    $Releases = & gh release list `
        --repo $Repository `
        --limit 20 `
        --json tagName,publishedAt,isDraft | ConvertFrom-Json |
        Where-Object { -not $_.isDraft } |
        Sort-Object publishedAt -Descending

    if ($Requested -eq "choose") {
        $Releases | Select-Object -First 10 tagName,publishedAt | Format-Table | Out-Host
        $Selected = Read-Host "Release tag"
    }
    elseif ($Requested -eq "latest") {
        $Selected = $Releases | Select-Object -First 1 -ExpandProperty tagName
    }
    else {
        $Selected = $Requested
    }

    if ($Selected -notmatch "^v[0-9A-Za-z._-]+$") {
        throw "Could not select a valid release tag."
    }
    return $Selected
}

function Get-PodmanPath {
    $Command = Get-Command podman -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Podman\podman.exe"),
        (Join-Path $env:ProgramFiles "Podman\podman.exe"),
        (Join-Path $env:ProgramFiles "RedHat\Podman\podman.exe")
    )
    return $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Invoke-PodmanCleanup {
    param(
        [string[]]$Arguments,
        [switch]$Engine
    )
    $Podman = Get-PodmanPath
    if (-not $Podman) {
        return
    }
    if ($Engine) {
        $Arguments = @("--connection", $MachineName) + $Arguments
    }
    & $Podman @Arguments *> $null
}

function Remove-TestContainer {
    Invoke-PodmanCleanup @("rm", "--force", $ContainerName) -Engine
}

function Remove-TestResources {
    Remove-TestContainer
    Invoke-PodmanCleanup @(
        "volume", "rm", "--force",
        $HomeVolumeName,
        $StateVolumeName
    ) -Engine
    Invoke-PodmanCleanup @("machine", "stop", $MachineName)
    Invoke-PodmanCleanup @("machine", "rm", "--force", $MachineName)
}

function Confirm-TestReset {
    param([string]$Description)
    if ($Yes) {
        return
    }
    Write-Host $Description
    $Answer = Read-Host "Type '$ConfirmationText' to continue"
    if ($Answer -ne $ConfirmationText) {
        Write-Host "Cancelled."
        exit 0
    }
}

function Write-TestSetupState {
    param(
        [string]$ProfileRoot,
        [string]$Status,
        [string]$Reason
    )
    New-Item -ItemType Directory -Path $ProfileRoot -Force | Out-Null
    $State = [ordered]@{
        schemaVersion = 1
        status = $Status
        reason = $Reason
        appVersion = "test-script"
        imageRef = $SyntheticImageRef
        imageDigest = "sha256:" + ("0" * 64)
        updatedAt = "test-script"
    } | ConvertTo-Json
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        (Join-Path $ProfileRoot "setup-state.json"),
        "$State`n",
        $Encoding
    )
}

function Require-CompletedSetup {
    param([string]$ProfileRoot)
    $StatePath = Join-Path $ProfileRoot "setup-state.json"
    if (-not (Test-Path -LiteralPath $StatePath)) {
        throw "This scenario needs a completed test profile first."
    }
    try {
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    }
    catch {
        throw "The selected profile does not contain valid setup state."
    }
    if ($State.status -ne "complete") {
        throw "This scenario needs a completed test profile first."
    }
}

$CacheRoot = Join-Path $env:LOCALAPPDATA "omnideck-release-testing-cache"
$ProfileRoot = [System.IO.Path]::GetFullPath((Join-Path $env:APPDATA "omnideck"))
$ExpectedProfileRoot = [System.IO.Path]::GetFullPath("$env:APPDATA\omnideck")
if (-not $ProfileRoot.Equals(
    $ExpectedProfileRoot,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to modify unexpected application state path: $ProfileRoot"
}

$SelectedRelease = if ($ResetOnly) { $null } else { Select-ReleaseTag $Release }

switch ($Scenario) {
    "FirstRun" {
        Confirm-TestReset "This removes the normal omnideck container, machine, volumes, and application state. Nothing is isolated or preserved."
        Remove-TestResources
        if (Test-Path -LiteralPath $ProfileRoot) {
            Remove-Item -LiteralPath $ProfileRoot -Recurse -Force
        }
    }
    "Resume" {
        Confirm-TestReset "This removes the normal omnideck container and marks setup interrupted."
        Remove-TestContainer
        Write-TestSetupState $ProfileRoot "in-progress" "first-run"
    }
    "Update" {
        Require-CompletedSetup $ProfileRoot
        Confirm-TestReset "This removes the normal omnideck container and marks its pinned environment as older."
        Remove-TestContainer
        Write-TestSetupState $ProfileRoot "complete" "first-run"
    }
    "Doctor" {
        Require-CompletedSetup $ProfileRoot
        Confirm-TestReset "This removes the normal omnideck container so the next launch opens diagnostics."
        Remove-TestContainer
    }
    "Returning" {
        Require-CompletedSetup $ProfileRoot
    }
}

if ($ResetOnly) {
    Write-Host "Reset complete. No release was downloaded or installed."
    exit 0
}

$ReleaseCache = Join-Path $CacheRoot "releases\$SelectedRelease\windows"
New-Item -ItemType Directory -Path $ReleaseCache -Force | Out-Null
$HostArchitecture = switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) {
    "Arm64" { "arm64" }
    "X64" { "x64" }
    default { throw "Published Windows builds do not support this host architecture." }
}
if ($Architecture -eq "Auto") {
    $Architecture = $HostArchitecture
}
elseif ($Architecture -ne $HostArchitecture) {
    throw "Requested $Architecture package does not match this native $HostArchitecture host."
}
& gh release download $SelectedRelease `
    --repo $Repository `
    --pattern "omnideck_*_${Architecture}-setup.exe" `
    --pattern "omnideck_*_${Architecture}-setup.exe.sha256" `
    --dir $ReleaseCache `
    --skip-existing
if ($LASTEXITCODE -ne 0) {
    throw "The selected Windows release could not be downloaded."
}

$Artifact = Get-ChildItem -LiteralPath $ReleaseCache -Filter "omnideck_*_${Architecture}-setup.exe" |
    Select-Object -First 1
if (-not $Artifact) {
    throw "The selected release does not contain a Windows $Architecture installer."
}
$ChecksumPath = "$($Artifact.FullName).sha256"
$ExpectedHash = ((Get-Content -LiteralPath $ChecksumPath -Raw).Trim() -split "\s+")[0]
$ActualHash = (Get-FileHash -LiteralPath $Artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedHash.ToLowerInvariant() -ne $ActualHash) {
    throw "The downloaded installer did not match its published SHA-256 checksum."
}
& gh attestation verify $Artifact.FullName --repo $Repository
if ($LASTEXITCODE -ne 0) {
    throw "The downloaded installer did not have valid GitHub provenance."
}

Write-Host "Installing $SelectedRelease..."
$Installer = Start-Process -FilePath $Artifact.FullName -ArgumentList "/S" -Wait -PassThru
if ($Installer.ExitCode -ne 0) {
    throw "The Windows installer exited with code $($Installer.ExitCode)."
}

# The one-click installer launches the application itself. Stop that instance so
# the selected scenario always begins at the controlled launch below.
$AutoLaunched = Get-Process -Name "omnideck" -ErrorAction SilentlyContinue
if ($AutoLaunched) {
    Write-Host "Stopping the instance started by the installer before the controlled launch."
    $AutoLaunched | Stop-Process -Force
    # The single-instance lock is released as the process exits.
    Start-Sleep -Seconds 2
}

$ExpectedApplications = @(
    (Join-Path $env:LOCALAPPDATA "omnideck\omnideck.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\omnideck\omnideck.exe")
)
$Application = $ExpectedApplications |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $Application) {
    $Application = Get-ChildItem `
        -LiteralPath (Join-Path $env:LOCALAPPDATA "Programs") `
        -Filter "omnideck.exe" `
        -File `
        -Recurse `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Application) {
    throw "The installed omnideck application could not be found."
}

Write-Host "Launching $SelectedRelease with scenario '$Scenario' using normal user state."
if ($Smoke) {
    $SmokeArguments = @{
        Application = $Application
    }
    if ($RequireReady) { $SmokeArguments.RequireReady = $true }
    & (Join-Path $PSScriptRoot "..\..\tests\hardware\run.ps1") @SmokeArguments
    exit 0
}
Start-Process -FilePath $Application -Wait
