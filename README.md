# ClassConnector · 班级连接器（.NET 8 / Visual Studio 2022）

教室电脑上的**采集端** + 教师浏览器里的**管理端**，全部跑在局域网内，不依赖云服务器、不依赖公网。

> ## v2.0：技术栈已切换为 .NET / C#
>
> 本项目**不再使用 Python**。请用 **Visual Studio 2022** 打开 `ClassConnector.sln`：
> 直接 **F5 调试**、「生成 → 发布」产出 `ClassConnector.exe`，所有修改都在 VS 里完成。
>
> 旧 Python / PyInstaller 版（v1.x，含 `.bat`、`agent/`、`requirements*.txt`、
> `ClassConnector.pyproj`）保留在仓库中作为归档，**不参与 `.sln` 构建、不再维护**。
> 那版存在「exe 无法启动服务」「没有系统托盘」「摄像头只显示编号」三个问题，本版已全部修复。

---

## 一、本次修复的三个问题

| 问题 | 旧版根因 | v2.0 做法 |
| --- | --- | --- |
| **exe 无法启动服务** | PyInstaller `--windowed` 下 `sys.stdout` 为 `None`，uvicorn 彩色日志 formatter 调用 `sys.stdout.isatty()` 抛异常，服务线程静默死亡；界面却仍显示「已启动」 | 改为 **.NET 8 进程内嵌 Kestrel**，不依赖控制台：所有日志写入 `data/agent.log`。`AgentServerHost.StartAsync()` 会 `await` 真正的端口绑定，并做一次 `/api/health` 探测；失败时状态栏和托盘气泡会显示具体错误，绝不假报「运行中」 |
| **不能右下角托盘运行** | 桌面版根本没有创建托盘 | WinForms `NotifyIcon` 常驻右下角；**关闭窗口 = 最小化到托盘**，服务继续在后台跑；托盘菜单含「打开设置窗口 / 打开管理端 / 重启服务 / 退出（需密码）」，双击图标回到设置；可勾选「启动即最小化到托盘」实现纯后台运行 |
| **选择摄像头页面不列名称** | 后端只返回 `f"摄像头 {index}"` | `WindowsCameraNameProvider` 通过 **WMI `Win32_PnPEntity`（Camera/Image）+ VFW `capGetDriverDescriptionW`** 取真实设备名（如 `Integrated Camera`、`Logitech C920 HD Pro Webcam`），设置窗口下拉框显示真实名称 + 设备号；网络侧锁定仍只暴露主机指定的那一路 |

---

## 二、Visual Studio 2022 快速开始

**环境**：VS 2022（17.8+），安装时勾选「.NET 桌面开发」与「ASP.NET 和 Web 开发」，自带 .NET 8 SDK。

1. 双击根目录 `ClassConnector.sln`（或 VS 里「打开项目/解决方案」）。
2. 把 `ClassConnector.App` 设为启动项目（已默认）。
3. 按 **F5**：直接编译并启动设置窗口，服务在后台自动运行，浏览器自动打开管理端。
4. 改代码 → 重新 F5 即可；需要换端口 / 不弹浏览器，用 `Properties/launchSettings.json` 里的三个 profile。
5. 出 exe：右键 `ClassConnector.App` →「发布」→ 选「文件夹」→ 发布，产物在 `publish/`。

命令行等价（CI 用的就是这套）：

```bash
dotnet restore ClassConnector.sln
dotnet build  ClassConnector.sln -c Debug          # 对应 VS 的 F5 调试
dotnet build  ClassConnector.sln -c Release
dotnet test   ClassConnector.sln -c Release       # 27 个单元 / 集成测试
dotnet publish src/ClassConnector.App/ClassConnector.App.csproj \
    -c Release -r win-x64 --self-contained true -o publish
```

> 详细步骤、调试排错见 [docs/DOTNET.md](docs/DOTNET.md)；接口见 [docs/API.md](docs/API.md)。

---

## 三、交付物

`publish/` 目录（整个文件夹拷到教室电脑即可）：

```
ClassConnector.exe        # 119 MB，单文件、自包含 win-x64，无需装 .NET / Python
manager/                  # Web 管理端静态页面（含 favicon / PWA / 竖屏适配）
assets/                   # 应用图标（与 Web 端同一份）
data/                     # 首次运行自动生成，配置与日志都在这里
```

**绿色版**：不装系统服务、不写系统目录；配置 `data/config.json`，日志 `data/agent.log`，管理密码用 PBKDF2-HMAC-SHA256 加盐哈希保存。开机自启是**可选开关**（设置窗口勾选后仅写一条当前用户的 `HKCU\...\Run` 值，随时可取消），删除文件夹即卸载；若开启过自启，请先取消勾选再删除。

**局域网连不上怎么办**：服务固定监听 `0.0.0.0`，Windows 防火墙通常会在首次运行时拦截。请到「网络与安全 → 局域网访问地址」点击 **「放行端口到局域网（需管理员）」**，在 UAC 提示中点「是」；或在 Windows 安全中心放行 TCP 8420（专用网络）。状态栏和该页会列出本机所有可用的 `http://IP:端口/` 地址。配置里若有残留的 `127.0.0.1` 监听地址，程序会自动纠正为 `0.0.0.0`。

