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

export class WsClient {
  constructor(onState, onStatus, onAck) {
    this.onState = onState;
    this.onStatus = onStatus;
    this.onAck = onAck;
    this.ws = null;
    this.role = "guest";
    this.name = localStorage.getItem("pewpew_name") || "";
    this.room = this._resolveRoom();
    this.wsOrigin = this._resolveWsOrigin();
    this.connected = false;
    this._reconnectTimer = null;
  }

  _resolveRoom() {
    const qs = new URLSearchParams(window.location.search);
    const r = (qs.get("room") || localStorage.getItem("pewpew_room") || "").trim().toUpperCase();
    if (r) localStorage.setItem("pewpew_room", r);
    const qsRole = (qs.get("role") || "").trim().toLowerCase();
    if (qsRole === "host" || qsRole === "guest") {
      this.role = qsRole;
    }
    return r;
  }

  _resolveWsOrigin() {
    const qs = new URLSearchParams(window.location.search);
    const raw = (qs.get("ws") || qs.get("server") || localStorage.getItem("pewpew_ws") || "").trim();
    if (qs.get("ws") || qs.get("server")) {
      localStorage.setItem("pewpew_ws", raw);
    }
    return raw;
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
      localStorage.setItem("pewpew_room", rm);
    }
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    try { this.ws?.close(); } catch (_) {}
    this.connect();
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
      const scheme = window.location.protocol === "https:" && !isLocal ? "wss:" : (window.location.protocol === "https:" ? "wss:" : "ws:");
      return `${scheme}//${cleanHost}/ws?${params.toString()}`;
    }
    if (window.location.hostname.endsWith("github.io")) {
      return null;
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws?${params.toString()}`;
  }

  connect() {
    if (!this.room) {
      this.onStatus(false, "MISSING ROOM");
      return;
    }
    const params = new URLSearchParams({
      room: this.room,
      role: this.role,
    });
    if (this.name) params.set("name", this.name);
    const url = this._buildWsUrl(params);
    if (!url) {
      this.onStatus(false, "NEED ?ws=SERVER");
      return;
    }
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
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "welcome") {
        this.role = msg.role || this.role;
        this.name = msg.name || this.name;
        this.room = msg.room || this.room;
        this.onStatus(true, this.room, msg);
      } else if (msg.type === "state") {
        this.onState(msg);
      } else if (msg.type === "error") {
        this.onStatus(false, msg.message || "ERROR");
      } else {
        this.onAck(msg);
      }
    };

    this.ws.onclose = () => {
      this.connected = false;
      this.onStatus(false, this.room || "DISCONNECTED");
      this._scheduleReconnect();
    };
  }

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, 1500);
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
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
