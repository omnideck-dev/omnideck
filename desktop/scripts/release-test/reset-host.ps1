# Destructively returns a disposable Windows test computer to the state it was
# in before WSL, Podman, the omnideck desktop app, or the omnideck CLI had been
# used. Source trees, downloaded installers, and local build outputs are kept.
[CmdletBinding()]
param(
    [switch]$Inventory,
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$Restart,
    [switch]$PreserveWsl
)

$ErrorActionPreference = "Stop"
$ConfirmationText = if ($PreserveWsl) {
    "ERASE OMNIDECK AND PODMAN"
} else {
    "ERASE OMNIDECK PODMAN AND WSL"
}
$OptionalFeatures = @(
    "VirtualMachinePlatform",
    "Microsoft-Windows-Subsystem-Linux"
)
$StatePaths = @(
    (Join-Path $env:APPDATA "omnideck"),
    (Join-Path $env:APPDATA "omnideck-cli"),
    (Join-Path $env:APPDATA "containers"),
    (Join-Path $env:LOCALAPPDATA "omnideck-release-testing"),
    (Join-Path $env:LOCALAPPDATA "omnideck-release-testing-cache"),
    (Join-Path $env:LOCALAPPDATA "omnideck-cli"),
    (Join-Path $env:LOCALAPPDATA "Programs\omnideck"),
    (Join-Path $env:LOCALAPPDATA "Programs\Podman"),
    (Join-Path $env:LOCALAPPDATA "Podman"),
    (Join-Path $env:LOCALAPPDATA "containers"),
    (Join-Path $env:USERPROFILE ".config\omnideck-cli"),
    (Join-Path $env:USERPROFILE ".config\containers"),
    (Join-Path $env:USERPROFILE ".local\share\containers")
)

function Test-IsAdministrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
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
    return $Candidates | Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}

function Get-UninstallEntries {
    $Roots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    return Get-ItemProperty -Path $Roots -ErrorAction SilentlyContinue
}

function Get-WslDistributions {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        return @()
    }
    # Windows keeps a wsl.exe stub even after WSL is uninstalled. On Windows
    # PowerShell 5, the stub's expected stderr message becomes a terminating
    # error under the script-wide Stop preference unless it is relaxed here.
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $Output = & wsl.exe --list --quiet 2>$null
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        return @()
    }
    return @($Output | ForEach-Object {
        $Name = ($_ -replace "`0", "").Trim()
        if ($Name) { $Name }
    })
}

function Get-WslDistributionPackageFamilies {
    $Keys = Get-ItemProperty `
        -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss\*" `
        -ErrorAction SilentlyContinue
    return @($Keys | ForEach-Object { $_.PackageFamilyName } |
        Where-Object { $_ } | Sort-Object -Unique)
}

function Get-FeatureState {
    param([string]$Name)
    try {
        $Feature = Get-CimInstance -ClassName Win32_OptionalFeature `
            -Filter "Name='$Name'" -ErrorAction Stop
        if (-not $Feature) {
            return "absent"
        }
        switch ($Feature.InstallState) {
            1 { return "enabled" }
            2 { return "disabled" }
            3 { return "absent" }
            default { return "unknown" }
        }
    }
    catch {
        return "unknown"
    }
}

function Show-Inventory {
    $Entries = Get-UninstallEntries
    $Omnideck = @($Entries | Where-Object { $_.DisplayName -match "^omnideck(?:\s|$)" })
    $Podman = @($Entries | Where-Object { $_.DisplayName -like "*Podman*" })
    $WslPackage = @(Get-AppxPackage -Name "MicrosoftCorporationII.WindowsSubsystemForLinux" `
        -ErrorAction SilentlyContinue)
    $Distributions = @(Get-WslDistributions)
    $FeatureStates = @{}
    foreach ($Feature in $OptionalFeatures) {
        $FeatureStates[$Feature] = Get-FeatureState $Feature
    }
    $ExistingPaths = @($StatePaths | Where-Object { Test-Path -LiteralPath $_ })

    Write-Host "Fresh-user reset inventory$(if ($PreserveWsl) { ' (WSL preserved)' })"
    Write-Host "  omnideck application : $(if ($Omnideck) { 'REMOVE' } else { 'absent' })"
    Write-Host "  Podman package       : $(if ($Podman -or (Get-PodmanPath)) { 'REMOVE' } else { 'absent' })"
    Write-Host "  WSL package          : $(if ($PreserveWsl) { 'preserved' } elseif ($WslPackage) { 'REMOVE' } else { 'absent' })"
    foreach ($Feature in $OptionalFeatures) {
        Write-Host "  $Feature : $($FeatureStates[$Feature])$(if ($PreserveWsl) { ' (preserved)' })"
    }
    Write-Host "  WSL distributions:"
    if ($Distributions) {
        foreach ($Distribution in $Distributions) {
            Write-Host "    $(if ($PreserveWsl) { 'preserved' } else { 'REMOVE' }) $Distribution"
        }
    }
    else {
        Write-Host "    (none)"
    }
    Write-Host "  installed state directories:"
    if ($ExistingPaths) {
        foreach ($StatePath in $ExistingPaths) {
            Write-Host "    REMOVE $StatePath"
        }
    }
    else {
        Write-Host "    (none)"
    }
    Write-Host ""
    $FeaturesAreOff = $PreserveWsl -or @($FeatureStates.Values | Where-Object {
        $_ -notin @("disabled", "absent")
    }).Count -eq 0
    $IsClean = (-not $Omnideck) -and (-not $Podman) -and
        (-not (Get-PodmanPath)) -and
        ($PreserveWsl -or ((-not $WslPackage) -and (-not $Distributions))) -and
        (-not $ExistingPaths) -and $FeaturesAreOff
    Write-Host "Result: $(if ($IsClean) { 'CLEAN - ready for a fresh-user test' } else { 'NOT CLEAN - run the reset and restart Windows' })"
    Write-Host "Repositories, installers, and local build outputs are not touched."
}

