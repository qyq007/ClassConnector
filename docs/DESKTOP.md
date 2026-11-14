# 桌面版（ClassConnector.exe）使用与构建

> 从 v1.2.0 起，推荐的使用方式是**双击 exe**：不需要 `.bat`、不需要命令行、不需要在教室电脑上安装 Python。exe 自带 Python 运行时与全部依赖。

## 一、双击之后会发生什么

1. 打开 **「ClassConnector · 设置」** 窗口（纯设置界面，没有监控画面）。
2. 后台线程自动启动采集端 HTTP / WebSocket 服务，默认监听 `0.0.0.0:8420`。
3. 窗口底部状态栏显示：运行状态、连接数、摄像头帧率、局域网地址。
4. 默认延迟 1.5 秒自动打开本机管理端；也可随时点「打开管理端」。
5. 同一局域网的其它电脑 / 手机浏览器打开状态栏里的地址，即可进入管理端（管理端也已适配竖屏）。

首次运行会在 exe 同目录创建 `data/`，里面只有 `config.json`、`agent.log`、横幅与 TTS 缓存。**不写注册表、不注册开机自启、不创建系统服务或托盘、不改系统 Python**；退出后删除整个文件夹即完成卸载。

退出按钮 / 关闭窗口时，如果设置过退出密码，会弹出输入框校验；密码以 PBKDF2-HMAC-SHA256 + 随机盐保存在 `data/config.json`，任何接口都不会返回明文或哈希。

## 二、设置窗口

| 页签 | 可设置项 |
| --- | --- |
| **摄像头** | 本机摄像头设备（下拉 + 刷新）、分辨率、帧率、JPEG 画质、**是否允许管理端枚举 / 切换摄像头** |
| **播报与音效** | 启用语音播报、Edge TTS 语音（晓晓 / 云希 / 云健等 8 种）、语速、音量、紧急事件独立警报音开关、试听播报、试听警报音 |
| **网络与安全** | 班级名称、服务端口、空闲休眠秒数、管理端密码登录、设置 / 修改退出密码、局域网访问地址 |

底部按钮：`打开管理端`、`重启服务`、`保存设置`、`退出`。

修改端口后点「保存设置」会自动按新端口重启服务；其余设置即时生效，无需重启。

## 三、摄像头权限：主机侧锁定（重要）

默认配置 `camera.remote_select = false`。此时：

- **只有本机设置窗口**能调用 `CameraHub.list_devices()` 枚举本机全部摄像头，并把选定的 `camera.index` 写入配置；
- `GET /api/camera/devices` 只返回**主机指定的那一个设备**，不返回其它设备、也不暴露设备总数；
- `POST /api/camera/config`、`POST /api/config`、WebSocket `camera_config` 消息里的 `index` 会被**静默丢弃**（返回 `ignored_fields: ["index"]`），避免通过报错探测设备信息；
- `camera.remote_select` **不能通过任何网络接口修改**，管理端无法自行解锁；`POST /api/config` 的 `camera` 白名单也不含 `index` / `remote_select`；
- Web 管理端检测到 `locked: true` 时，会隐藏「摄像头设备」下拉并显示提示，应用画质时也不再发送 `index`。

这样能确保教室电脑上接了多个影像设备（例如内置摄像头 + 外接展台 + 其它 USB 设备）时，管理端**只能看到老师在这台电脑设置里指定的那一路**。

需要放开时，在设置窗口「摄像头 → 网络访问权限」勾选「允许管理端在 Web 上枚举 / 切换摄像头」并保存。请只在可信局域网内开启；**不要把 8420 端口映射到公网**。

## 四、Web 端 icon 与桌面应用一致

`scripts/make_icons.py` 用纯几何方式绘制同一份图形（深蓝圆角底 + 两个白色 C 弧 + 中间连接线），生成：

| 文件 | 用途 |
| --- | --- |
| `assets/icon.svg` | 矢量源文件 |
| `assets/icon.png` / `assets/icon.ico` | 桌面窗口图标、Windows exe 图标（16~256 多尺寸） |
| `manager/icon.png` | 管理端顶栏 logo、PWA 图标 |
| `manager/favicon.ico` | 浏览器标签页 |
| `manager/apple-touch-icon.png` | 添加到 iOS 主屏 |
| `manager/manifest.webmanifest` | PWA manifest（`display: standalone`） |

