[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkDir,
    [ValidateSet("warning-bypassed", "trusted-without-warning")]
    [string]$Result,
    [switch]$RegisterDriver,
    [switch]$Drive
)

$ErrorActionPreference = "Stop"
$WorkDir = [System.IO.Path]::GetFullPath($WorkDir)
$Results = Join-Path $WorkDir "results"
$Markers = Join-Path $WorkDir "trust-markers"
$Installer = Join-Path $WorkDir "candidate-setup.exe"
$TaskName = "OmnideckDesktopTrust-$([System.IO.Path]::GetFileName($WorkDir))"
New-Item -ItemType Directory -Path $Results,$Markers -Force | Out-Null

if ($RegisterDriver) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -WorkDir `"$WorkDir`" -Drive"
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments
    $Principal = New-ScheduledTaskPrincipal -UserId "tester" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Principal $Principal -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    return
}

if ($Drive) {
    try {
        Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
        function New-EvidenceMarker([string]$Name) {
            New-Item -ItemType File -Path (Join-Path $Markers $Name) -Force | Out-Null
        }
        function Find-ExactControl([string]$Name, [int]$TimeoutSeconds = 20) {
            $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
            $Condition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::NameProperty,
                $Name
            )
            while ([DateTime]::UtcNow -lt $Deadline) {
                $Element = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst(
                    [System.Windows.Automation.TreeScope]::Descendants,
                    $Condition
                )
                if ($Element) { return $Element }
                Start-Sleep -Milliseconds 250
            }
            return $null
        }

        # Start-Process runs inside this limited, interactive tester task. It
        # therefore traverses the same Explorer/Attachment Manager path as a
        # double-click without depending on QEMU keyboard focus or timing.
        Start-Process -FilePath (Join-Path $env:WINDIR "explorer.exe") -ArgumentList "`"$Installer`""
        New-EvidenceMarker -Name "launch-invoked"

        $MoreInfo = Find-ExactControl -Name "More info"
        if (-not $MoreInfo) {
            $Consent = Get-Process consent -ErrorAction SilentlyContinue
            $InstallerProcess = Get-Process -Name "candidate-setup" -ErrorAction SilentlyContinue
            if ($Consent -or $InstallerProcess) {
                New-EvidenceMarker -Name "trusted-without-warning"
                return
            }
            throw "The interactive installer launch produced neither SmartScreen nor an installer process."
        }

        New-EvidenceMarker -Name "warning-observed"
        Start-Sleep -Seconds 3
        $MoreInfo.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        New-EvidenceMarker -Name "more-info-invoked"
        Start-Sleep -Seconds 3

        $RunAnyway = Find-ExactControl -Name "Run anyway"
        if (-not $RunAnyway) { throw "Timed out waiting for the exact SmartScreen control: Run anyway" }
        $RunAnyway.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        New-EvidenceMarker -Name "run-anyway-invoked"
    }
    catch {
        $_ | Out-String | Set-Content -LiteralPath (Join-Path $Results "trust-driver-error.txt") -Encoding utf8
        throw
    }
    return
}

if ($Result) {
    $TrustPath = Join-Path $Results "trust.json"
    if (-not (Test-Path -LiteralPath $TrustPath)) { throw "Trust evidence is missing: $TrustPath" }
    $Trust = Get-Content -LiteralPath $TrustPath -Raw | ConvertFrom-Json
    $Trust.smartScreen = $Result
    $Trust | ConvertTo-Json | Set-Content -LiteralPath $TrustPath -Encoding utf8
    return
}

if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer is missing: $Installer" }
$Zone = @'
[ZoneTransfer]
ZoneId=3
ReferrerUrl=https://github.com/omnideck-dev/omnideck/releases
HostUrl=https://github.com/omnideck-dev/omnideck/releases/download/
'@
Set-Content -LiteralPath $Installer -Stream "Zone.Identifier" -Value $Zone -NoNewline
$Signature = Get-AuthenticodeSignature -LiteralPath $Installer
$ZoneIdentifier = (Get-Content -LiteralPath $Installer -Stream "Zone.Identifier" -Raw).ToString()
$ZoneIdentifier = [string]::Concat($ZoneIdentifier)
$Trust = [ordered]@{
    observedAt = [DateTime]::UtcNow.ToString("o")
    sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    zoneIdentifier = $ZoneIdentifier
    signatureStatus = $Signature.Status.ToString()
    signer = $(if ($Signature.SignerCertificate) { $Signature.SignerCertificate.Subject } else { $null })
    smartScreen = "pending"
}
$Trust | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Results "trust.json") -Encoding utf8
New-Item -ItemType File -Path (Join-Path $Markers "trust-started") -Force | Out-Null
