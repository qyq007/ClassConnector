# 用 Visual Studio 打开与调试

仓库根目录提供 **`ClassConnector.sln`** 和 **`ClassConnector.pyproj`**，用 Visual Studio 打开即可编辑、F5 调试整个项目（采集端 Python + 管理端静态页面）。

> 若你用的是 **VS Code**，请用 `.vscode/` 配置，见 [开发指南](DEVELOPMENT.md)。两者互不冲突。

## 1. 环境要求

- **Visual Studio 2019 / 2022**（Community 版即可）
- 安装时勾选 **「Python 开发」工作负载**（Python development workload）。没有它，VS 会提示项目类型不受支持，此时仍可用「文件 → 打开 → 文件夹」把整个目录作为文件夹工作区来编辑，只是不能用 F5 调试。
- Python 3.8+ 解释器（VS 会自动探测；也可在「Python 环境」窗口里指定）

## 2. 打开项目

双击根目录的 `ClassConnector.sln`，或 VS 里「文件 → 打开 → 项目/解决方案」选中它。

解决方案包含：

| 节点 | 内容 |
| --- | --- |
| `ClassConnector`（Python 项目） | `agent/`、`manager/`、`scripts/`、`docs/`、`tests/` 全部文件，按文件夹分组 |
| `Solution Items` | README、PORTABLE.txt、requirements、各文档快捷入口 |

`.pyproj` 里已经配置好：

- `StartupFile` = `agent\portable.py` → **F5 直接以绿色便携模式启动**（不写注册表、不注册自启，数据写到 `data/`）
- `WorkingDirectory` / `SearchPath` = 项目根目录 → `import agent` 正常解析
- `CommandLineArguments` = `--no-browser` → 调试时不自动弹浏览器，如需可删掉
- `LaunchProvider` = Standard Python launcher、`TestFramework` = Pytest

## 3. F5 调试

1. 首次运行前，在 VS 的「Python 环境」节点选择你的解释器，并确认装了依赖：
   `python -m pip install -r requirements-dev.txt`（或双击 `scripts/start-portable.bat` 让它自动装到目录内 `runtime/venv`）。
2. 按 **F5**。控制台会打印本机与局域网管理地址，浏览器打开 `http://127.0.0.1:8420/`。
3. 断点可直接打在 `agent/server.py`、`agent/camera.py`、`agent/portable.py` 等任意 Python 文件里。
4. 前端 `manager/*.js` / `*.css` / `index.html` 改完**刷新浏览器即生效**，无需编译或重新生成。

> 调试时配置与日志落在项目目录的 `data/` 下（已被 `.gitignore` 忽略），不会写用户目录。想恢复正式安装版行为，改用 `python -m agent.install`。

## 4. 常用操作

| 需求 | 做法 |
| --- | --- |
| 指定端口 | 项目属性 → Debug → Script Arguments 加 `--port 8421` |
| 自动打开浏览器 | 去掉 `--no-browser` |
| 设置退出密码 | 命令行运行 `python -m agent.portable --set-password`，或双击 `scripts/set-password.bat` |
| 跑单元测试 | 测试资源管理器（Pytest），或 `pytest tests/test_units.py -q` |
| 新增文件后同步项目树 | 运行 `python scripts/gen_vs_project.py` 重新生成 `.pyproj` / `.sln` |
| 打发行 zip | 运行 `python scripts/package.py` |

`scripts/gen_vs_project.py` 会扫描当前目录、自动排除 `.git`、`data/`、`runtime/`、`dist/`、`__pycache__` 等运行时目录，并按 UTF-8 + CRLF 重写两个项目文件。**新增源码文件后跑一次，VS 里就能立刻看到。**

## 5. 常见问题

- **项目显示「加载失败 / 需要安装工作负载」**：在 Visual Studio Installer 里补装「Python 开发」，然后重新打开 sln。
- **F5 报 `No module named agent`**：`WorkingDirectory` 被改成了别的目录，改回项目根目录；或检查 `.pyproj` 的 `SearchPath` 是否包含 `.`。
- **F5 报缺 fastapi / uvicorn**：给当前解释器装依赖，或让 `scripts/start-portable.bat` 建好 `runtime/venv` 后在 VS 里把解释器切到 `runtime\venv\Scripts\python.exe`。
- **Python 3.8 用户**：项目已做兼容（`agent/compat.py` 提供 `asyncio.to_thread` 降级），3.8 可直接调试。
- **想改启动入口**：编辑 `scripts/gen_vs_project.py` 里的 `StartupFile` 常量后重新生成；也可直接在 VS 项目属性里改「Startup File」。
