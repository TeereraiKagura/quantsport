# Registers the QuantSport jobs with Windows Task Scheduler for the current user.
#
#   QuantSport daily   every day at 06:00    python -m quantsport job daily
#   QuantSport weekly  Mondays at 07:00      python -m quantsport job weekly
#
# Run this yourself from a PowerShell prompt in the project folder:
#     powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1
# Remove the tasks again with:
#     powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Remove
#
# The tasks only run while you are logged in. Output goes to logs\quantsport.log
# and every step is recorded in the job_runs table (python -m quantsport job-log).

param([switch]$Remove)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$names = @("QuantSport daily", "QuantSport weekly")

if ($Remove) {
    foreach ($name in $names) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed: $name"
    }
    exit 0
}

if (-not (Test-Path $python)) {
    Write-Error "Virtual environment not found at $python. Create it first (see README)."
    exit 1
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$daily = New-ScheduledTaskAction -Execute $python -Argument "-m quantsport job daily" -WorkingDirectory $root
Register-ScheduledTask -TaskName $names[0] -Action $daily -Settings $settings -Force `
    -Trigger (New-ScheduledTaskTrigger -Daily -At 6:00am) `
    -Description "QuantSport: update data, collect fixtures, store live forecasts, paper trading" | Out-Null

$weekly = New-ScheduledTaskAction -Execute $python -Argument "-m quantsport job weekly" -WorkingDirectory $root
Register-ScheduledTask -TaskName $names[1] -Action $weekly -Settings $settings -Force `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 7:00am) `
    -Description "QuantSport: daily steps plus performance monitoring, ML comparison and weekly audit" | Out-Null

Write-Host "Registered: $($names -join ', ')"
Write-Host "The weekly job repeats the daily steps, so Monday runs both; the second run finds nothing new."