改图标后运行 `python scripts/make_icons.py` 会同时刷新全部资源，桌面与 Web 不会出现两套图标。

## 五、竖屏适配

`manager/style.css` 中 `@media (orientation: portrait)` 会把连接页、监控页、横幅页、设置页的所有双栏栅格改为单栏，视频舞台改为 `4/3`（窄竖屏 `1/1`），顶栏换行，标签栏横向可滚动，按钮与输入框触控高度提升到 42px，并处理 `safe-area-inset`。横屏窄设备仍走原有的 `max-width` 规则。

## 六、如何得到 exe

### 方式 A：CI 自动构建（推荐）

仓库的 `.github/workflows/build-exe.yml` 在以下时机于 `windows-latest` 上构建：

- 提 PR / 更新 PR → 在 PR 的 Checks 里下载 artifact **`ClassConnector-Windows-exe`**；
- 推送 `v*` tag → 自动把 exe 附加到对应 Release；
- 也可在 Actions 页面手动 `workflow_dispatch`。

流程：`setup-python 3.11` → 安装 `requirements-build.txt` → 生成图标 → `scripts/build_exe.py` 调用 PyInstaller → 校验大小与 SHA256 → 上传。

### 方式 B：本地 Windows 自行编译

```bat
python -m pip install -r requirements-build.txt
python scripts/make_icons.py
python scripts\build_exe.py
```

产物：`dist\ClassConnector.exe`（单文件、`console=False`、图标为 `assets/icon.ico`）。构建只依赖 `ClassConnector.spec`，其中会把 `manager/`、`assets/` 以及全部可选依赖（OpenCV / PyAudio / edge-tts / pygame / mss）一起打进 exe，因此最终用户电脑上什么都不会被安装。

> PyInstaller **不支持跨平台编译**：Windows exe 必须在 Windows 上构建，macOS / Linux 同理。仓库提供的 CI 已覆盖 Windows。

### 方式 C：不想打包，直接开窗口

```bash
python -m agent.desktop            # 与 exe 完全相同的设置窗口
python -m agent.desktop --no-browser --port 8420
python -m agent.desktop --headless-check   # 无显示器环境自检控制层
```

## 七、冻结（frozen）路径处理

`agent/paths.py` 统一处理两种运行形态：

| | 源码运行 | exe 运行 |
| --- | --- | --- |
| 只读资源（`manager/`、`assets/`） | 仓库根目录 | `sys._MEIPASS`（PyInstaller 解压目录） |
| 可写数据（`data/`） | 仓库根 `data/` | **exe 所在目录** `data/` |

`agent.config.app_dir()`、`agent.server.MANAGER_DIR`、`agent.platform_util.project_root()` 与 `agent.portable.prepare()` 都走这两个函数。横幅窗口原本是独立 Python 子进程，exe 模式下由 `agent.paths.banner_argv()` 改成复用同一个 exe 并传 `--cc-banner <spec.json>`，因此冻结后横幅、签收、TTS 仍然可用。

## 八、常见问题

**Q：双击 exe 没反应 / 被杀毒软件拦截？**
PyInstaller onefile 首次启动会解压到临时目录，慢 2~5 秒属正常；部分杀软会误报，可加白名单或用 `scripts/build_exe.py` 自行构建。

**Q：exe 里能用摄像头 / 麦克风 / 语音播报吗？**
能，依赖已打进 exe。Edge TTS 合成仍需联网；若本机无音频播放后端，设置窗口的「播报与音效」页会显示当前播放器状态。

**Q：管理端说看不到摄像头设备列表？**
这是设计如此（主机侧锁定）。请到教室电脑的设置窗口选择设备；需要列表出现在 Web 上再勾选「允许管理端枚举 / 切换摄像头」。

**Q：还可以开机自启吗？**
桌面 exe 版刻意**不注册自启**（绿色）。需要开机自启请用安装版 `python -m agent.install` / `scripts/install.bat`，它仍保留注册表 Run / XDG autostart / systemd / LaunchAgent 能力。
