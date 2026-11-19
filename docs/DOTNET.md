# Visual Studio 2022 构建 / 调试 / 打包指南

本版是**纯 C# / .NET 8 项目**，不再有 Python、不再有 `.bat`、不再有 PyInstaller。
之前在 VS 里调试 Python 版遇到的报错（中文批处理乱码、`No module named 'agent'`、
打包后服务起不来）在本方案中从根上不存在。

---

## 1. 环境

| 项 | 要求 |
| --- | --- |
| IDE | Visual Studio 2022 **17.8 或更高** |
| 工作负载 | 「.NET 桌面开发」+「ASP.NET 和 Web 开发」 |
| SDK | .NET 8 SDK（VS 自带；`global.json` 里 `rollForward: latestMajor`，更高版本 SDK 也能用） |
| 目标平台 | Windows x64（采集端 exe 只在 Windows 运行） |

`global.json` 里的版本是**下限**而非锁定，避免「SDK 版本不匹配」导致 VS 打不开解决方案。
`Directory.Build.props` 统一设置 `Nullable`、`LangVersion`、`DebugType=embedded`，
并显式关闭 `TreatWarningsAsErrors`，保证 F5 时警告不会变成阻断错误。

---

## 2. 打开与调试

1. 双击根目录 **`ClassConnector.sln`**。
2. 解决方案里有 3 个项目：
   - `ClassConnector.Core`（类库，跨平台）
   - `ClassConnector.App`（WinForms 桌面应用，**启动项目**）
   - `ClassConnector.Tests`（xUnit）
3. 按 **F5**（或「调试 → 开始调试」）。VS 会：
   - 还原 NuGet、编译 Debug；
   - 启动 `ClassConnector.exe`（调试宿主）；
   - 打开设置窗口，后台启动 Kestrel 服务；
   - 1.5 秒后自动打开 `http://127.0.0.1:8420/`。

### launchSettings.json 的三个调试配置

| Profile | 参数 | 用途 |
| --- | --- | --- |
| `ClassConnector (Debug)` | `--no-browser` | 默认：只开设置窗口，不自动弹浏览器 |
| `ClassConnector (Tray only)` | `--minimized --no-browser` | 验证托盘 / 纯后台运行：只有右下角图标 |
| `ClassConnector (Service only)` | `--no-browser --no-service` | 只调界面，不启动服务 |

其他可用参数：`--port 9000`（临时改端口）、`--headless-check`（托盘模式 + 服务自检，CI 用）。

### 建议下断点的地方

| 关注点 | 文件 / 方法 |
| --- | --- |
| 服务是否真的启动 | `Core/Hosting/AgentServerHost.StartAsync()`、`ProbeAsync()` |
| 服务启动失败原因 | `AgentServerHost.LastError`（状态栏红字、托盘气泡也会显示） |
| 服务路由与 API | `Core/Hosting/AgentServer.MapApis()` |
| 摄像头名称 | `App/Windows/WindowsCameraNameProvider.GetFriendlyNames()` |
| 摄像头画面 | `App/Windows/WindowsCameraFrameSource.ReadJpeg()` |
| 托盘与关闭行为 | `App/TrayHost.cs`、`Forms/MainForm.OnFormClosing()`、`AppBootstrapper.HideToTray()` |
| 空闲休眠 | `Core/Runtime/AgentRuntime.CheckIdle()` |

运行日志：`data/agent.log`（相对 exe 所在目录），Kestrel 日志也写这里，不弹控制台。

---

## 3. 之前那些报错，现在为什么不会再出现

| 旧报错 | 原因 | 本版 |
| --- | --- | --- |
| `'cho' 不是内部或外部命令`、`'orlevel'`、`'装'` | 中文 `.bat` + LF + `chcp 65001` 被 cmd 按字节拆开 | **没有任何 .bat**，双击 exe 或 VS F5 |
| `No module named 'agent'` | 批处理 `cd /d` 被吞，工作目录不对 | 无 Python 模块概念，程序集引用由 MSBuild 管理 |
| VS 里 F5 调试不了 / `.pyproj` 报错 | PTVS 的 Python 项目方案 | 真正的 `.sln` + `.csproj`（SDK 风格项目 GUID `9A19103F…`），VS 原生支持 |
| 打包后 exe「服务起不来」 | `--windowed` 下 `sys.stdout is None`，uvicorn 彩色 formatter 调 `isatty()` 崩溃，线程静默死亡 | Kestrel 同进程内嵌，日志只写文件；启动时做 HTTP 健康探测，失败可见 |
| `NETSDK1100: Windows is required to build Windows desktop applications` | 非 Windows 构建机缺 Windows targeting pack | csproj 已设 `<EnableWindowsTargeting>true</EnableWindowsTargeting>`，CI 可交叉编译 |
| 打包后找不到管理端页面 / 图标 | 资源未随 exe 发布 | `manager/`、`assets/` 作为 Content 发布；`.ico` 由 `CopyIconResourcesToPublish` 目标显式复制 |

