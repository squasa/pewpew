// Real Three.js WebGL 3D Face Darts — holographic 3D target head synced live to webcam + palm hex shield
import {
  THREE,
  createDartMesh,
  createPubRenderer,
} from "./three_helpers.js";

export class FaceDartsView {
  constructor(ws, sfx) {
    this.ws = ws;
    this.sfx = sfx;
    this._aim = { x: 0.5, y: 0.45 };
    this._power = 0.85;
    this._state = null;
    this._canvas = null;
    this._container = null;
    this._lastSig = "";

    this._raf = 0;
    this._pub = null;
    this._headGroup = null;
    this._shieldMesh = null;
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

    const sig = `${fd.phase}|${fd.roundNum}|${fd.dartsLeft}|${fd.scores.guest}|${fd.scores.host}|${fd.roundWins.guest}|${fd.roundWins.host}|${fd.lastResult?.label || ""}|${state.cam?.present}|${state.cam?.openPalms}`;
    if (sig !== this._lastSig || !this._canvas) {
      if (this._lastSig && fd.lastResult?.outcome === "hit") this.sfx.play("thud");
      else if (this._lastSig && fd.lastResult?.outcome === "blocked") this.sfx.play("clack");
      this._lastSig = sig;
      this._renderDOM(fd, state.cam || {});
    }
  }

