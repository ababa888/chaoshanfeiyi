# 打包《踏鼓 / Project Drumbeat》M0 原型为单文件 exe
#
# 重要：必须使用「已安装 sounddevice 的 Python 环境」执行本脚本。
# 本机 python 命令对应 3.10 环境（含 pygame / numpy / sounddevice / PyInstaller），
# 而独立的 pyinstaller 命令指向另一个未安装 sounddevice 的环境，会导致打包出的 exe 静音。
#
# 用法：在 drumbeat-m0 目录下执行  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "踏鼓M0" `
    --add-data "drumbeat/data;drumbeat/data" `
    --add-data "assets;assets" `
    --collect-all sounddevice `
    --exclude-module tkinter `
    --exclude-module matplotlib `
    --exclude-module PIL `
    --exclude-module scipy `
    --exclude-module pandas `
    run.py

Write-Host ""
Write-Host "打包完成：dist\踏鼓M0.exe" -ForegroundColor Green
Write-Host "自检运行（自动退出并导出日志）：`$env:DRUMBEAT_SMOKE_FRAMES=400; .\dist\踏鼓M0.exe" -ForegroundColor DarkGray