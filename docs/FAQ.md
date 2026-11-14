# 常见问题排查

## 连接

**Q：管理端提示「连接失败」或「该地址不是 ClassConnector 采集端」？**

1. 在教室电脑上执行 `python -m agent.control status`，确认服务「在线」。
2. 浏览器直接访问 `http://<设备IP>:8420/api/health`，应返回含 `"service":"classconnector-agent"` 的 JSON。
3. 确认两台设备在同一局域网、教室电脑防火墙放行 TCP 8420（Windows 首次运行会弹出网络访问授权，请选择「允许」）。
4. 若改过端口，连接面板里要填新端口；`python -m agent.install --port 9000` 可修改。
5. 独立部署的管理端若用 `https://` 打开，浏览器会拦截 `http://` / `ws://` 的混合内容，请改用 `http://` 访问管理端页面。

**Q：地址填 IP 还是完整 URL？**

都支持：填 `192.168.1.50` + 端口 `8420`，或直接填 `http://192.168.1.50:8420`（此时端口框会被忽略）。

**Q：如何一个页面管理多个班级？**

在连接面板依次连接各台设备，它们会保存在浏览器 `localStorage`，用顶部下拉框切换。

---

## 画面

**Q：显示「测试画面」而不是真实摄像头？**

- 在「实时监控 → 画质设置 → 摄像头设备」里尝试其它索引，`GET /api/camera/devices` 可列出探测结果。
- Windows：检查「设置 → 隐私 → 相机」允许桌面应用访问摄像头；摄像头是否被其它软件（会议软件、监控客户端）独占。
- Linux：确认 `/dev/video*` 存在且当前用户有权限（`sudo usermod -aG video $USER`）。
- 未安装 `opencv-python` 时永远显示测试画面，执行 `pip install opencv-python` 后重启采集端。

**Q：画面卡顿 / 帧率低？**

降低画质（40–55）、分辨率（640×480）与帧率（10 fps）。多管理端同时观看不会重复占用摄像头，但会成倍占用出口带宽。

**Q：修改画质后画面没变？**

管理端会自动重载 MJPEG 流；若浏览器缓存了旧流，点「重载画面」。配置是设备级的，其他管理端会同步收到 `camera_config` 广播。

---

## 音频

**Q：听不到教室声音 / 对讲没声音？**

1. 在「设备设置 → 能力检测」看「音频监听」是否可用；不可用时安装 PyAudio：
   - Windows：`pip install pyaudio`
   - Linux：`sudo apt install portaudio19-dev && pip install pyaudio`
2. 浏览器麦克风权限：`getUserMedia` 只在 `http://localhost` 或 **HTTPS** 下可用。若管理端通过 `http://` + IP 独立部署，多数浏览器会拒绝麦克风 → 对讲无法录音。**解决办法**：直接访问采集端托管的页面（`http://设备IP:8420`）在部分浏览器同样受限，建议给管理端配置 HTTPS，或在浏览器地址栏对该 IP 添加安全例外（Chrome: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`）。
3. 音频播放需要用户手势，务必点击「开启监听」按钮，不要只靠自动播放。
4. 采集端扬声器/麦克风被系统静音或选错设备时，PyAudio 会打开默认设备，请在系统声音设置里检查。

**Q：对讲时有啸叫？**

对讲开启时采集端会立即停止推送教室音频、浏览器端也会停止播放，理论上不会自激。若仍有回声，请让对讲者戴耳机，或降低采集端扬声器音量。

---

## 横幅与播报

**Q：横幅没有在教室电脑上弹出？**

- 采集端必须运行在**有桌面会话**的用户会话中。Linux 服务器 / SSH 会话 / Windows 服务会话没有可显示桌面，此时 `display_mode=headless`，请用管理端「网页预览」查看。
- 检查是否安装 `tkinter`（Windows/macOS 自带；Linux 需 `sudo apt install python3-tk`）。
- 横幅为独立子进程，日志在 `<数据目录>/agent.log`；被安全软件拦截时会标记 `failed`。

**Q：紧急通知和普通通知的声音区别？**

紧急事件先播放一段本地生成的双音警报（`<数据目录>/urgent.wav`，可用任意 wav 覆盖），再朗读正文；普通通知只朗读。红色横幅样式也仅紧急事件使用。

**Q：Edge TTS 不播报？**

1. 确认安装 `edge-tts` 且教室电脑**能联网**访问微软语音服务；离线环境下横幅与警报音仍可用，只是不朗读。
2. 确认有音频播放器：安装 `pygame`（推荐）或 `ffmpeg`（提供 `ffplay`）。`GET /api/tts/status` 的 `player` 字段会显示当前后端，`last_error` 给出失败原因。
3. 语音名称必须是 edge-tts 支持的 ID，管理端下拉框已内置常用中文语音。

**Q：签收状态没有更新？**

横幅窗口通过 `http://127.0.0.1:<端口>/api/banner/ack` 回传。若采集端端口被改过但旧窗口仍在运行，重启采集端即可。也可由管理端在「网页预览」里代签收。

