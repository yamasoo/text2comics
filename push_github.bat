@echo off
rem One-click publish: strip dev data, build the public snapshot, push v1_baseline / main / gh-pages.
rem Chinese messages are printed by tools\push_github.py (cmd.exe cannot parse non-ASCII here).
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\push_github.py %*
) else (
  py -3 tools\push_github.py %*
)
if errorlevel 1 (
  echo.
  echo [FAILED] See the message above.
  pause
  exit /b 1
)
pause
