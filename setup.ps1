# One-time setup for Windows. Run from this folder:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Each step asks first. Nothing outside your user account is changed, and
# you can undo every step (see the end of README.md).

$ErrorActionPreference = "Stop"
$root  = $PSScriptRoot
$tools = Join-Path $root "tools"

function Ask($question) {
    $a = Read-Host "$question [Y/n]"
    return ($a -eq "" -or $a -match "^[Yy]")
}

Write-Host "`nMy Day / personal assistant setup`n" -ForegroundColor Cyan

# 1. Python 3.9+ with Tkinter (standard library only, nothing to pip install)
$python = $null
foreach ($cand in @("py -3", "python")) {
    $parts = $cand -split " "
    if (Get-Command $parts[0] -ErrorAction SilentlyContinue) {
        $pyArgs = @($parts | Select-Object -Skip 1) + @("-c", "import sys, tkinter; assert sys.version_info >= (3, 9); print(sys.executable)")
        try { $exe = & $parts[0] @pyArgs 2>$null } catch { $exe = $null }
        if ($LASTEXITCODE -eq 0 -and $exe) { $python = "$exe".Trim(); break }
    }
}
if (-not $python) {
    Write-Host "Python 3.9+ (with Tkinter) not found. Install it from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "(tick 'Add python.exe to PATH'), then run this script again."
    exit 1
}
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }
Write-Host "Python: $python" -ForegroundColor Green

# 2. The `day` command in every terminal
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -split ";" -contains $tools) {
    Write-Host "The 'day' command is already on your PATH." -ForegroundColor Green
} elseif (Ask "Add the 'day' command to your PATH (user setting)?") {
    [Environment]::SetEnvironmentVariable("Path", (($userPath.TrimEnd(";")) + ";" + $tools), "User")
    Write-Host "Done. Open a NEW terminal, then type: day" -ForegroundColor Green
}

# 3. Show My Day each morning (at login and at the first unlock of the day)
$taskName = "My Day morning"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "The '$taskName' task already exists." -ForegroundColor Green
} elseif (Ask "Show My Day at login and at the first unlock each day (a scheduled task)?") {
    $user   = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$tools\day.py`" morning" -WorkingDirectory $root
    $cls    = Get-CimClass -Namespace ROOT\Microsoft\Windows\TaskScheduler -ClassName MSFT_TaskSessionStateChangeTrigger
    $unlock = New-CimInstance -CimClass $cls -ClientOnly
    $unlock.StateChange = 8   # session unlock
    $unlock.UserId = $user
    $unlock.Enabled = $true
    $logon  = New-ScheduledTaskTrigger -AtLogOn -User $user
    $set    = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $logon, $unlock -Settings $set | Out-Null
    Write-Host "Done. Undo any time: Unregister-ScheduledTask '$taskName'" -ForegroundColor Green
}

# 4. Try it with the fictional sample person first
if (Ask "Load Alex, the fictional sample person, to try things out? (clear later with: python tools\sample.py clear)") {
    & $python (Join-Path $tools "sample.py") load
}

# 5. The AI side (optional: My Day's todos, calendar, goals and pop-ups work without it)
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Host "Claude Code found. Run 'claude' once in this folder to sign in if you haven't." -ForegroundColor Green
} else {
    Write-Host "`nNo AI agent CLI found. For '?', Suggest and the skills, install one, e.g. Claude Code:" -ForegroundColor Yellow
    Write-Host "  https://docs.claude.com/en/docs/claude-code   (then run 'claude' in this folder once to sign in)"
    Write-Host "Or set `"assistant_command`" in tools\day_ui.config.json to another agent."
}
# A local model is the fallback when the API can't answer (Settings -> Assistant)
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama found: My Day falls back to a local model (ollama pull qwen3.5:4b if you have none)." -ForegroundColor Green
} else {
    Write-Host "Optional: install Ollama (https://ollama.com) and run 'ollama pull qwen3.5:4b' for a free, offline fallback."
}

Write-Host "`nAll set. Start My Day now?" -ForegroundColor Cyan
if (Ask "Open My Day") { Start-Process $pythonw -ArgumentList "`"$tools\day_ui.py`"" -WorkingDirectory $root }
