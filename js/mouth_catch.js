// Real Three.js WebGL 3D Mouth Catch — animated articulated 3D jaw synced live to webcam + frosted donut toss
import { THREE, createPubRenderer } from "./three_helpers.js";

export class MouthCatchView {
  constructor(ws, sfx) {
    this.ws = ws;
    this.sfx = sfx;
    this._aim = { x: 0.5, y: 0.55 };
    this._state = null;
    this._canvas = null;
    this._container = null;
    this._lastSig = "";

    this._raf = 0;
    this._pub = null;
    this._headGroup = null;
    this._jawGroup = null;
    this._donut = null;
    this._flight = null;
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

    const sig = `${mc.phase}|${mc.throwsLeft}|${mc.score}|${mc.combo}|${mc.lastResult?.outcome || ""}`;
    if (sig !== this._lastSig || !this._canvas) {
      if (this._lastSig && mc.lastResult?.outcome === "catch") this.sfx.play("win");
      else if (this._lastSig && mc.lastResult?.outcome === "splat") this.sfx.play("splash");
      this._lastSig = sig;
      this._renderDOM(mc, state.cam || {});
    } else {
      this._updateHudText(mc, state.cam || {});
    }
  }

  _initThree() {
    const c = this._canvas;
    if (!c) return;
    if (this._pub) this._pub.renderer.dispose();
    const pub = createPubRenderer(c, {
      fov: 42,
      camPos: [0, 0.10, 1.95],
      lookAt: [0, 0, 0],
    });
    const { scene, keySpot } = pub;
    keySpot.position.set(0.3, 1.6, 2.0);

    // 3D Head with articulated lower jaw synced live to cam.jawOpen!
    this._headGroup = new THREE.Group();
    const skinMat = new THREE.MeshPhysicalMaterial({ color: 0xf2c2a8, roughness: 0.40 });
    const upperHead = new THREE.Mesh(new THREE.SphereGeometry(0.24, 28, 18, 0, Math.PI * 2, 0, Math.PI * 0.65), skinMat);
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0x11151e, roughness: 0.15 });
    const eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.028, 12, 12), eyeMat);
    eyeL.position.set(-0.078, 0.07, 0.205);
    const eyeR = eyeL.clone();
    eyeR.position.x = 0.078;
    const innerMouth = new THREE.Mesh(
      new THREE.SphereGeometry(0.14, 20, 16),
      new THREE.MeshBasicMaterial({ color: 0x2b0a14 })
    );
    innerMouth.position.set(0, -0.04, 0.08);
    this._headGroup.add(upperHead, eyeL, eyeR, innerMouth);

    this._jawGroup = new THREE.Group();
    this._jawGroup.position.set(0, -0.02, 0.04);
    const jawMesh = new THREE.Mesh(new THREE.SphereGeometry(0.21, 24, 16, 0, Math.PI * 2, Math.PI * 0.45, Math.PI * 0.5), skinMat);
    jawMesh.position.set(0, -0.02, -0.02);
    this._jawGroup.add(jawMesh);
    this._headGroup.add(this._jawGroup);
    scene.add(this._headGroup);

    // 3D Frosted Sprinkled Donut!
    this._donut = new THREE.Group();
    const dough = new THREE.Mesh(
      new THREE.TorusGeometry(0.055, 0.024, 16, 28),
      new THREE.MeshStandardMaterial({ color: 0xd99b56, roughness: 0.55 })
    );
    const icing = new THREE.Mesh(
      new THREE.TorusGeometry(0.055, 0.022, 16, 28),
      new THREE.MeshPhysicalMaterial({ color: 0xf460a6, roughness: 0.2, clearcoat: 0.8 })
    );
    icing.position.z = 0.008;
    this._donut.add(dough, icing);
    this._donut.position.set(0, -0.34, 1.25);
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
    if (this._headGroup) {
      const mx = cam.present && cam.mouth ? (cam.mouth[0] - 0.5) * 1.45 : Math.sin(tSec * 1.3) * 0.14;
      const my = cam.present && cam.mouth ? (0.5 - cam.mouth[1]) * 0.92 : Math.cos(tSec * 1.5) * 0.06;
      this._headGroup.position.lerp(new THREE.Vector3(mx, my + 0.06, 0), Math.min(1, dt * 12));
      if (this._jawGroup) {
        const jaw = Math.min(1, Math.max(0, (cam.jawOpen || 0.25) * 1.4));
        this._jawGroup.rotation.x = 0.12 + jaw * 0.45;
      }
    }
    const ax = (this._aim.x - 0.5) * 1.45;
    const ay = (0.5 - this._aim.y) * 0.92;

    if (this._donut) {
      if (this._flight) {
        this._flight.t += dt * 3.8;
        const p = Math.min(1, this._flight.t);
        this._donut.position.set(
          ax * p,
          -0.34 * (1 - p) + ay * p + Math.sin(p * Math.PI) * 0.26,
          1.25 * (1 - p) + 0.18 * p
        );
        this._donut.rotation.x += dt * 10;
        this._donut.rotation.y += dt * 7;
        if (p >= 1) this._flight = null;
      } else {
        this._donut.position.set(ax * 0.35, -0.34, 1.25);
        this._donut.rotation.set(0.35, Math.sin(tSec * 2) * 0.4, 0);
      }
    }
  }

  _updateHudText(mc, cam) {
    const jawPct = Math.min(100, Math.round((cam.jawOpen || 0) * 100));
    const mouthOpen = (cam.jawOpen || 0) > 0.28;
    const jEl = this._container.querySelector("#mc-jaw");
    if (jEl) {
      jEl.style.color = mouthOpen ? "var(--green)" : "var(--accent-pink)";
      jEl.textContent = `${jawPct}% ${mouthOpen ? "😮 READY!" : "😶 CLOSED"}`;
    }
  }

  _renderDOM(mc, cam) {
    const keepCanvas = this._canvas && this._container.querySelector("#mc-3d-canvas");
    if (!keepCanvas) {
      this._container.innerHTML = `
        <div class="game-panel">
          <div class="hud-row">
            <div>Co-op Score: <strong id="mc-sc" style="color:var(--green);"></strong></div>
            <div>Combo: <strong id="mc-co" style="color:var(--gold);"></strong></div>
            <div>Left: <strong id="mc-left"></strong></div>
          </div>
          <div class="hud-row">
            <span>Mouth Open: <strong id="mc-jaw"></strong></span>
            <span id="mc-stats"></span>
          </div>
          <div class="canvas-frame" style="background:#091826;">
            <canvas id="mc-3d-canvas" width="520" height="320" style="width:100%;height:320px;display:block;touch-action:none;"></canvas>
          </div>
          <div style="display:flex;gap:8px;width:100%;">
            <button class="btn-primary" id="mc-toss-btn" style="flex:1;">TOSS SNACK 🍩</button>
            <button class="btn-primary" id="mc-reset-btn" style="flex:1;display:none;">PLAY AGAIN</button>
            <button class="btn-cyan" id="mc-restart-btn">Reset</button>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#mc-3d-canvas");
      this._initThree();
      const pick = (e) => {
        const rect = this._canvas.getBoundingClientRect();
        this._aim.x = Math.max(0.08, Math.min(0.92, (e.clientX - rect.left) / rect.width));
        this._aim.y = Math.max(0.08, Math.min(0.92, (e.clientY - rect.top) / rect.height));
      };
      this._canvas.addEventListener("pointerdown", pick);
      this._canvas.addEventListener("pointermove", (e) => { if (e.buttons) pick(e); });
      this._container.querySelector("#mc-toss-btn").addEventListener("click", () => {
        this.sfx.unlock();
        this._flight = { t: 0 };
        this.ws.action("mouth_catch", "throw", { x: this._aim.x, y: this._aim.y, power: 0.78 });
      });
      this._container.querySelector("#mc-reset-btn").addEventListener("click", () => this.ws.action("mouth_catch", "reset"));
      this._container.querySelector("#mc-restart-btn").addEventListener("click", () => this.ws.action("mouth_catch", "reset"));
    }

    this._container.querySelector("#mc-sc").textContent = String(mc.score);
    this._container.querySelector("#mc-co").textContent = `${mc.combo}x (Best ${mc.bestCombo}x)`;
    this._container.querySelector("#mc-left").textContent = String(mc.throwsLeft);
    this._container.querySelector("#mc-stats").textContent = `Catches ${mc.catches} · Splats ${mc.splats}`;
    this._container.querySelector("#mc-toss-btn").style.display = mc.phase === "playing" ? "block" : "none";
    this._container.querySelector("#mc-reset-btn").style.display = mc.phase === "playing" ? "none" : "block";
    this._updateHudText(mc, cam);
  }
}