function Start-ElevatedReset {
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath)
    )
    # The destructive confirmation was already completed before elevation.
    $Arguments += "-Yes"
    if ($Restart) { $Arguments += "-Restart" }
    if ($PreserveWsl) { $Arguments += "-PreserveWsl" }
    Write-Host "Windows will ask for approval so installed software can be removed."
    $Process = Start-Process -FilePath "powershell.exe" -Verb RunAs `
        -ArgumentList $Arguments -Wait -PassThru
    exit $Process.ExitCode
}

function Invoke-BestEffort {
    param(
        [string]$Description,
        [scriptblock]$Action
    )
    try {
        & $Action
    }
    catch {
        Write-Warning "$Description failed: $($_.Exception.Message)"
    }
}

function Remove-InstalledProduct {
    param(
        [Parameter(Mandatory)]$Entry,
        [Parameter(Mandatory)][string]$Label
    )
    if ($Entry.PSChildName -notmatch "^\{[0-9A-Fa-f-]+\}$") {
        throw "$Label is not registered as an MSI. Remove it from Settings > Apps, then run this reset again."
    }
    Write-Host "Uninstalling $($Entry.DisplayName)..."
    $Removal = Start-Process -FilePath "msiexec.exe" `
        -ArgumentList @("/x", $Entry.PSChildName, "/passive", "/norestart") `
        -Wait -PassThru
    if ($Removal.ExitCode -notin @(0, 1605, 3010)) {
        throw "$Label could not be uninstalled (Windows Installer code $($Removal.ExitCode)). Remove it from Settings > Apps, then run this reset again."
    }
}

function Remove-VerifiedStateDirectory {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $FullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $AllowedRoots = @($env:APPDATA, $env:LOCALAPPDATA, $env:USERPROFILE) |
        ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') }
    $Allowed = $false
    foreach ($Root in $AllowedRoots) {
        if ($FullPath.StartsWith(
            "$Root\",
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $Allowed = $true
            break
        }
    }
    if (-not $Allowed) {
        throw "Refusing to recursively remove unexpected path: $FullPath"
    }
    Write-Host "Removing $FullPath"
    Remove-Item -LiteralPath $FullPath -Recurse -Force
}

if ($Inventory) {
    Show-Inventory
    return
}

Show-Inventory
if ($PreserveWsl) {
    Write-Host "This reset permanently deletes Podman machines/containers/images/volumes"
    Write-Host "and all installed omnideck state. WSL itself and non-Podman distributions are preserved."
} else {
    Write-Host "This reset permanently deletes every WSL distribution, every Podman"
    Write-Host "machine/container/image/volume, and all installed omnideck state."
}
Write-Host ""

if ($DryRun) {
    Write-Host "Dry run: nothing was changed."
    return
}

if (-not $Yes) {
    $Answer = Read-Host "Type '$ConfirmationText' to continue"
    if ($Answer -ne $ConfirmationText) {
        Write-Host "Cancelled. Nothing was changed."
        return
    }
}

if (-not (Test-IsAdministrator)) {
    Start-ElevatedReset
}

$PodmanPath = Get-PodmanPath
if ($PodmanPath) {
    $Machines = @(& $PodmanPath machine list --format "{{.Name}}" 2>$null |
        ForEach-Object { $_.Trim().TrimEnd('*') } |
        Where-Object { $_ })
    foreach ($Machine in $Machines) {
        Write-Host "Stopping Podman machine $Machine..."
        & $PodmanPath machine stop $Machine *> $null
        if ($PreserveWsl) {
            Write-Host "Deleting Podman machine $Machine..."
            & $PodmanPath machine rm --force $Machine *> $null
        }
    }
}

Invoke-BestEffort "Stopping WSL" { & wsl.exe --shutdown *> $null }

if (-not $PreserveWsl) {
    $WslDistributionPackageFamilies = @(Get-WslDistributionPackageFamilies)
    foreach ($Distribution in @(Get-WslDistributions)) {
        Write-Host "Deleting WSL distribution $Distribution..."
        & wsl.exe --unregister $Distribution
        if ($LASTEXITCODE -ne 0) {
            throw "WSL could not delete '$Distribution'. Restart Windows and run the reset again."
        }
    }

    if ($WslDistributionPackageFamilies) {
        $DistributionPackages = @(Get-AppxPackage -ErrorAction SilentlyContinue |
            Where-Object {
                $WslDistributionPackageFamilies -contains $_.PackageFamilyName
            })
        foreach ($Package in $DistributionPackages) {
            Write-Host "Uninstalling WSL distribution app $($Package.Name)..."
            $Package | Remove-AppxPackage -ErrorAction Stop
        }
    }
}

Get-Process -Name "omnideck", "gvproxy", "win-sshproxy" `
    -ErrorAction SilentlyContinue | Stop-Process -Force

