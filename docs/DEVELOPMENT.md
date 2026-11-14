# 使用 VS Code 开发

本项目是**标准 Python 包 + 零构建静态前端**，不需要 webpack / Node 编译 / 数据库。用 VS Code 打开仓库根目录即可直接编辑与调试。

## 1. 打开项目

```bash
git clone https://github.com/ssq0324/ClassConnector.git
cd ClassConnector
code .
```

首次打开时 VS Code 会提示安装推荐扩展（`.vscode/extensions.json`）：Python、Pylance、debugpy、Black Formatter、EditorConfig、Live Server。点「安装全部」即可。

> 使用 **Visual Studio**（而非 VS Code）：直接双击根目录的 `ClassConnector.sln`（需「Python 开发」工作负载），F5 即以绿色便携模式调试，详见 [VISUAL_STUDIO.md](VISUAL_STUDIO.md)。没有该工作负载时也可用「文件 → 打开 → 文件夹」把本目录作为文件夹工作区编辑。

## 2. 准备解释器

建议在项目内建虚拟环境，VS Code 右下角选择该解释器：

```bash
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -r requirements-dev.txt
# Linux/macOS: .venv/bin/python -m pip install -r requirements-dev.txt
```

或者在命令面板运行任务 **「① 安装开发依赖（含测试工具）」**（`Ctrl/Cmd+Shift+P` → `Tasks: Run Task`）。

`requirements.txt` 中的摄像头、音频、TTS、托盘等依赖都是**可选的**，任一缺失都会自动降级。若 `PyAudio` 在你的环境编译失败，改用最小开发依赖即可，不影响编辑和绝大部分调试：

```bash
python -m pip install fastapi uvicorn python-multipart pytest requests websockets pyflakes
```

## 3. 调试启动（F5）

打开「运行和调试」侧栏，选择 **「采集端：调试启动（无托盘 · 8420）」** 后按 F5：

- 以模块 `agent` 启动，禁用托盘，日志级别 DEBUG，便于打断点；
- 配置与日志写入工作区下的 `.classconnector/`（已被 `.gitignore` 忽略），**不会污染系统目录，也不会注册开机自启**；
- 启动后浏览器打开 `http://127.0.0.1:8420/`，管理端会自动连接本机。

其它配置：

| 配置 | 用途 |
| --- | --- |
| 采集端：自定义端口 | 弹出输入框指定端口，避免与已运行实例冲突 |
| 安装向导（交互设置密码） | 调试 `agent.install` 的安装 / 卸载流程 |
| pytest：当前文件 | 调试当前打开的测试文件 |
| 管理端：Chrome 调试 | 附加 Chrome 到 `http://127.0.0.1:8420/`，调试 `manager/` 下的 JS |

## 4. 常用任务

`Ctrl/Cmd+Shift+P` → `Tasks: Run Task`：

| 任务 | 说明 |
| --- | --- |
| ① 安装运行依赖 | `pip install -r requirements.txt` |
| ① 安装开发依赖 | 追加 pytest / requests / websockets / pyflakes |
| ② 启动采集端（调试 8420） | 后台任务，等价于 F5 但无调试器 |
| ③ 单元测试（无需服务） | `pytest tests/test_units.py -q`（默认测试任务 `Ctrl+Shift+T` 之类可绑定） |
| ③ 密码与自启流程测试 | `python tests/password_flow_test.py` |
| ③ 端到端冒烟测试 | `pytest tests/smoke_test.py -q`，**需先启动采集端** |
| ④ 静态检查 + 前端语法 | `pyflakes` + `compileall` |
| ⑤ 打包发行 zip | `python scripts/package.py`，输出到 `dist/` |
| ⑥ 构建 Windows exe | `python scripts/build_exe.py`（**仅 Windows**，或由 `.github/workflows/build-exe.yml` 在 CI 构建） |

桌面设置窗口用「**桌面设置窗口（GUI · 与 exe 相同）**」配置 F5 启动，等价于 `python -m agent.desktop --no-browser`；无显示器环境可用 `python -m agent.desktop --headless-check` 只自检控制层。exe 打包链路见 [DESKTOP.md](DESKTOP.md)。

测试侧栏默认只收集 `tests/test_units.py`，避免在没有启动服务时误跑需要网络的冒烟测试。

## 5. 编辑前端

`manager/` 是纯静态 SPA（`index.html` + `style.css` + `app.js` + `markdown.js` + `audio.js`），改完**刷新浏览器即可生效**，无需构建。

两种预览方式：

1. **推荐**：保持采集端运行，直接访问 `http://127.0.0.1:8420/`（同源，WebSocket / 麦克风 / MJPEG 全部可用）；
2. 右键 `manager/index.html` → 「Open with Live Server」（端口 5500），此时页面会显示连接面板，需手工填入 `http://127.0.0.1:8420`。跨源访问已由采集端开放 CORS。

前端 JS 改完可顺手做语法检查：`node --check manager/app.js`。

## 6. 打包发行包

```bash
python scripts/package.py                       # 默认 dist/ClassConnector-v<版本>.zip
python scripts/package.py --output /tmp/cc.zip   # 自定义输出路径
python scripts/gen_vs_project.py                # 新增文件后刷新 .sln / .pyproj
```

脚本按白名单收集 `agent/ manager/ scripts/ docs/ tests/ .vscode/ assets/ .github/` 与顶层说明文件（含 `app_main.py`、`ClassConnector.spec`、`requirements-build.txt`），自动排除 `.git`、`__pycache__`、`*.pyc`、`.pytest_cache`、`data/`、`runtime/`、`build/`、`dist/`、日志与音频缓存。zip 内含单一顶层目录 `ClassConnector-v<版本>/`，并附 `VERSION.txt`、`README-FIRST.txt` 与 `PORTABLE.txt`，同时打印文件数与 SHA256 便于发布校验。**所有 `.bat` / `.sln` / `.pyproj` 在打包时强制转为 CRLF**，请勿把它们改成 LF 或加入中文（cmd 会解析错乱）。

版本号取自 `agent/__init__.py` 的 `__version__`，升级版本只需改这一处。

## 7. 常见问题

- **端口被占用**：用「采集端：自定义端口」配置，或改 `.classconnector/config.json` 里的 `port`。
- **浏览器无法使用麦克风对讲**：`http://` + IP 属于非安全上下文，独立部署的管理端需配 HTTPS，详见 `FAQ.md`。
- **改了 Python 代码没生效**：采集端不是热重载，按 `Ctrl+C` 停止后重新 F5。
- **调试时想恢复正式安装状态**：删掉调试环境变量 `CLASSCONNECTOR_HOME` 后重新运行 `python -m agent.install`，配置会回到用户目录。
- **提交前**：`git status` 确认 `.classconnector/`、`dist/`、`.venv/` 都未被跟踪（`.gitignore` 已覆盖）。