  _initThree() {
    const c = this._canvas;
    if (!c) return;
    if (this._pub) this._pub.renderer.dispose();
    const pub = createPubRenderer(c, {
      fov: 42,
      camPos: [0, 0.08, 1.95],
      lookAt: [0, 0, 0],
    });
    const { scene, keySpot } = pub;
    keySpot.position.set(0.4, 1.6, 2.1);

    // Stage floor grid
    const grid = new THREE.GridHelper(3.4, 14, 0x3b82f6, 0x162238);
    grid.position.y = -0.62;
    scene.add(grid);

    // 3D Sculpted Hologram Target Bust (tracks cam.nose live!)
    this._headGroup = new THREE.Group();
    const skinMat = new THREE.MeshPhysicalMaterial({ color: 0xf4c7b0, roughness: 0.42, clearcoat: 0.25 });
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.24, 28, 22), skinMat);
    head.scale.set(0.88, 1.08, 0.94);
    head.castShadow = true;
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.036, 0.085, 14), skinMat);
    nose.rotation.x = Math.PI / 2;
    nose.position.set(0, 0.0, 0.23);
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.15 });
    const eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.028, 12, 12), eyeMat);
    eyeL.position.set(-0.075, 0.055, 0.195);
    const eyeR = eyeL.clone();
    eyeR.position.x = 0.075;
    this._headGroup.add(head, nose, eyeL, eyeR);
    scene.add(this._headGroup);

    // 3D Open Palm Hex Shield popup
    this._shieldMesh = new THREE.Mesh(
      new THREE.CylinderGeometry(0.32, 0.32, 0.03, 6),
      new THREE.MeshPhysicalMaterial({
        color: 0x38bdf8,
        emissive: 0x0284c7,
        emissiveIntensity: 0.55,
        roughness: 0.1,
        transparent: true,
        opacity: 0.65,
      })
    );
    this._shieldMesh.rotation.x = Math.PI / 2;
    this._shieldMesh.position.z = 0.34;
    this._shieldMesh.visible = false;
    this._headGroup.add(this._shieldMesh);

    // 3D Foreground Suction Dart (no guide rings)
    this._handDart = createDartMesh(0xf45d86);
    this._handDart.position.set(0, -0.35, 1.25);
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
    if (this._headGroup) {
      const nx = cam.present && cam.nose ? (cam.nose[0] - 0.5) * 1.45 : Math.sin(tSec * 1.2) * 0.12;
      const ny = cam.present && cam.nose ? (0.5 - cam.nose[1]) * 0.92 : Math.cos(tSec * 1.6) * 0.08;
      this._headGroup.position.lerp(new THREE.Vector3(nx, ny, 0), Math.min(1, dt * 12));
      this._headGroup.rotation.y = nx * 0.25;
      if (this._shieldMesh) {
        this._shieldMesh.visible = !!(cam.openPalms > 0);
        this._shieldMesh.rotation.y = tSec * 2.2;
      }
    }
    const ax = (this._aim.x - 0.5) * 1.90;
    const ay = (0.5 - this._aim.y) * 1.28;
    if (this._handDart) {
      if (this._flight) {
        this._flight.t += dt * 4.2;
        const p = Math.min(1, this._flight.t);
        this._handDart.position.set(
          this._flight.sx + (ax - this._flight.sx) * p,
          this._flight.sy + (ay - this._flight.sy) * p + Math.sin(p * Math.PI) * 0.14,
          1.25 * (1 - p) + 0.24 * p
        );
        this._handDart.rotation.z += dt * 14;
        if (p >= 1) this._flight = null;
      } else {
        this._handDart.position.set(ax * 0.35, -0.34 + ay * 0.2, 1.25);
        this._handDart.rotation.set(0.14, -ax * 0.24, 0);
      }
    }
  }

  _renderDOM(fd, cam) {
    const faceStatus = cam.present
      ? (cam.openPalms > 0 ? "✋ PALM SHIELD UP!" : "🎯 Face Tracked 3D")
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
            <span>Her (Offense): <strong id="fd-gs" style="color:var(--accent-pink);"></strong></span>
            <span id="fd-fstat" style="font-size:11px;color:var(--accent-cyan);"></span>
            <span>Him (Defense): <strong id="fd-hs" style="color:var(--accent-cyan);"></strong></span>
          </div>
          <div class="canvas-frame" style="background:#081426;">
            <canvas id="fd-3d-canvas" width="520" height="320" style="width:100%;height:320px;display:block;touch-action:none;"></canvas>
          </div>
          <div id="fd-lbl" class="hud-row" style="justify-content:center;color:var(--gold);font-weight:700;"></div>
          <div style="display:flex;gap:8px;width:100%;">
            <button class="btn-cyan" id="fd-fire-btn" style="flex:1;">Tap Throw 🎯</button>
            <button class="btn-primary" id="fd-next-btn" style="flex:1;display:none;">NEXT ROUND</button>
            <button class="btn-cyan" id="fd-reset-btn">Reset</button>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#fd-3d-canvas");
      this._initThree();
      this._wireCanvas();
      this._container.querySelector("#fd-fire-btn").addEventListener("click", () => {
        this.sfx.unlock();
        this._flight = { sx: this._handDart.position.x, sy: this._handDart.position.y, t: 0 };
        this.ws.action("face_darts", "throw", { x: this._aim.x, y: this._aim.y, power: this._power });
      });
      this._container.querySelector("#fd-next-btn").addEventListener("click", () => this.ws.action("face_darts", "next"));
      this._container.querySelector("#fd-reset-btn").addEventListener("click", () => this.ws.action("face_darts", "reset"));
    }

    this._container.querySelector("#fd-rnd").textContent = `${fd.roundNum}/${fd.bestOf}`;
    this._container.querySelector("#fd-wins").textContent = `${fd.roundWins.guest} - ${fd.roundWins.host}`;
    this._container.querySelector("#fd-left").textContent = "🎯".repeat(fd.dartsLeft) || "0";
    this._container.querySelector("#fd-gs").textContent = String(fd.scores.guest);
    this._container.querySelector("#fd-hs").textContent = String(fd.scores.host);
    this._container.querySelector("#fd-fstat").textContent = faceStatus;
    this._container.querySelector("#fd-lbl").textContent = fd.lastResult?.label || "Flick UP fast to throw — gentle drag aims!";
    this._container.querySelector("#fd-fire-btn").style.display = fd.phase === "playing" ? "block" : "none";
    const nextBtn = this._container.querySelector("#fd-next-btn");
    nextBtn.style.display = fd.phase !== "playing" ? "block" : "none";
    nextBtn.textContent = fd.phase === "match_over" ? "REMATCH" : "NEXT ROUND";
  }

  _wireCanvas() {
    const c = this._canvas;
    if (!c) return;
    const pick = (ev) => {
      const rect = c.getBoundingClientRect();
      this._aim.x = Math.max(0.06, Math.min(0.94, (ev.clientX - rect.left) / rect.width));
      this._aim.y = Math.max(0.06, Math.min(0.94, (ev.clientY - rect.top) / rect.height));
    };
    c.addEventListener("pointerdown", (e) => {
      this.sfx.unlock();
      try { c.setPointerCapture(e.pointerId); } catch (_) {}
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag = { startX: pt.x, startY: pt.y, currX: pt.x, currY: pt.y };
      this._swipeTrail = [pt];
      pick(e);
    });
    c.addEventListener("pointermove", (e) => {
      if (!this._drag) return;
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag.currX = pt.x;
      this._drag.currY = pt.y;
      this._swipeTrail.push(pt);
      if (this._swipeTrail.length > 20) this._swipeTrail.shift();
      pick(e);
    });
    const finish = (e) => {
      if (!this._drag) return;
      const end = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._swipeTrail.push(end);
      const trail = this._swipeTrail;
      const rect = c.getBoundingClientRect();
      const hPx = Math.max(rect.height, 240);
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
      // Crisp GamePigeon upward flick fires immediately; gentle drag calibrates aim with hint
      if (dyUp >= 16 && vh >= 0.45 && this._state?.face_darts?.phase === "playing" && !this._flight) {
        const vx = ((end.x - anchor.x) / dtS) / hPx;
        const startOffset = (trail[0].x - rect.left) / Math.max(rect.width, 1) - 0.5;
        const dxNorm = (end.x - trail[0].x) / Math.max(rect.width, 200);
        const fx = Math.max(0.08, Math.min(0.92, 0.50 + startOffset * 0.55 + dxNorm * 0.90 + vx * 0.14));
        const speedNorm = Math.max(0, Math.min(1, (vh - 0.45) / 3.6));
        const fy = Math.max(0.24, Math.min(0.76, 0.68 - speedNorm * 0.40));
        this._aim = { x: fx, y: fy };
        this._power = Math.max(0.45, Math.min(1.0, 0.45 + speedNorm * 0.55));
        this._flight = { sx: this._handDart.position.x, sy: this._handDart.position.y, t: 0 };
        this.ws.action("face_darts", "throw", { x: this._aim.x, y: this._aim.y, power: this._power });
      } else if (dyUp >= 14 && vh < 0.45 && this._state?.face_darts?.phase === "playing") {
        const lbl = this._container?.querySelector("#fd-lbl");
        if (lbl) lbl.textContent = "Flick upward faster!";
      }
    };
    c.addEventListener("pointerup", finish);
    c.addEventListener("pointercancel", () => { this._drag = null; this._swipeTrail = []; });
  }
}
