# Returns this computer to a pre-install state so the desktop application can be
# tested from scratch: podman is uninstalled and the isolated test machine is
# destroyed. Containers, volumes and images belonging to anything else stay
# exactly where they are.
[CmdletBinding()]
param(
    [Alias("Profile")]
    [string]$TestProfile = "default",
    [switch]$IncludeWsl,
    [switch]$Inventory,
    [switch]$DryRun,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

if ($TestProfile -notmatch "^[a-z0-9][a-z0-9-]{0,17}$") {
    throw "Profile names may contain up to 18 lowercase letters, numbers, and hyphens."
}
$TestNamespace = "release-test-$TestProfile"

# Everything the reset may destroy is derived from the namespace. A name that is
# not one of these belongs to somebody else and is never touched.
$TestResources = @(
    "omnideck-desktop-$TestNamespace",
    "omnideck-desktop-home-$TestNamespace",
    "omnideck-desktop-state-$TestNamespace",
    "omnideck-runtime-$TestNamespace"
)

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

# Prints every container, volume and machine and marks which a reset removes.
# This is the check that matters before running anything destructive: if a name
# you care about is listed as preserved, it stays.
function Show-ResourceInventory {
    $Podman = Get-PodmanPath
    if (-not $Podman) {
        Write-Host "Podman is not installed, so there is nothing to inventory."
        return
    }

    $Groups = @(
        @{ Label = "containers"; Arguments = @("ps", "--all", "--format", "{{.Names}}") },
        @{ Label = "volumes"; Arguments = @("volume", "ls", "--format", "{{.Name}}") },
        @{ Label = "machines"; Arguments = @("machine", "list", "--format", "{{.Name}}") }
    )
    foreach ($Group in $Groups) {
        Write-Host "$($Group.Label):"
        $Names = & $Podman @($Group.Arguments) 2>$null
        if (-not $Names) {
            Write-Host "  (none)"
            continue
        }
        foreach ($Name in $Names) {
            # podman marks the active machine with a trailing asterisk.
            $Trimmed = $Name.Trim().TrimEnd("*")
            if (-not $Trimmed) { continue }
            if ($TestResources -contains $Trimmed) {
                Write-Host "  REMOVE    $Trimmed"
            }
            else {
                Write-Host "  preserved $Trimmed"
            }
        }
    }
}

function Get-PodmanUninstallCommand {
    $Roots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    return Get-ItemProperty -Path $Roots -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like "*Podman*" } |
        Select-Object -First 1
}

if ($Inventory) {
    Show-ResourceInventory
    return
}

Write-Host "Resources on this host:"
Show-ResourceInventory
Write-Host ""
Write-Host "A reset removes only the entries marked REMOVE above, then uninstalls"
Write-Host "podman itself. Container storage is left in place, so anything marked"
Write-Host "preserved comes back when podman is reinstalled."
if ($IncludeWsl) {
    Write-Host ""
    Write-Host "WSL will also be uninstalled. Registered Linux distributions are kept:"
    Write-Host "this removes the WSL feature, never a distribution's disk."
}
Write-Host ""

if ($DryRun) {
    Write-Host "Dry run: nothing was changed."
    return
}

if (-not $Yes) {
    $Answer = Read-Host "Type $TestNamespace to continue"
    if ($Answer -ne $TestNamespace) {
        Write-Host "Cancelled."
        return
    }
}

$Podman = Get-PodmanPath
if (-not $Podman) {
    Write-Host "Podman is already absent; nothing to uninstall."
}
else {
    # The test machine is its own WSL distribution, so removing it leaves every
    # other distribution registered. It has to go before the binary that manages
    # it does.
    & $Podman machine stop "omnideck-runtime-$TestNamespace" *> $null
    & $Podman machine rm --force "omnideck-runtime-$TestNamespace" *> $null

    $Uninstall = Get-PodmanUninstallCommand
    if (-not $Uninstall) {
        throw "Podman is on PATH but has no uninstall entry. Remove it from Settings, then run this script again."
    }
    Write-Host "Uninstalling $($Uninstall.DisplayName)..."
    if ($Uninstall.PSChildName -match "^\{[0-9A-Fa-f-]+\}$") {
        $Removal = Start-Process -FilePath "msiexec.exe" `
            -ArgumentList @("/x", $Uninstall.PSChildName, "/passive", "/norestart") `
            -Wait -PassThru
        if ($Removal.ExitCode -notin @(0, 1605, 3010)) {
            throw "The podman uninstaller exited with code $($Removal.ExitCode)."
        }
    }
    else {
        throw "Podman was installed by something other than an MSI. Remove it from Settings, then run this script again."
    }
}

if ($IncludeWsl) {
    # `wsl --uninstall` removes the WSL application and leaves registered
    # distributions on disk. `--unregister` would delete a distribution outright
    # and is never used here.
    Write-Host "Uninstalling WSL (registered distributions are kept)..."
    & wsl.exe --uninstall
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "WSL could not be uninstalled automatically. Remove it from Settings if a fully clean run is needed."
    }
}

Write-Host "Done. The next launch will install its prerequisites from scratch."