---

## 截图与休眠

**Q：截图显示「屏幕截图不可用」占位图？**

说明采集端当前会话没有图形桌面（Linux 无 `DISPLAY`、Windows 服务会话、远程断开的会话）。截图需在**登录并解锁的桌面会话**中运行。响应头 `X-CC-Fallback: 1` 与 `X-CC-Meta` 会标明原因。

**Q：设备状态一直显示「休眠中」？**

这是正常设计：没有任何管理端连接且超过 `idle_timeout`（默认 20 秒）后，采集端释放摄像头与麦克风。打开管理页面 / 视频流会立即唤醒。设为 `0` 可关闭休眠（不推荐，会长期占用摄像头）。

---

## 安装、密码与自启

**Q：忘记安装密码怎么办？**

密码只以哈希保存，无法找回。有本地操作权限时：

```bash
python -m agent.control stop          # 若还记得密码
python -m agent.install --uninstall --force --purge   # 无密码强制卸载并删除配置
python -m agent.install                # 重新安装并设置新密码
```

`--force` 需要能物理操作教室电脑，这是刻意设计：远程无法绕过密码关闭采集端。

**Q：开机自启没有生效？**

| 系统 | 检查 |
| --- | --- |
| Windows | `python -m agent.control autostart` 查看注册表 Run 项；确认 `pythonw.exe` 路径有效；组策略是否禁用启动项 |
| Linux 桌面 | 确认 `~/.config/autostart/classconnector.desktop` 存在，且以图形会话登录 |
| Linux 服务器 | 用 `python -m agent.install --systemd`，然后 `systemctl --user enable --now classconnector` |
| macOS | 确认 `~/Library/LaunchAgents/com.classconnector.agent.plist` 已加载（`launchctl list | grep classconnector`） |

修改 Python 路径 / 移动仓库后需要重新运行安装器刷新自启指向。

**Q：端口被占用？**

`python -m agent.install --port 9000` 换端口，或先 `python -m agent.control stop` 停止旧实例。

**Q：Windows 后台运行看不到托盘图标？**

安装 `pystray`（`pip install pystray`）后重启采集端；没有托盘不影响任何功能，仍可用网页或 `python -m agent.control` 管理。

**Q：日志在哪？**

- Windows：`%APPDATA%\ClassConnector\agent.log`
- macOS：`~/Library/Application Support/ClassConnector/agent.log`
- Linux：`~/.classconnector/agent.log`

也可用 `python -m agent.control logs` 或管理端「运行日志」卡片查看。

---

## 安全

**Q：同网段其他人能随便看摄像头吗？**

默认信任局域网。建议在「设备设置」开启「需要管理密码登录」，或用 VLAN / 防火墙限制 8420 端口来源。**不要把采集端端口映射到公网**。

**Q：为什么开放了 CORS `*`？**

为了让部署在教师机 / 静态服务器上的管理端能跨源连接多台设备。这是局域网内部工具的取舍，若需更严格，可在 `agent/server.py` 的 `CORSMiddleware` 中把 `allow_origins` 改成管理端的具体地址。

---

## 绿色便携版与 Windows 批处理

**Q：双击 `.bat` 出现 `'cho' 不是内部或外部命令`、`'orlevel' ...`、`No module named 'agent'`，怎么回事？**

