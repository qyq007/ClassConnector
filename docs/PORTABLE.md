# 绿色便携版使用说明（不安装到电脑里）

> **v1.0.0 的 Windows 批处理有编码问题**：`.bat` 用了 UTF-8 中文 + LF 换行 + `chcp 65001`，中文 Windows 的 cmd 按字节解析时会把 `echo` 拆成 `cho`、`errorlevel` 拆成 `orlevel`，`cd /d` 被吞掉，于是工作目录没切换、报 `No module named 'agent'`。**v1.1.0 已把全部 `.bat` 改为纯 ASCII + CRLF 并去掉 `chcp 65001`**，同时把最低 Python 版本降到 3.8。

## 什么是「绿色版」

绿色版 = **解压即用、不写入系统**。与正式安装（`scripts/install.bat`）的区别：

| 项目 | 绿色便携版 | 正式安装版 |
| --- | --- | --- |
| 启动方式 | 双击 `scripts/start-portable.bat` | 双击 `scripts/install.bat` |
| 注册表 / 启动文件夹 / systemd / LaunchAgent | **不写** | 注册开机自启 |
| 系统服务 / 系统托盘 | **不创建** | 可选托盘 |
| 系统 Python 的 site-packages | **不写**（依赖装到目录内 `runtime/venv`） | 写入当前解释器 |
| 用户目录配置文件 | **不写**（全部在解压目录 `data/`） | 写到用户目录 |
| 管理员权限 | 不需要 | 部分自启方式需要 |
| 退出 | Ctrl+C / 关窗口 | 托盘退出或密码退出接口 |
| 卸载 | **删除整个文件夹** | `python -m agent.install --uninstall` |

功能完全一致：摄像头、监听/对讲、Markdown 横幅、签收、Edge TTS、紧急警报、屏幕截图、局域网管理、休眠唤醒都能用。

## 三步开始

1. 解压 zip，得到 `ClassConnector-v1.2.0/`。
2. 双击 **`scripts/start-portable.bat`**
   （Linux / macOS：`bash scripts/start-portable.sh`）
3. 首次运行会自动在文件夹内创建 `runtime/venv` 并安装核心依赖，随后启动服务并打开浏览器。

控制台会打印：

```
数据目录 : <解压目录>\data
管理地址 : http://127.0.0.1:8420/
局域网   : http://192.168.x.x:8420/
```

同局域网的教师机浏览器打开「局域网」地址即可连接；也可在管理端连接面板填写设备 IP + 端口。

> 要求 Python 3.8+ 且在 PATH 中（安装 Python 时勾选「Add Python to PATH」）。脚本会先找 `python`，再找 `py -3`。

## 目录结构（绿色版运行时新增）

```
ClassConnector-v1.2.0/
├── data/                    ← 唯一的数据写入位置
│   ├── config.json          配置（含 PBKDF2 密码哈希）
│   ├── agent.log            运行日志
│   ├── urgent.wav           紧急警报音
│   ├── banners/             横幅渲染参数
│   └── tmp/                 TTS 临时音频（播放后删除）
├── runtime/venv/            ← 便携虚拟环境（首次运行生成）
├── scripts/start-portable.bat
└── ... 源码与文档
```

`data/` 和 `runtime/` 都已被 `.gitignore` 忽略，不会污染仓库。

## 依赖策略

首次启动只装 `requirements-portable.txt` 的 4 个核心包（fastapi / uvicorn / python-multipart / Pillow），**保证几秒内启动成功**。缺其它依赖时程序自动降级：无摄像头显示测试画面、无音频设备静音、无 TTS 只显示文字横幅，状态页会明确标注。

想启用全部功能，把可选依赖也装进**目录内**的虚拟环境（依然不碰系统 Python）：

```bat
runtime\venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
runtime/venv/bin/python -m pip install -r requirements.txt
```

如果系统 Python 本来就已装好依赖，脚本会直接复用系统解释器、不创建 `runtime/venv`。

## 退出密码

绿色版保留了「退出需要密码」的安全机制，但密码只存在 `data/config.json`：

- 双击 **`scripts/set-password.bat`**（或 `python -m agent.portable --set-password`）设置/修改；
- 未设置密码时，管理端的「退出/重启/改密」接口保持锁定（与正式安装版一致）；
- 停止服务本身不需要密码——按 Ctrl+C 或关掉窗口即可。

## 停止与卸载

- **停止**：在黑色控制台窗口按 `Ctrl+C`，或直接关闭窗口。
- **卸载**：直接删除整个 `ClassConnector-v1.2.0` 文件夹，无残留、无需反安装。

## 用 Visual Studio 编辑

双击根目录 `ClassConnector.sln`（VS 2019/2022 +「Python 开发」工作负载），F5 即以绿色便携模式调试。详见 [VISUAL_STUDIO.md](VISUAL_STUDIO.md)。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 提示 `Python 3.8+ not found in PATH` | 安装 Python 3.8+ 并勾选 Add Python to PATH，或设置 `PYTHON` 环境变量指向解释器 |
| 首次运行卡在装依赖 | 需要联网；可手工执行脚本里那条 pip 命令看具体报错，PyAudio 装不上不影响启动 |
| 端口被占用 | `start-portable.bat --port 8421`，或改 `data/config.json` 的 `port` |
| 局域网其它电脑连不上 | 放行 Windows 防火墙的 8420 端口；确认两台机器在同一网段 |
| 麦克风对讲按钮灰色 | 浏览器安全策略要求 HTTPS 或 localhost，见 [FAQ.md](FAQ.md) |
| 想回到正式安装版 | 运行 `python -m agent.install`，它会注册自启并改用用户目录配置 |
