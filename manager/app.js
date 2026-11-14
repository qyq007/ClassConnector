/* ClassConnector 管理端主逻辑 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var S = {
    base: '', token: '', connected: false, ws: null,
    device: {}, status: {}, config: {}, devices: [],
    videoOn: false, listenOn: false, talkOn: false, spaceTalk: false,
    player: new PcmPlayer(), recorder: null,
    currentBannerId: null, history: [],
    autoShotTimer: null, statusTimer: null, reconnectTimer: null,
    bannerTimer: null, lastShotUrl: null, initialRequireAuth: false,
    cameraLocked: true   // 默认按「主机锁定」处理，连接成功后由 /api/camera/devices 更新
  };

  /* =============================== 工具 =============================== */
  function toast(msg, type) {
    var el = $('toast');
    el.textContent = msg;
    el.className = 'toast' + (type ? ' ' + type : '');
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.hidden = true; }, 3200);
  }
  function errText(e) { return (e && e.message) || String(e); }
  function fmtTime(ts) {
    if (!ts) return '-';
    var d = new Date(ts * 1000);
    return d.toLocaleString('zh-CN', { hour12: false });
  }
  function normalizeBase(ip, port) {
    var raw = String(ip || '').trim().replace(/\/+$/, '');
    if (!raw) throw new Error('请填写设备 IP 地址');
    if (!/^https?:\/\//i.test(raw)) raw = 'http://' + raw;
    var u;
    try { u = new URL(raw); } catch (e) { throw new Error('设备地址格式不正确'); }
    if (!/^https?:$/.test(u.protocol)) throw new Error('仅支持 http/https');
    // 地址中未显式带端口时，使用输入框里的端口
    if (!u.port) u.port = String(port || 8420);
    return u.origin;
  }
  function withTimeout(ms) {
    var ctrl = new AbortController();
    setTimeout(function () { ctrl.abort(); }, ms || 8000);
    return ctrl;
  }
  async function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({}, opts.headers || {});
    if (S.token) headers['X-CC-Token'] = S.token;
    var ctrl = withTimeout(opts.timeout || 8000);
    var res = await fetch(S.base + path, {
      method: opts.method || 'GET', headers: headers,
      body: opts.body, signal: ctrl.signal, cache: 'no-store'
    });
    return res;
  }
  async function apiJson(path, opts) {
    var res = await api(path, opts);
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      var msg = data.detail || ('请求失败（HTTP ' + res.status + '）');
      if (res.status === 401) msg = '登录已失效，请重新输入管理密码';
      throw new Error(msg);
    }
    return data;
  }
  function postJson(path, obj) {
    return apiJson(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(obj || {})
    });
  }
  function tokenQuery() { return S.token ? '?token=' + encodeURIComponent(S.token) : ''; }
  // 设备上的实际参数可能不在预设选项里（例如 fps=12），动态补一个「当前」选项，
  // 避免 select 显示为空白。
  function ensureOption(el, value, label) {
    if (value === undefined || value === null || value === '') return;
    var str = String(value);
    var found = false;
    for (var i = 0; i < el.options.length; i++) {
      if (el.options[i].value === str) { found = true; break; }
    }
    if (!found) {
      var op = document.createElement('option');
      op.value = str; op.textContent = label;
      el.appendChild(op);
    }
    el.value = str;
  }

  /* =============================== 设备列表 =============================== */
  function loadDevices() {
    try { S.devices = JSON.parse(localStorage.getItem('cc.devices') || '[]'); }
    catch (e) { S.devices = []; }
    if (!Array.isArray(S.devices)) S.devices = [];
  }
  function saveDevice(ip, port, info) {
    var key = ip + ':' + port;
    S.devices = S.devices.filter(function (d) { return d.key !== key; });
    S.devices.unshift({
      key: key, ip: ip, port: port,
      name: (info && info.name) || ip,
      room: (info && info.room) || ''
    });
    S.devices = S.devices.slice(0, 12);
    localStorage.setItem('cc.devices', JSON.stringify(S.devices));
    renderDeviceLists();
  }
  function renderDeviceLists() {
    var saved = $('savedDevices'), select = $('deviceSelect');
    saved.innerHTML = '';
    if (!S.devices.length) {
      saved.innerHTML = '<span class="muted small">暂无记录，连接成功后会自动保存</span>';
    }
    S.devices.forEach(function (d) {
      var item = document.createElement('div');
      item.className = 'saved-item';
      item.innerHTML = '<span>🖥️ ' + escapeHtml(d.name) + '</span><small>' + escapeHtml(d.key) + '</small>';
      item.onclick = function () {
        $('ipInput').value = d.ip; $('portInput').value = d.port;
        $('pwdInput').focus();
      };
      saved.appendChild(item);
    });
    select.innerHTML = '';
    S.devices.forEach(function (d) {
      var op = document.createElement('option');
      op.value = d.key;
      op.textContent = (d.room ? d.room + ' · ' : '') + d.name + ' (' + d.key + ')';
      select.appendChild(op);
    });
    select.hidden = false;
  }

  /* =============================== 连接 =============================== */
  async function connect(ip, port, password) {
    var base = normalizeBase(ip, port);
    $('connectError').hidden = true;
    $('btnConnect').disabled = true;
    $('btnConnect').textContent = '正在连接…';
    try {
      var health = await (await fetch(base + '/api/health',
        { signal: withTimeout(5000).signal, cache: 'no-store' })).json();
      if (!health.ok || health.service !== 'classconnector-agent') {
        throw new Error('该地址不是 ClassConnector 采集端');
      }
      S.token = '';
      if (password) {
        var auth = await (await fetch(base + '/api/auth', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: password }),
          signal: withTimeout(6000).signal
        })).json();
        if (!auth.ok) throw new Error(auth.detail || '管理密码错误');
        S.token = auth.token;
      } else if (health.auth_required) {
        throw new Error('该设备已开启管理密码登录，请填写安装时设置的密码');
      }
      S.base = base;
      S.connected = true;
      S.device = health;
      saveDevice(ip, port, health);

      $('connectPanel').hidden = true;
      $('workspace').hidden = false;
      $('btnSwitch').hidden = false;
      $('btnDisconnect').hidden = false;
      $('versionText').textContent = 'v' + (health.version || '');
      updateConnBadge(true);

      connectWS();
      await Promise.allSettled([
        loadStatus(), loadConfig(), loadVoices(), loadCameraDevices(),
        loadDisplays(), loadHistory(), loadLogs()
      ]);
      renderMdPreview();
      startVideo();
      S.statusTimer = setInterval(function () { if (S.connected) loadStatus().catch(function () {}); }, 6000);
      toast('已连接到 ' + (health.room || health.name) + ' · ' + base, 'ok');
    } catch (e) {
      $('connectError').textContent = '连接失败：' + errText(e);
      $('connectError').hidden = false;
      toast('连接失败：' + errText(e), 'err');
    } finally {
      $('btnConnect').disabled = false;
      $('btnConnect').textContent = '连接设备';
    }
  }
  function disconnect(showPanel) {
    S.connected = false;
    clearInterval(S.statusTimer); clearTimeout(S.reconnectTimer);
    clearInterval(S.autoShotTimer);
    if (S.ws) { try { S.ws.close(); } catch (e) {} S.ws = null; }
    stopVideo(); stopListen(); stopTalk();
    S.base = ''; S.token = '';
    updateConnBadge(false);
    if (showPanel !== false) {
      $('workspace').hidden = true;
      $('connectPanel').hidden = false;
      $('btnSwitch').hidden = true;
      $('btnDisconnect').hidden = true;
    }
  }
  function updateConnBadge(ok) {
    var el = $('connBadge');
    el.textContent = ok
      ? '● 已连接 ' + (S.device.room || S.device.name || '')
      : '● 未连接';
    el.className = 'badge ' + (ok ? 'badge-on' : 'badge-off');
  }

  /* =============================== WebSocket =============================== */
  function connectWS() {
    if (!S.connected) return;
    var url = S.base.replace(/^http/, 'ws') + '/ws';
    try { S.ws = new WebSocket(url); } catch (e) { return; }
    S.ws.binaryType = 'arraybuffer';
    S.ws.onopen = function () {
      if (S.token) S.ws.send(JSON.stringify({ type: 'auth', token: S.token }));
      toast('实时通道已建立', 'ok');
    };
    S.ws.onmessage = function (ev) {
      if (ev.data instanceof ArrayBuffer) {
        if (S.listenOn && !S.talkOn) S.player.feed(ev.data);
        return;
      }
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      handleWs(msg);
    };
    S.ws.onclose = function () {
      S.ws = null;
      if (!S.connected) return;
      toast('实时通道断开，正在重连…');
      clearTimeout(S.reconnectTimer);
      S.reconnectTimer = setTimeout(connectWS, 3000);
    };
    S.ws.onerror = function () {};
  }
  function wsSend(obj) {
    if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify(obj));
  }
  function handleWs(msg) {
    switch (msg.type) {
      case 'hello':
        if (msg.device) S.device = Object.assign(S.device, msg.device);
        updateConnBadge(true);
        break;
      case 'status':
        loadStatus().catch(function () {});
        break;
      case 'banner':
        S.currentBannerId = msg.banner.id;
        toast('📢 已发送横幅：' + msg.banner.title, 'ok');
        loadHistory().catch(function () {});
        break;
      case 'banner_ack':
        toast('✅ 横幅已签收', 'ok');
        loadHistory().catch(function () {});
        break;
      case 'banner_dismissed':
        loadHistory().catch(function () {});
        break;
      case 'banner_headless':
        toast('采集端无图形界面，可用「网页预览」查看横幅效果', 'err');
        break;
      case 'talk_state':
        if (msg.active && S.listenOn) S.player.stop();
        updateTalkButton(msg.active);
        break;
      case 'camera_config':
        syncQualityInputs(msg.config);
        break;
      case 'tts_state':
        break;
      case 'config':
        if (msg.config) { S.config = msg.config; fillConfig(msg.config); }
        break;
      case 'error':
        toast(msg.message || '设备返回错误', 'err');
        break;
    }
  }

  /* =============================== 视频 =============================== */
  function startVideo() {
    if (!S.connected) return;
    S.videoOn = true;
    var img = $('video');
    img.src = S.base + '/api/camera/stream' + tokenQuery() +
      (S.token ? '&' : '?') + 't=' + Date.now();
    img.classList.add('show');
    $('videoPlaceholder').hidden = true;
    $('btnStartVideo').hidden = true;
    $('btnStopVideo').hidden = false;
    $('videoTag').textContent = '推流中';
    $('videoTag').className = 'badge badge-on';
  }
  function stopVideo() {
    S.videoOn = false;
    var img = $('video');
    img.src = ''; img.classList.remove('show');
    $('videoPlaceholder').hidden = false;
    $('btnStartVideo').hidden = false;
    $('btnStopVideo').hidden = true;
    $('videoTag').textContent = '未开启';
    $('videoTag').className = 'badge badge-off';
  }
  function reloadStream() { if (S.connected && S.videoOn) startVideo(); }

  /* =============================== 音频 / 对讲 =============================== */
  async function startListen() {
    if (!S.connected) return;
    try {
      await S.player.enable();
      S.player.setVolume(Number($('volumeSlider').value) / 100);
      S.listenOn = true;
      $('btnListen').textContent = '🔇 关闭监听';
      toast('已开启教室声音监听', 'ok');
    } catch (e) { toast('无法开启音频播放：' + errText(e), 'err'); }
  }
  function stopListen() {
    S.listenOn = false;
    S.player.stop();
    $('btnListen').textContent = '🔊 开启监听';
  }
  function updateTalkButton(on) {
    S.talkOn = !!on;
    var b = $('btnTalk');
    b.textContent = on ? '⏹ 结束对讲' : '🎙️ 开始对讲';
    b.classList.toggle('active', !!on);
    if (on) {
      $('videoOverlay').hidden = false;
    }
  }
  async function startTalk() {
    if (!S.connected || S.talkOn) return;
    if (!S.ws || S.ws.readyState !== WebSocket.OPEN) {
      toast('实时通道未连接，无法对讲', 'err'); return;
    }
    wsSend({ type: 'talk', active: true });
    // 对讲时关闭监听音频，避免啸叫
    S.player.stop();
    try {
      S.recorder = new MicRecorder(function (buf) {
        if (S.talkOn && S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(buf);
      });
      await S.recorder.start();
      updateTalkButton(true);
      toast('对讲已开启：教室音频监听已暂时关闭', 'ok');
    } catch (e) {
      wsSend({ type: 'talk', active: false });
      if (S.recorder) { S.recorder.stop(); S.recorder = null; }
      updateTalkButton(false);
      if (S.listenOn) S.player.enable().catch(function () {});
      toast('无法打开麦克风：' + errText(e), 'err');
    }
  }
  function stopTalk() {
    if (!S.talkOn) return;
    if (S.recorder) { S.recorder.stop(); S.recorder = null; }
    wsSend({ type: 'talk', active: false });
    updateTalkButton(false);
    if (S.listenOn) S.player.enable().catch(function () {});
    toast('对讲结束，已恢复教室音频监听');
  }

  /* =============================== 状态 / 配置 =============================== */
  function kv(k, v, cls) {
    return '<div class="status-item"><span class="k">' + escapeHtml(k) + '</span>' +
      '<span class="v ' + (cls || '') + '">' + escapeHtml(String(v)) + '</span></div>';
  }
  async function loadStatus() {
    var d = await apiJson('/api/status');
    S.status = d; S.config = d.config || S.config;
    var rt = d.runtime || {}, cam = d.camera || {}, aud = d.audio || {};
    $('statusGrid').innerHTML =
      kv('连接状态', rt.sleeping ? '休眠中' : (rt.active > 0 ? '活跃 ' + rt.active + ' 路' : '待机'),
        rt.sleeping ? 'warn' : 'ok') +
      kv('休眠倒计时', rt.idle_remaining >= 0 ? rt.idle_remaining + ' 秒' : '—') +
      kv('摄像头', cam.available ? '真实设备' : '测试画面', cam.available ? 'ok' : 'warn') +
      kv('实测帧率', (cam.measured_fps || 0) + ' fps') +
      kv('分辨率', (cam.actual_width || cam.width) + '×' + (cam.actual_height || cam.height)) +
      kv('音频设备', aud.available ? '可用' : '不可用', aud.available ? 'ok' : 'bad') +
      kv('对讲状态', aud.talk_mode ? '对讲中' : '关闭', aud.talk_mode ? 'warn' : '') +
      kv('运行时长', Math.floor((rt.uptime || 0) / 60) + ' 分钟');

    $('deviceInfo').innerHTML =
      kv('设备名称', d.device.name) + kv('班级', d.device.room) +
      kv('IP / 端口', d.device.ip + ':' + d.device.port) +
      kv('操作系统', d.device.os) + kv('Python', d.device.python) +
      kv('采集端版本', d.version) +
      kv('开机自启', d.autostart.enabled ? '已启用' : '未启用', d.autostart.enabled ? 'ok' : 'warn') +
      kv('局域网地址', 'http://' + d.device.ip + ':' + d.device.port);

    var caps = d.capabilities || {}, names = {
      camera: '摄像头画面', audio: '音频监听', screen: '屏幕截图',
      banner: '横幅通知', tts: 'Edge TTS 播报', talk: '麦克风对讲'
    };
    $('capabilityList').innerHTML = Object.keys(names).map(function (k) {
      return '<div class="cap-item"><span>' + names[k] + '</span><span class="' +
        (caps[k] ? 'v ok' : 'v bad') + '">' + (caps[k] ? '● 可用' : '○ 降级') + '</span></div>';
    }).join('');

    var overlay = $('videoOverlay');
    overlay.innerHTML =
      '<span class="chip">' + (cam.available ? '📷 真实摄像头' : '🧪 测试画面') + '</span>' +
      '<span class="chip">' + (cam.width || 0) + '×' + (cam.height || 0) + ' @ ' + (cam.fps || 0) + 'fps</span>' +
      '<span class="chip">画质 ' + (cam.quality || 0) + '</span>' +
      (rt.sleeping ? '<span class="chip">💤 休眠中</span>' : '') +
      (aud.talk_mode ? '<span class="chip">🎙️ 对讲中</span>' : '');
    overlay.hidden = !S.videoOn;
    $('videoTag').textContent = rt.sleeping ? '休眠中' : (S.videoOn ? '推流中' : '未开启');
    $('videoTag').className = 'badge ' + (rt.sleeping ? 'badge-warn' : (S.videoOn ? 'badge-on' : 'badge-off'));
  }
  async function loadConfig() {
    var c = await apiJson('/api/config');
    S.config = c;
    fillConfig(c);
  }
  function fillConfig(c) {
    $('setRoom').value = c.room_name || '';
    $('setDeviceName').value = c.device_name || '';
    $('setIdle').value = c.idle_timeout;
    $('setTtsEnabled').checked = !!(c.tts && c.tts.enabled);
    $('setUrgentAlert').checked = !!(c.tts && c.tts.urgent_alert);
    $('setAudioEnabled').checked = !!(c.audio && c.audio.enabled);
    $('setRequireAuth').checked = !!c.require_auth;
    S.initialRequireAuth = !!c.require_auth;
    if (c.tts && c.tts.voice) {
      ensureOption($('setVoice'), c.tts.voice, c.tts.voice + '（当前）');
      ensureOption($('voiceSelect'), c.tts.voice, c.tts.voice + '（当前）');
    }
    if (c.camera) syncQualityInputs(c.camera);
  }
  function syncQualityInputs(cam) {
    if (!cam) return;
    $('qualitySlider').value = cam.quality || 70;
    $('qualityVal').textContent = cam.quality || 70;
    var w = cam.width || 1280, h = cam.height || 720, fps = cam.fps || 15;
    ensureOption($('resolutionSelect'), w + 'x' + h, w + ' × ' + h + '（当前）');
    ensureOption($('fpsSelect'), fps, fps + ' fps（当前）');
    if (!S.cameraLocked) {
      ensureOption($('cameraDeviceSelect'), cam.index, '当前设备（索引 ' + cam.index + '）');
    }
  }
  async function loadVoices() {
    var d = await apiJson('/api/tts/voices');
    ['voiceSelect', 'setVoice'].forEach(function (id) {
      var el = $(id); el.innerHTML = '';
      d.voices.forEach(function (v) {
        var op = document.createElement('option');
        op.value = v.id; op.textContent = v.name; el.appendChild(op);
      });
      ensureOption(el, d.current, d.current + '（当前）');
    });
  }
  async function loadCameraDevices() {
    var d = await apiJson('/api/camera/devices');
    var el = $('cameraDeviceSelect');
    // 主机锁定摄像头时：服务端只返回主机指定的那一个设备，
    // 前端直接隐藏设备下拉，避免管理端以为可以枚举/切换本机摄像头。
    S.cameraLocked = !!d.locked;
    $('cameraDeviceField').hidden = S.cameraLocked;
    $('cameraLockHint').hidden = !S.cameraLocked;
    el.innerHTML = '';
    if (S.cameraLocked) return;
    d.devices.forEach(function (dev) {
      var op = document.createElement('option');
      op.value = dev.index;
      op.textContent = dev.name + (dev.width ? ' (' + dev.width + '×' + dev.height + ')' : '');
      el.appendChild(op);
    });
    ensureOption(el, d.current, '当前设备（索引 ' + d.current + '）');
  }
  async function loadDisplays() {
    var d = await apiJson('/api/screen/displays');
    var el = $('displaySelect'); el.innerHTML = '';
    d.displays.forEach(function (m) {
      var op = document.createElement('option');
      op.value = m.index;
      op.textContent = m.name + (m.width ? ' · ' + m.width + '×' + m.height : '');
      el.appendChild(op);
    });
  }
  async function loadLogs() {
    var d = await apiJson('/api/logs?limit=60');
    $('logList').innerHTML = (d.logs || []).slice().reverse().map(function (l) {
      var t = new Date(l.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false });
      return '<div class="log-line ' + escapeHtml(l.level) + '"><span class="t">' + t +
        '</span><span class="m">' + escapeHtml(l.message) + '</span></div>';
    }).join('');
  }

  /* =============================== 画质 =============================== */
  async function applyQuality() {
    var wh = $('resolutionSelect').value.split('x');
    var payload = {
      quality: Number($('qualitySlider').value),
      width: Number(wh[0]), height: Number(wh[1]),
      fps: Number($('fpsSelect').value)
    };
    // 只有主机在设置窗口里显式开放后，管理端才能切换摄像头设备
    if (!S.cameraLocked && $('cameraDeviceSelect').value !== '') {
      payload.index = Number($('cameraDeviceSelect').value);
      if (payload.index < 0) delete payload.index;
    }
    try {
      var d = await postJson('/api/camera/config', payload);
      syncQualityInputs(d.config);
      reloadStream();
      toast('画质设置已应用', 'ok');
    } catch (e) { toast(errText(e), 'err'); }
  }

  /* =============================== 横幅 =============================== */
  function currentBannerPayload() {
    return {
      title: $('bannerTitle').value.trim() || '班级通知',
      markdown: $('bannerText').value,
      urgent: $('optUrgent').checked,
      need_ack: $('optAck').checked,
      tts: $('optTts').checked,
      voice: $('voiceSelect').value,
      duration: Number($('durationInput').value) || 0
    };
  }
  function renderMdPreview() {
    $('mdPreview').innerHTML = '<h1>' + escapeHtml($('bannerTitle').value || '班级通知') +
      '</h1>' + renderMarkdown($('bannerText').value);
  }
  async function sendBanner() {
    try {
      var d = await postJson('/api/banner/send', currentBannerPayload());
      S.currentBannerId = d.banner.id;
      await loadHistory();
      toast('横幅已发送至采集端' + (d.banner.display_mode === 'headless' ? '（无图形界面，请用网页预览）' : ''), 'ok');
    } catch (e) { toast(errText(e), 'err'); }
  }
  function previewBanner() {
    var p = currentBannerPayload();
    $('bannerBox').classList.toggle('urgent', p.urgent);
    $('bannerRoom').textContent = 'ClassConnector · ' + (S.device.room || '班级');
    $('bannerBadge').textContent = p.urgent ? '⚠ 紧急通知' : '📢 班级通知';
    $('bannerHeading').textContent = p.title;
    $('bannerContent').innerHTML = renderMarkdown(p.markdown);
    $('bannerAckBtn').hidden = !p.need_ack;
    $('bannerAckBtn').disabled = false;
    $('bannerAckBtn').textContent = '我已知悉，点击签收';
    $('bannerCountdown').textContent = '';
    $('bannerOverlay').hidden = false;
    clearInterval(S.bannerTimer);
    var remain = p.duration;
    if (remain > 0) {
      var tick = function () {
        if (remain <= 0) { closeBannerPreview(); return; }
        $('bannerCountdown').textContent = '本通知将在 ' + remain + ' 秒后自动关闭';
        remain -= 1;
      };
      tick(); S.bannerTimer = setInterval(tick, 1000);
    }
    var clock = function () {
      $('bannerClock').textContent = new Date().toLocaleString('zh-CN', { hour12: false });
    };
    clock(); clearInterval(S.bannerClockTimer);
    S.bannerClockTimer = setInterval(clock, 1000);
  }
  function closeBannerPreview() {
    $('bannerOverlay').hidden = true;
    clearInterval(S.bannerTimer); clearInterval(S.bannerClockTimer);
  }
  async function loadHistory() {
    var d = await apiJson('/api/banner/history?limit=30');
    S.history = d.items || [];
    S.currentBannerId = d.current || S.currentBannerId;
    var labels = { showing: ['展示中', 'badge-warn'], acked: ['已签收', 'badge-on'],
      dismissed: ['已关闭', 'badge-off'], closed: ['窗口已关闭', 'badge-off'] };
    $('bannerHistory').innerHTML = S.history.length ? S.history.map(function (b) {
      var lb = labels[b.status] || labels.showing;
      return '<div class="history-item">' +
        '<div class="row1">' +
        (b.urgent ? '<span class="badge badge-urgent">紧急</span>' : '') +
        '<span class="title">' + escapeHtml(b.title) + '</span>' +
        '<span class="badge ' + lb[1] + '">' + lb[0] + '</span>' +
        '<span class="time">' + fmtTime(b.created_at) + '</span></div>' +
        '<div class="excerpt">' + escapeHtml(stripMarkdownText(b.markdown).slice(0, 110)) + '</div>' +
        '<div class="ops">' +
        '<button class="btn btn-mini" data-act="preview" data-id="' + b.id + '">预览</button>' +
        '<button class="btn btn-mini" data-act="resend" data-id="' + b.id + '">重发</button>' +
        (b.status === 'showing' ? '<button class="btn btn-mini" data-act="dismiss" data-id="' + b.id + '">撤回</button>' : '') +
        (b.acked_at ? '<span class="muted small">签收于 ' + fmtTime(b.acked_at) + '</span>' : '') +
        '</div></div>';
    }).join('') : '<span class="muted small">暂无通知记录</span>';

    $('bannerHistory').querySelectorAll('button[data-act]').forEach(function (btn) {
      btn.onclick = function () {
        var b = S.history.filter(function (x) { return x.id === btn.dataset.id; })[0];
        if (!b) return;
        var act = btn.dataset.act;
        if (act === 'preview') { showHistoryPreview(b); }
        else if (act === 'resend') {
          postJson('/api/banner/send', {
            title: b.title, markdown: b.markdown, urgent: b.urgent,
            need_ack: b.need_ack, tts: b.tts, voice: b.voice, duration: b.duration
          }).then(function () { toast('已重新发送', 'ok'); loadHistory(); })
            .catch(function (e) { toast(errText(e), 'err'); });
        } else if (act === 'dismiss') {
          postJson('/api/banner/dismiss', { id: b.id })
            .then(function () { toast('已关闭横幅', 'ok'); loadHistory(); })
            .catch(function (e) { toast(errText(e), 'err'); });
        }
      };
    });
  }
  function showHistoryPreview(b) {
    $('bannerBox').classList.toggle('urgent', !!b.urgent);
    $('bannerRoom').textContent = 'ClassConnector · ' + (S.device.room || '班级');
    $('bannerBadge').textContent = b.urgent ? '⚠ 紧急通知' : '📢 班级通知';
    $('bannerHeading').textContent = b.title;
    $('bannerContent').innerHTML = renderMarkdown(b.markdown);
    $('bannerAckBtn').hidden = false;
    $('bannerAckBtn').disabled = b.status === 'acked';
    $('bannerAckBtn').textContent = b.status === 'acked' ? '✓ 已签收' : '我已知悉，点击签收';
    $('bannerCountdown').textContent = '历史通知预览';
    $('bannerOverlay').hidden = false;
    S.currentBannerId = b.id;
  }

  /* =============================== 截图 =============================== */
  async function takeShot() {
    try {
      var display = Number($('displaySelect').value) || 0;
      var scale = Number($('scaleSelect').value) || 1;
      var res = await api('/api/screen/shot?display=' + display + '&scale=' + scale +
        (S.token ? '&token=' + encodeURIComponent(S.token) : ''), { timeout: 20000 });
      if (!res.ok) throw new Error('截图失败（HTTP ' + res.status + '）');
      var blob = await res.blob();
      var meta = {};
      try { meta = JSON.parse(res.headers.get('X-CC-Meta') || '{}'); } catch (e) {}
      if (S.lastShotUrl) URL.revokeObjectURL(S.lastShotUrl);
      S.lastShotUrl = URL.createObjectURL(blob);
      var img = $('shotImage');
      img.src = S.lastShotUrl; img.classList.add('show');
      $('shotPlaceholder').hidden = true;
      $('btnDownloadShot').disabled = false;
      $('screenMeta').textContent = (meta.out_width || meta.width || '?') + '×' +
        (meta.out_height || meta.height || '?') + ' · ' +
        Math.round(blob.size / 1024) + ' KB · ' + (meta.backend || '');
      var fallback = res.headers.get('X-CC-Fallback') === '1';
      $('shotFallback').hidden = !fallback;
      if (fallback) $('shotFallback').textContent = '⚠ ' + (meta.reason || '采集端无图形桌面会话，当前为占位图');
    } catch (e) { toast('截图失败：' + errText(e), 'err'); }
  }
  function downloadShot() {
    if (!S.lastShotUrl) return;
    var a = document.createElement('a');
    a.href = S.lastShotUrl;
    a.download = 'classconnector-screen-' + Date.now() + '.png';
    a.click();
  }

  /* =============================== 设置操作 =============================== */
  async function saveSettings() {
    var patch = {
      room_name: $('setRoom').value.trim() || '未命名班级',
      device_name: $('setDeviceName').value.trim(),
      idle_timeout: Number($('setIdle').value) || 0,
      tts: { enabled: $('setTtsEnabled').checked,
        urgent_alert: $('setUrgentAlert').checked,
        voice: $('setVoice').value },
      audio: { enabled: $('setAudioEnabled').checked }
    };
    var body = { config: patch };
    if (!!$('setRequireAuth').checked !== S.initialRequireAuth) {
      patch.require_auth = $('setRequireAuth').checked;
      body.password = $('authPwd').value;
    }
    try {
      await postJson('/api/config', body);
      var authChanged = patch.require_auth !== undefined;
      S.initialRequireAuth = $('setRequireAuth').checked;
      if (authChanged) {
        // 切换登录验证会让服务端吊销全部旧令牌，需立即用密码重新登录
        var reauth = await postJson('/api/auth', { password: $('authPwd').value });
        S.token = reauth.token || S.token;
        if (S.ws) { try { S.ws.close(); } catch (e) {} }
      }
      toast(authChanged ? '设置已保存，已自动重新登录' : '设置已保存', 'ok');
      loadStatus().catch(function () {});
    } catch (e) { toast(errText(e), 'err'); }
  }
  async function changePassword() {
    try {
      var d = await postJson('/api/password/change', {
        old_password: $('oldPwd').value, new_password: $('newPwd').value
      });
      if (d.token) S.token = d.token;
      $('oldPwd').value = ''; $('newPwd').value = '';
      toast('安装密码已修改', 'ok');
    } catch (e) { toast(errText(e), 'err'); }
  }
  async function agentAction(kind) {
    var password = $('stopPwd').value;
    if (!password) { toast('请输入安装时设置的密码', 'err'); return; }
    var verb = kind === 'stop' ? '退出' : '重启';
    if (!confirm('确认要' + verb + '采集端吗？' + (kind === 'stop' ? '退出后需要到教室电脑上重新启动。' : ''))) return;
    try {
      await postJson('/api/agent/' + kind, { password: password });
      toast(verb + '指令已发送，连接即将断开', 'ok');
      if (kind === 'stop') setTimeout(function () { disconnect(true); }, 1200);
    } catch (e) { toast(errText(e), 'err'); }
  }

  /* =============================== 标签页 =============================== */
  function activateTab(name) {
    var btn = document.querySelector('.tab[data-tab="' + name + '"]');
    if (!btn) return;
    document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
    document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
    btn.classList.add('active');
    $('tab-' + name).classList.add('active');
    if (name === 'banner') { loadHistory().catch(function () {}); renderMdPreview(); }
    if (name === 'screen') { loadDisplays().catch(function () {}); }
  }

  /* =============================== 事件绑定 =============================== */
  function bind() {
    $('connectForm').addEventListener('submit', function (e) {
      e.preventDefault();
      connect($('ipInput').value, $('portInput').value, $('pwdInput').value);
    });
    $('btnClearDevices').onclick = function () {
      S.devices = []; localStorage.removeItem('cc.devices'); renderDeviceLists();
    };
    $('deviceSelect').onchange = function () {
      var d = S.devices.filter(function (x) { return x.key === this.value; }.bind(this))[0];
      if (d) { $('ipInput').value = d.ip; $('portInput').value = d.port; }
    };
    $('btnSwitch').onclick = function () {
      $('connectPanel').hidden = false; $('workspace').hidden = true;
      $('pwdInput').focus();
    };
    $('btnDisconnect').onclick = function () { disconnect(true); };

    $('tabs').addEventListener('click', function (e) {
      var btn = e.target.closest('.tab');
      if (btn) activateTab(btn.dataset.tab);
    });
    window.addEventListener('hashchange', function () {
      var name = location.hash.slice(1);
      if (name) activateTab(name);
    });

    $('btnStartVideo').onclick = startVideo;
    $('btnStopVideo').onclick = stopVideo;
    $('btnReloadStream').onclick = reloadStream;
    $('btnFullscreen').onclick = function () {
      var el = $('videoStage');
      if (el.requestFullscreen) el.requestFullscreen();
    };
    $('btnSnapshot').onclick = async function () {
      try {
        var res = await api('/api/camera/snapshot' + tokenQuery(), { timeout: 10000 });
        var blob = await res.blob(), url = URL.createObjectURL(blob);
        var a = document.createElement('a'); a.href = url;
        a.download = 'classconnector-camera-' + Date.now() + '.jpg'; a.click();
        setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
      } catch (e) { toast('抓拍失败：' + errText(e), 'err'); }
    };
    $('btnListen').onclick = function () { S.listenOn ? stopListen() : startListen(); };
    $('volumeSlider').oninput = function () { S.player.setVolume(Number(this.value) / 100); };
    $('btnTalk').onclick = function () { S.talkOn ? stopTalk() : startTalk(); };
    document.addEventListener('keydown', function (e) {
      if (e.code !== 'Space' || e.repeat) return;
      var tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (!$('bannerOverlay').hidden) return;
      if (!S.talkOn) { S.spaceTalk = true; startTalk(); e.preventDefault(); }
    });
    document.addEventListener('keyup', function (e) {
      if (e.code === 'Space' && S.spaceTalk) { S.spaceTalk = false; stopTalk(); }
    });

    $('qualitySlider').oninput = function () { $('qualityVal').textContent = this.value; };
    $('btnApplyQuality').onclick = applyQuality;
    $('btnRefreshStatus').onclick = function () { loadStatus().then(function () { loadLogs(); }).catch(function (e) { toast(errText(e), 'err'); }); };

    $('bannerTitle').oninput = renderMdPreview;
    $('bannerText').oninput = renderMdPreview;
    $('btnSendBanner').onclick = sendBanner;
    $('btnPreviewBanner').onclick = previewBanner;
    $('btnTestTts').onclick = async function () {
      try {
        await postJson('/api/tts/speak', {
          text: stripMarkdownText($('bannerTitle').value + '。' + $('bannerText').value),
          urgent: $('optUrgent').checked, voice: $('voiceSelect').value
        });
        toast('已加入语音播报队列', 'ok');
      } catch (e) { toast(errText(e), 'err'); }
    };
    $('btnDismissBanner').onclick = async function () {
      try { await postJson('/api/banner/dismiss', {}); toast('已关闭当前横幅', 'ok'); loadHistory(); }
      catch (e) { toast(errText(e), 'err'); }
    };
    $('btnRefreshHistory').onclick = function () { loadHistory().catch(function (e) { toast(errText(e), 'err'); }); };
    $('bannerCloseBtn').onclick = closeBannerPreview;
    $('bannerAckBtn').onclick = async function () {
      if (!S.currentBannerId) { closeBannerPreview(); return; }
      var target = S.history.filter(function (x) { return x.id === S.currentBannerId; })[0];
      if (!target || target.status !== 'showing') {
        toast('这是网页预览签收（未发送真实通知）');
        setTimeout(closeBannerPreview, 700);
        return;
      }
      try {
        await postJson('/api/banner/ack', { id: S.currentBannerId, source: 'web' });
        toast('✅ 已完成签收', 'ok');
        $('bannerAckBtn').textContent = '✓ 已签收';
        $('bannerAckBtn').disabled = true;
        loadHistory().catch(function () {});
        setTimeout(closeBannerPreview, 900);
      } catch (e) { toast(errText(e), 'err'); }
    };

    $('btnShot').onclick = takeShot;
    $('btnDownloadShot').onclick = downloadShot;
    $('autoShot').onchange = function () {
      clearInterval(S.autoShotTimer);
      if (this.checked) {
        var ms = Number($('autoShotInterval').value) || 10000;
        S.autoShotTimer = setInterval(function () { if (S.connected) takeShot(); }, ms);
        takeShot();
      }
    };
    $('autoShotInterval').onchange = function () {
      if ($('autoShot').checked) $('autoShot').onchange.call($('autoShot'));
    };

    $('btnSaveSettings').onclick = saveSettings;
    $('btnChangePwd').onclick = changePassword;
    $('btnStopAgent').onclick = function () { agentAction('stop'); };
    $('btnRestartAgent').onclick = function () { agentAction('restart'); };
  }

  /* =============================== 启动 =============================== */
  async function boot() {
    loadDevices(); renderDeviceLists(); bind();
    var initialTab = location.hash.slice(1);
    if (initialTab) activateTab(initialTab);
    // 若页面由采集端自己托管，则自动连接本机，无需手工输入
    try {
      var res = await fetch('/api/health', { cache: 'no-store', signal: withTimeout(2500).signal });
      var h = await res.json();
      if (h && h.service === 'classconnector-agent') {
        $('ipInput').value = location.hostname;
        $('portInput').value = location.port || '80';
        await connect(location.hostname, location.port || 80, '');
        return;
      }
    } catch (e) { /* 独立部署的管理端，显示连接面板 */ }
    renderMdPreview();
  }
  boot();
})();
