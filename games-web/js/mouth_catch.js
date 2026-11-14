// Real Three.js WebGL 3D Mouth Catch — live webcam video feed + 3D sprinkled/dripping donut + Pong-style swipe toss
import { THREE, createPubRenderer } from "./three_helpers.js";

export class MouthCatchView {
  constructor(ws, sfx) {
    this.ws = ws;
    this.sfx = sfx;
    this._aim = { x: 0.5, y: 0.52 };
    this._power = 0.65;
    this._state = null;
    this._canvas = null;
    this._container = null;
    this._lastSig = "";

    this._raf = 0;
    this._pub = null;
    this._mouthTarget = null;
    this._mouthRingMat = null;
    this._mouthInnerMat = null;
    this._donut = null;
    this._flight = null;
    this._drag = null;
    this._swipeTrail = [];
  }

  mount(container, state) {
    this._container = container;
    this._lastSig = "";
    this.update(state);
  }

  unmount() {
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = 0;
    }
    if (this._pub) {
      this._pub.renderer.dispose();
      this._pub = null;
    }
    this._canvas = null;
    this._container = null;
  }

  update(state) {
    this._state = state;
    const mc = state.mouth_catch;
    if (!mc || !this._container) return;

    const p1 = this.ws.playerName("guest");
    const p2 = this.ws.playerName("host");
    const sig = `${mc.phase}|${mc.throwsLeft}|${mc.score}|${mc.combo}|${mc.catches}|${mc.splats}|${mc.lastResult?.outcome || ""}|${p1}|${p2}`;
    if (sig !== this._lastSig || !this._canvas) {
      if (this._lastSig && mc.lastResult?.outcome === "catch") this.sfx.play("win");
      else if (this._lastSig && mc.lastResult?.outcome === "splat") this.sfx.play("splash");
      this._lastSig = sig;
      this._renderDOM(mc, state.cam || {});
    } else {
      this._updateHudText(mc, state.cam || {});
    }
    this._syncCamFrame(state.cam);
  }

  _syncCamFrame(cam) {
    if (!this._container) return;
    const img = this._container.querySelector("#mc-cam-bg");
    const wait = this._container.querySelector("#mc-cam-wait");
    if (img && cam?.jpg) {
      img.src = `data:image/jpeg;base64,${cam.jpg}`;
      img.style.display = "block";
      if (wait) wait.style.display = "none";
    }
  }

  _updatePowerBar(pwr, text = "") {
    const fill = this._container?.querySelector("#mc-power-fill");
    const lbl = this._container?.querySelector("#mc-power-label");
    if (!fill || !lbl) return;
    const p = Math.max(0, Math.min(1, pwr));
    const pct = Math.round(p * 100);
    fill.style.width = `${pct}%`;
    fill.style.background =
      p <= 0.5
        ? "linear-gradient(90deg,#22c55e,#eab308)"
        : "linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444)";
    lbl.textContent = text || `SWIPE UP LIKE PONG TO AIM & TOSS · ${pct}%`;
  }

  _normToWorld(nx, ny, zPlane = 0) {
    const cam = this._pub?.camera;
    const aspect = cam?.aspect || 16 / 9;
    const dist = (cam?.position?.z ?? 1.95) - zPlane;
    const halfH = Math.tan(((cam?.fov ?? 42) * Math.PI) / 360) * dist;
    const halfW = halfH * aspect;
    return new THREE.Vector3((nx - 0.5) * 2 * halfW, (0.5 - ny) * 2 * halfH, zPlane);
  }

  _buildDonutMesh() {
    const grp = new THREE.Group();
    const doughMat = new THREE.MeshStandardMaterial({
      color: 0xd99b56,
      roughness: 0.48,
      metalness: 0.04,
    });
    const dough = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.055, 28, 48), doughMat);
    dough.castShadow = true;

    const icingMat = new THREE.MeshPhysicalMaterial({
      color: 0xf45fa8,
      roughness: 0.14,
      clearcoat: 0.95,
      clearcoatRoughness: 0.08,
    });
    const icing = new THREE.Mesh(new THREE.TorusGeometry(0.112, 0.049, 24, 48), icingMat);
    icing.position.z = 0.016;
    grp.add(dough, icing);

    // Glossy icing drips around the outer rim
    const dripGeo = new THREE.SphereGeometry(0.017, 12, 10);
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2 + 0.2;
      const r = 0.156 + (i % 2) * 0.008;
      const drip = new THREE.Mesh(dripGeo, icingMat);
      drip.scale.set(0.95, 1.35, 0.85);
      drip.position.set(Math.cos(a) * r, Math.sin(a) * r, 0.004);
      grp.add(drip);
    }

    // 20 colorful 3D sprinkles across top icing surface
    const sprColors = [0x38bdf8, 0xfacc15, 0x4ade80, 0xffffff, 0xfb7185, 0xc084fc];
    const sprGeo = new THREE.CylinderGeometry(0.0045, 0.0045, 0.022, 8);
    for (let i = 0; i < 20; i++) {
      const a = (i / 20) * Math.PI * 2 + (i % 3) * 0.15;
      const r = 0.085 + (i % 4) * 0.015;
      const mat = new THREE.MeshStandardMaterial({
        color: sprColors[i % sprColors.length],
        roughness: 0.25,
      });
      const spr = new THREE.Mesh(sprGeo, mat);
      spr.position.set(Math.cos(a) * r, Math.sin(a) * r, 0.062);
      spr.rotation.set(Math.PI * 0.48 + (i % 3) * 0.18, 0, a + 0.65);
      grp.add(spr);
    }
    return grp;
  }

  _initThree() {
    const c = this._canvas;
    if (!c) return;
    if (this._pub) this._pub.renderer.dispose();
    const pub = createPubRenderer(c, {
      fov: 42,
      camPos: [0, 0.0, 1.95],
      lookAt: [0, 0, 0],
      alpha: true,
    });
    const { scene, keySpot } = pub;
    keySpot.position.set(0.35, 1.6, 2.2);

    // Live 3D Mouth Target Ring synced to cam.mouth & cam.jawOpen
    this._mouthTarget = new THREE.Group();
    this._mouthRingMat = new THREE.MeshStandardMaterial({
      color: 0xf43f5e,
      emissive: 0xe11d48,
      emissiveIntensity: 0.8,
      roughness: 0.2,
      transparent: true,
      opacity: 0.9,
    });
    this._mouthInnerMat = new THREE.MeshStandardMaterial({
      color: 0xfb7185,
      emissive: 0xf43f5e,
      emissiveIntensity: 0.55,
      transparent: true,
      opacity: 0.72,
    });
    const outerRing = new THREE.Mesh(new THREE.TorusGeometry(0.145, 0.011, 12, 36), this._mouthRingMat);
    const innerRing = new THREE.Mesh(new THREE.TorusGeometry(0.082, 0.008, 10, 32), this._mouthInnerMat);
    this._mouthTarget.add(outerRing, innerRing);
    scene.add(this._mouthTarget);

    // Plump 3D Frosted & Sprinkled Donut
    this._donut = this._buildDonutMesh();
    this._donut.position.set(0, -0.34, 1.16);
    scene.add(this._donut);

    this._pub = pub;
    if (!this._raf) {
      let lastT = performance.now();
      const loop = (now) => {
        if (!this._pub) return;
        const dt = Math.min(0.05, (now - lastT) / 1000);
        lastT = now;
        this._animate(dt, now * 0.001);
        this._pub.syncSize();
        this._pub.renderer.render(this._pub.scene, this._pub.camera);
        this._raf = requestAnimationFrame(loop);
      };
      this._raf = requestAnimationFrame(loop);
    }
  }

  _animate(dt, tSec) {
    const cam = this._state?.cam || {};
    const mouthOpen = Number(cam.jawOpen || 0) > 0.28;
    if (this._mouthTarget) {
      const mx = cam.present && cam.mouth ? Number(cam.mouth[0]) : 0.5;
      const my = cam.present && cam.mouth ? Number(cam.mouth[1]) : 0.56;
      const pos = this._normToWorld(mx, my, 0.0);
      this._mouthTarget.position.lerp(pos, Math.min(1, dt * 14));
      this._mouthTarget.visible = !!cam.present || !!cam.jpg;
      const pulse = mouthOpen ? 1.0 + Math.sin(tSec * 8) * 0.08 : 0.78;
      this._mouthTarget.scale.setScalar(pulse);
      if (this._mouthRingMat && this._mouthInnerMat) {
        this._mouthRingMat.color.setHex(mouthOpen ? 0x22c55e : 0xf43f5e);
        this._mouthRingMat.emissive.setHex(mouthOpen ? 0x16a34a : 0xe11d48);
        this._mouthInnerMat.color.setHex(mouthOpen ? 0x86efac : 0xfb7185);
      }
    }

    const aimW = this._normToWorld(this._aim.x, this._aim.y, 0.06);
    if (this._donut) {
      if (this._flight) {
        this._flight.t += dt * 3.4;
        const p = Math.min(1, this._flight.t);
        this._donut.position.set(
          this._flight.sx + (aimW.x - this._flight.sx) * p,
          this._flight.sy + (aimW.y - this._flight.sy) * p + Math.sin(p * Math.PI) * 0.28,
          1.16 * (1 - p) + 0.06 * p
        );
        this._donut.rotation.x += dt * 9.5;
        this._donut.rotation.y += dt * 6.5;
        this._donut.scale.setScalar(1.0 - p * 0.35);
        if (p >= 1) {
          this._flight = null;
          this._donut.scale.setScalar(1.0);
        }
      } else {
        this._donut.scale.setScalar(1.0);
        this._donut.position.set(aimW.x * 0.22, -0.34 + aimW.y * 0.08, 1.16);
        this._donut.rotation.set(-0.55 + Math.sin(tSec * 2) * 0.08, Math.sin(tSec * 1.6) * 0.35, -aimW.x * 0.15);
      }
    }
  }

  _updateHudText(mc, cam) {
    const jawPct = Math.min(100, Math.round((cam.jawOpen || 0) * 100));
    const mouthOpen = (cam.jawOpen || 0) > 0.28;
    const jEl = this._container.querySelector("#mc-jaw");
    if (jEl) {
      jEl.style.color = mouthOpen ? "var(--green)" : "var(--accent-pink)";
      jEl.textContent = `${jawPct}% ${mouthOpen ? "😮 OPEN!" : "😶 CLOSED"}`;
    }
  }

  _renderDOM(mc, cam) {
    const p1 = this.ws.playerName("guest");
    const p2 = this.ws.playerName("host");
    const keepCanvas = this._canvas && this._container.querySelector("#mc-3d-canvas");
    if (!keepCanvas) {
      this._container.innerHTML = `
        <div class="game-panel">
          <div class="hud-row">
            <div><span id="mc-p1n"></span> → <span id="mc-p2n"></span> · Score: <strong id="mc-sc" style="color:var(--green);"></strong></div>
            <div>Combo: <strong id="mc-co" style="color:var(--gold);"></strong></div>
            <div>Left: <strong id="mc-left"></strong></div>
          </div>
          <div class="hud-row">
            <span>Target Mouth: <strong id="mc-jaw"></strong></span>
            <span id="mc-stats"></span>
          </div>
          <div class="canvas-frame" style="background:#091826;position:relative;overflow:hidden;aspect-ratio:16/9;">
            <img id="mc-cam-bg" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none;pointer-events:none;" />
            <div id="mc-cam-wait" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:rgba(148,163,184,0.85);font-size:13px;font-weight:700;pointer-events:none;">Waiting for live webcam feed...</div>
            <canvas id="mc-3d-canvas" width="540" height="304" style="position:relative;z-index:2;width:100%;height:100%;display:block;touch-action:none;background:transparent;"></canvas>
          </div>
          <div id="mc-swipe-pad" style="position:relative;width:100%;height:84px;border-radius:14px;background:linear-gradient(180deg,rgba(244,95,168,0.16),rgba(15,23,42,0.88));border:1.5px dashed rgba(244,114,182,0.5);display:flex;align-items:center;justify-content:center;touch-action:none;user-select:none;-webkit-user-select:none;cursor:grab;">
            <span style="font-weight:800;font-size:13px;color:#fce7f3;letter-spacing:0.05em;pointer-events:none;">🍩 SWIPE UP &amp; AIM FOR MOUTH (LIKE CUP PONG)</span>
          </div>
          <div id="mc-power-wrap" style="position:relative;width:100%;height:26px;border-radius:10px;background:rgba(15,23,42,0.88);border:1px solid rgba(255,255,255,0.18);overflow:hidden;display:flex;align-items:center;justify-content:center;">
            <div id="mc-power-fill" style="position:absolute;left:0;top:0;bottom:0;width:0%;background:linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444);opacity:0.85;transition:width 0.04s;"></div>
            <span id="mc-power-label" style="position:relative;z-index:1;font-size:11px;font-weight:800;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.9);">SWIPE UP LIKE PONG TO AIM &amp; TOSS · 0%</span>
          </div>
          <div id="mc-status" style="color:var(--gold);font-weight:700;text-align:center;font-size:13px;"></div>
          <div style="display:flex;gap:8px;width:100%;">
            <button class="btn-primary" id="mc-reset-btn" style="flex:1;display:none;">PLAY AGAIN</button>
            <button class="btn-cyan" id="mc-restart-btn" style="flex:1;">Reset</button>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#mc-3d-canvas");
      this._initThree();
      this._wireSurface(this._canvas);
      this._wireSurface(this._container.querySelector("#mc-swipe-pad"));
      this._container.querySelector("#mc-reset-btn").addEventListener("click", () => this.ws.action("mouth_catch", "reset"));
      this._container.querySelector("#mc-restart-btn").addEventListener("click", () => this.ws.action("mouth_catch", "reset"));
    }

    this._container.querySelector("#mc-p1n").textContent = p1;
    this._container.querySelector("#mc-p2n").textContent = p2;
    this._container.querySelector("#mc-sc").textContent = String(mc.score);
    this._container.querySelector("#mc-co").textContent = `${mc.combo}x (Best ${mc.bestCombo}x)`;
    this._container.querySelector("#mc-left").textContent = String(mc.throwsLeft);
    this._container.querySelector("#mc-stats").textContent = `Catches ${mc.catches} · Splats ${mc.splats}`;
    const lastOutcome = mc.lastResult?.outcome;
    this._container.querySelector("#mc-status").textContent =
      lastOutcome === "catch"
        ? `🍩 CAUGHT! +${mc.lastResult?.pts || 0} pts!`
        : lastOutcome === "splat"
        ? "💦 SPLAT! Mouth missed or closed!"
        : lastOutcome === "miss"
        ? "💨 Missed wide! Adjust your swipe angle & speed!"
        : "Aim left/right + control swipe speed to land inside the mouth!";
    this._container.querySelector("#mc-reset-btn").style.display = mc.phase === "playing" ? "none" : "block";
    this._updateHudText(mc, cam);
  }

  _wireSurface(el) {
    if (!el) return;
    const pick = (ev) => {
      const rect = el.getBoundingClientRect();
      this._aim.x = Math.max(0.08, Math.min(0.92, (ev.clientX - rect.left) / Math.max(rect.width, 1)));
      this._aim.y = Math.max(0.08, Math.min(0.92, (ev.clientY - rect.top) / Math.max(rect.height, 1)));
    };
    el.addEventListener("pointerdown", (e) => {
      this.sfx.unlock();
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag = { startX: pt.x, startY: pt.y, currX: pt.x, currY: pt.y };
      this._swipeTrail = [pt];
      pick(e);
      this._updatePowerBar(0.08, "PULL & FLICK UP TO TOSS!");
    });
    el.addEventListener("pointermove", (e) => {
      if (!this._drag) return;
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag.currX = pt.x;
      this._drag.currY = pt.y;
      this._swipeTrail.push(pt);
      if (this._swipeTrail.length > 20) this._swipeTrail.shift();
      pick(e);
      const dyUp = Math.max(0, this._drag.startY - pt.y);
      const previewPwr = Math.max(0.08, Math.min(1.0, dyUp / 155));
      this._updatePowerBar(previewPwr);
    });
    const finish = (e) => {
      if (!this._drag) return;
      const end = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._swipeTrail.push(end);
      const trail = this._swipeTrail;
      const rect = el.getBoundingClientRect();
      const hPx = Math.max(rect.height, 180);
      let anchor = trail[0];
      const cutoff = end.t - 85;
      for (let i = trail.length - 1; i >= 0; i--) {
        if (trail[i].t <= cutoff) { anchor = trail[i]; break; }
      }
      const dyUp = trail[0].y - end.y;
      const dtS = Math.max(0.02, (end.t - anchor.t) / 1000);
      const vh = ((anchor.y - end.y) / dtS) / hPx;
      this._drag = null;
      this._swipeTrail = [];

      if (dyUp >= 18 && vh >= 0.42 && this._state?.mouth_catch?.phase === "playing" && !this._flight) {
        const vx = ((end.x - anchor.x) / dtS) / hPx;
        const startOffset = (trail[0].x - rect.left) / Math.max(rect.width, 1) - 0.5;
        const dxNorm = (end.x - trail[0].x) / Math.max(rect.width, 200);
        // Pong-like unassisted aim: start X + drag angle + release swerve + vertical arc height from speed
        const tx = Math.max(0.08, Math.min(0.92, 0.50 + startOffset * 0.55 + dxNorm * 0.95 + vx * 0.16));
        const speedNorm = Math.max(0, Math.min(1, (vh - 0.42) / 3.2));
        const ty = Math.max(0.16, Math.min(0.84, 0.78 - speedNorm * 0.56));
        const power = Math.max(0.32, Math.min(1.0, 0.32 + speedNorm * 0.68));
        this._aim = { x: tx, y: ty };
        this._power = power;
        this._updatePowerBar(power, `TOSSED · ${Math.round(power * 100)}%`);
        this._flight = { sx: this._donut.position.x, sy: this._donut.position.y, t: 0 };
        this.ws.action("mouth_catch", "throw", { x: tx, y: ty, power });
      } else if (dyUp >= 12 && vh < 0.42 && this._state?.mouth_catch?.phase === "playing") {
        this._updatePowerBar(0, "SWIPE UP FASTER TO TOSS!");
      } else {
        this._updatePowerBar(0);
      }
    };
    el.addEventListener("pointerup", finish);
    el.addEventListener("pointercancel", () => {
      this._drag = null;
      this._swipeTrail = [];
      this._updatePowerBar(0);
    });
  }
}
