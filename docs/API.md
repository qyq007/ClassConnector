# REST / WebSocket API 参考

- 基址：`http://<设备IP>:<端口>`（默认端口 `8420`）
- 所有响应为 JSON，除非标注为图片 / 流。
- 除 `/api/health`、静态页面与 `/api/tts/voices` 外，当 `require_auth=true` 时都需要认证。
- 服务端开放 CORS（`Access-Control-Allow-Origin: *`），便于独立部署的管理端跨源连接。

## 认证

登录（用安装密码换取会话令牌，有效期 8 小时）：

```http
POST /api/auth
Content-Type: application/json

{"password": "安装时设置的密码"}
```

```json
{"ok": true, "token": "...", "expires_in": 28800}
```

后续请求携带其一：

| 方式 | 适用 |
| --- | --- |
| 请求头 `X-CC-Token: <token>` | 所有 REST / fetch 请求 |
| 查询参数 `?token=<token>` | `<img>` 等无法自定义头部的场景（MJPEG 流、快照） |
| WebSocket 首条消息 `{"type":"auth","token":"..."}` | `/ws` 连接 |

`POST /api/agent/stop`、`/api/agent/restart`、`/api/password/change` 以及修改 `require_auth` **始终额外要求密码字段**，令牌不能替代密码。

横幅窗口子进程用 `X-CC-Token: <internal_token>` 回传签收，服务端据此把来源标记为 `desktop`。

## 错误码

| 状态码 | 含义 |
| --- | --- |
| 400 | 参数错误（如画质不是整数、横幅标题正文皆空） |
| 401 | 未登录或令牌失效 |
| 403 | 密码错误 |
| 404 | 资源不存在（如横幅 id） |
| 409 | 尚未设置安装密码，退出/改密被锁定 |
| 500 | 内部错误（详见 `<数据目录>/agent.log`） |

---

## 基础

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查与设备摘要，**无需认证**；管理端据此判断地址是否为采集端、是否已开启登录验证 |
| GET | `/api/status` | 完整状态：设备、运行时、摄像头、音频、屏幕、横幅、TTS、自启、能力、公开配置 |
| GET | `/api/logs?limit=100` | 最近运行日志（内存环形缓冲） |
| GET | `/api/platform` | 操作系统、Python、项目路径、开机自启状态 |
| GET | `/api/config` | 公开配置（不含任何密钥字段） |
| POST | `/api/config` | 更新配置，见下 |
| POST | `/api/password/change` | `{old_password, new_password}` 修改安装密码，吊销所有令牌 |
| POST | `/api/agent/stop` | `{password}` 校验通过后延时退出采集端 |
| POST | `/api/agent/restart` | `{password}` 校验通过后重启（1.5 秒后重新拉起后台进程） |

`GET /api/health` 示例：

```json
{
  "ok": true, "service": "classconnector-agent", "version": "1.0.0",
  "name": "教室-pc-01", "room": "高三(1)班",
  "ip": "192.168.1.50", "port": 8420,
  "sleeping": false, "auth_required": false, "has_password": true
}
```

`POST /api/config` 可更新字段：

```json
{
  "room_name": "高三(1)班",
  "device_name": "教室-pc-01",
  "idle_timeout": 20,
  "require_auth": true,
  "password": "仅修改 require_auth 时需要",
  "camera": {"index": 0, "width": 1280, "height": 720, "fps": 15, "quality": 70},
  "audio": {"enabled": true, "sample_rate": 16000, "chunk": 1024},
  "banner": {"auto_close": 0, "need_ack_default": true, "tts_default": true},
  "tts": {"enabled": true, "voice": "zh-CN-XiaoxiaoNeural",
          "rate": "+0%", "volume": "+0%", "urgent_alert": true}
}
```

> 修改 `require_auth` 会让所有令牌立即失效，管理端需要用安装密码重新登录。

---

## 摄像头

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/camera/config` | 当前画质配置 + 采集状态（后端、实测帧率、订阅数、错误） |
| POST | `/api/camera/config` | 调整画质，参数自动收敛到合法范围 |
| GET | `/api/camera/devices` | 枚举可用摄像头（最多探测 4 个）；无设备时返回测试画面项 |
| GET | `/api/camera/snapshot` | 单帧 JPEG（`image/jpeg`）；若处于休眠会临时唤醒 |
| GET | `/api/camera/stream` | **MJPEG 流** `multipart/x-mixed-replace; boundary=classconnector-frame` |

画质参数范围：

| 字段 | 范围 | 默认 |
| --- | --- | --- |
| `index` | 0–15 | 0 |
| `width` | 320–3840 | 1280 |
| `height` | 240–2160 | 720 |
| `fps` | 1–30 | 15 |
| `quality` | 10–100 | 70 |

```bash
curl "http://192.168.1.50:8420/api/camera/stream?token=xxx" -o stream.mjpg
curl -X POST "http://192.168.1.50:8420/api/camera/config" \
  -H 'Content-Type: application/json' -d '{"quality":55,"fps":10}'
```

浏览器直接用 `<img src="http://IP:8420/api/camera/stream?token=...">` 即可播放。每个流订阅都会让采集端保持唤醒。

---

## 屏幕截图

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/screen/displays` | 显示器列表（`index=0` 在 mss 下表示全部屏幕拼接） |
| GET | `/api/screen/shot?display=0&scale=1.0` | PNG 图片；`scale` 范围 0.2–1.0 |

响应头：

