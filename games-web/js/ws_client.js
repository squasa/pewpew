// WebSocket client + procedural WebAudio SFX engine for low-latency phone feedback

const WAV_SOUNDS = {
  pool_clack: "/sounds/pool_clack.wav",
  clack: "/sounds/pool_clack.wav",
  pool_break: "/sounds/pool_break.wav",
  pool_pot: "/sounds/pool_pot.wav",
  pong_bounce: "/sounds/pong_bounce.wav",
  pong_cup: "/sounds/pong_cup.wav",
  splash: "/sounds/pong_cup.wav",
  thud: "/sounds/thud.wav",
  krill_tick: "/sounds/krill_tick.wav",
  krill_deep: "/sounds/krill_deep.wav",
};

export class SoundFX {
  constructor() {
    this.enabled = true;
    this.ctx = null;
    this._buffers = new Map();
    this._loading = false;
    this._noiseBuf = null;
  }

  _ensureCtx() {
    if (!this.enabled) return null;
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC();
      this._preloadAll();
    }
    if (this.ctx.state === "suspended") {
      this.ctx.resume().catch(() => {});
    }
    return this.ctx;
  }

  async _preloadAll() {
    if (this._loading || !this.ctx) return;
    this._loading = true;
    const uniqueUrls = [...new Set(Object.values(WAV_SOUNDS))];
    await Promise.all(
      uniqueUrls.map(async (url) => {
        try {
          const res = await fetch(url);
          if (!res.ok) return;
          const raw = await res.arrayBuffer();
          const buf = await this.ctx.decodeAudioData(raw);
          this._buffers.set(url, buf);
        } catch (_) {
          // Safe fallback to synth when audio decode unavailable
        }
      })
    );
  }

  _playBuffer(url, gainVal = 0.85, rateJitter = 0.04) {
    const ctx = this.ctx;
    const buf = this._buffers.get(url);
    if (!ctx || !buf) return false;
    const src = ctx.createBufferSource();
    const gain = ctx.createGain();
    src.buffer = buf;
    src.playbackRate.value = 1 + (Math.random() * 2 - 1) * rateJitter;
    gain.gain.value = gainVal;
    src.connect(gain);
    gain.connect(ctx.destination);
    src.start(0);
    return true;
  }

  _getNoiseBuffer(ctx) {
    if (this._noiseBuf && this._noiseBuf.sampleRate === ctx.sampleRate) {
      return this._noiseBuf;
    }
    const len = Math.floor(ctx.sampleRate * 1.6);
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
    this._noiseBuf = buf;
    return buf;
  }

  _noise(ctx, start, { dur = 0.35, lp = 900, sweepTo = null, hp = 0, peak = 0.14 } = {}) {
    const src = ctx.createBufferSource();
    src.buffer = this._getNoiseBuffer(ctx);
    let node = src;
    if (hp > 0) {
      const hpf = ctx.createBiquadFilter();
      hpf.type = "highpass";
      hpf.frequency.setValueAtTime(hp, start);
      node.connect(hpf);
      node = hpf;
    }
    const lpf = ctx.createBiquadFilter();
    lpf.type = "lowpass";
    lpf.frequency.setValueAtTime(lp, start);
    if (sweepTo) lpf.frequency.exponentialRampToValueAtTime(Math.max(40, sweepTo), start + dur);
    node.connect(lpf);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, start);
    g.gain.linearRampToValueAtTime(peak, start + Math.min(0.03, dur * 0.2));
    g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    lpf.connect(g);
    g.connect(ctx.destination);
    src.start(start);
    src.stop(start + dur + 0.03);
  }

  unlock() {
    this._ensureCtx();
  }

  play(kind, opts = {}) {
    const ctx = this._ensureCtx();
    if (!ctx) return;
    const t = ctx.currentTime;
    try {
      const wavUrl = WAV_SOUNDS[kind];
      if (wavUrl) {
        const vol = opts.gain ?? (kind === "pong_bounce" ? 0.65 : kind === "pool_clack" ? 0.78 : 0.9);
        if (this._playBuffer(wavUrl, vol, opts.jitter ?? 0.05)) return;
      }

      if (kind === "krill_submit") {
        this._tone(ctx, t, 1150, 920, 0.16, "sine", 0.16);
      } else if (kind === "krill_tierline" || kind === "krill_ping") {
        this._tone(ctx, t, 780, 1560, 0.08, "triangle", 0.14);
      } else if (kind === "krill_sink") {
        this._tone(ctx, t, 1150, 420, 0.68, "sine", 0.10);
        this._noise(ctx, t, { dur: 1.25, lp: 1400, sweepTo: 180, peak: 0.16 });
        this._tone(ctx, t, 300, 62, 1.2, "sine", 0.10);
      } else if (kind === "krill_land_small") {
        this._tone(ctx, t, 145, 70, 0.25, "sine", 0.26);
        this._noise(ctx, t, { dur: 0.14, lp: 520, peak: 0.11 });
      } else if (kind === "krill_land_big") {
        this._tone(ctx, t, 84, 44, 0.58, "sine", 0.34);
        this._noise(ctx, t + 0.02, { dur: 0.65, lp: 920, sweepTo: 200, peak: 0.17 });
        this._tone(ctx, t + 0.14, 523.25, 659.25, 0.38, "triangle", 0.11);
      } else if (kind === "krill_gold" || kind === "krill_deep") {
        this._tone(ctx, t, 64, 40, 1.1, "sine", 0.30);
        [784, 988, 1175, 1568].forEach((f, idx) => {
          this._tone(ctx, t + idx * 0.12, f, f * 1.02, 0.55, "triangle", 0.15);
        });
        this._noise(ctx, t + 0.25, { dur: 1.2, lp: 2600, hp: 1100, peak: 0.06 });
      } else if (kind === "krill_surface") {
        this._noise(ctx, t, { dur: 1.1, lp: 280, sweepTo: 2400, peak: 0.12 });
        [392, 523.25, 659.25].forEach((f, idx) => {
          this._tone(ctx, t + 0.18 + idx * 0.1, f, f * 1.08, 0.28, "sine", 0.11);
        });
      } else if (kind === "krill_tick") {
        this._tone(ctx, t, 880, 860, 0.07, "sine", 0.14);
        this._tone(ctx, t + 0.11, 880, 860, 0.05, "sine", 0.06);
      } else if (kind === "krill_reject") {
        this._noise(ctx, t, { dur: 0.20, lp: 420, peak: 0.18 });
        this._tone(ctx, t, 150, 62, 0.34, "sawtooth", 0.16);
      } else if (kind === "krill_miss") {
        this._tone(ctx, t, 220, 52, 0.65, "triangle", 0.20);
        this._noise(ctx, t + 0.05, { dur: 0.45, lp: 380, peak: 0.13 });
      } else if (kind === "jinx") {
        this._tone(ctx, t, 310, 190, 0.25, "sawtooth", 0.10);
        this._tone(ctx, t + 0.1, 240, 130, 0.30, "sawtooth", 0.10);
      } else if (kind === "bubble") {
        this._tone(ctx, t, 410, 920, 0.11, "sine", 0.08);
      } else if (kind === "win") {
        [523.25, 659.25, 783.99, 1046.5].forEach((f, idx) => {
          this._tone(ctx, t + idx * 0.07, f, f * 1.02, 0.24, "triangle", 0.11);
        });
      } else if (kind === "clack" || kind === "pool_clack") {
        this._tone(ctx, t, 460, 180, 0.06, "triangle", 0.14);
      } else if (kind === "pool_break") {
        this._noise(ctx, t, { dur: 0.24, lp: 2400, sweepTo: 400, peak: 0.22 });
        this._tone(ctx, t, 360, 110, 0.09, "triangle", 0.18);
      } else if (kind === "pool_pot") {
        this._tone(ctx, t, 220, 90, 0.18, "sine", 0.20);
        this._tone(ctx, t + 0.06, 150, 65, 0.22, "triangle", 0.14);
      } else if (kind === "pong_bounce") {
        this._tone(ctx, t, 980, 640, 0.045, "sine", 0.14);
      } else if (kind === "splash" || kind === "pong_cup") {
        this._tone(ctx, t, 680, 320, 0.18, "sine", 0.12);
        this._tone(ctx, t + 0.06, 860, 520, 0.16, "sine", 0.10);
      } else if (kind === "thud") {
        this._tone(ctx, t, 210, 85, 0.10, "sine", 0.16);
      }
    } catch (_) {
      // Ignore WebAudio autoplay race before first tap
    }
  }

  _tone(ctx, start, f0, f1, dur, type, vol) {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(f0, start);
    osc.frequency.exponentialRampToValueAtTime(Math.max(20, f1), start + dur);
    g.gain.setValueAtTime(0.0001, start);
    g.gain.linearRampToValueAtTime(vol, start + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    osc.connect(g);
    g.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + dur + 0.02);
  }
}

