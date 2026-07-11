@echo off
REM Copyright 2026 Ariku
REM SPDX-License-Identifier: Apache-2.0
setlocal
cd /d "%~dp0"
title AmiorAI - Repair Chatterbox

echo.
echo ============================================================
echo  AmiorAI - Chatterbox runtime repair
echo ============================================================
echo  This repair is safe to run on an existing installation.
echo  It verifies Python Embedded, pip, dependencies and the
echo  official chatterbox-tts package without using system Python.
echo.
call "%~dp0install.bat"
exit /b %ERRORLEVEL%
