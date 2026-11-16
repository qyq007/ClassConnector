# REST / WebSocket API 参考（.NET 8 版）

- 基址：`http://<设备IP>:<端口>`，默认端口 `8420`（由 `data/config.json` 的 `Port` 决定）。
- 服务端是 exe 进程内嵌的 **ASP.NET Core / Kestrel**，同时托管 `manager/` 静态页面。
- 除图片与 MJPEG 流外，响应均为 JSON（`camelCase` / 蛇形混合，字段与 v1.x 前端兼容）。
- CORS 全开（`Access-Control-Allow-Origin: *`），便于把管理端单独部署后跨源连接。
- 日志写 `data/agent.log`，不写控制台。

---

## 认证

`require_auth = true` 时，除 `/api/health`、`/api/auth`、`/api/tts/voices` 与静态页面外，
所有 `/api/*` 请求都需要携带请求头 **`X-CC-Token: <token>`**。

```http
POST /api/auth
Content-Type: application/json

{"password": "设置窗口里设置的退出密码"}
```

```json
{"ok": true, "token": "...", "expires_in": 28800}
```

令牌有效期 8 小时，保存在进程内存中；改密或关闭 `require_auth` 时全部失效。
`/ws` 连接建立后会收到 `hello`，其中 `token_required` 指明是否需要认证。

`X-CC-Token` 请求头用于普通 `fetch`；`<img src>` 与 MJPEG 流无法设置请求头，
因此同时支持 `?token=<token>` 查询参数（管理端 `app.js` 的 `tokenQuery()` 用的就是它）。
两种形式与 v1.x 前端完全兼容，无需改动页面。

---

## 端点一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查：版本、教室名、IP、端口、实际监听 `host`/`bind`、`lan_urls`、休眠状态、是否设密码（**匿名**） |
| GET | `/api/status` | 汇总：设备（含 `bind`/`lan_urls`）、运行时、摄像头、音频、屏幕、横幅、TTS、`autostart`、配置、能力集 |
| GET | `/api/logs?limit=100` | 最近日志（最多 500 条） |
| GET | `/api/platform` | 运行平台信息；`autostart.enabled` 反映当前用户自启是否开启，`method` 为 `registry-run`（桌面版）或 `portable`（纯 Core 测试宿主） |
| POST | `/api/autostart` | `{"enabled": true/false}` 开启或关闭当前用户开机自启；桌面版由 App 提供实现 |
| GET | `/api/config` | 可公开配置（已剔除 `password_salt` / `password_hash`） |
| POST | `/api/config` | 更新教室名、设备名、空闲休眠、画质、TTS、登录开关等；**不接受 `camera.index` / `camera.remote_select`** |
| POST | `/api/password/change` | 校验旧密码后改密，并使所有令牌失效 |
| GET | `/api/camera/config` | 当前画质配置 + 采集状态 + `camera_select_locked` |
| POST | `/api/camera/config` | 调整 `width` / `height` / `fps` / `quality`；锁定状态下 `index` 被静默丢弃并写入 `ignored_fields` |
| GET | `/api/camera/devices` | 设备列表（**真实名称**，见下节） |
| GET | `/api/camera/snapshot` | 最新一帧 JPEG |
| GET | `/api/camera/stream` | MJPEG 流 `multipart/x-mixed-replace; boundary=classconnector-frame` |
| GET | `/api/screen/displays` | 显示器列表（index / name / width / height / primary） |
| GET | `/api/screen/shot?display=0&scale=1.0` | PNG 截图；失败返回占位图，并置 `X-CC-Fallback: 1`、`X-CC-Meta` |
| POST | `/api/banner/send` | 发送 Markdown 横幅（title / markdown / urgent / need_ack / tts / voice / duration） |
| GET | `/api/banner/history?limit=50` | 横幅历史 + 当前横幅 |
| GET | `/api/banner/status` | 当前横幅与条数 |
| POST | `/api/banner/ack` | 签收（`{"id": "..."}`） |
| POST | `/api/banner/dismiss` | 关闭横幅 |
| POST | `/api/markdown/render` | 返回 `{html, plain}` |
| GET | `/api/tts/status` | 播报组件状态与已播报次数 |
| GET | `/api/tts/voices` | 可选中文语音（**匿名**） |
| POST | `/api/tts/speak` | 触发播报 `{"text":"...","urgent":false,"voice":"..."}` |
| POST | `/api/agent/stop` | 校验密码后退出采集端 |
| POST | `/api/agent/restart` | 校验密码后重启采集端 |
| WS | `/ws` | 实时通道，见下节 |
| GET | `/` | 管理端 SPA（由 `manager/index.html` 提供） |

