[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Prepare", "Driver", "ConfigureClean", "Runtime", "RuntimePreserve", "RunOnceProof", "SetupStatus", "Doctor", "Resume", "Update", "PortConflict", "VerifyPortConflict", "CustomAppFixture", "HostBoundaryDownload", "SeedArtifact", "HostBoundaryArtifactDownload", "SeedUpdateFixture", "PromoteUpdateFixture", "Final")]
    [string]$Phase,
    [Parameter(Mandatory = $true)]
    [string]$WorkDir,
    [string]$ArtifactSha256,
    [string]$ExpectedCliVersion,
    [string]$ExpectedCliCommit,
    [string]$FixtureName,
    [string]$FixtureFilename,
    [string]$ArtifactFilename
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$WorkDir = [System.IO.Path]::GetFullPath($WorkDir)
$Results = Join-Path $WorkDir "results"
$UserData = Join-Path $WorkDir "user-data"
$CliConfig = Join-Path $WorkDir "cli-config"
$Installer = Join-Path $WorkDir "candidate-setup.exe"
$ApplicationFile = Join-Path $WorkDir "application-path.txt"
$StatePath = Join-Path $UserData "setup-state.json"
$TestNamespace = ([System.IO.Path]::GetFileName($WorkDir).ToLowerInvariant() -replace '[^a-z0-9-]', '')
if ($TestNamespace.Length -gt 40) { $TestNamespace = $TestNamespace.Substring(0, 40) }
if (-not $TestNamespace) { throw "The Windows test namespace is empty after normalization." }
$ContainerName = "omnideck-desktop-$TestNamespace"
$HomeVolume = "omnideck-desktop-home-$TestNamespace"
$StateVolume = "omnideck-desktop-state-$TestNamespace"
$MachineName = "odrt-$TestNamespace"

New-Item -ItemType Directory -Path $Results,$UserData,$CliConfig -Force | Out-Null
$env:OMNIDECK_CONFIG_DIR = $CliConfig

function Get-PodmanPath {
    $Command = Get-Command podman.exe -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Podman\podman.exe"),
        (Join-Path $env:ProgramFiles "Podman\podman.exe"),
        (Join-Path $env:ProgramFiles "RedHat\Podman\podman.exe")
    )
    return $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Invoke-Engine {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $Podman = Get-PodmanPath
    if (-not $Podman) { throw "Podman is not installed." }
    & $Podman --connection $MachineName @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Podman command failed: $($Arguments -join ' ')"
    }
}

function Start-PodmanMachine {
    $Podman = Get-PodmanPath
    if (-not $Podman) { throw "Podman is not installed." }
    $Log = Join-Path $Results "podman-machine-start.txt"
    $Distribution = "podman-$MachineName"
    $HostDns = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" |
        Where-Object { $_.NextHop -and $_.NextHop -ne "0.0.0.0" } |
        Sort-Object RouteMetric,InterfaceMetric |
        ForEach-Object {
            (Get-DnsClientServerAddress -AddressFamily IPv4 -InterfaceIndex $_.InterfaceIndex).ServerAddresses
        } |
        Where-Object { $_ -and $_ -ne "127.0.0.1" -and $_ -ne "192.168.127.1" } |
        Select-Object -First 1
    if (-not $HostDns) { throw "The Windows default-route DNS server was not found." }
    $ResolverUpdated = $false
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Podman machine start $MachineName *>> $Log
        $Deadline = [DateTime]::UtcNow.AddMinutes(3)
        while ([DateTime]::UtcNow -lt $Deadline) {
            & $Podman --connection $MachineName info *> $null
            if ($LASTEXITCODE -eq 0) {
                if (-not $ResolverUpdated) {
                    # Podman's user-mode WSL resolver can be written with the
                    # unreachable 192.168.127.1 proxy. Pin the VM guest's real
                    # default-route DNS in a regular resolv.conf and disable
                    # WSL regeneration so it stays valid for the whole journey.
                    $ResolverCommand = "printf '[network]\ngenerateResolvConf=false\n' > /etc/wsl.conf; rm -f /etc/resolv.conf; printf 'nameserver $HostDns\noptions timeout:2 attempts:3\n' > /etc/resolv.conf"
                    & wsl.exe -d $Distribution -u root -- sh -c $ResolverCommand *>> $Log
                    $ResolverUpdated = $true
                }
                & wsl.exe -d $Distribution -u root -- getent hosts ghcr.io *>> $Log
                if ($LASTEXITCODE -eq 0) {
                    & wsl.exe -d $Distribution -u root -- cat /etc/resolv.conf *>> $Log
                    return
                }
            }
            Start-Sleep -Seconds 2
        }
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
    throw "Podman machine $MachineName did not become ready."
}

