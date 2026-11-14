// Real Three.js WebGL 3D Classic Darts 301 with upward swipe flick, parabolic flight & camera zoom impact
import {
  THREE,
  createDartMesh,
  createPubRenderer,
  makeDartboardTexture,
  makeWoodTexture,
} from "./three_helpers.js";

const BOARD_RADIUS_WORLD = 0.56; // 3D outer double wire radius

export class ClassicDartsView {
  constructor(ws, sfx, myRole = () => "guest") {
    this.ws = ws;
    this.sfx = sfx;
    this.myRole = myRole;
    this._aim = { x: 0.0, y: -0.59 };
    this._drag = null;
    this._swipeTrail = [];
    this._flight = null;
    this._cameraZoom = 1.0;
    this._zoomTarget = { x: 0, y: 0 };
    this._boardShake = 0.0;
    this._boardGroup = null;
    this._stuckGroup = null;
    this._heldDart = null;
    this._cd = null;
    this._container = null;
    this._canvas = null;
    this._lastSig = "";
    this._lastThrowSig = "";
    this._liveAim = null;
    this._lastAimSend = 0;
    this._raf = 0;
    this._pub = null;
  }

  mount(container, state) {
    this._container = container;
    this._lastSig = "";
    this._lastThrowSig = "";
    this._flight = null;
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

  _isMyTurn(cd) {
    return !!cd && cd.phase !== "finished" && cd.turn === this.myRole();
  }

  update(state) {
    const cd = state.classic_darts;
    if (!cd || !this._container) return;
    this._liveAim = state.liveAim && state.liveAim.game === "classic_darts" ? state.liveAim : null;

    const throwSig = `${cd.lastThrow?.label || ""}|${cd.lastThrow?.x || 0}|${cd.lastThrow?.y || 0}|${cd.dartsLeft}`;
    if (this._lastSig && throwSig !== this._lastThrowSig && cd.lastThrow?.label) {
      this.sfx.play("thud");
      this._cameraZoom = 1.28;
      this._zoomTarget = {
        x: (cd.lastThrow.x || 0) * BOARD_RADIUS_WORLD,
        y: -(cd.lastThrow.y || 0) * BOARD_RADIUS_WORLD,
      };
      this._boardShake = 1.0;
    }
    this._lastThrowSig = throwSig;
    if (this._cd && this._cd.phase !== "finished" && cd.phase === "finished") {
      this.sfx.play("win");
    }
    this._cd = cd;

    const sig = `${cd.phase}|${cd.turn}|${cd.dartsLeft}|${cd.scores.guest}|${cd.scores.host}|${cd.doubleOut}|${cd.status}|${cd.winner}|${this.myRole()}|${cd.hitsThisTurn?.length || 0}`;
    if (sig !== this._lastSig || !this._canvas) {
      this._lastSig = sig;
      this._renderDOM(cd);
    } else if (!this._isMyTurn(cd) && this._liveAim) {
      const opp = this.myRole() === "host" ? this.ws.playerName("guest").toUpperCase() : this.ws.playerName("host").toUpperCase();
      this._updatePowerBar(Number(this._liveAim.power || 0), `${opp} AIMING`);
    }
    this._syncStuckDarts(cd);
  }

  _updatePowerBar(pwr, labelPrefix = "FLICK") {
    const fill = this._container?.querySelector("#cd-power-fill");
    const lbl = this._container?.querySelector("#cd-power-label");
    if (!fill || !lbl) return;
    const p = Math.max(0, Math.min(1, pwr));
    const pct = Math.round(p * 100);
    fill.style.width = `${pct}%`;
    fill.style.background = p <= 0.5 ? "linear-gradient(90deg,#22c55e,#eab308)" : "linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444)";
    lbl.textContent = p > 0.02 ? `${labelPrefix} ${pct}%` : "SWIPE UP TO THROW DART · 0%";
  }

  _sendAimThrottled(x, y, power) {
    const now = performance.now();
    if (now - this._lastAimSend < 45) return;
    this._lastAimSend = now;
    this.ws.action("classic_darts", "aim", { x, y, power });
  }

  _initThree() {
    const c = this._canvas;
    if (!c) return;
    if (this._pub) this._pub.renderer.dispose();
    const pub = createPubRenderer(c, {
      fov: 42,
      camPos: [0, 0.02, 2.05],
      lookAt: [0, 0, 0],
    });
    const { scene, keySpot } = pub;
    keySpot.position.set(0.35, 1.4, 2.2);
    keySpot.target.position.set(0, 0, 0);

    // Oak pub wall surround
    const oakMat = new THREE.MeshStandardMaterial({
      map: makeWoodTexture("#442412", "#261207"),
      roughness: 0.45,
      metalness: 0.04,
    });
    const wall = new THREE.Mesh(new THREE.BoxGeometry(3.2, 2.4, 0.08), oakMat);
    wall.position.z = -0.10;
    wall.receiveShadow = true;
    scene.add(wall);

    // Backboard leather surround & 3D sisal board
    this._boardGroup = new THREE.Group();
    const cabinet = new THREE.Mesh(
      new THREE.CylinderGeometry(0.70, 0.72, 0.06, 48),
      new THREE.MeshStandardMaterial({ color: 0x16171c, roughness: 0.55 })
    );
    cabinet.rotation.x = Math.PI / 2;
    cabinet.position.z = -0.04;
    cabinet.castShadow = true;
    cabinet.receiveShadow = true;
    this._boardGroup.add(cabinet);

    const sisalTex = makeDartboardTexture();
    const boardFace = new THREE.Mesh(
      new THREE.CylinderGeometry(BOARD_RADIUS_WORLD, BOARD_RADIUS_WORLD, 0.042, 64),
      [
        new THREE.MeshStandardMaterial({ color: 0x111216, roughness: 0.7 }),
        new THREE.MeshStandardMaterial({ map: sisalTex, roughness: 0.85, metalness: 0.05 }),
        new THREE.MeshStandardMaterial({ color: 0x111216, roughness: 0.7 }),
      ]
    );
    boardFace.rotation.x = Math.PI / 2;
    boardFace.position.z = -0.01;
    boardFace.receiveShadow = true;
    this._boardGroup.add(boardFace);

    // Brass number ring wire
    const outerWire = new THREE.Mesh(
      new THREE.TorusGeometry(BOARD_RADIUS_WORLD * 0.99, 0.006, 10, 64),
      new THREE.MeshStandardMaterial({ color: 0xd0d6df, metalness: 0.88, roughness: 0.2 })
    );
    outerWire.position.z = 0.013;
    this._boardGroup.add(outerWire);

    this._stuckGroup = new THREE.Group();
    this._boardGroup.add(this._stuckGroup);
    scene.add(this._boardGroup);

    // Foreground 3D Dart in hand (no guide circles)
    this._heldDart = createDartMesh(0xf45d86);
    this._heldDart.position.set(0, -0.34, 1.25);
    scene.add(this._heldDart);

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

  _syncStuckDarts(cd) {
    if (!this._stuckGroup) return;
    while (this._stuckGroup.children.length) {
      this._stuckGroup.remove(this._stuckGroup.children[0]);
    }
    const col = cd.turn === "guest" ? 0xf45d86 : 0x5be3ff;
    for (const h of cd.hitsThisTurn || []) {
      const dm = createDartMesh(col);
      dm.position.set(h.x * BOARD_RADIUS_WORLD, -h.y * BOARD_RADIUS_WORLD, 0.025);
      dm.rotation.x = 0.08;
      dm.rotation.y = (h.x || 0) * -0.14;
      this._stuckGroup.add(dm);
    }
  }

  _animate(dt, tSec) {
    if (!this._pub) return;
    if (this._cameraZoom > 1.002) {
      this._cameraZoom += (1.0 - this._cameraZoom) * Math.min(1, dt * 3.8);
    } else {
      this._cameraZoom = 1.0;
    }
    const zPos = 2.05 / this._cameraZoom;
    const tx = this._zoomTarget.x * (this._cameraZoom - 1.0) * 1.4;
    const ty = this._zoomTarget.y * (this._cameraZoom - 1.0) * 1.4;
    this._pub.camera.position.set(tx, 0.02 + ty, zPos);
    this._pub.camera.lookAt(tx * 0.6, ty * 0.6, 0);

    if (this._boardShake > 0.01 && this._boardGroup) {
      this._boardShake = Math.max(0, this._boardShake - dt * 5.2);
      this._boardGroup.position.x = Math.sin(tSec * 70) * this._boardShake * 0.012;
      this._boardGroup.position.y = Math.cos(tSec * 62) * this._boardShake * 0.012;
    } else if (this._boardGroup) {
      this._boardGroup.position.set(0, 0, 0);
    }

    const bx = this._aim.x * BOARD_RADIUS_WORLD + Math.sin(tSec * 2.6) * 0.012;
    const by = -this._aim.y * BOARD_RADIUS_WORLD + Math.cos(tSec * 2.1) * 0.014;

    if (this._heldDart) {
      if (this._flight) {
        this._flight.t += dt * 4.4;
        const p = Math.min(1, this._flight.t);
        const ease = 1 - Math.pow(1 - p, 2);
        const fx = this._flight.sx + (this._flight.ex - this._flight.sx) * ease;
        const fy = this._flight.sy + (this._flight.ey - this._flight.sy) * ease + Math.sin(p * Math.PI) * 0.22;
        const fz = 1.25 * (1 - ease) + 0.025 * ease;
        this._heldDart.position.set(fx, fy, fz);
        this._heldDart.rotation.x = 0.35 * (1 - p) + 0.08 * p;
        this._heldDart.rotation.z += dt * 16;
        if (p >= 1) this._flight = null;
      } else {
        const pull = this._drag ? Math.max(-0.15, Math.min(0.18, (this._drag.currY - this._drag.startY) * 0.0014)) : 0;
        this._heldDart.position.set(bx * 0.36, -0.34 - pull * 0.5, 1.25 + pull);
        this._heldDart.rotation.set(0.18, -bx * 0.22, 0);
      }
    }
  }

  _computeFlick(allowSoft = false) {
    const trail = this._swipeTrail;
    if (trail.length < 2) return null;
    const end = trail[trail.length - 1];
    const cutoff = end.t - 95;
    let anchor = trail[0];
    for (let i = trail.length - 1; i >= 0; i--) {
      if (trail[i].t <= cutoff) {
        anchor = trail[i];
        break;
      }
    }
    const dyUp = trail[0].y - end.y;
    if (!allowSoft && dyUp < 14) return null;
    const rect = this._canvas.getBoundingClientRect();
    const hPx = Math.max(rect.height, 260);
    const dtS = Math.max(0.025, (end.t - anchor.t) / 1000);
    const vyUp = Math.max(20, (anchor.y - end.y) / dtS);
    const vh = vyUp / hPx;
    const vx = (end.x - anchor.x) / dtS;
    const startOffset = (trail[0].x - rect.left) / Math.max(rect.width, 1) - 0.5;
    const dxNorm = (end.x - trail[0].x) / Math.max(rect.width, 200);
    const x = Math.max(-1.08, Math.min(1.08, startOffset * 0.72 + dxNorm * 1.55 + (vx / hPx) * 0.25));
    const speedNorm = Math.max(0.05, Math.min(1, (Math.max(0, dyUp) / (hPx * 0.55)) * 0.55 + (vh / 2.6) * 0.45));
    const y = Math.max(-1.08, Math.min(1.06, 0.86 - speedNorm * 1.84));
    return { x, y, power: speedNorm };
  }

  _renderDOM(cd) {
    const keepCanvas = this._canvas && this._container.querySelector("#cd-3d-canvas");
    if (!keepCanvas) {
      this._container.innerHTML = `
        <div class="game-panel">
          <div class="hud-row">
            <span style="color:var(--accent-pink);"><span id="cd-p1n">P1</span>: <strong id="cd-gs" style="font-size:20px;"></strong></span>
            <span>Darts <strong id="cd-left"></strong> · <span id="cd-turn"></span></span>
            <span style="color:var(--accent-cyan);"><span id="cd-p2n">P2</span>: <strong id="cd-hs" style="font-size:20px;"></strong></span>
          </div>
          <div class="canvas-frame" style="background:#0d0b0a;">
            <canvas id="cd-3d-canvas" width="540" height="390" style="width:100%;height:390px;display:block;touch-action:none;"></canvas>
          </div>
          <div style="position:relative;width:100%;height:24px;border-radius:10px;background:rgba(15,23,42,0.85);border:1px solid rgba(255,255,255,0.18);overflow:hidden;display:flex;align-items:center;justify-content:center;">
            <div id="cd-power-fill" style="position:absolute;left:0;top:0;bottom:0;width:0%;background:linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444);opacity:0.85;transition:width 0.04s;"></div>
            <span id="cd-power-label" style="position:relative;z-index:1;font-size:11px;font-weight:800;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.9);">SWIPE UP TO THROW DART · 0%</span>
          </div>
          <div id="cd-status" style="color:var(--gold);font-weight:700;text-align:center;font-size:13px;"></div>
          <div style="display:flex;gap:8px;width:100%;align-items:center;">
            <label style="font-size:12px;color:var(--muted);flex:1;">
              <input type="checkbox" id="cd-dbl"> Double-Out
            </label>
            <button class="btn-secondary" id="cd-reset">New 301</button>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#cd-3d-canvas");
      this._initThree();
      this._wireSwipe();
      this._container.querySelector("#cd-dbl").addEventListener("change", (e) =>
        this.ws.action("classic_darts", "reset", { doubleOut: e.target.checked })
      );
      this._container.querySelector("#cd-reset").addEventListener("click", () =>
        this.ws.action("classic_darts", "reset", { doubleOut: !!this._cd?.doubleOut })
      );
    }

    const p1 = this.ws.playerName("guest");
    const p2 = this.ws.playerName("host");
    const activeName = cd.turn === "guest" ? p1 : p2;
    const mine = this._isMyTurn(cd);
    const oppLbl = this.myRole() === "host" ? p1 : p2;
    this._container.querySelector("#cd-p1n").textContent = p1;
    this._container.querySelector("#cd-p2n").textContent = p2;
    this._container.querySelector("#cd-gs").textContent = String(cd.scores.guest);
    this._container.querySelector("#cd-hs").textContent = String(cd.scores.host);
    this._container.querySelector("#cd-left").textContent = String(cd.dartsLeft);
    this._container.querySelector("#cd-turn").textContent =
      cd.phase === "finished"
        ? (cd.winner === "guest" ? `${p1.toUpperCase()} WINS!` : `${p2.toUpperCase()} WINS!`)
        : mine
        ? `YOUR TURN (${activeName})`
        : `${activeName.toUpperCase()}'S TURN`;
    this._container.querySelector("#cd-dbl").checked = !!cd.doubleOut;
    this._container.querySelector("#cd-status").textContent =
      cd.status || (mine ? "Swipe UP smoothly toward a sector to flick!" : `Watching ${oppLbl} aim live...`);
  }

  _wireSwipe() {
    const c = this._canvas;
    if (!c) return;
    c.addEventListener("pointerdown", (e) => {
      this.sfx.unlock();
      if (!this._cd || !this._isMyTurn(this._cd) || this._flight) return;
      try { c.setPointerCapture(e.pointerId); } catch (_) {}
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag = { startX: pt.x, startY: pt.y, currX: pt.x, currY: pt.y };
      this._swipeTrail = [pt];
    });
    c.addEventListener("pointermove", (e) => {
      if (!this._drag) return;
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._drag.currX = pt.x;
      this._drag.currY = pt.y;
      this._swipeTrail.push(pt);
      if (this._swipeTrail.length > 20) this._swipeTrail.shift();
      const rect = c.getBoundingClientRect();
      this._aim.x = Math.max(-0.9, Math.min(0.9, ((e.clientX - rect.left) / rect.width - 0.5) * 1.8));
      this._aim.y = Math.max(-0.9, Math.min(0.9, ((e.clientY - rect.top) / rect.height - 0.5) * 1.8));
      const preview = this._computeFlick(true);
      const pwr = preview ? preview.power : 0.25;
      this._updatePowerBar(pwr, "AIM");
      this._sendAimThrottled(this._aim.x, this._aim.y, pwr);
    });
    const release = (e) => {
      if (!this._drag) return;
      this._swipeTrail.push({ x: e.clientX, y: e.clientY, t: performance.now() });
      const res = this._computeFlick(false);
      this._drag = null;
      this._swipeTrail = [];
      this._updatePowerBar(0);
      if (res) {
        this._aim = { x: res.x, y: res.y };
        this._flight = {
          sx: this._heldDart ? this._heldDart.position.x : 0,
          sy: this._heldDart ? this._heldDart.position.y : -0.34,
          ex: res.x * BOARD_RADIUS_WORLD,
          ey: -res.y * BOARD_RADIUS_WORLD,
          t: 0,
        };
        this.ws.action("classic_darts", "throw", { x: res.x, y: res.y, wobble: 0.02 });
      }
    };
    c.addEventListener("pointerup", release);
    c.addEventListener("pointercancel", () => {
      this._drag = null;
      this._swipeTrail = [];
    });
  }
}
