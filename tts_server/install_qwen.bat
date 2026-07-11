@echo off
REM Copyright 2026 Ariku
REM SPDX-License-Identifier: Apache-2.0
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM  AmiorAI v40.0.5 - optional Qwen3-TTS 0.6B
REM  Fully isolated official Python embeddable runtime.
REM  No system Python and no virtual environment are required.
REM ============================================================
set "PY_VERSION=3.12.10"
set "PY_MM=312"
set "EMBED_DIR=python_qwen"
set "EPY=%EMBED_DIR%\python.exe"
set "ZIP_NAME=python-%PY_VERSION%-embed-amd64.zip"
set "ZIP_URL=https://www.python.org/ftp/python/%PY_VERSION%/%ZIP_NAME%"
set "GETPIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "TORCH_INDEX=cu128"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PYTHONUTF8=1"

 echo.
echo ============================================================
echo  AmiorAI v40.0.5 - optional Qwen3-TTS 0.6B
echo  Autonomous runtime: %EMBED_DIR%
echo  Chatterbox is not modified.
echo ============================================================
echo.

if exist "%EPY%" goto have_python

echo  [1/7] Downloading official Python %PY_VERSION% embeddable package...
if not exist "%EMBED_DIR%" mkdir "%EMBED_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_NAME%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto download_fail

echo  [2/7] Extracting the autonomous Python runtime...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -LiteralPath '%ZIP_NAME%' -DestinationPath '%EMBED_DIR%' -Force } catch { Write-Host $_.Exception.Message; exit 1 }"
del "%ZIP_NAME%" >nul 2>&1
if not exist "%EPY%" goto extract_fail

echo  [3/7] Enabling site-packages and pip...
if not exist "%EMBED_DIR%\Lib\site-packages" mkdir "%EMBED_DIR%\Lib\site-packages"
(
  echo python%PY_MM%.zip
  echo .
  echo Lib\site-packages
  echo import site
) > "%EMBED_DIR%\python%PY_MM%._pth"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%GETPIP_URL%' -OutFile '%EMBED_DIR%\get-pip.py' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto download_fail
"%EPY%" "%EMBED_DIR%\get-pip.py" --no-warn-script-location
if errorlevel 1 goto pip_fail
del "%EMBED_DIR%\get-pip.py" >nul 2>&1

:have_python
echo  [4/7] Verifying embedded Python and updating pip...
"%EPY%" -c "import sys; print(sys.version); print('Runtime:', sys.executable)"
if errorlevel 1 goto runtime_fail
"%EPY%" -m pip install --upgrade pip setuptools wheel --no-warn-script-location
if errorlevel 1 goto pip_fail

echo  [5/7] Installing PyTorch 2.8 for %TORCH_INDEX%...
"%EPY%" -m pip install --upgrade --force-reinstall torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/%TORCH_INDEX% --no-warn-script-location
if errorlevel 1 goto torch_fail

echo  [6/7] Installing official Qwen3-TTS and local server dependencies...
"%EPY%" -m pip install "qwen-tts==0.1.1" flask soundfile imageio-ffmpeg --no-warn-script-location
if errorlevel 1 goto qwen_fail

echo  [7/7] Verifying imports and CUDA visibility...
"%EPY%" -c "import sys, torch; from qwen_tts import Qwen3TTSModel; import flask, soundfile, imageio_ffmpeg; print('Embedded Python:', sys.executable); print('PyTorch', torch.__version__, '| CUDA available:', torch.cuda.is_available()); print('Qwen3-TTS import: OK')"
if errorlevel 1 goto verify_fail

echo ok> "%EMBED_DIR%\.installed"
echo %PY_VERSION%> "%EMBED_DIR%\.python_version"
echo.
echo ============================================================
echo  Optional Qwen3-TTS is installed autonomously.
echo  No system Python was used or modified.
echo  For best cloning, add the exact transcript of the voice sample.
echo ============================================================
echo.
pause
exit /b 0

:download_fail
echo.
echo  Download failed. Check the Internet connection and retry.
goto failed
:extract_fail
echo.
echo  Extraction failed. Delete %EMBED_DIR% and retry.
goto failed
:runtime_fail
echo.
echo  The embedded runtime is incomplete. Delete %EMBED_DIR% and retry.
goto failed
:pip_fail
echo.
echo  pip installation or update failed. Delete %EMBED_DIR% and retry.
goto failed
:torch_fail
echo.
echo  PyTorch installation failed. Check TORCH_INDEX and your connection.
goto failed
:qwen_fail
echo.
echo  Qwen3-TTS installation failed. See the error above.
goto failed
:verify_fail
echo.
echo  Import verification failed. Delete %EMBED_DIR% and retry.
goto failed
:failed
echo.
pause
exit /b 1