- `X-CC-Fallback: 1` 表示当前为降级占位图（无图形会话 / 截图失败）
- `X-CC-Meta`：JSON 元信息（后端、尺寸、时间、失败原因，全部 ASCII 转义）

---

## 横幅通知

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/banner/send` | 发送横幅，见下 |
| GET | `/api/banner/history?limit=50` | 历史（倒序）与当前展示 id |
| GET | `/api/banner/status` | 当前横幅、总数、已签收数 |
| POST | `/api/banner/ack` | `{id, source}` 签收；省略 id 时对当前横幅签收 |
| POST | `/api/banner/dismiss` | `{id}` 关闭 / 撤回；省略 id 时关闭当前横幅 |
| POST | `/api/markdown/render` | `{markdown}` → `{html, plain}`，用于管理端预览 |

`POST /api/banner/send` 请求体：

```json
{
  "title": "临时集合通知",
  "markdown": "# 请全体同学注意\n\n**14:30** 到操场集合\n\n> 带好水杯\n\n1. 各班整队\n2. 保持安静",
  "urgent": true,
  "need_ack": true,
  "tts": true,
  "voice": "zh-CN-XiaoxiaoNeural",
  "duration": 0
}
```

| 字段 | 说明 |
| --- | --- |
| `markdown` | 支持标题、粗斜体、删除线、列表/任务清单、引用、代码块、表格、链接、分割线；上限 20000 字符 |
| `urgent` | 红色紧急样式 + 播报前播放独立警报音 |
| `need_ack` | 显示签收按钮并回传状态；`duration=0` 时必须签收才能关闭窗口 |
| `tts` | 用 Edge TTS 朗读标题 + 正文（自动去除 Markdown 标记） |
| `duration` | 秒；`0` 为手动关闭，最大 3600 |

响应中的 `display_mode`：`desktop`（已弹出窗口）/ `headless`（无图形会话，用网页预览）/ `failed`。
`status` 取值：`showing` → `acked` / `dismissed` / `closed`。

---

## 语音播报

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tts/status` | 是否启用、edge-tts 是否安装、当前播放器、队列、最近错误 |
| GET | `/api/tts/voices` | 可选中文语音列表 |
| POST | `/api/tts/speak` | `{text, urgent, voice}` 加入播报队列，立即返回 |

播报是异步串行的：紧急事件先播放本地 `urgent.wav`，再朗读文本；edge-tts 不可用或断网时只跳过朗读并记录日志。

---

## WebSocket `/ws`

连接地址：`ws://<设备IP>:<端口>/ws`。`binaryType` 建议设为 `arraybuffer`。

### 服务端 → 客户端（文本 JSON）

| `type` | 主要字段 | 时机 |
| --- | --- | --- |
| `hello` | `client_id, version, device, token_required, authed, state` | 建连后立刻 |
| `status` | `sleeping / active / talk_mode`（或 `runtime.snapshot()` 全量） | 休眠唤醒、对讲切换、状态查询 |
| `banner` | `banner` 完整对象 | 新横幅发出 |
| `banner_ack` | `id, acked_at, status` | 任一签收发生 |
| `banner_dismissed` | `id, reason, status` | 撤回 / 超时 / 窗口关闭 |
| `banner_headless` | `id, message` | 采集端无图形界面 |
| `talk_state` | `active` | 对讲开启/结束（同步给所有管理端） |
| `camera_config` | `config` | 画质被任一管理端修改 |
| `tts_state` | `busy, urgent` | 播报开始/结束 |
| `config` | `config` | 配置变更 |
| `pong` | `ts` | 心跳响应 |
| `error` | `message` | 参数错误 / 未登录 |

**二进制帧**：教室麦克风 PCM（16 kHz / 单声道 / 16-bit）。对讲期间服务端不会推送该帧。

### 客户端 → 服务端

| 消息 | 说明 |
| --- | --- |
| `{"type":"auth","token":"..."}` | 登录（开启 `require_auth` 时必须在其它操作前发送） |
| `{"type":"ping"}` | 心跳 |
| `{"type":"talk","active":true}` | 开启对讲：服务端停止推送教室音频并准备播放 |
| `{"type":"talk","active":false}` | 结束对讲：恢复音频监听 |
| `{"type":"camera_config","config":{...}}` | 调整画质（等价 REST 接口） |
| `{"type":"banner","banner":{...}}` | 发送横幅（等价 REST 接口） |
| `{"type":"banner_dismiss","id":"..."}` | 关闭横幅 |
| `{"type":"tts","text":"...","urgent":false,"voice":"..."}` | 单独播报 |
| `{"type":"status"}` | 请求全量运行时状态 |

**二进制帧**：管理端麦克风 PCM（同格式），仅在 `talk.active=true` 时被采集端播放。

### 最小示例

```javascript
const ws = new WebSocket('ws://192.168.1.50:8420/ws');
ws.binaryType = 'arraybuffer';
ws.onmessage = (e) => {
  if (e.data instanceof ArrayBuffer) { player.feed(e.data); return; }
  const msg = JSON.parse(e.data);
  if (msg.type === 'hello' && msg.token_required) {
    ws.send(JSON.stringify({type: 'auth', token: token}));
  }
};
ws.send(JSON.stringify({type: 'talk', active: true}));
ws.send(int16PcmBuffer);           // 对讲音频
ws.send(JSON.stringify({type: 'talk', active: false}));
```

---

## 静态资源

`GET /` 返回管理端 `index.html`，同级可访问 `/style.css`、`/app.js`、`/markdown.js`、`/audio.js`。整个 `manager/` 目录可原样复制到任意静态服务器使用。