const CLOUD_BROKERS = [
  "wss://broker.emqx.io:8084/mqtt",
  "wss://broker.hivemq.com:8884/mqtt",
];
const _ENC = new TextEncoder();
const _DEC = new TextDecoder();

function _mqttVarInt(n) {
  const out = [];
  do {
    let b = n % 128;
    n = Math.floor(n / 128);
    if (n > 0) b |= 0x80;
    out.push(b);
  } while (n > 0);
  return new Uint8Array(out);
}

function _mqttStr(s) {
  const raw = _ENC.encode(s);
  const out = new Uint8Array(2 + raw.length);
  out[0] = (raw.length >> 8) & 0xff;
  out[1] = raw.length & 0xff;
  out.set(raw, 2);
  return out;
}

function _mqttConcat(...parts) {
  let len = 0;
  for (const p of parts) len += p.length;
  const out = new Uint8Array(len);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

function _mqttEncodeConnect(clientId, keepalive = 20) {
  const varHdr = _mqttConcat(
    _mqttStr("MQTT"),
    new Uint8Array([0x04, 0x02, (keepalive >> 8) & 0xff, keepalive & 0xff]),
    _mqttStr(clientId)
  );
  return _mqttConcat(new Uint8Array([0x10]), _mqttVarInt(varHdr.length), varHdr);
}

function _mqttEncodeSubscribe(pktId, topic) {
  const body = _mqttConcat(
    new Uint8Array([(pktId >> 8) & 0xff, pktId & 0xff]),
    _mqttStr(topic),
    new Uint8Array([0x00])
  );
  return _mqttConcat(new Uint8Array([0x82]), _mqttVarInt(body.length), body);
}

function _mqttEncodePublish(topic, text) {
  const body = _mqttConcat(_mqttStr(topic), _ENC.encode(text));
  return _mqttConcat(new Uint8Array([0x30]), _mqttVarInt(body.length), body);
}

function _mqttParseFrames(buf) {
  const packets = [];
  let off = 0;
  while (buf.length - off >= 2) {
    const hdr = buf[off];
    let idx = off + 1;
    let rem = 0;
    let mul = 1;
    let complete = false;
    while (idx < buf.length) {
      const b = buf[idx++];
      rem += (b & 0x7f) * mul;
      if (!(b & 0x80)) {
        complete = true;
        break;
      }
      mul *= 128;
    }
    if (!complete || buf.length - idx < rem) break;
    packets.push({ hdr, body: buf.subarray(idx, idx + rem) });
    off = idx + rem;
  }
  return { packets, rest: off ? buf.subarray(off) : buf };
}

function _mqttDecodePublish(hdr, body) {
  if (body.length < 2) return null;
  const tlen = (body[0] << 8) | body[1];
  let pos = 2 + tlen;
  if (body.length < pos) return null;
  const qos = (hdr >> 1) & 0x03;
  if (qos > 0) {
    pos += 2;
    if (body.length < pos) return null;
  }
  return _DEC.decode(body.subarray(pos));
}

export class WsClient {
  constructor(onState, onStatus, onAck) {
    this.onState = onState;
    this.onStatus = onStatus;
    this.onAck = onAck;
    this.ws = null;
    this.role = "guest";
    this.name = localStorage.getItem("pewpew_name") || "";
    this.clientId = this._resolveClientId();
    this.room = this._resolveRoom();
    this.wsOrigin = this._resolveWsOrigin();
    this.connected = false;
    this.mode = "direct"; // "direct" | "cloud"
    this._mqttReady = false;
    this._brokerIdx = 0;
    this._reconnectTimer = null;
    this._pingTimer = null;
    this._handshakeTimer = null;
    this._haltedError = false;
    this._rxBuf = new Uint8Array(0);
    window.addEventListener("pagehide", () => {
      if (this.mode === "cloud" && this._mqttReady && this.ws?.readyState === WebSocket.OPEN) {
        this.send({ type: "leave" });
      }
    });
  }

  _resolveClientId() {
    let cid = "";
    try {
      cid = sessionStorage.getItem("pewpew_cid") || "";
      if (!cid) {
        cid = "c" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
        sessionStorage.setItem("pewpew_cid", cid);
      }
    } catch (_) {
      cid = "c" + Math.random().toString(36).slice(2, 12);
    }
    return cid.slice(0, 20);
  }

  _roleFromCode(code, explicitRole = "") {
    if (explicitRole === "host" || explicitRole === "guest") return explicitRole;
    if (code.length === 4) {
      if (code.endsWith("1")) return "guest";
      if (code.endsWith("2")) return "host";
    }
    return this.role || "guest";
  }

  _resolveRoom() {
    const qs = new URLSearchParams(window.location.search);
    const r = (
      qs.get("code") ||
      qs.get("room") ||
      localStorage.getItem("pewpew_code") ||
      localStorage.getItem("pewpew_room") ||
      ""
    ).trim().toUpperCase();
    if (r) {
      localStorage.setItem("pewpew_code", r);
      localStorage.setItem("pewpew_room", r);
    }
    const qsRole = (qs.get("role") || "").trim().toLowerCase();
    this.role = this._roleFromCode(r, qsRole);
    return r;
  }

  _resolveWsOrigin() {
    const qs = new URLSearchParams(window.location.search);
    const explicit = (qs.get("ws") || qs.get("server") || "").trim();
    if (explicit) return explicit;
    if (window.location.hostname.endsWith("github.io") || window.location.protocol === "file:") {
      return "";
    }
    return (localStorage.getItem("pewpew_ws") || "").trim();
  }

  _shouldUseCloud() {
    if (this.wsOrigin) return false;
    const qs = new URLSearchParams(window.location.search);
    if (qs.get("cloud") === "1") return true;
    const h = window.location.hostname;
    return h.endsWith("github.io") || (!h && window.location.protocol === "file:");
  }

  setCode(code) {
    this.setTarget("", code);
  }

  setTarget(serverHostOrUrl, roomCode) {
    const srv = (serverHostOrUrl || "").trim();
    const rm = (roomCode || "").trim().toUpperCase();
    if (srv) {
      this.wsOrigin = srv;
      localStorage.setItem("pewpew_ws", srv);
    }
    if (rm) {
      this.room = rm;
      this.role = this._roleFromCode(rm);
      localStorage.setItem("pewpew_code", rm);
      localStorage.setItem("pewpew_room", rm);
    }
    this._haltedError = false;
    this._clearTimers();
    this._closeSocket();
    this.connect();
  }

  _clearTimers() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._pingTimer) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
    if (this._handshakeTimer) {
      clearTimeout(this._handshakeTimer);
      this._handshakeTimer = null;
    }
  }

  _closeSocket() {
    const prev = this.ws;
    this.ws = null;
    this.connected = false;
    this._mqttReady = false;
    if (prev) {
      prev.onopen = null;
      prev.onmessage = null;
      prev.onclose = null;
      prev.onerror = null;
      try { prev.close(); } catch (_) {}
    }
  }

  _buildWsUrl(params) {
    const raw = this.wsOrigin;
    if (raw) {
      if (raw.startsWith("ws://") || raw.startsWith("wss://")) {
        return `${raw.replace(/\/+$/, "")}/ws?${params.toString()}`;
      }
      if (raw.startsWith("http://") || raw.startsWith("https://")) {
        const wsUrl = raw.replace(/^http/, "ws").replace(/\/+$/, "");
        return `${wsUrl}/ws?${params.toString()}`;
      }
      const cleanHost = raw.replace(/\/+$/, "");
      const isLocal = /^(localhost|127\.0\.0\.1|192\.168\.|10\.|172\.)/.test(cleanHost);
      const scheme = (window.location.protocol === "https:" && !isLocal) ? "wss:" : "ws:";
      return `${scheme}//${cleanHost}/ws?${params.toString()}`;
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws?${params.toString()}`;
  }

  connect() {
    if (!this.room || this.room.length < 3) {
      this.onStatus(false, "MISSING CODE", { code: "missing_code" });
      return;
    }
    if (this._shouldUseCloud()) {
      this._connectCloud();
      return;
    }
    this.mode = "direct";
    this._mqttReady = false;
    const params = new URLSearchParams({
      room: this.room,
      role: this.role,
    });
    if (this.name) params.set("name", this.name);
    const url = this._buildWsUrl(params);
    try {
      this.ws = new WebSocket(url);
    } catch (_) {
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.connected = true;
      this.onStatus(true, this.room);
    };

    this.ws.onmessage = (ev) => {
      let msg = null;
      try {
        msg = JSON.parse(ev.data);
      } catch (_) {
        return;
      }
      this._handleIncoming(msg);
    };

    this.ws.onclose = () => {
      this.connected = false;
      this.onStatus(false, this.room || "DISCONNECTED");
      if (!this._haltedError) this._scheduleReconnect();
    };
  }

  _connectCloud() {
    this.mode = "cloud";
    this._mqttReady = false;
    this._rxBuf = new Uint8Array(0);
    const prefix = this.room.slice(0, 3);
    const broker = CLOUD_BROKERS[this._brokerIdx % CLOUD_BROKERS.length];
    let sock;
    try {
      sock = new WebSocket(broker, "mqtt");
      sock.binaryType = "arraybuffer";
    } catch (_) {
      this._brokerIdx = (this._brokerIdx + 1) % CLOUD_BROKERS.length;
      this._scheduleReconnect(800);
      return;
    }
    this.ws = sock;
    this.onStatus(false, this.room, { code: "connecting", broker });

    this._handshakeTimer = setTimeout(() => {
      if (this.ws === sock && !this._mqttReady) {
        this._brokerIdx = (this._brokerIdx + 1) % CLOUD_BROKERS.length;
        this._closeSocket();
        this._scheduleReconnect(250);
      }
    }, 4500);

    sock.onopen = () => {
      if (this.ws !== sock) return;
      const cid = `pp-cli-${this.clientId}-${Math.random().toString(36).slice(2, 6)}`;
      sock.send(_mqttEncodeConnect(cid, 25));
    };

    sock.onmessage = (ev) => {
      if (this.ws !== sock) return;
      const chunk = new Uint8Array(ev.data);
      this._rxBuf = _mqttConcat(this._rxBuf, chunk);
      let parsed;
      try {
        parsed = _mqttParseFrames(this._rxBuf);
      } catch (_) {
        this._rxBuf = new Uint8Array(0);
        return;
      }
      this._rxBuf = parsed.rest;
      for (const pkt of parsed.packets) {
        const ptype = pkt.hdr & 0xf0;
        if (ptype === 0x20) {
          if (pkt.body.length < 2 || pkt.body[1] !== 0) {
            this._brokerIdx = (this._brokerIdx + 1) % CLOUD_BROKERS.length;
            this._closeSocket();
            this._scheduleReconnect(400);
            return;
          }
          sock.send(_mqttEncodeSubscribe(1, `pewpew/v1/${prefix}/client/${this.clientId}`));
        } else if (ptype === 0x90) {
          if (this._handshakeTimer) {
            clearTimeout(this._handshakeTimer);
            this._handshakeTimer = null;
          }
          this.connected = true;
          this._mqttReady = true;
          this.onStatus(true, this.room);
          this.send({ type: "join", code: this.room, role: this.role, name: this.name });
          if (this._pingTimer) clearInterval(this._pingTimer);
          this._pingTimer = setInterval(() => {
            if (this.ws === sock && sock.readyState === WebSocket.OPEN && this._mqttReady) {
              sock.send(new Uint8Array([0xc0, 0x00]));
              this.send({ type: "ping", t: Date.now() });
            }
          }, 12000);
        } else if (ptype === 0x30) {
          const text = _mqttDecodePublish(pkt.hdr, pkt.body);
          if (!text) continue;
          try {
            const msg = JSON.parse(text);
            this._handleIncoming(msg);
          } catch (_) {}
        }
      }
    };

    sock.onclose = () => {
      if (this.ws !== sock) return;
      this._clearTimers();
      this.connected = false;
      this._mqttReady = false;
      if (!this._haltedError) {
        this.onStatus(false, this.room || "DISCONNECTED");
        this._scheduleReconnect(1200);
      }
    };
  }

  _handleIncoming(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "welcome") {
      this.role = msg.role || this.role;
      this.name = msg.name || this.name;
      if (msg.herCode && msg.role === "guest") this.room = msg.herCode;
      else if (msg.hostCode && msg.role === "host") this.room = msg.hostCode;
      else if (msg.room) this.room = msg.room;
      this.onStatus(true, this.room, msg);
    } else if (msg.type === "state") {
      this.onState(msg);
    } else if (msg.type === "error") {
      if (msg.code === "bad_room" || msg.code === "expired") {
        this._haltedError = true;
        this._clearTimers();
        this._closeSocket();
      }
      this.onStatus(false, msg.message || "ERROR", msg);
    } else {
      this.onAck(msg);
    }
  }

  _scheduleReconnect(delayMs = 1500) {
    if (this._reconnectTimer || this._haltedError) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, delayMs);
  }

  send(obj) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    if (this.mode === "cloud") {
      if (!this._mqttReady || !this.room || this.room.length < 3) return;
      const prefix = this.room.slice(0, 3);
      const env = JSON.stringify({
        cid: this.clientId,
        role: this.role,
        code: this.room,
        name: this.name,
        msg: obj,
      });
      this.ws.send(_mqttEncodePublish(`pewpew/v1/${prefix}/in`, env));
      return;
    }
    this.ws.send(JSON.stringify(obj));
  }

  selectGame(game) {
    this.send({ type: "select_game", game });
  }

  action(game, act, extra = {}) {
    this.send({ type: "action", game, act, ...extra });
  }

  setProfile(name, role = null) {
    this.name = (name || "").trim();
    localStorage.setItem("pewpew_name", this.name);
    const msg = { type: "set_profile", name: this.name };
    if (role) msg.role = role;
    this.send(msg);
  }
}
