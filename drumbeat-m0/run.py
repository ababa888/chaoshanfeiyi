"""《踏鼓 / Project Drumbeat》M0 原型可执行入口。

开发运行：python run.py
打包运行：PyInstaller 以本文件为入口生成单文件 exe。
"""
from __future__ import annotations

import os
import sys
import traceback


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _report(msg: str) -> None:
    try:
        with open(os.path.join(_app_dir(), "crash.log"), "w", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg[-1800:], "踏鼓 M0 启动失败", 0x10)
    except Exception:
        pass


def main() -> int:
    try:
        from drumbeat.app import main as app_main
        return app_main()
    except Exception:
        _report(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())