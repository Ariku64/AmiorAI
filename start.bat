@echo off
REM Copyright 2026 Ariku
REM SPDX-License-Identifier: Apache-2.0
cd /d "%~dp0"
setlocal

REM One-time acknowledgement of the bundled legal notice.
set "LEGAL_VERSION=v40.0.6"
set "LEGAL_MARKER=%LOCALAPPDATA%\AmiorAI\legal_acceptance_%LEGAL_VERSION%.txt"
if not defined LOCALAPPDATA set "LEGAL_MARKER=%~dp0.legal_acceptance_%LEGAL_VERSION%.txt"
if exist "%LEGAL_MARKER%" goto legal_ok

echo.
echo ============================================================
echo  Before using AmiorAI, read LEGAL_NOTICE.md
echo ============================================================
echo.
if exist "%~dp0LEGAL_NOTICE.md" start "" /wait notepad.exe "%~dp0LEGAL_NOTICE.md"
choice /C YN /N /M "I have read and accept the AmiorAI legal notice [Y/N]: "
if errorlevel 2 goto legal_declined
for %%D in ("%LEGAL_MARKER%") do if not exist "%%~dpD" mkdir "%%~dpD" >nul 2>&1
> "%LEGAL_MARKER%" echo Accepted %LEGAL_VERSION% on %DATE% %TIME%

:legal_ok

REM ============================================================
REM  AmiorAI - Windows launcher
REM  Text generation: LM Studio (external local server)
REM  Image generation: ComfyUI
REM ============================================================

set "PYTHON=python"

if exist "python_embed\python.exe" (
    set "VPY=python_embed\python.exe"
    if exist "python_embed\.installed" (
        call :check_deps "python_embed\python.exe"
        goto run
    )
    echo.
    echo   python_embed exists, but setup is incomplete.
    echo   Run install.bat again.
    echo.
    pause
    goto end
)

set "VENV=.venv"
set "VPY=%VENV%\Scripts\python.exe"

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 goto no_python

if not exist "%VPY%" (
    echo.
    echo   First launch: creating the local Python environment...
    "%PYTHON%" -m venv "%VENV%"
)
if not exist "%VPY%" goto venv_fail

if not exist "%VENV%\.installed" (
    echo.
    echo   Installing AmiorAI dependencies...
    "%VPY%" -m pip install --upgrade pip
    "%VPY%" -m pip install -r requirements.txt
    if errorlevel 1 goto deps_fail
    for /f "delims=" %%H in ('certutil -hashfile requirements.txt MD5 ^| findstr /v ":"') do echo %%H> "%VENV%\.deps_hash"
    echo ok> "%VENV%\.installed"
    echo   Installation complete.
) else (
    call :check_deps "%VPY%"
)

:run
echo.
echo   Starting AmiorAI on http://127.0.0.1:8800
echo   Make sure the LM Studio local server is running on port 1234.
echo   ComfyUI can be started automatically on first image generation.
start "" cmd /c "timeout /t 4 >nul & start "" http://127.0.0.1:8800"
"%VPY%" app.py
echo.
echo   Server stopped.
pause
goto end

:check_deps
set "DVPY=%~1"
set "DEPS_HASH_FILE="
if exist ".venv\.deps_hash" set "DEPS_HASH_FILE=.venv\.deps_hash"
if exist "python_embed\.deps_hash" set "DEPS_HASH_FILE=python_embed\.deps_hash"
for /f "delims=" %%H in ('certutil -hashfile requirements.txt MD5 ^| findstr /v ":"') do set "CURRENT_HASH=%%H"
set "STORED_HASH="
if defined DEPS_HASH_FILE if exist "%DEPS_HASH_FILE%" set /p STORED_HASH=<"%DEPS_HASH_FILE%"
if "%CURRENT_HASH%"=="%STORED_HASH%" goto :eof
echo.
echo   requirements.txt changed - updating dependencies...
"%DVPY%" -m pip install -r requirements.txt
if errorlevel 1 goto deps_fail
> "%DEPS_HASH_FILE%" echo %CURRENT_HASH%
echo   Dependencies updated.
goto :eof

:no_python
echo.
echo   Python was not found in PATH.
echo   Run install.bat, or install Python 3.10 to 3.12.
echo.
pause
goto end

:venv_fail
echo.
echo   Failed to create the local Python environment.
pause
goto end

:deps_fail
echo.
echo   Dependency installation failed. Check your internet connection and retry.
pause
goto end

:legal_declined
echo.
echo   AmiorAI was not started because the legal notice was not accepted.
pause
goto end

:end
endlocal
