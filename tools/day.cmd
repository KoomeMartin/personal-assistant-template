@echo off
rem My Day from any terminal (Windows). setup.ps1 puts this folder on your PATH; then type: day
setlocal
set PYTHONIOENCODING=utf-8
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0day.py" %*
) else (
  python "%~dp0day.py" %*
)
