@echo off
REM Copyright 2026 Ariku
REM SPDX-License-Identifier: Apache-2.0
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM One-time acknowledgement of the bundled legal notice.
set "LEGAL_VERSION=v40.0.6"
set "LEGAL_MARKER=%LOCALAPPDATA%\AmiorAI\legal_acceptance_%LEGAL_VERSION%.txt"
if not defined LOCALAPPDATA set "LEGAL_MARKER=%~dp0.legal_acceptance_%LEGAL_VERSION%.txt"
if exist "%LEGAL_MARKER%" goto legal_ok

echo.
echo ============================================================
echo  Before installing AmiorAI, read LEGAL_NOTICE.md
echo ============================================================
echo.
if exist "%~dp0LEGAL_NOTICE.md" start "" /wait notepad.exe "%~dp0LEGAL_NOTICE.md"
choice /C YN /N /M "I have read and accept the AmiorAI legal notice [Y/N]: "
if errorlevel 2 goto legal_declined
for %%D in ("%LEGAL_MARKER%") do if not exist "%%~dpD" mkdir "%%~dpD" >nul 2>&1
> "%LEGAL_MARKER%" echo Accepted %LEGAL_VERSION% on %DATE% %TIME%

:legal_ok

REM ============================================================
REM  AmiorAI - installer (isolated embedded Python)
REM  LM Studio and ComfyUI remain external local applications.
REM ============================================================

set "PY_VERSION=3.12.7"
set "WITH_WHISPER=true"
set "EMBED_DIR=python_embed"
set "EPY=%EMBED_DIR%\python.exe"
set "ZIP_NAME=python-%PY_VERSION%-embed-amd64.zip"
set "ZIP_URL=https://www.python.org/ftp/python/%PY_VERSION%/%ZIP_NAME%"
set "GETPIP_URL=https://bootstrap.pypa.io/get-pip.py"

if exist "%EPY%" goto have_python

echo.
echo   [1/5] Downloading official Python %PY_VERSION% embeddable package...
if not exist "%EMBED_DIR%" mkdir "%EMBED_DIR%"
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_NAME%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 goto dl_fail

echo   [2/5] Extracting Python...
powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_NAME%' -DestinationPath '%EMBED_DIR%' -Force"
del "%ZIP_NAME%" >nul 2>&1
if not exist "%EPY%" goto extract_fail

echo   [3/5] Enabling site-packages and pip support...
for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do set "PY_MM=%%a%%b"
for %%f in ("%EMBED_DIR%\python*._pth") do set "PTH_FILE=%%f"
(
  echo python%PY_MM%.zip
  echo .
  echo ..
  echo Lib\site-packages
  echo import site
) > "%PTH_FILE%"

echo   [4/5] Installing pip...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%GETPIP_URL%' -OutFile '%EMBED_DIR%\get-pip.py' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 goto dl_fail
"%EPY%" "%EMBED_DIR%\get-pip.py" --no-warn-script-location
del "%EMBED_DIR%\get-pip.py" >nul 2>&1

:have_python
echo   [5/5] Installing AmiorAI dependencies...
"%EPY%" -m pip install --upgrade pip --no-warn-script-location
"%EPY%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 goto deps_fail
if /I "%WITH_WHISPER%"=="true" (
  echo   Installing optional local dictation support...
  "%EPY%" -m pip install faster-whisper --no-warn-script-location --quiet
  if errorlevel 1 echo   Warning: optional dictation support could not be installed.
)
for /f "delims=" %%H in ('certutil -hashfile requirements.txt MD5 ^| findstr /v ":"') do echo %%H> "%EMBED_DIR%\.deps_hash"
echo ok> "%EMBED_DIR%\.installed"

echo.
echo ============================================================
echo  AmiorAI installation complete. Run start.bat.
echo ============================================================
echo.
pause
goto end

:dl_fail
echo.
echo   Download failed. Check your internet connection and retry.
pause
goto end

:extract_fail
echo.
echo   Extraction failed. Delete python_embed and retry.
pause
goto end

:deps_fail
echo.
echo   Dependency installation failed.
pause
goto end

:legal_declined
echo.
echo   Installation cancelled because the legal notice was not accepted.
pause
goto end

:end
endlocal
