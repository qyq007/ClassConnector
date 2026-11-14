#!/usr/bin/env python3
"""ClassConnector 可执行文件入口（PyInstaller 构建脚本）。

源码调试可直接运行 ``python app_main.py``，效果等同双击 exe：
打开图形设置窗口并在后台启动采集端服务。
"""

from __future__ import annotations

import sys

from agent.desktop import main

if __name__ == "__main__":
    sys.exit(main())