function Remove-CheckpointResources {
    $Podman = Get-PodmanPath
    if (-not $Podman) { throw "Podman is not installed." }
    $Log = Join-Path $Results "preflight.txt"
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Podman --connection $MachineName rm --force $ContainerName *>> $Log
        & $Podman --connection $MachineName volume rm --force $HomeVolume $StateVolume *>> $Log
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

function Write-Inventory {
    param([string]$Suffix)
    $Lines = [System.Collections.Generic.List[string]]::new()
    $Lines.Add("timestamp=$([DateTime]::UtcNow.ToString('o'))")
    $Lines.Add("windows=$([Environment]::OSVersion.VersionString)")
    $Lines.Add("architecture=$([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)")
    $Lines.Add("webview2=$((Get-WebViewVersion))")
    $Podman = Get-PodmanPath
    if ($Podman) {
        $Lines.Add((& $Podman --version | Out-String).Trim())
        foreach ($Line in @(& $Podman machine list --format "machine={{.Name}}|{{.Running}}" 2>&1)) {
            if ($null -ne $Line) { $Lines.Add([string]$Line) }
        }
        foreach ($Line in @(& $Podman --connection $MachineName ps --all --format "container={{.Names}}|{{.Status}}|{{.Image}}" 2>&1)) {
            if ($null -ne $Line) { $Lines.Add([string]$Line) }
        }
        foreach ($Line in @(& $Podman --connection $MachineName volume ls --format "volume={{.Name}}" 2>&1)) {
            if ($null -ne $Line) { $Lines.Add([string]$Line) }
        }
        foreach ($Line in @(& $Podman --connection $MachineName images --format "image={{.Repository}}:{{.Tag}}|{{.Digest}}|{{.ID}}" 2>&1)) {
            if ($null -ne $Line) { $Lines.Add([string]$Line) }
        }
    }
    else {
        $Lines.Add("podman=absent")
    }
    [IO.File]::WriteAllLines((Join-Path $Results "inventory-$Suffix.txt"), $Lines)
}

function Get-WebViewVersion {
    $WebViewClientId = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $RegistryPaths = @(
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$WebViewClientId",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$WebViewClientId",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$WebViewClientId"
    )
    foreach ($RegistryPath in $RegistryPaths) {
        $Version = (Get-ItemProperty -LiteralPath $RegistryPath -Name pv -ErrorAction SilentlyContinue).pv
        if ($Version -and $Version -match '^\d+\.\d+\.\d+\.\d+$') {
            return [pscustomobject]@{
                Version = $Version
                RegistryPath = $RegistryPath
            }
        }
    }
    throw "The active Microsoft Edge WebView2 Runtime pv registry value was not found."
}

function Install-EdgeDriver {
    $WebView = Get-WebViewVersion
    $Version = $WebView.Version
    $DriverDirectory = Join-Path $WorkDir "edgedriver"
    $Driver = Join-Path $DriverDirectory "msedgedriver.exe"
    $DriverVersionPattern = '^(?:MSEdgeDriver|Microsoft Edge WebDriver)\s+(\d+)\.'
    if (Test-Path -LiteralPath $Driver) {
        $ExistingVersion = (& $Driver --version | Out-String).Trim()
        if ($ExistingVersion -match $DriverVersionPattern) {
            $ExistingMajor = [int]$Matches[1]
            if ($ExistingMajor -eq ([version]$Version).Major) {
                $Record = [ordered]@{
                    webViewVersion = $Version
                    webViewRegistryPath = $WebView.RegistryPath
                    driverVersion = $ExistingVersion
                    driverSha256 = (Get-FileHash -LiteralPath $Driver -Algorithm SHA256).Hash.ToLowerInvariant()
                }
                $Record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "webdriver.json") -Encoding utf8
                return $Driver
            }
        }
        Remove-Item -LiteralPath $DriverDirectory -Recurse -Force
    }
    New-Item -ItemType Directory -Path $DriverDirectory -Force | Out-Null
    $Archive = Join-Path $WorkDir "edgedriver.zip"
    Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
    $DriverUrl = "https://msedgedriver.microsoft.com/$Version/edgedriver_win64.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $DriverUrl -OutFile $Archive
    Expand-Archive -LiteralPath $Archive -DestinationPath $DriverDirectory -Force
    if (-not (Test-Path -LiteralPath $Driver)) { throw "EdgeDriver archive had no msedgedriver.exe." }
    $DriverVersion = (& $Driver --version | Out-String).Trim()
    if ($DriverVersion -notmatch $DriverVersionPattern) {
        throw "Could not parse the installed EdgeDriver version: $DriverVersion"
    }
    $DriverMajor = [int]$Matches[1]
    if ($DriverMajor -ne ([version]$Version).Major) {
        throw "EdgeDriver major $DriverMajor does not match WebView2 $Version."
    }
    $Record = [ordered]@{
        webViewVersion = $Version
        webViewRegistryPath = $WebView.RegistryPath
        driverVersion = $DriverVersion
        driverSha256 = (Get-FileHash -LiteralPath $Driver -Algorithm SHA256).Hash.ToLowerInvariant()
        driverArchiveSha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        driverUrl = $DriverUrl
    }
    $Record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "webdriver.json") -Encoding utf8
    return $Driver
}

