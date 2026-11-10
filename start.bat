@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

rem ASCII only: cmd.exe mis-parses non-ASCII bytes in .bat files, so every
rem message lives in tools\bootstrap.py (Python prints UTF-8 properly).

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py %*
    goto :done
)

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo Python 3 not found. Install Python 3.10 or newer, then run start.bat again.
    goto :done
)

%PY% tools\bootstrap.py %*

:done
pause
