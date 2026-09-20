@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_LAUNCHER="

for %%C in ("py -3.14" "py -3.13" "py -3.12" "py -3.11" "py -3.10") do (
    if not defined PYTHON_LAUNCHER (
        %%~C -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PYTHON_LAUNCHER=%%~C"
    )
)

REM No pinned version found via the "py" launcher - fall back to whatever
REM "py -3" or a bare "python" on PATH resolves to, but only accept it if
REM its version falls inside what PySide6 supports (3.10 up to, but not
REM including, 3.15).
if not defined PYTHON_LAUNCHER (
    for %%C in ("py -3" "python") do (
        if not defined PYTHON_LAUNCHER (
            %%~C -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
            if not errorlevel 1 set "PYTHON_LAUNCHER=%%~C"
        )
    )
)

if not defined PYTHON_LAUNCHER (
    echo No compatible Python installation was found - this app needs Python 3.10 to 3.14.
    echo Install it from https://www.python.org/downloads/windows/
    echo During setup, make sure "Add python.exe to PATH" is checked.
    goto :error
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating ComfyUI Prompt Builder V2 environment with:
    %PYTHON_LAUNCHER% --version
    %PYTHON_LAUNCHER% -m venv .venv
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo ComfyUI Prompt Builder V2 could not start. Review the message above.
pause
exit /b 1
