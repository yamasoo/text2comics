@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py %*
    goto :done
)
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 run.py %*
    goto :done
)
where python >nul 2>nul
if %errorlevel%==0 (
    python run.py %*
    goto :done
)
echo Python 3 not found. Please install Python 3 first.

:done
pause
