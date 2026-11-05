@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 踏鼓 M0

rem 只使用项目虚拟环境，避免误用系统 Python
rem 依次尝试：工作区 .venv、仓库根 .venv、游戏目录 .venv
set PY=
for %%P in ("%~dp0..\..\..\.venv\Scripts\python.exe" "%~dp0..\..\.venv\Scripts\python.exe" "%~dp0..\.venv\Scripts\python.exe" "%~dp0.venv\Scripts\python.exe") do (
  if not defined PY (
    if exist "%%~P" (
      "%%~P" -c "import pygame" >nul 2>&1
      if not errorlevel 1 set PY=%%~P
    )
  )
)

if not defined PY (
  echo [错误] 没有找到可用的 .venv 虚拟环境，或其中缺少 pygame。
  echo.
  echo 请确认以下任一位置存在 .venv：
  echo     %~dp0..\..\..\.venv
  echo     %~dp0..\..\.venv
  echo     %~dp0..\.venv
  echo     %~dp0.venv
  echo.
  echo 如需安装依赖：
  echo     "%~dp0..\..\..\.venv\Scripts\python.exe" -m pip install pygame numpy sounddevice pyinstaller
  pause
  exit /b 1
)

echo 使用解释器: %PY%
"%PY%" run.py
if errorlevel 1 pause