---

## 四、功能对照

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 图形化设置窗口（只放设置） | ✅ | 三个页签：摄像头 / 播报与音效 / 网络与安全；底部状态栏显示服务状态、连接数、局域网地址；按钮：打开管理端 / 重启服务 / 保存设置 / 重启程序 / 退出 |
| 摄像头真实名称 + 主机侧锁定 | ✅ | 本机设置窗口枚举并选定；管理端默认只能用这一路，无法枚举或切换其他摄像头 |
| 实时画面（MJPEG）、画质 / 分辨率 / 帧率 | ✅ | OpenCV / DirectShow 采集；无摄像头时输出带时间戳的测试画面，服务照常可用 |
| 内嵌 HTTP / WebSocket 服务、局域网管理 | ✅ | Kestrel 监听 `0.0.0.0:8420`，开放 CORS，同时托管管理端页面 |
| 右下角托盘 / 后台运行 / 启动最小化 | ✅ | `NotifyIcon` + `ApplicationContext`；**关闭窗口 = 自动转入后台**，服务不中断，双击托盘图标回来 |
| 管理密码保护 | ✅ | 设置窗口「退出」、托盘「退出」、Web `/api/agent/stop` 校验同一管理密码；打开设置窗口与「重启程序」同样需要输入管理密码 |
| 开机自启（可选） | ✅ | 设置窗口「启动方式」勾选即可（当前用户 HKCU Run，`--minimized --no-browser`）；Web `POST /api/autostart` 也可切换 |
| 无连接时休眠 | ✅ | 超过「空闲休眠」秒数暂停采集，新连接立即唤醒 |
| 管理端页面 | ✅ | 复用原 SPA（IP+端口连接、实时监控、横幅、截图、竖屏适配、统一图标） |
| 屏幕截图（多显示器 / 缩放） | ✅ | Windows GDI `CopyFromScreen`，失败返回占位图并标记 `X-CC-Fallback` |
| Markdown 横幅 / 签收 / 紧急样式 | ✅ | Web 端渲染与签收，服务端保存历史与状态 |
| 语音播报 / 紧急警报音 | ⚠️ 部分 | 本地提示音与 `/api/tts/speak` 接口可用；Edge TTS 云端合成未内置（需联网的第三方组件） |
| 麦克风对讲 / 教室音频监听 | ⚠️ 未迁移 | 需要独立音频栈，本版 API 保留占位（`audio.available=false`） |

> ⚠️ 标记项是本次语言切换时有意收敛的范围，接口与页面保持兼容，后续可单独补齐。

---

## 五、解决方案结构

```
ClassConnector.sln                # VS 2022 解决方案（3 个 C# 项目）
global.json / Directory.Build.props
src/
  ClassConnector.Core/            # net8.0 跨平台：配置、密码、摄像头管道、Kestrel 服务、API
    Configuration/                #   AppConfig / AppConfigStore(PBKDF2) / AppPaths
    Camera/                       #   CameraService / CameraNameResolver / 设备 DTO
    Runtime/                      #   AgentRuntime（连接计数、空闲休眠、日志）
    Hosting/                      #   AgentServer（REST+WS+静态页）/ AgentServerHost（启动+健康探测）
  ClassConnector.App/             # net8.0-windows WinForms 桌面应用（主 exe）
    Forms/MainForm.cs             #   三页签设置窗口
    TrayHost.cs                   #   系统托盘
    AppBootstrapper.cs            #   组合根：生命周期 / 后台运行 / 密码退出
    Windows/                      #   WMI+VFW 名称、OpenCV 采集、截图、音效
  ClassConnector.Tests/           # net8.0 xUnit：27 个单元 + 真实 HTTP 集成测试
manager/                          # Web 管理端静态资源（随 exe 发布）
assets/                           # 统一图标（icon.svg / .png / .ico）
.github/workflows/build-dotnet.yml # Windows runner：build + test + publish + 上传 exe
```

`ClassConnector.Core` 是纯 `net8.0`，所以单元测试和 HTTP 接口**在 Linux/macOS 上也能跑**；只有 WinForms / 托盘 / 摄像头采集是 Windows 专属，用 `EnableWindowsTargeting` 支持非 Windows 构建机交叉编译。

---

## 六、归档说明

`agent/`、`scripts/*.bat`、`requirements*.txt`、`ClassConnector.pyproj`、`PORTABLE.txt`、
`docs/ARCHITECTURE.md` / `PORTABLE.md` / `VISUAL_STUDIO.md` / `FAQ.md` / `DEVELOPMENT.md`
属于 **v1.x Python 版归档**，不在 `ClassConnector.sln` 中，VS 打开解决方案时不会看到它们。
当前唯一维护的实现是 `src/` 下的 .NET 项目。
