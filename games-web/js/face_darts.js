// Real Three.js WebGL 3D Face Darts — transparent AR HUD + upgraded suction dart + hex shield over live webcam video
import {
  THREE,
  createSuctionDartMesh,
  createPubRenderer,
} from "./three_helpers.js";

export class FaceDartsView {
  constructor(ws, sfx) {
    this.ws = ws;
    this.sfx = sfx;
    this._aim = { x: 0.5, y: 0.45 };
    this._power = 0.72;
    this._state = null;
    this._canvas = null;
    this._container = null;
    this._lastSig = "";

    this._raf = 0;
    this._pub = null;
    this._targetGroup = null;
    this._outerRing = null;
    this._innerRing = null;
    this._shieldGroup = null;
    this._shieldOuter = null;
    this._shieldInner = null;
    this._handDart = null;
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
    const fd = state.face_darts;
    if (!fd || !this._container) return;

    const p1 = this.ws.playerName("guest");
    const p2 = this.ws.playerName("host");
    const sig = `${fd.phase}|${fd.roundNum}|${fd.dartsLeft}|${fd.scores.guest}|${fd.scores.host}|${fd.roundWins.guest}|${fd.roundWins.host}|${fd.lastResult?.label || ""}|${state.cam?.present}|${state.cam?.openPalms}|${p1}|${p2}`;
    if (sig !== this._lastSig || !this._canvas) {
      if (this._lastSig && fd.lastResult?.outcome === "hit") this.sfx.play("thud");
      else if (this._lastSig && fd.lastResult?.outcome === "blocked") this.sfx.play("clack");
      this._lastSig = sig;
      this._renderDOM(fd, state.cam || {});
    }
    this._syncCamFrame(state.cam);
  }

  _syncCamFrame(cam) {
    if (!this._container) return;
    const img = this._container.querySelector("#fd-cam-bg");
    const wait = this._container.querySelector("#fd-cam-wait");
    if (img && cam?.jpg) {
      img.src = `data:image/jpeg;base64,${cam.jpg}`;
      img.style.display = "block";
      if (wait) wait.style.display = "none";
    }
  }

  _updatePowerBar(pwr, text = "") {
    const fill = this._container?.querySelector("#fd-power-fill");
    const lbl = this._container?.querySelector("#fd-power-label");
    if (!fill || !lbl) return;
    const p = Math.max(0, Math.min(1, pwr));
    const pct = Math.round(p * 100);
    fill.style.width = `${pct}%`;
    fill.style.background =
      p <= 0.5
        ? "linear-gradient(90deg,#22c55e,#eab308)"
        : "linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444)";
    lbl.textContent = text || `SWIPE UP TO THROW DART · ${pct}%`;
  }