### 仍然可能遇到的问题

- **端口被占用**：状态栏显示「■ 启动失败」并给出原因；在「网络与安全」页改端口后会自动重启服务。
- **浏览器打开 `http://设备IP:8420` 是空白 / 404，但 `/api/health` 能通**：曾因只设了 `WebRootPath` 而没有同步 `WebRootFileProvider`，导致 `UseStaticFiles` 指向默认 `wwwroot`，管理页返回 404。现已同时设置 `PhysicalFileProvider(manager)`，并有回归测试 + CI 冒烟（除 `/api/health` 外还会抓取 `GET /` 验证页面非空）。
- **局域网其他设备连不上**：服务固定监听 `0.0.0.0`（配置里的空值 / `127.0.0.1` 会自动纠正），先到「网络与安全 → 局域网访问地址」点 **「放行端口到局域网（需管理员）」** 添加入站规则；若仍不通，检查路由器是否开启了 AP/访客隔离。可用地址在状态栏与该页列出，`/api/health` 也返回 `bind` 与 `lan_urls` 便于核对。
- **NuGet 还原失败**：需要能访问 `api.nuget.org`；VS 里「工具 → NuGet 包管理器 → 还原」重试。
- **OpenCV native dll 缺失**：`OpenCvSharp4.runtime.win` 已随包发布；单文件模式会自解压到临时目录。若杀毒软件拦截，将文件夹加入白名单。

---

## 4. 打包 / 发布 exe

### 方式 A：VS 图形界面（推荐）

1. 右键 `ClassConnector.App` → **发布**。
2. 目标选「文件夹」→ 下一步 → 文件夹（默认 `bin/Release/net8.0-windows/win-x64/publish/`）。
3. 「显示所有设置」确认：
   - 配置 `Release`、目标运行时 `win-x64`、部署模式 **独立**；
   - 已由 csproj 固定：生成单个文件 ✅、启用压缩 ✅、包含本机库自解压 ✅。
4. 点「发布」。把输出目录**整个文件夹**拷到教室电脑，双击 `ClassConnector.exe`。

### 方式 B：命令行 / CI

```bash
dotnet publish src/ClassConnector.App/ClassConnector.App.csproj \
    -c Release -r win-x64 --self-contained true -o publish
```

产物：

```
publish/ClassConnector.exe   # 约 119 MB，PE32+ GUI，自带 .NET 运行时
publish/manager/             # 管理端页面（含 favicon.ico / PWA / 竖屏适配）
publish/assets/              # icon.ico / icon.png
```

> `manager/` 与 `assets/` 是随 exe 一起交付的静态资源，**不要只单独拷 exe**。
> CI（`.github/workflows/build-dotnet.yml`）在 `windows-latest` 上执行
> restore → Debug/Release build → test → publish → 上传 artifact，打 `v*` tag 时附加到 Release。

### 验证产物

```powershell
Get-Item publish/ClassConnector.exe
Get-FileHash publish/ClassConnector.exe -Algorithm SHA256
```

测试（无需 Windows 界面，Linux/macOS 也能跑 Core 与测试项目）：

```bash
dotnet test ClassConnector.sln -c Release
# 27 个用例，包含真实 Kestrel 服务的 HTTP / MJPEG / WebSocket 集成测试
```

---

## 5. 绿色版与数据

- 所有运行时数据落在 exe 同目录 `data/`：`config.json`、`agent.log`、`PORTABLE.txt`。
- 管理密码用 PBKDF2-HMAC-SHA256（20 万次迭代、随机盐）保存，接口永不返回明文或哈希。
- 不安装系统服务、不往用户目录写文件；删掉文件夹即卸载。
- **开机自启为可选开关**：设置窗口「启动方式 → 开机自动启动」勾选后写入当前用户 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 一条 `ClassConnector`（命令带 `--minimized --no-browser`），取消勾选即删除；Web 端 `POST /api/autostart` 等效。仅影响当前用户，不写机器级策略。
- 打开设置窗口、重启程序和退出都校验同一个管理密码；关闭设置窗口只是隐藏到托盘，服务继续运行。

---

## 6. 数据流向（调试时便于定位）

```
VS F5
 └─ Program.Main (STAThread, 单实例 Mutex)
     └─ AppBootstrapper
         ├─ AppConfigStore  → data/config.json
         ├─ CameraService   → 后台采集循环 → Channel<byte[]> 广播
         │    └─ WindowsCameraFrameSource (OpenCV / DirectShow)
         ├─ AgentRuntime    → 连接计数 / 空闲休眠 / 日志环形缓冲
         ├─ AgentServerHost → Kestrel :8420 → 启动确认 + /api/health 探测
         │    └─ AgentServer → REST + MJPEG + /ws + 托管 manager/
         ├─ MainForm        → 设置窗口（关闭 = 隐藏）
         └─ TrayHost        → NotifyIcon 常驻（退出需密码）
```