function Get-InstalledApplication {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "omnideck\omnideck.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\omnideck\omnideck.exe")
    )
    $Application = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $Application) {
        $Application = Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Filter "omnideck.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "$WorkDir*" } |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $Application) { throw "Installed omnideck.exe was not found." }
    return [System.IO.Path]::GetFullPath($Application)
}

function Install-Candidate {
    $Process = Start-Process -FilePath $Installer -ArgumentList "/S" -PassThru -Wait
    if ($Process.ExitCode -ne 0) { throw "NSIS install failed with exit $($Process.ExitCode)." }
    $Application = Get-InstalledApplication
    [IO.File]::WriteAllText($ApplicationFile, "$Application`n", [Text.UTF8Encoding]::new($false))
    return $Application
}

function Stop-Omnideck {
    Get-Process -Name "omnideck" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Invoke-Smoke {
    param([string]$Application)
    $Smoke = Join-Path $Results "smoke"
    $SmokeUserData = Join-Path $Smoke "user-data"
    $Proof = Join-Path $Smoke "smoke-proof.json"
    New-Item -ItemType Directory -Path $SmokeUserData -Force | Out-Null
    Remove-Item -LiteralPath $Proof -Force -ErrorAction SilentlyContinue
    $PreviousSmoke = $env:OMNIDECK_DESKTOP_SMOKE_FILE
    $PreviousData = $env:OMNIDECK_DESKTOP_USER_DATA
    try {
        $env:OMNIDECK_DESKTOP_SMOKE_FILE = $Proof
        $env:OMNIDECK_DESKTOP_USER_DATA = $SmokeUserData
        $Process = Start-Process -FilePath $Application -PassThru
        $Deadline = [DateTime]::UtcNow.AddSeconds(90)
        while (-not (Test-Path -LiteralPath $Proof)) {
            if ($Process.HasExited) { throw "Desktop host exited before writing smoke proof." }
            if ([DateTime]::UtcNow -ge $Deadline) { throw "Desktop smoke proof timed out." }
            Start-Sleep -Milliseconds 250
        }
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $ProofObject = Get-Content -LiteralPath $Proof -Raw | ConvertFrom-Json
        if ($ProofObject.cliVersion -ne $ExpectedCliVersion) { throw "Smoke CLI version mismatch." }
        if ($ProofObject.cliCommit -ne $ExpectedCliCommit) { throw "Smoke CLI commit mismatch." }
        if ($ProofObject.schemaVersion -ne 4 -or $ProofObject.mutation -ne $false) {
            throw "Smoke proof contract mismatch."
        }
    }
    finally {
        $env:OMNIDECK_DESKTOP_SMOKE_FILE = $PreviousSmoke
        $env:OMNIDECK_DESKTOP_USER_DATA = $PreviousData
        Stop-Omnideck
    }
}

switch ($Phase) {
    "Driver" {
        Install-EdgeDriver | Set-Content -LiteralPath (Join-Path $WorkDir "edgedriver-path.txt") -Encoding utf8
        Write-Host "DRIVER READY"
    }
    "Prepare" {
        $Actual = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Actual -ne $ArtifactSha256.ToLowerInvariant()) { throw "Installer SHA-256 mismatch." }
        $Application = Install-Candidate
        Get-FileHash -LiteralPath $Application -Algorithm SHA256 |
            Format-List | Out-File -LiteralPath (Join-Path $Results "application.sha256.txt") -Encoding utf8
        Install-EdgeDriver | Set-Content -LiteralPath (Join-Path $WorkDir "edgedriver-path.txt") -Encoding utf8
        Invoke-Smoke $Application
        Write-Host "PREPARED application=$Application"
    }
    "ConfigureClean" {
        [Environment]::SetEnvironmentVariable("OMNIDECK_DESKTOP_USER_DATA", $UserData, "User")
        [Environment]::SetEnvironmentVariable("OMNIDECK_CONFIG_DIR", $CliConfig, "User")
        [Environment]::SetEnvironmentVariable("OMNIDECK_DESKTOP_TEST_NAMESPACE", $TestNamespace, "User")
        [Environment]::SetEnvironmentVariable(
            "OMNIDECK_DESKTOP_UPDATE_FIXTURE",
            (Join-Path $WorkDir "update-fixture.json"),
            "User"
        )
        Remove-ItemProperty `
            -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" `
            -Name "omnideckSetupResume" `
            -ErrorAction SilentlyContinue
        Write-Inventory "clean"
        Write-Host "CLEAN ENVIRONMENT CONFIGURED userData=$UserData"
    }
    "Runtime" {
        # Podman's WSL user-mode networking helper must be launched from the
        # logged-in desktop session. Starting it through the short-lived SSH
        # provisioning process leaves the packaged Tauri app with a dead
        # helper after that process exits.
        Start-PodmanMachine
        Write-Inventory "before"
        Remove-CheckpointResources
        Write-Host "RUNTIME READY machine=$MachineName"
    }
    "RuntimePreserve" {
        Start-PodmanMachine
        Write-Inventory "before"
        Write-Host "RUNTIME PRESERVED machine=$MachineName"
    }
    "RunOnceProof" {
        $RunOnce = Get-ItemProperty `
            -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" `
            -Name "omnideckSetupResume" `
            -ErrorAction SilentlyContinue
        $Processes = @(Get-Process -Name "omnideck" -ErrorAction SilentlyContinue |
            Where-Object { $_.SessionId -gt 0 })
        $State = if (Test-Path -LiteralPath $StatePath) {
            Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        }
        else { $null }
        $Proof = [ordered]@{
            observedAt = [DateTime]::UtcNow.ToString("o")
            runOnceValueConsumed = ($null -eq $RunOnce)
            interactiveProcessCount = $Processes.Count
            processIds = @($Processes | Select-Object -ExpandProperty Id)
            setupStatePresent = ($null -ne $State)
            setupStatus = $(if ($State) { $State.status } else { $null })
            setupReason = $(if ($State) { $State.reason } else { $null })
        }
        $Proof | ConvertTo-Json | Set-Content `
            -LiteralPath (Join-Path $Results "runonce-proof.json") -Encoding utf8
        if ($RunOnce) { throw "The omnideck RunOnce value was not consumed after sign-in." }
        if (-not $Processes) { throw "RunOnce did not reopen omnideck in an interactive session." }
        if (-not $State) { throw "RunOnce reopened without the persisted setup state." }
        Write-Host "RUNONCE PROVED processCount=$($Processes.Count) status=$($State.status)"
    }
    "SetupStatus" {
        if (-not (Test-Path -LiteralPath $StatePath)) {
            Write-Host "missing"
            return
        }
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        Write-Host $State.status
    }
    "Doctor" {
        Stop-Omnideck
        Invoke-Engine rm --force $ContainerName | Out-Null
    }
    "Resume" {
        Stop-Omnideck
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $State.status = "in-progress"
        $State.reason = "first-run"
        [IO.File]::WriteAllText(
            $StatePath,
            (($State | ConvertTo-Json) + "`n"),
            [Text.UTF8Encoding]::new($false)
        )
        Invoke-Engine rm --force $ContainerName | Out-Null
    }
    "Update" {
        Stop-Omnideck
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $State.status = "complete"
        $State.appVersion = "0.0.0-e2e-older"
        [IO.File]::WriteAllText(
            $StatePath,
            (($State | ConvertTo-Json) + "`n"),
            [Text.UTF8Encoding]::new($false)
        )
    }
    "PortConflict" {
        Stop-Omnideck
        $PortPath = Join-Path $UserData "runtime\app-port"
        $OldPort = (Get-Content -LiteralPath $PortPath -Raw).Trim()
        if ($OldPort -notmatch '^\d+$') { throw "The persisted Desktop port is invalid." }
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $State.status = "complete"
        $State.appVersion = "0.0.0-e2e-port-conflict"
        [IO.File]::WriteAllText(
            $StatePath,
            (($State | ConvertTo-Json) + "`n"),
            [Text.UTF8Encoding]::new($false)
        )

        $InstancePath = Join-Path $CliConfig "instances\$ContainerName.yaml"
        $ConflictPath = Join-Path $CliConfig "instances\$ContainerName-occupied-port.yaml"
        $Source = Get-Content -LiteralPath $InstancePath -Raw
        $ExpectedName = "container_name: $ContainerName"
        if (-not $Source.Contains($ExpectedName)) { throw "The saved Desktop instance name changed." }
        if (-not $Source.Contains("web_ui_port: `"$OldPort`"")) {
            throw "The saved Desktop instance does not use port $OldPort."
        }
        $Conflict = $Source.Replace(
            $ExpectedName,
            "container_name: $ContainerName-occupied-port"
        )
        [IO.File]::WriteAllText($ConflictPath, $Conflict, [Text.UTF8Encoding]::new($false))
        [ordered]@{ occupiedPort = [int]$OldPort } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "port-conflict-pending.json") -Encoding utf8
        Write-Host $OldPort
    }
    "VerifyPortConflict" {
        Stop-Omnideck
        $Pending = Get-Content -LiteralPath (Join-Path $Results "port-conflict-pending.json") -Raw |
            ConvertFrom-Json
        $OldPort = [string]$Pending.occupiedPort
        $NewPort = (Get-Content -LiteralPath (Join-Path $UserData "runtime\app-port") -Raw).Trim()
        if ($NewPort -eq $OldPort) { throw "Desktop did not select a new port automatically." }
        $InstancePath = Join-Path $CliConfig "instances\$ContainerName.yaml"
        $ConflictPath = Join-Path $CliConfig "instances\$ContainerName-occupied-port.yaml"
        if (-not (Get-Content -LiteralPath $ConflictPath -Raw).Contains("web_ui_port: `"$OldPort`"")) {
            throw "The occupied-port fixture no longer owns the original port."
        }
        if (-not (Get-Content -LiteralPath $InstancePath -Raw).Contains("web_ui_port: `"$NewPort`"")) {
            throw "Desktop did not persist the replacement port."
        }
        [ordered]@{ occupiedPort = [int]$OldPort; selectedPort = [int]$NewPort } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "port-conflict-recovery.json") -Encoding utf8
        Write-Host "PORT CONFLICT RECOVERED occupied=$OldPort selected=$NewPort"
    }
    "CustomAppFixture" {
        Stop-Omnideck
        $Fixture = Join-Path $WorkDir "custom_app_fixture.py"
        if (-not (Test-Path -LiteralPath $Fixture -PathType Leaf)) {
            throw "The Custom App fixture script is missing."
        }
        Invoke-Engine cp $Fixture "${ContainerName}:/tmp/omnideck-custom-app-fixture.py" | Out-Null
        Invoke-Engine exec --user omnideck $ContainerName `
            python3 /tmp/omnideck-custom-app-fixture.py | Out-Null

        $PortPath = Join-Path $UserData "runtime\app-port"
        $Port = (Get-Content -LiteralPath $PortPath -Raw).Trim()
        if ($Port -notmatch '^\d+$') { throw "The persisted Desktop port is invalid." }
        $Headers = @{ "X-Requested-With" = "XMLHttpRequest" }
        $Settings = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$Port/api/settings" `
            -Method Put `
            -Headers $Headers `
            -ContentType "application/json" `
            -Body '{"custom_apps_enabled":true,"setup_complete":true}'
        $Catalog = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/custom-apps"
        $App = @($Catalog.apps | Where-Object { $_.slug -eq "desktop-smoke" })
        if ($App.Count -ne 1 -or $App[0].title -ne "Desktop Custom App Smoke" -or -not $App[0].has_actions) {
            throw "The Desktop Custom App fixture was not discovered."
        }
        $Settings | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath (Join-Path $Results "custom-app-settings.json") -Encoding utf8
        $Catalog | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath (Join-Path $Results "custom-app-catalog.json") -Encoding utf8
        Write-Host "CUSTOM APP FIXTURE READY port=$Port"
    }
    "HostBoundaryDownload" {
        if (-not $FixtureName -or -not $FixtureFilename) {
            throw "HostBoundaryDownload requires FixtureName and FixtureFilename."
        }
        if ([IO.Path]::GetFileName($FixtureFilename) -ne $FixtureFilename) {
            throw "FixtureFilename must be a leaf filename."
        }
        $Downloads = Join-Path $env:USERPROFILE "Downloads"
        New-Item -ItemType Directory -Path $Downloads -Force | Out-Null
        $Download = Join-Path $Downloads $FixtureFilename
        $Deadline = [DateTime]::UtcNow.AddSeconds(30)
        while (-not (Test-Path -LiteralPath $Download -PathType Leaf)) {
            if ([DateTime]::UtcNow -ge $Deadline) {
                throw "Native download did not create $Download."
            }
            Start-Sleep -Milliseconds 250
        }
        $Pack = Get-Content -LiteralPath $Download -Raw | ConvertFrom-Json
        if ($Pack.kind -ne "omnideck.pack") { throw "Downloaded file has the wrong pack kind." }
        if ($Pack.version -ne 1) { throw "Downloaded file has the wrong pack version." }
        if (@($Pack.profiles).Count -ne 1) { throw "Downloaded file did not contain one profile." }
        if ($Pack.profiles[0].name -ne $FixtureName) {
            throw "Downloaded profile name did not match the fixture."
        }
        $BoundaryResults = Join-Path $Results "host-boundaries"
        New-Item -ItemType Directory -Path $BoundaryResults -Force | Out-Null
        [ordered]@{
            status = "passed"
            path = $Download
            size = (Get-Item -LiteralPath $Download).Length
            kind = $Pack.kind
            version = $Pack.version
            profileName = $Pack.profiles[0].name
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $BoundaryResults "filesystem.json") -Encoding utf8
        Write-Host $Download
    }
    "SeedArtifact" {
        if (-not $ArtifactFilename) { throw "SeedArtifact requires ArtifactFilename." }
        if ([IO.Path]::GetFileName($ArtifactFilename) -ne $ArtifactFilename) {
            throw "ArtifactFilename must be a leaf filename."
        }
        $Contents = "native artifact download $ArtifactFilename"
        # Windows PowerShell strips embedded double quotes when forwarding a
        # native-process argument. Keep this Python payload single-quoted so
        # podman passes it to `python -c` byte-for-byte.
        $Python = "import os; from pathlib import Path; from artifacts import record_artifact; name=os.environ['E2E_ARTIFACT_FILENAME']; path=Path('/home/computron') / name; path.write_text(os.environ['E2E_ARTIFACT_CONTENTS'], encoding='utf-8'); record_artifact(conversation_id='desktop-vm-artifact', path=str(path), filename=name, content_type='text/plain', agent_name='Desktop VM', sent_at='2026-08-12T00:00:00Z')"
        Invoke-Engine exec --env "E2E_ARTIFACT_FILENAME=$ArtifactFilename" --env "E2E_ARTIFACT_CONTENTS=$Contents" $ContainerName python -c $Python | Out-Null
        Write-Host $Contents
    }
    "HostBoundaryArtifactDownload" {
        if (-not $ArtifactFilename) {
            throw "HostBoundaryArtifactDownload requires ArtifactFilename."
        }
        $Expected = "native artifact download $ArtifactFilename"
        $Download = Join-Path (Join-Path $env:USERPROFILE "Downloads") $ArtifactFilename
        $Deadline = [DateTime]::UtcNow.AddSeconds(30)
        while (-not (Test-Path -LiteralPath $Download -PathType Leaf)) {
            if ([DateTime]::UtcNow -ge $Deadline) {
                throw "Native artifact download did not create $Download."
            }
            Start-Sleep -Milliseconds 250
        }
        $Contents = Get-Content -LiteralPath $Download -Raw
        if ($Contents -ne $Expected) { throw "Downloaded artifact contents did not match." }
        $BoundaryResults = Join-Path $Results "host-boundaries"
        New-Item -ItemType Directory -Path $BoundaryResults -Force | Out-Null
        [ordered]@{
            status = "passed"
            path = $Download
            size = (Get-Item -LiteralPath $Download).Length
            contents = $Contents
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $BoundaryResults "artifact-filesystem.json") -Encoding utf8
        Write-Host $Download
    }
    "SeedUpdateFixture" {
        $UpdateFixture = Join-Path $WorkDir "update-fixture.json"
        $Value = [ordered]@{
            version = "0.1.4"
            imageRef = "ghcr.io/omnideck-dev/omnideck@sha256:$('a' * 64)"
        } | ConvertTo-Json
        [IO.File]::WriteAllText($UpdateFixture, "$Value`n", [Text.UTF8Encoding]::new($false))
        Write-Host $UpdateFixture
    }
    "PromoteUpdateFixture" {
        $UpdateFixture = Join-Path $WorkDir "update-fixture.json"
        $Value = [ordered]@{
            version = "0.1.5"
            imageRef = "ghcr.io/omnideck-dev/omnideck@sha256:$('a' * 64)"
        } | ConvertTo-Json
        [IO.File]::WriteAllText($UpdateFixture, "$Value`n", [Text.UTF8Encoding]::new($false))
        Write-Host $UpdateFixture
    }
    "Final" {
        Stop-Omnideck
        Invoke-Engine container inspect $ContainerName |
            Out-File -LiteralPath (Join-Path $Results "container-inspect.json") -Encoding utf8
        Invoke-Engine volume inspect $HomeVolume $StateVolume |
            Out-File -LiteralPath (Join-Path $Results "volume-inspect.json") -Encoding utf8
        Copy-Item -LiteralPath $StatePath -Destination (Join-Path $Results "setup-state.json")

        $Application = Get-Content -LiteralPath $ApplicationFile -Raw
        $Application = $Application.Trim()
        $InstallDirectory = Split-Path -Parent $Application
        Get-ChildItem -LiteralPath $InstallDirectory -Recurse -Force |
            Select-Object FullName,Length,Mode |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "installed-files.json") -Encoding utf8
        $Uninstaller = Get-ChildItem -LiteralPath $InstallDirectory -Filter "*uninstall*.exe" -File |
            Select-Object -First 1 -ExpandProperty FullName
        if (-not $Uninstaller) { throw "NSIS uninstaller was not found." }
        $Uninstall = Start-Process -FilePath $Uninstaller -ArgumentList "/S" -PassThru -Wait
        if ($Uninstall.ExitCode -ne 0) { throw "NSIS uninstall failed with exit $($Uninstall.ExitCode)." }
        Start-Sleep -Seconds 2
        if (Test-Path -LiteralPath $Application) { throw "Installed application remained after uninstall." }
        if (-not (Test-Path -LiteralPath $UserData)) { throw "Uninstall unexpectedly removed user data." }
        $Reinstalled = Install-Candidate
        if (-not (Test-Path -LiteralPath $Reinstalled)) { throw "Reinstall did not restore the application." }
        Invoke-Smoke $Reinstalled

        Invoke-Engine rm --force $ContainerName | Out-Null
        Invoke-Engine volume rm --force $HomeVolume $StateVolume | Out-Null
        Write-Inventory "after"
        $Summary = [ordered]@{
            status = "passed"
            packageKind = "nsis"
            artifactSha256 = $ArtifactSha256.ToLowerInvariant()
            expectedCliVersion = $ExpectedCliVersion
            expectedCliCommit = $ExpectedCliCommit
            finishedAt = [DateTime]::UtcNow.ToString("o")
        }
        $Summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "summary.json") -Encoding utf8
        @'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="omnideck-desktop-windows-vm-e2e" tests="15" failures="0">
  <testcase classname="desktop-vm-e2e" name="nsis-install"/>
  <testcase classname="desktop-vm-e2e" name="package-and-sidecar-smoke"/>
  <testcase classname="desktop-vm-e2e" name="first-run-exact-copy"/>
  <testcase classname="desktop-vm-e2e" name="hosted-open"/>
  <testcase classname="desktop-vm-e2e" name="returning-user"/>
  <testcase classname="desktop-vm-e2e" name="doctor-resume-update"/>
  <testcase classname="desktop-vm-e2e" name="occupied-port-auto-recovery"/>
  <testcase classname="desktop-vm-e2e" name="custom-app-webview-action-and-restart"/>
  <testcase classname="desktop-vm-e2e" name="native-host-download"/>
  <testcase classname="desktop-vm-e2e" name="native-host-upload"/>
  <testcase classname="desktop-vm-e2e" name="native-artifact-download-and-toast"/>
  <testcase classname="desktop-vm-e2e" name="native-zoom"/>
  <testcase classname="desktop-vm-e2e" name="native-update-bridge"/>
  <testcase classname="desktop-vm-e2e" name="nsis-uninstall"/>
  <testcase classname="desktop-vm-e2e" name="nsis-reinstall"/>
</testsuite>
'@ | Set-Content -LiteralPath (Join-Path $Results "junit.xml") -Encoding utf8
    }
}
