@echo off
REM Copyright 2026 Ariku
REM SPDX-License-Identifier: Apache-2.0
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM  AmiorAI v40.0.4 - Chatterbox Multilingual V3
REM  Self-healing official Python embeddable runtime.
REM  No system Python and no virtual environment are required.
REM ============================================================
set "PY_VERSION=3.11.9"
set "PY_MM=311"
set "EMBED_DIR=python_chatterbox"
set "EPY=%EMBED_DIR%\python.exe"
set "PTH_FILE=%EMBED_DIR%\python%PY_MM%._pth"
set "ZIP_NAME=python-%PY_VERSION%-embed-amd64.zip"
set "ZIP_URL=https://www.python.org/ftp/python/%PY_VERSION%/%ZIP_NAME%"
set "GETPIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "TORCH_INDEX=cu128"
set "CHATTERBOX_VERSION=0.1.7"
set "PIP_LOG=%CD%\install_chatterbox_pip.log"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PYTHONUTF8=1"

if exist "%PIP_LOG%" del "%PIP_LOG%" >nul 2>&1
if exist "%EMBED_DIR%\.installed" del "%EMBED_DIR%\.installed" >nul 2>&1

echo.
echo ============================================================
echo  AmiorAI v40.0.4 - Chatterbox Multilingual V3
echo  Autonomous runtime: %EMBED_DIR%
echo ============================================================
echo.

if exist "%EPY%" goto runtime_ready

echo  [1/9] Downloading official Python %PY_VERSION% embeddable package...
if not exist "%EMBED_DIR%" mkdir "%EMBED_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_NAME%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto download_fail

echo  [2/9] Extracting the autonomous Python runtime...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -LiteralPath '%ZIP_NAME%' -DestinationPath '%EMBED_DIR%' -Force } catch { Write-Host $_.Exception.Message; exit 1 }"
del "%ZIP_NAME%" >nul 2>&1
if not exist "%EPY%" goto extract_fail
goto configure_runtime

:runtime_ready
echo  [1/9] Existing embedded Python detected; checking and repairing it...

:configure_runtime
echo  [3/9] Enabling site-packages for the embedded runtime...
if not exist "%EMBED_DIR%\Lib\site-packages" mkdir "%EMBED_DIR%\Lib\site-packages"
(
  echo python%PY_MM%.zip
  echo .
  echo Lib\site-packages
  echo import site
) > "%PTH_FILE%"

REM A partially-created runtime may have python.exe but no pip. Repair it automatically.
"%EPY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto pip_ready

echo  [4/9] pip is missing; bootstrapping it...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%GETPIP_URL%' -OutFile '%EMBED_DIR%\get-pip.py' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto download_fail
"%EPY%" "%EMBED_DIR%\get-pip.py" --no-warn-script-location
if errorlevel 1 goto pip_fail
del "%EMBED_DIR%\get-pip.py" >nul 2>&1
goto verify_runtime

:pip_ready
echo  [4/9] pip is already available.

:verify_runtime
echo  [5/9] Verifying embedded Python and updating build tools...
"%EPY%" -c "import sys, site; print(sys.version); print('Runtime:', sys.executable); print('site-packages:', site.getsitepackages())"
if errorlevel 1 goto runtime_fail
"%EPY%" -m pip install --upgrade pip setuptools wheel --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto pip_fail

echo  [6/9] Checking PyTorch 2.8 CUDA runtime...
"%EPY%" -c "import torch, torchaudio; assert torch.__version__.startswith('2.8.0'); assert torchaudio.__version__.startswith('2.8.0'); print('PyTorch already valid:', torch.__version__)" >nul 2>&1
if not errorlevel 1 goto torch_ready

echo        Installing PyTorch 2.8 for %TORCH_INDEX%...
"%EPY%" -m pip install --upgrade torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/%TORCH_INDEX% --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto torch_fail