  _normToWorld(nx, ny, zPlane = 0) {
    const cam = this._pub?.camera;
    const aspect = cam?.aspect || 16 / 9;
    const dist = (cam?.position?.z ?? 1.95) - zPlane;
    const halfH = Math.tan(((cam?.fov ?? 42) * Math.PI) / 360) * dist;
    const halfW = halfH * aspect;
    return new THREE.Vector3((nx - 0.5) * 2 * halfW, (0.5 - ny) * 2 * halfH, zPlane);
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
    keySpot.position.set(0.4, 1.6, 2.2);

    // 3D Holographic Bullseye Target Reticle over live face
    this._targetGroup = new THREE.Group();
    const outerMat = new THREE.MeshStandardMaterial({
      color: 0xf43f5e,
      emissive: 0xe11d48,
      emissiveIntensity: 0.75,
      roughness: 0.2,
      transparent: true,
      opacity: 0.88,
    });
    const innerMat = new THREE.MeshStandardMaterial({
      color: 0x38bdf8,
      emissive: 0x0284c7,
      emissiveIntensity: 0.75,
      roughness: 0.2,
      transparent: true,
      opacity: 0.9,
    });
    this._outerRing = new THREE.Mesh(new THREE.TorusGeometry(0.24, 0.011, 12, 40), outerMat);
    this._innerRing = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.009, 10, 32), innerMat);
    const barGeo = new THREE.BoxGeometry(0.08, 0.008, 0.008);
    const barMat = new THREE.MeshBasicMaterial({ color: 0xfef08a });
    for (let i = 0; i < 4; i++) {
      const b = new THREE.Mesh(barGeo, barMat);
      const ang = (i * Math.PI) / 2;
      b.rotation.z = ang;
      b.position.set(Math.cos(ang) * 0.175, Math.sin(ang) * 0.175, 0);
      this._targetGroup.add(b);
    }
    this._targetGroup.add(this._outerRing, this._innerRing);
    scene.add(this._targetGroup);

    // 3D Dual-Ring Hex Palm Shield
    this._shieldGroup = new THREE.Group();
    const hexPlate = new THREE.Mesh(
      new THREE.CylinderGeometry(0.32, 0.32, 0.022, 6),
      new THREE.MeshPhysicalMaterial({
        color: 0x38bdf8,
        emissive: 0x0ea5e9,
        emissiveIntensity: 0.48,
        roughness: 0.12,
        transparent: true,
        opacity: 0.34,
      })
    );
    hexPlate.rotation.x = Math.PI / 2;
    this._shieldOuter = new THREE.Mesh(
      new THREE.TorusGeometry(0.34, 0.014, 12, 6),
      new THREE.MeshStandardMaterial({ color: 0x67e8f9, emissive: 0x06b6d4, emissiveIntensity: 0.85 })
    );
    this._shieldInner = new THREE.Mesh(
      new THREE.TorusGeometry(0.21, 0.011, 10, 6),
      new THREE.MeshStandardMaterial({ color: 0xf472b6, emissive: 0xdb2777, emissiveIntensity: 0.8 })
    );
    this._shieldGroup.add(hexPlate, this._shieldOuter, this._shieldInner);
    this._shieldGroup.position.z = 0.24;
    this._shieldGroup.visible = false;
    this._targetGroup.add(this._shieldGroup);

    // Upgraded Multi-Part 3D Suction Cup Dart
    this._handDart = createSuctionDartMesh(0xf45d86);
    this._handDart.scale.setScalar(1.35);
    this._handDart.position.set(0, -0.30, 1.18);
    scene.add(this._handDart);

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
    if (this._targetGroup) {
      const nx = cam.present && cam.nose ? Number(cam.nose[0]) : 0.5;
      const ny = cam.present && cam.nose ? Number(cam.nose[1]) : 0.45;
      const targetPos = this._normToWorld(nx, ny, 0.0);
      this._targetGroup.position.lerp(targetPos, Math.min(1, dt * 14));
      this._targetGroup.visible = !!cam.present || !!cam.jpg;
      if (this._outerRing) this._outerRing.rotation.z = tSec * 0.8;
      if (this._innerRing) this._innerRing.rotation.z = -tSec * 1.4;
      if (this._shieldGroup) {
        this._shieldGroup.visible = !!(cam.openPalms > 0);
        if (this._shieldOuter) this._shieldOuter.rotation.z = tSec * 1.9;
        if (this._shieldInner) this._shieldInner.rotation.z = -tSec * 2.8;
      }
    }

    const aimW = this._normToWorld(this._aim.x, this._aim.y, 0.08);
    if (this._handDart) {
      if (this._flight) {
        this._flight.t += dt * 4.0;
        const p = Math.min(1, this._flight.t);
        this._handDart.position.set(
          this._flight.sx + (aimW.x - this._flight.sx) * p,
          this._flight.sy + (aimW.y - this._flight.sy) * p + Math.sin(p * Math.PI) * 0.16,
          1.18 * (1 - p) + 0.08 * p
        );
        this._handDart.rotation.set(0.18 - p * 0.35, 0, this._handDart.rotation.z + dt * 14);
        if (p >= 1) this._flight = null;
      } else {
        const restX = aimW.x * 0.25;
        const restY = -0.30 + aimW.y * 0.12;
        this._handDart.position.set(restX, restY, 1.18);
        this._handDart.rotation.set(0.16, -aimW.x * 0.22, Math.sin(tSec * 2.2) * 0.05);
      }
    }
  }

  _renderDOM(fd, cam) {
    const p1 = this.ws.playerName("guest");
    const p2 = this.ws.playerName("host");
    const faceStatus = cam.present
      ? (cam.openPalms > 0 ? "✋ PALM SHIELD UP!" : "🎯 Face Tracked Live")
      : "📷 Waiting for face...";
    const keepCanvas = this._canvas && this._container.querySelector("#fd-3d-canvas");

    if (!keepCanvas) {
      this._container.innerHTML = `
        <div class="game-panel">
          <div class="hud-row">
            <div>Round <strong id="fd-rnd"></strong> · Wins <strong id="fd-wins"></strong></div>
            <div>Darts: <strong id="fd-left"></strong></div>
          </div>
          <div class="hud-row">
            <span><span id="fd-p1n"></span> (Offense): <strong id="fd-gs" style="color:var(--accent-pink);"></strong></span>
            <span id="fd-fstat" style="font-size:11px;color:var(--accent-cyan);"></span>
            <span><span id="fd-p2n"></span> (Defense): <strong id="fd-hs" style="color:var(--accent-cyan);"></strong></span>
          </div>
          <div class="canvas-frame" style="background:#081426;position:relative;overflow:hidden;aspect-ratio:16/9;">
            <img id="fd-cam-bg" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none;pointer-events:none;" />
            <div id="fd-cam-wait" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:rgba(148,163,184,0.85);font-size:13px;font-weight:700;pointer-events:none;">Waiting for live webcam feed...</div>
            <canvas id="fd-3d-canvas" width="540" height="304" style="position:relative;z-index:2;width:100%;height:100%;display:block;touch-action:none;background:transparent;"></canvas>
          </div>
          <div id="fd-swipe-pad" style="position:relative;width:100%;height:78px;border-radius:14px;background:linear-gradient(180deg,rgba(56,189,248,0.14),rgba(15,23,42,0.88));border:1.5px dashed rgba(103,232,249,0.45);display:flex;align-items:center;justify-content:center;touch-action:none;user-select:none;-webkit-user-select:none;cursor:grab;">
            <span style="font-weight:800;font-size:13px;color:#e0f2fe;letter-spacing:0.06em;pointer-events:none;">🎯 SWIPE UP HERE OR ON CAM TO FLICK DART</span>
          </div>
          <div id="fd-power-wrap" style="position:relative;width:100%;height:26px;border-radius:10px;background:rgba(15,23,42,0.88);border:1px solid rgba(255,255,255,0.18);overflow:hidden;display:flex;align-items:center;justify-content:center;">
            <div id="fd-power-fill" style="position:absolute;left:0;top:0;bottom:0;width:0%;background:linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444);opacity:0.85;transition:width 0.04s;"></div>
            <span id="fd-power-label" style="position:relative;z-index:1;font-size:11px;font-weight:800;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.9);">SWIPE UP TO THROW DART · 0%</span>
          </div>
          <div id="fd-lbl" class="hud-row" style="justify-content:center;color:var(--gold);font-weight:700;"></div>
          <div style="display:flex;gap:8px;width:100%;">
            <button class="btn-primary" id="fd-next-btn" style="flex:1;display:none;">NEXT ROUND</button>
            <button class="btn-cyan" id="fd-reset-btn" style="flex:1;">Reset</button>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#fd-3d-canvas");
      this._initThree();
      this._wireSurface(this._canvas);
      this._wireSurface(this._container.querySelector("#fd-swipe-pad"));
      this._container.querySelector("#fd-next-btn").addEventListener("click", () => this.ws.action("face_darts", "next"));
      this._container.querySelector("#fd-reset-btn").addEventListener("click", () => this.ws.action("face_darts", "reset"));
    }

    this._container.querySelector("#fd-rnd").textContent = `${fd.roundNum}/${fd.bestOf}`;
    this._container.querySelector("#fd-wins").textContent = `${fd.roundWins.guest} - ${fd.roundWins.host}`;
    this._container.querySelector("#fd-left").textContent = "🎯".repeat(fd.dartsLeft) || "0";
    this._container.querySelector("#fd-p1n").textContent = p1;
    this._container.querySelector("#fd-p2n").textContent = p2;
    this._container.querySelector("#fd-gs").textContent = String(fd.scores.guest);
    this._container.querySelector("#fd-hs").textContent = String(fd.scores.host);
    this._container.querySelector("#fd-fstat").textContent = faceStatus;
    this._container.querySelector("#fd-lbl").textContent = fd.lastResult?.label || "Swipe UP smoothly toward nose/cheeks to throw!";
    const nextBtn = this._container.querySelector("#fd-next-btn");
    nextBtn.style.display = fd.phase !== "playing" ? "block" : "none";
    nextBtn.textContent = fd.phase === "match_over" ? "REMATCH" : "NEXT ROUND";
  }

  _wireSurface(el) {
    if (!el) return;
    const pick = (ev) => {
      const rect = el.getBoundingClientRect();
      this._aim.x = Math.max(0.06, Math.min(0.94, (ev.clientX - rect.left) / Math.max(rect.width, 1)));
      this._aim.y = Math.max(0.06, Math.min(0.94, (ev.clientY - rect.top) / Math.max(rect.height, 1)));
    };
    el.addEventListener("pointerdown", (e) => {
      this.sfx.unlock();
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag = { startX: pt.x, startY: pt.y, currX: pt.x, currY: pt.y };
      this._swipeTrail = [pt];
      pick(e);
      this._updatePowerBar(0.1, "AIMING · SWIPE UP!");
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
      const previewPwr = Math.max(0.1, Math.min(1.0, dyUp / 160));
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
      if (dyUp >= 16 && vh >= 0.42 && this._state?.face_darts?.phase === "playing" && !this._flight) {
        const vx = ((end.x - anchor.x) / dtS) / hPx;
        const startOffset = (trail[0].x - rect.left) / Math.max(rect.width, 1) - 0.5;
        const dxNorm = (end.x - trail[0].x) / Math.max(rect.width, 200);
        const fx = Math.max(0.08, Math.min(0.92, 0.50 + startOffset * 0.55 + dxNorm * 0.90 + vx * 0.14));
        const speedNorm = Math.max(0, Math.min(1, (vh - 0.42) / 3.4));
        const fy = Math.max(0.18, Math.min(0.82, 0.74 - speedNorm * 0.54));
        this._aim = { x: fx, y: fy };
        this._power = Math.max(0.35, Math.min(1.0, 0.35 + speedNorm * 0.65));
        this._updatePowerBar(this._power, `THROWN · ${Math.round(this._power * 100)}%`);
        this._flight = { sx: this._handDart.position.x, sy: this._handDart.position.y, t: 0 };
        this.ws.action("face_darts", "throw", { x: this._aim.x, y: this._aim.y, power: this._power });
      } else if (dyUp >= 12 && vh < 0.42 && this._state?.face_darts?.phase === "playing") {
        this._updatePowerBar(0, "SWIPE UP FASTER!");
        const lbl = this._container?.querySelector("#fd-lbl");
        if (lbl) lbl.textContent = "Flick upward faster!";
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