这是 **v1.0.0 的已知问题**：`.bat` 使用了 UTF-8 中文 + LF 换行 + `chcp 65001`，中文 Windows 的 `cmd.exe` 按字节解析时会把命令拆碎（`echo`→`cho`、`errorlevel`→`orlevel`），`cd /d` 被吞掉导致工作目录没切换，进而找不到 `agent` 包。**v1.1.0 已修复**：全部 `.bat` 改为纯 ASCII + CRLF 并去掉 `chcp 65001`。

- 请下载 **`ClassConnector-v1.1.0.zip`**，不要继续用 v1.0.0。
- 若你要自己改 `.bat`：**不要写中文、不要改成 LF 换行、不要加 BOM**；中文说明放在 `.txt` / `.md` 里。

**Q：不想安装到电脑里，能直接运行吗？**

能，用绿色便携版：双击 `scripts/start-portable.bat`（Linux/macOS 用 `bash scripts/start-portable.sh`）。它不写注册表、不注册自启、不建服务或托盘，依赖装到解压目录内 `runtime/venv`，所有数据只写 `data/`；退出按 Ctrl+C，卸载直接删除文件夹。详见 [PORTABLE.md](PORTABLE.md)。

**Q：绿色版日志在哪？**

解压目录下的 `data/agent.log`（不再是用户目录的 `%APPDATA%\ClassConnector\`）。

**Q：我是 Python 3.8，能跑吗？**

能。v1.1.0 起最低支持 3.8，`agent/compat.py` 为 `asyncio.to_thread` 提供了 3.8 降级实现。注意部分可选依赖（如 PyAudio）在 3.8 上可能没有预编译 wheel，缺失时对应功能自动降级，不影响启动。

**Q：Visual Studio 能打开吗？**

双击根目录 `ClassConnector.sln`（VS 2019/2022 +「Python 开发」工作负载），F5 即调试。详见 [VISUAL_STUDIO.md](VISUAL_STUDIO.md)。用 VS Code 则打开 `.vscode/` 配置，见 [DEVELOPMENT.md](DEVELOPMENT.md)。

**Q：不想用 `.bat`，也不想装 Python，有能直接双击的程序吗？**

有。下载 **`ClassConnector.exe`** 双击即可打开「ClassConnector · 设置」图形窗口，服务自动在后台启动；exe 自带 Python 运行时与全部依赖，教室电脑上不需要安装任何东西。窗口里可设置摄像头、播报语音、紧急音效、端口、密码与摄像头网络权限；底部状态栏显示局域网地址。数据只在 exe 同目录 `data/`，删除文件夹即卸载。

exe 由 `.github/workflows/build-exe.yml` 在 Windows runner 上自动构建（PR 的 Checks artifact 或 Release 资产），也可在 Windows 上执行 `python scripts/build_exe.py` 自行编译。**PyInstaller 不支持跨平台编译**，Windows exe 必须在 Windows 上生成。源码环境下 `python -m agent.desktop` 可打开同一个窗口。详见 [DESKTOP.md](DESKTOP.md)。

**Q：为什么管理端看不到「摄像头设备」下拉，也列不出本机所有摄像头？**

这是 v1.2.0 起的**主机侧锁定**（默认开启），属于隐私设计：只有教室电脑上的设置窗口能枚举并选择本机摄像头，Web 管理端只能使用主机指定的那一路画面。服务端 `GET /api/camera/devices` 在锁定状态下只返回一个设备，且不会暴露设备总数；`index` 在网络请求里会被静默忽略，`camera.remote_select` 开关也无法通过任何网络接口修改，因此管理端不能自行解锁。

如需放开，在设置窗口「摄像头 → 网络访问权限」勾选「允许管理端在 Web 上枚举 / 切换摄像头」并保存。请只在可信局域网内开启。

**Q：手机竖屏打开管理端能用吗？**

能。竖屏时所有双栏栅格改为单栏，视频画面放大为 4:3（窄屏 1:1），顶栏换行、标签横向滚动、按钮触控高度 42px，并处理了 `safe-area`。另外浏览器麦克风在非 HTTPS 的 `http://IP` 下仍会被浏览器限制，见上文 HTTPS 说明。
