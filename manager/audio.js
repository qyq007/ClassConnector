/* 浏览器端 PCM 音频：监听播放 + 麦克风采集（统一 16kHz / 单声道 / 16bit） */
(function (global) {
  'use strict';

  var SAMPLE_RATE = 16000;
  var TARGET_CHUNK = 1024; // 每 64ms 发送一帧

  /* ---------------- 监听播放 ---------------- */
  function PcmPlayer() {
    this.ctx = null; this.gain = null; this.sources = [];
    this.nextTime = 0; this.volume = 0.8; this.enabled = false;
  }
  PcmPlayer.prototype.enable = async function () {
    var AC = global.AudioContext || global.webkitAudioContext;
    if (!AC) throw new Error('当前浏览器不支持 Web Audio');
    if (!this.ctx) {
      this.ctx = new AC({ latencyHint: 'interactive' });
      this.gain = this.ctx.createGain();
      this.gain.gain.value = this.volume;
      this.gain.connect(this.ctx.destination);
    }
    await this.ctx.resume();
    this.enabled = true;
    this.nextTime = this.ctx.currentTime + 0.03;
  };
  PcmPlayer.prototype.setVolume = function (v) {
    this.volume = v;
    if (this.gain) this.gain.gain.value = v;
  };
  PcmPlayer.prototype.feed = function (arrayBuffer) {
    if (!this.enabled || !this.ctx) return;
    var pcm = new Int16Array(arrayBuffer);
    if (!pcm.length) return;
    var buf = this.ctx.createBuffer(1, pcm.length, SAMPLE_RATE);
    var data = buf.getChannelData(0);
    for (var i = 0; i < pcm.length; i++) data[i] = pcm[i] / 32768;
    var src = this.ctx.createBufferSource();
    src.buffer = buf; src.connect(this.gain);
    var now = this.ctx.currentTime;
    if (this.nextTime < now + 0.02) this.nextTime = now + 0.02;
    if (this.nextTime > now + 1.0) this.nextTime = now + 0.02; // 延迟过大时重置
    try { src.start(this.nextTime); } catch (e) { return; }
    this.nextTime += buf.duration;
    var self = this;
    this.sources.push(src);
    src.onended = function () {
      var idx = self.sources.indexOf(src);
      if (idx >= 0) self.sources.splice(idx, 1);
    };
  };
  PcmPlayer.prototype.stop = function () {
    this.enabled = false;
    this.sources.forEach(function (s) { try { s.stop(); } catch (e) {} });
    this.sources = [];
    this.nextTime = 0;
  };

  /* ---------------- 麦克风采集 ---------------- */
  var WORKLET_CODE = [
    'class CCPcm extends AudioWorkletProcessor {',
    '  process(inputs) {',
    '    var input = inputs[0];',
    '    if (input && input[0] && input[0].length) {',
    '      this.port.postMessage(new Float32Array(input[0]));',
    '    }',
    '    return true;',
    '  }',
    '}',
    "registerProcessor('cc-pcm', CCPcm);"
  ].join('\n');

  function MicRecorder(onChunk) {
    this.onChunk = onChunk;
    this.stream = null; this.ctx = null; this.node = null; this.source = null;
    this.running = false; this._pending = [];
    this._pendingLen = 0;
  }
  MicRecorder.prototype.start = async function () {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('浏览器不支持麦克风采集，请使用 http:// 或 https:// 访问');
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false
    });
    var AC = global.AudioContext || global.webkitAudioContext;
    this.ctx = new AC();
    await this.ctx.resume();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    var self = this;
    var handle = function (f32) { self._onFloat(f32); };

    if (this.ctx.audioWorklet) {
      try {
        var url = URL.createObjectURL(new Blob([WORKLET_CODE], { type: 'application/javascript' }));
        await this.ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        this.node = new AudioWorkletNode(this.ctx, 'cc-pcm', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1]
        });
        this.node.port.onmessage = function (e) { handle(e.data); };
      } catch (e) {
        this.node = null;
      }
    }
    if (!this.node) {
      this.node = this.ctx.createScriptProcessor(2048, 1, 1);
      this.node.onaudioprocess = function (e) { handle(e.inputBuffer.getChannelData(0)); };
    }
    this.source.connect(this.node);
    this.node.connect(this.ctx.destination);
    this.running = true;
  };
  MicRecorder.prototype._onFloat = function (f32) {
    if (!this.running || !f32 || !f32.length) return;
    var ratio = SAMPLE_RATE / this.ctx.sampleRate;
    var outLen = Math.floor(f32.length * ratio);
    var out = new Int16Array(outLen);
    for (var i = 0; i < outLen; i++) {
      var pos = i / ratio, i0 = Math.floor(pos), i1 = Math.min(f32.length - 1, i0 + 1);
      var frac = pos - i0;
      var v = f32[i0] * (1 - frac) + f32[i1] * frac;
      v = Math.max(-1, Math.min(1, v));
      out[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
    }
    this._pending.push(out);
    this._pendingLen += outLen;
    if (this._pendingLen >= TARGET_CHUNK) {
      var merged = new Int16Array(this._pendingLen), offset = 0;
      for (var p = 0; p < this._pending.length; p++) {
        merged.set(this._pending[p], offset); offset += this._pending[p].length;
      }
      this._pending = []; this._pendingLen = 0;
      this.onChunk(merged.buffer);
    }
  };
  MicRecorder.prototype.stop = function () {
    this.running = false;
    try { if (this.source) this.source.disconnect(); } catch (e) {}
    try { if (this.node) { this.node.disconnect(); if (this.node.port) this.node.port.onmessage = null; } } catch (e) {}
    if (this.stream) this.stream.getTracks().forEach(function (t) { t.stop(); });
    if (this.ctx) this.ctx.close().catch(function () {});
    this.stream = null; this.ctx = null; this.node = null; this.source = null;
    this._pending = []; this._pendingLen = 0;
  };

  global.PcmPlayer = PcmPlayer;
  global.MicRecorder = MicRecorder;
  global.CC_SAMPLE_RATE = SAMPLE_RATE;
})(window);