$ExpectedOmnideckUninstaller = Join-Path $env:LOCALAPPDATA `
    "Programs\omnideck\Uninstall omnideck.exe"
if (Test-Path -LiteralPath $ExpectedOmnideckUninstaller) {
    Write-Host "Uninstalling omnideck..."
    $Removal = Start-Process -FilePath $ExpectedOmnideckUninstaller `
        -ArgumentList @("/currentuser", "/S") -Wait -PassThru
    if ($Removal.ExitCode -notin @(0, 3010)) {
        throw "omnideck could not be uninstalled (code $($Removal.ExitCode)). Remove it from Settings > Apps, then run this reset again."
    }
}

$Entries = Get-UninstallEntries
$PodmanEntries = @($Entries | Where-Object { $_.DisplayName -like "*Podman*" })
foreach ($Entry in $PodmanEntries) {
    Remove-InstalledProduct -Entry $Entry -Label "Podman"
}

foreach ($StatePath in $StatePaths) {
    Remove-VerifiedStateDirectory -Path $StatePath
}

Remove-ItemProperty `
    -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" `
    -Name "omnideckSetupResume" `
    -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:APPDATA `
    "Microsoft\Windows\Start Menu\Programs\omnideck.lnk") `
    -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:USERPROFILE "Desktop\omnideck.lnk") `
    -Force -ErrorAction SilentlyContinue

if (-not $PreserveWsl -and (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Host "Uninstalling the WSL package..."
    & wsl.exe --uninstall
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The WSL package did not uninstall cleanly. The Windows features will still be disabled; run the reset again after restarting if Inventory still shows WSL installed."
    }
}

if (-not $PreserveWsl) {
    $WslPackages = @(Get-AppxPackage `
        -Name "MicrosoftCorporationII.WindowsSubsystemForLinux" `
        -ErrorAction SilentlyContinue)
    foreach ($Package in $WslPackages) {
        Invoke-BestEffort "Removing the remaining WSL app package" {
            $Package | Remove-AppxPackage -ErrorAction Stop
        }
    }

    foreach ($Feature in $OptionalFeatures) {
        Write-Host "Disabling Windows feature $Feature..."
        $FeatureRemoval = Start-Process -FilePath "dism.exe" -ArgumentList @(
            "/online",
            "/disable-feature",
            "/featurename:$Feature",
            "/norestart"
        ) -Wait -PassThru
        if ($FeatureRemoval.ExitCode -notin @(0, 3010)) {
            throw "Windows could not disable $Feature (DISM code $($FeatureRemoval.ExitCode)). Install pending Windows updates, restart, and run the reset again."
        }
    }
}

Write-Host ""
Write-Host "Reset complete.$(if (-not $PreserveWsl) { ' Windows must restart before this is a valid fresh-user test.' })"
Write-Host "After sign-in, run this script with -Inventory to verify the clean state."

if ($Restart) {
    Write-Host "Restarting Windows now..."
    Restart-Computer -Force
}
else {
    Write-Host "Restart when ready, or rerun with -Yes -Restart to restart automatically."
}