:torch_ready
echo  [7/9] Installing or repairing Chatterbox dependencies...
"%EPY%" -m pip install --upgrade ^
  "numpy>=1.24,<2" "librosa==0.11.0" s3tokenizer ^
  "transformers==5.2.0" "diffusers==0.29.0" ^
  "conformer==0.3.2" "safetensors==0.5.3" ^
  spacy-pkuseg "pykakasi==2.3.0" pyloudnorm omegaconf ^
  flask soundfile imageio-ffmpeg --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto deps_fail
"%EPY%" -m pip install --upgrade "https://github.com/resemble-ai/Perth/archive/refs/heads/master.zip" --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto deps_fail

REM Install the official universal wheel without allowing its older torch pin to replace
REM the Blackwell-compatible PyTorch selected above.
echo  [8/9] Installing the official chatterbox-tts %CHATTERBOX_VERSION% package...
"%EPY%" -m pip install --upgrade --no-deps --only-binary=:all: "chatterbox-tts==%CHATTERBOX_VERSION%" --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto tts_repair

goto verify_import

:tts_repair
echo        Normal installation failed; forcing a clean package repair...
"%EPY%" -m pip uninstall -y chatterbox-tts >nul 2>&1
"%EPY%" -m pip install --no-cache-dir --force-reinstall --no-deps --only-binary=:all: "chatterbox-tts==%CHATTERBOX_VERSION%" --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto tts_fail

:verify_import
echo  [9/9] Verifying package location, imports and CUDA visibility...
"%EPY%" -c "import sys, importlib.util, importlib.metadata, torch; spec=importlib.util.find_spec('chatterbox'); assert spec is not None, 'module chatterbox absent'; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; import flask, soundfile, imageio_ffmpeg; print('Embedded Python:', sys.executable); print('Chatterbox:', importlib.metadata.version('chatterbox-tts')); print('Module:', spec.origin); print('PyTorch', torch.__version__, '| CUDA available:', torch.cuda.is_available()); print('Chatterbox import: OK')"
if errorlevel 1 goto final_repair

goto success

:final_repair
echo.
echo  Import verification failed. Performing one final clean reinstall...
"%EPY%" -m pip uninstall -y chatterbox-tts >nul 2>&1
"%EPY%" -m pip install --no-cache-dir --force-reinstall --no-deps --only-binary=:all: "chatterbox-tts==%CHATTERBOX_VERSION%" --no-warn-script-location --log "%PIP_LOG%"
if errorlevel 1 goto tts_fail
"%EPY%" -c "from chatterbox.mtl_tts import ChatterboxMultilingualTTS; import importlib.metadata; print('Chatterbox import repaired:', importlib.metadata.version('chatterbox-tts'))"
if errorlevel 1 goto verify_fail

:success
echo ok> "%EMBED_DIR%\.installed"
echo %PY_VERSION%> "%EMBED_DIR%\.python_version"
echo %CHATTERBOX_VERSION%> "%EMBED_DIR%\.chatterbox_version"
echo.
echo ============================================================
echo  Chatterbox Multilingual V3 is installed and verified.
echo  Existing partial runtimes have been repaired automatically.
echo  No system Python was used or modified.
echo  Model weights will download automatically on first start.
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
echo  pip installation or update failed. See %PIP_LOG%.
goto failed
:torch_fail
echo.
echo  PyTorch installation failed. See %PIP_LOG%.
echo  NVIDIA RTX 30/40/50: keep TORCH_INDEX=cu128.
echo  CPU only: edit this file and set TORCH_INDEX=cpu, then delete %EMBED_DIR%.
goto failed
:deps_fail
echo.
echo  A Chatterbox dependency failed to install. See %PIP_LOG%.
goto failed
:tts_fail
echo.
echo  The official chatterbox-tts package failed to install. See %PIP_LOG%.
goto failed
:verify_fail
echo.
echo  Chatterbox is still unavailable after repair. See %PIP_LOG%.
echo  Delete %EMBED_DIR% and run this installer again.
goto failed
:failed
if exist "%EMBED_DIR%\.installed" del "%EMBED_DIR%\.installed" >nul 2>&1
echo.
pause
exit /b 1
