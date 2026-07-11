# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath = Join-Path $ScriptDir "install_qwen.bat"
& cmd.exe /c "`"$BatPath`""
exit $LASTEXITCODE
