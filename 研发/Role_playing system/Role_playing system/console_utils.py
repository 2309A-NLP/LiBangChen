# -*- coding: utf-8 -*-
"""
控制台编码辅助工具
功能：配置 Windows 控制台编码为 UTF-8，确保中文输出正确显示。
解决 Windows 终端默认编码（GBK）与 Python UTF-8 编码不兼容导致的中文乱码问题。

主要函数：
  - configure_console_encoding(): 配置控制台和标准流编码
"""

import locale
import os
import sys


def configure_console_encoding() -> None:
    """
    配置控制台编码为 UTF-8。
    
    功能：
    1. 设置 PYTHONIOENCODING 环境变量为 utf-8
    2. 重新配置 stdout/stderr 编码为 utf-8
    3. 在 Windows 上通过 Win32 API 设置控制台代码页为 65001 (UTF-8)
    4. 设置 locale 为系统默认
    """
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if os.name != "nt":
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
