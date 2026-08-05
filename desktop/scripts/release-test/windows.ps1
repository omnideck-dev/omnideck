[CmdletBinding()]
param(
    [string]$Release = "latest",
    [ValidateSet("Keep", "FirstRun", "Resume", "Update", "Doctor", "Returning")]
    [string]$Scenario = "Keep",
    [Alias("Profile")]
    [string]$TestProfile = "default",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Repository = "omnideck-dev/omnideck"
$SyntheticImageRef = "ghcr.io/omnideck-dev/omnideck@sha256:" + ("0" * 64)

if ($TestProfile -notmatch "^[a-z0-9][a-z0-9-]{0,17}$") {
    throw "Profile names may contain up to 18 lowercase letters, numbers, and hyphens."
}
$TestNamespace = "release-test-$TestProfile"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is required."
}
$GitHubConfigDirectory = $env:GH_CONFIG_DIR
if (-not $GitHubConfigDirectory) {
    $GitHubConfigDirectory = Join-Path $env:APPDATA "GitHub CLI"
}
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated. Run: gh auth login"
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

function Assert-IsolatedRelease {
    param([string]$Selected)
    if ($Selected -match "^v0\.1\.0-alpha\.(\d+)$" -and [int]$Matches[1] -lt 4) {
        throw "Release $Selected predates isolated release-test resources. Choose v0.1.0-alpha.4 or newer."
    }
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
    param([string[]]$Arguments)
    $Podman = Get-PodmanPath
    if (-not $Podman) {
        return
    }
    & $Podman @Arguments *> $null
}

function Remove-TestContainer {
    Invoke-PodmanCleanup @("rm", "--force", "omnideck-desktop-$TestNamespace")
}

function Remove-TestResources {
    Remove-TestContainer
    Invoke-PodmanCleanup @(
        "volume", "rm", "--force",
        "omnideck-desktop-home-$TestNamespace",
        "omnideck-desktop-state-$TestNamespace"
    )
    Invoke-PodmanCleanup @("machine", "stop", "omnideck-runtime-$TestNamespace")
    Invoke-PodmanCleanup @("machine", "rm", "--force", "omnideck-runtime-$TestNamespace")
}

function Confirm-TestReset {
    param([string]$Description)
    if ($Yes) {
        return
    }
    Write-Host $Description
    $Answer = Read-Host "Type $TestNamespace to continue"
    if ($Answer -ne $TestNamespace) {
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

$StateRoot = Join-Path $env:LOCALAPPDATA "omnideck-release-testing"
$CacheRoot = Join-Path $env:LOCALAPPDATA "omnideck-release-testing-cache"
$ProfilesRoot = Join-Path $StateRoot "profiles"
$ProfileRoot = Join-Path $ProfilesRoot $TestProfile
$ExpectedPrefix = [System.IO.Path]::GetFullPath($ProfilesRoot) +
    [System.IO.Path]::DirectorySeparatorChar
if (-not [System.IO.Path]::GetFullPath($ProfileRoot).StartsWith(
    $ExpectedPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to modify a profile outside $ProfilesRoot"
}

$env:OMNIDECK_DESKTOP_USER_DATA = $ProfileRoot
$env:OMNIDECK_DESKTOP_TEST_NAMESPACE = $TestNamespace
$env:GH_CONFIG_DIR = $GitHubConfigDirectory
$env:XDG_CACHE_HOME = Join-Path $ProfileRoot "runtime\cache"
$env:XDG_CONFIG_HOME = Join-Path $ProfileRoot "runtime\config"
$env:XDG_DATA_HOME = Join-Path $ProfileRoot "runtime\data"
$env:REGISTRY_AUTH_FILE = Join-Path $ProfileRoot "runtime\auth\auth.json"

$SelectedRelease = Select-ReleaseTag $Release
Assert-IsolatedRelease $SelectedRelease

switch ($Scenario) {
    "FirstRun" {
        Confirm-TestReset "This removes only the isolated $TestNamespace container, machine, volumes, and profile at: $ProfileRoot"
        Remove-TestResources
        if (Test-Path -LiteralPath $ProfileRoot) {
            Remove-Item -LiteralPath $ProfileRoot -Recurse -Force
        }
    }
    "Resume" {
        Confirm-TestReset "This removes the isolated test container, preserves cached work and volumes, and marks setup interrupted."
        Remove-TestContainer
        Write-TestSetupState $ProfileRoot "in-progress" "first-run"
    }
    "Update" {
        Require-CompletedSetup $ProfileRoot
        Confirm-TestReset "This removes the isolated test container, preserves its volumes, and marks the pinned environment as older."
        Remove-TestContainer
        Write-TestSetupState $ProfileRoot "complete" "first-run"
    }
    "Doctor" {
        Require-CompletedSetup $ProfileRoot
        Confirm-TestReset "This removes only the isolated test container so the next launch opens diagnostics."
        Remove-TestContainer
    }
    "Returning" {
        Require-CompletedSetup $ProfileRoot
    }
}

$ReleaseCache = Join-Path $CacheRoot "releases\$SelectedRelease\windows"
New-Item -ItemType Directory -Path $ReleaseCache -Force | Out-Null
& gh release download $SelectedRelease `
    --repo $Repository `
    --pattern "omnideck-*-win-x64.exe" `
    --pattern "omnideck-*-win-x64.exe.sha256" `
    --dir $ReleaseCache `
    --skip-existing
if ($LASTEXITCODE -ne 0) {
    throw "The selected Windows release could not be downloaded."
}

$Artifact = Get-ChildItem -LiteralPath $ReleaseCache -Filter "omnideck-*-win-x64.exe" |
    Select-Object -First 1
if (-not $Artifact) {
    throw "The selected release does not contain a Windows x64 installer."
}
$ChecksumPath = "$($Artifact.FullName).sha256"
$ExpectedHash = ((Get-Content -LiteralPath $ChecksumPath -Raw).Trim() -split "\s+")[0]
$ActualHash = (Get-FileHash -LiteralPath $Artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedHash.ToLowerInvariant() -ne $ActualHash) {
    throw "The downloaded installer did not match its published SHA-256 checksum."
}

Write-Host "Installing $SelectedRelease..."
$Installer = Start-Process -FilePath $Artifact.FullName -ArgumentList "/S" -Wait -PassThru
if ($Installer.ExitCode -ne 0) {
    throw "The Windows installer exited with code $($Installer.ExitCode)."
}

# The one-click installer launches the application itself, before this script
# has applied the test profile. That instance holds the single-instance lock, so
# the launch below would only focus it and the run would silently exercise the
# normal profile instead of the isolated one.
$AutoLaunched = Get-Process -Name "omnideck" -ErrorAction SilentlyContinue
if ($AutoLaunched) {
    Write-Host "Stopping the instance started by the installer so the test profile applies."
    $AutoLaunched | Stop-Process -Force
    # The single-instance lock is released as the process exits.
    Start-Sleep -Seconds 2
}

$ExpectedApplications = @(
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

Write-Host "Launching $SelectedRelease with scenario '$Scenario' and profile '$TestProfile'."
Start-Process -FilePath $Application -Wait