---

## 摄像头设备与「主机侧锁定」

这是本版重点修复之一。服务端返回的 `devices[].name` 是**教室电脑上摄像头的真实名称**：

```
Windows: WMI Win32_PnPEntity (PNPClass = Camera / Image)
       → 例如 "Integrated Camera"、"Logitech C920 HD Pro Webcam"
       失败时回退 VFW capGetDriverDescriptionW 的驱动描述
       都没有时才降级为 "摄像头 N"
```

`camera.remote_select` 默认为 `false`（**主机特权，只能在本机设置窗口里改**）：

```json
// GET /api/camera/devices —— 锁定状态
{
  "locked": true,
  "current": 0,
  "devices": [
    { "index": 0, "name": "主机指定的摄像头：Integrated Camera", "width": 0, "height": 0 }
  ]
}
```

锁定状态下：

- 只返回主机选中的**那一个**设备，不暴露本机其他摄像头，也不返回设备总数；
- `POST /api/camera/config`、WebSocket `camera_config`、`POST /api/config` 中的 `index` 一律丢弃，
  响应里 `ignored_fields: ["index"]`；
- `remote_select` 开关**永远不能**由网络侧打开。

在设置窗口「摄像头 → 网络访问权限」里勾选后，`remote_select = true`，
`/api/camera/devices` 才会列出全部设备（同样带真实名称），管理端下拉框即可切换。

---

## MJPEG 与 WebSocket

**MJPEG**：`GET /api/camera/stream` 返回长连接 multipart 流，每帧形如

```
--classconnector-frame
Content-Type: image/jpeg
Content-Length: 12345

<JPEG 字节>\r\n
```

无摄像头时会持续输出带时间戳的测试画面，保证联调始终可用。
无订阅者超过「空闲休眠」秒数后采集暂停，新连接立即唤醒。

**WebSocket** `/ws`：

- 建连后服务端推送 `{"type":"hello", "version", "device", "state", "token_required", ...}`；
- 客户端 `{"type":"ping"}` → `{"type":"pong"}`；
- `{"type":"status"}` → 返回运行时状态；
- `{"type":"auth","token":"..."}` → `auth_result`；
- 关闭时服务端会回 Close 帧完成握手，浏览器不会报连接异常。

> 麦克风对讲 / 教室音频监听在本版未迁移，`/ws` 不推送音频帧，
> `/api/status` 中 `audio.available = false`、`capabilities.audio/talk = false`。

---

## 截图降级

`GET /api/screen/shot` 成功返回 `image/png`；无图形会话或截图失败时返回内置占位 PNG，并带：

```
X-CC-Fallback: 1
X-CC-Meta: {"display":0,"error":"...","note":"截图不可用"}
```

管理端据此提示用户，不会把占位图当成真实截图展示。

---

## 与 v1.x（Python 版）的兼容性

- 所有前端用到的路径与字段名保持一致，`manager/` 静态页面可原样复用。
- 认证只保留 `X-CC-Token` 请求头。
- `config` 中摄像头相关的 `index` / `remote_select` 严格限定为主机侧设置。
- Edge TTS 云端合成、音频对讲未内置；`/api/tts/speak` 与音效接口保留，
  便于后续单独接入。
