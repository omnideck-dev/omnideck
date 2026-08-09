[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkDir,
    [switch]$Register
)

$ErrorActionPreference = "Stop"
$WorkDir = [System.IO.Path]::GetFullPath($WorkDir)
$TaskName = "OmnideckDesktopE2E-$([System.IO.Path]::GetFileName($WorkDir))"
if ($Register) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -WorkDir `"$WorkDir`""
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments
    $Principal = New-ScheduledTaskPrincipal -UserId "tester" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Principal $Principal -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    [IO.File]::WriteAllText((Join-Path $WorkDir "driver-task-name.txt"), "$TaskName`n", [Text.UTF8Encoding]::new($false))
    return
}
$Application = (Get-Content -LiteralPath (Join-Path $WorkDir "application-path.txt") -Raw).Trim()
$Driver = Join-Path $WorkDir "tauri-driver.exe"
$EdgeDriver = (Get-Content -LiteralPath (Join-Path $WorkDir "edgedriver-path.txt") -Raw).Trim()
$GuestScript = Join-Path $WorkDir "windows_guest.ps1"

if (-not (Test-Path -LiteralPath $Application)) { throw "Installed application is missing: $Application" }
if (-not (Test-Path -LiteralPath $Driver)) { throw "tauri-driver is missing: $Driver" }
if (-not (Test-Path -LiteralPath $EdgeDriver)) { throw "EdgeDriver is missing: $EdgeDriver" }
if (-not (Test-Path -LiteralPath $GuestScript)) { throw "Guest harness is missing: $GuestScript" }

$env:OMNIDECK_DESKTOP_USER_DATA = Join-Path $WorkDir "user-data"
$env:OMNIDECK_CONFIG_DIR = Join-Path $WorkDir "cli-config"
Remove-Item Env:OMNIDECK_DESKTOP_TEST_NAMESPACE -ErrorAction SilentlyContinue
& $GuestScript -Phase Runtime -WorkDir $WorkDir *>> (Join-Path $WorkDir "runtime-start.log")
$Process = Start-Process -FilePath $Driver `
    -ArgumentList @("--native-driver", $EdgeDriver) `
    -RedirectStandardOutput (Join-Path $WorkDir "tauri-driver.stdout.log") `
    -RedirectStandardError (Join-Path $WorkDir "tauri-driver.stderr.log") `
    -PassThru -Wait
exit $Process.ExitCode
