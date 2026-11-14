// Real Three.js WebGL 3D Cup Pong (GamePigeon BeerView-faithful swipe & rim-bounce visuals)
import {
  THREE,
  createPubRenderer,
  createSoloCupMesh,
  makeWoodTexture,
} from "./three_helpers.js";

export class BeerPongView {
  constructor(ws, sfx, myRole = () => "guest") {
    this.ws = ws;
    this.sfx = sfx;
    this.myRole = myRole;
    this._bp = null;
    this._container = null;
    this._canvas = null;
    this._lastSig = "";
    this._lastBallCount = 0;
    this._lastBounced = false;
    this._lastStatus = "";
    this._drag = null;
    this._swipeTrail = [];
    this._throwCooldownUntil = 0;
    this._simBalls = [];
    this._liveAim = null;
    this._lastAimSend = 0;

    this._raf = 0;
    this._pub = null;
    this._cupMeshes = new Map();
    this._ballMeshes = [];
    this._handBall = null;
    this._shadowMat = null;
    this._shadowDisc = null;
    this._splashParticles = [];
    this._splashGroup = null;
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
    this._cupMeshes.clear();
    this._ballMeshes = [];
    this._splashParticles = [];
    this._canvas = null;
    this._container = null;
  }

  _isMyTurn(bp) {
    return !!bp && bp.phase !== "finished" && bp.turn === this.myRole();
  }

  update(state) {
    const bp = state.beer_pong;
    if (!bp || !this._container) return;
    this._liveAim = state.liveAim && state.liveAim.game === "beer_pong" ? state.liveAim : null;

    const prevStatus = this._lastStatus;
    const prevCount = this._lastBallCount;
    const myAlive = (bp.racks?.[bp.turn === "guest" ? "host" : "guest"] || []).filter((c) => c.alive).length;
    const activeB = bp.balls?.[0];
    const nowBounced = !!activeB?.bounced;

    if (nowBounced && !this._lastBounced) {
      this.sfx.play("pong_bounce");
    }
    if (bp.status && bp.status !== prevStatus && bp.status.includes("RIM")) {
      this.sfx.play("clack");
    }
    if (this._lastSig && bp.phase === "finished" && prevStatus !== bp.status) {
      this.sfx.play("win");
    } else if (this._lastSig && bp.status && bp.status !== prevStatus && bp.status.includes("SPLASH")) {
      this.sfx.play("pong_cup");
      this._spawnSplash3D(0, 0.16, -0.82);
    }

    this._lastBounced = nowBounced;
    this._lastBallCount = prevCount;
    this._lastStatus = bp.status || "";
    this._bp = bp;
    this._simBalls = (bp.balls || []).map((b) => ({
      x: Number(b.x),
      y: Number(b.y),
      z: Number(b.z),
      vx: Number(b.vx || 0),
      vy: Number(b.vy || 0),
      vz: Number(b.vz || 0),
      bounced: !!b.bounced,
    }));

    const sig = `${bp.phase}|${bp.turn}|${bp.shotsLeft ?? 3}|${bp.cupCount}|${myAlive}|${bp.status}|${bp.practiceMode}|${bp.winner}|${this.myRole()}|${JSON.stringify(bp.rules)}`;
    if (sig !== this._lastSig || !this._canvas) {
      this._lastSig = sig;
      this._renderDOM(bp);
    } else if (!this._isMyTurn(bp) && this._liveAim) {
      const opp = this.myRole() === "host" ? "HER" : "HIM";
      this._updatePowerBar(Number(this._liveAim.power || 0), `${opp} AIMING`);
    }
    this._syncSceneMeshes(bp);
  }

  _spawnSplash3D(x, y, z) {
    if (!this._splashGroup) return;
    const geo = new THREE.SphereGeometry(0.011, 8, 8);
    const mat = new THREE.MeshStandardMaterial({ color: 0xffe49e, roughness: 0.15, transparent: true, opacity: 0.9 });
    for (let i = 0; i < 18; i++) {
      const m = new THREE.Mesh(geo, mat);
      const ang = (i / 18) * Math.PI * 2 + Math.random() * 0.4;
      const spd = 0.25 + Math.random() * 0.55;
      m.position.set(x, y, z);
      this._splashGroup.add(m);
      this._splashParticles.push({
        mesh: m,
        vx: Math.cos(ang) * spd,
        vy: 0.45 + Math.random() * 0.65,
        vz: Math.sin(ang) * spd,
        life: 0.72,
      });
    }
  }

  _initThree() {
    const c = this._canvas;
    if (!c) return;
    if (this._pub) {
      this._pub.renderer.dispose();
    }
    const pub = createPubRenderer(c, {
      fov: 42,
      camPos: [0, 0.52, 0.62],
      lookAt: [0, 0.10, -0.78],
    });
    const { scene, keySpot } = pub;
    keySpot.position.set(0.25, 1.85, -0.35);
    keySpot.target.position.set(0, 0, -0.75);

    // Rich mahogany pub table
    const woodTex = makeWoodTexture("#56301b", "#2a1308");
    woodTex.repeat.set(2, 3);
    const tableGeo = new THREE.BoxGeometry(1.18, 0.06, 1.95);
    const tableMat = new THREE.MeshStandardMaterial({
      map: woodTex,
      roughness: 0.34,
      metalness: 0.04,
    });
    const table = new THREE.Mesh(tableGeo, tableMat);
    table.position.set(0, -0.03, -0.45);
    table.receiveShadow = true;
    scene.add(table);

    // Beveled table trim rail
    const trimMat = new THREE.MeshStandardMaterial({ color: 0x261209, roughness: 0.45 });
    const railL = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.075, 1.97), trimMat);
    railL.position.set(-0.59, -0.025, -0.45);
    const railR = railL.clone();
    railR.position.x = 0.59;
    scene.add(railL, railR);

    // Pub room back wall & warm bokeh sign lights
    const wall = new THREE.Mesh(
      new THREE.PlaneGeometry(8, 5),
      new THREE.MeshStandardMaterial({ color: 0x161215, roughness: 0.85 })
    );
    wall.position.set(0, 1.4, -2.5);
    scene.add(wall);

    // Interactive foreground ball held at player hand
    const ballGeo = new THREE.SphereGeometry(0.019, 24, 20);
    const ballMat = new THREE.MeshPhysicalMaterial({
      color: 0xfbf9f3,
      roughness: 0.16,
      clearcoat: 0.75,
      clearcoatRoughness: 0.15,
    });
    this._handBall = new THREE.Mesh(ballGeo, ballMat);
    this._handBall.castShadow = true;
    this._handBall.position.set(0, 0.24, 0.24);
    scene.add(this._handBall);

    // Crisp micro contact shadow under flying ball (no cartoony rings)
    this._shadowMat = new THREE.MeshBasicMaterial({
      color: 0x050302,
      transparent: true,
      opacity: 0.42,
      depthWrite: false,
    });
    this._shadowDisc = new THREE.Mesh(new THREE.CircleGeometry(0.022, 20), this._shadowMat);
    this._shadowDisc.rotation.x = -Math.PI / 2;
    this._shadowDisc.position.y = 0.002;
    this._shadowDisc.visible = false;
    scene.add(this._shadowDisc);

    this._splashGroup = new THREE.Group();
    scene.add(this._splashGroup);

    this._cupMeshes.clear();
    this._ballMeshes = [];
    this._pub = pub;

    if (!this._raf) {
      let lastT = performance.now();
      const tick = (now) => {
        if (!this._pub) return;
        const dt = Math.min(0.05, (now - lastT) / 1000);
        lastT = now;
        this._animateScene(dt, now * 0.001);
        this._pub.syncSize();
        this._pub.renderer.render(this._pub.scene, this._pub.camera);
        this._raf = requestAnimationFrame(tick);
      };
      this._raf = requestAnimationFrame(tick);
    }
  }

  _syncSceneMeshes(bp) {
    if (!this._pub) return;
    const { scene } = this._pub;
    const targetSide = bp.turn === "guest" ? "host" : "guest";
    const rack = bp.racks?.[targetSide] || [];

    // Reconcile 3D Solo cups
    const keepIds = new Set();
    for (const c of rack) {
      const key = `${targetSide}-${c.id}`;
      keepIds.add(key);
      let mesh = this._cupMeshes.get(key);
      if (!mesh) {
        mesh = createSoloCupMesh({ topR: 0.056, botR: 0.039, h: 0.145 });
        this._cupMeshes.set(key, mesh);
        scene.add(mesh);
      }
      mesh.visible = !!c.alive;
      // Backend cup coords: x in [-0.4..0.4], z in [0.72..0.94] -> scene -z [ -0.58 .. -0.94 ]
      mesh.position.set(c.x, 0, -c.z);
      mesh.userData.wobble = Number(c.wobble || 0);
    }
    for (const [key, mesh] of this._cupMeshes.entries()) {
      if (!keepIds.has(key)) {
        scene.remove(mesh);
        this._cupMeshes.delete(key);
      }
    }

    // Active balls
    const balls = bp.balls || [];
    while (this._ballMeshes.length < balls.length) {
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(0.017, 22, 18),
        new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.14, clearcoat: 0.8 })
      );
      m.castShadow = true;
      scene.add(m);
      this._ballMeshes.push(m);
    }
    for (let i = 0; i < this._ballMeshes.length; i++) {
      const m = this._ballMeshes[i];
      if (i < balls.length) {
        const b = balls[i];
        m.visible = true;
        m.position.set(b.x, Math.max(0.017, b.y), -b.z);
      } else {
        m.visible = false;
      }
    }

    if (balls.length > 0 && this._shadowDisc) {
      const b0 = balls[0];
      this._shadowDisc.visible = true;
      this._shadowDisc.position.set(b0.x, 0.002, -b0.z);
      const hFrac = Math.min(1, Math.max(0, b0.y / 0.45));
      const sc = 0.85 + hFrac * 0.9;
      this._shadowDisc.scale.set(sc, sc, sc);
      this._shadowMat.opacity = Math.max(0.08, 0.48 - hFrac * 0.36);
    } else if (this._shadowDisc) {
      this._shadowDisc.visible = false;
    }

    // Foreground ready ball while waiting for swipe
    if (this._handBall) {
      const showReady = balls.length === 0 && this._isMyTurn(bp);
      this._handBall.visible = showReady;
      if (showReady) {
        if (this._drag) {
          const rect = this._canvas.getBoundingClientRect();
          const nx = ((this._drag.currX - rect.left) / Math.max(rect.width, 1) - 0.5) * 0.65;
          const dy = Math.max(-180, Math.min(40, this._drag.currY - this._drag.startY));
          this._handBall.position.set(nx, 0.23 - dy * 0.0005, 0.24 + dy * 0.0008);
        } else {
          this._handBall.position.set(0, 0.23, 0.24);
        }
      }
    }
  }

  _updatePowerBar(pwr, labelPrefix = "POWER") {
    const fill = this._container?.querySelector("#bp-power-fill");
    const lbl = this._container?.querySelector("#bp-power-label");
    if (!fill || !lbl) return;
    const p = Math.max(0, Math.min(1, pwr));
    const pct = Math.round(p * 100);
    fill.style.width = `${pct}%`;
    fill.style.background = p <= 0.5 ? "linear-gradient(90deg,#22c55e,#eab308)" : "linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444)";
    const zone = p < 0.05 ? "SWIPE UP TO SHOOT" : p < 0.36 ? "BOUNCE ZONE" : p <= 0.76 ? "GREEN · CUP SWEET SPOT" : p <= 0.88 ? "YELLOW · BACK CUPS" : "RED · OVERSHOOT";
    lbl.textContent = p > 0.02 ? `${labelPrefix} ${pct}% · ${zone}` : "SWIPE UP FROM ANYWHERE TO THROW · 0%";
  }

  _sendAimThrottled(spec, force = false) {
    const now = performance.now();
    if (!force && now - this._lastAimSend < 45) return;
    this._lastAimSend = now;
    if (spec) {
      this.ws.action("beer_pong", "aim", spec);
    }
  }

  _animateScene(dt, tSec) {
    // 60fps local parabolic flight interpolation matching GamePigeon BeerView g=-6.2
    if (this._simBalls.length > 0) {
      const airDrag = Math.pow(0.997, dt * 60);
      for (let i = 0; i < this._simBalls.length; i++) {
        const b = this._simBalls[i];
        b.x += b.vx * dt;
        b.y += b.vy * dt;
        b.z += b.vz * dt;
        b.vx *= airDrag;
        b.vz *= airDrag;
        b.vy -= 6.2 * dt;
        if (b.y <= 0.017 && b.vy < 0 && !b.bounced && b.z <= 0.78) {
          b.y = 0.017;
          b.vy = Math.abs(b.vy) * 0.78;
          b.bounced = true;
        }
        const m = this._ballMeshes[i];
        if (m) {
          m.visible = true;
          m.position.set(b.x, Math.max(0.017, b.y), -b.z);
        }
        if (i === 0 && this._shadowDisc) {
          this._shadowDisc.visible = true;
          this._shadowDisc.position.set(b.x, 0.002, -b.z);
          const hFrac = Math.min(1, Math.max(0, b.y / 0.45));
          const sc = 0.85 + hFrac * 0.9;
          this._shadowDisc.scale.set(sc, sc, sc);
          this._shadowMat.opacity = Math.max(0.08, 0.48 - hFrac * 0.36);
        }
      }
    }
    // Realistic spring cup wobble when rim is struck
    for (const mesh of this._cupMeshes.values()) {
      const wob = mesh.userData.wobble || 0;
      if (wob > 0.01) {
        mesh.rotation.z = Math.sin(tSec * 36) * wob * 0.095;
        mesh.rotation.x = Math.cos(tSec * 29) * wob * 0.065;
      } else {
        mesh.rotation.z *= 0.85;
        mesh.rotation.x *= 0.85;
      }
    }
    if (this._handBall && this._handBall.visible && !this._drag) {
      this._handBall.position.y = 0.23 + Math.sin(tSec * 3.1) * 0.004;
    }
    // Fade beer splashes
    for (let i = this._splashParticles.length - 1; i >= 0; i--) {
      const p = this._splashParticles[i];
      p.life -= dt;
      if (p.life <= 0) {
        this._splashGroup.remove(p.mesh);
        this._splashParticles.splice(i, 1);
      } else {
        p.vy -= 2.8 * dt;
        p.mesh.position.x += p.vx * dt;
        p.mesh.position.y += p.vy * dt;
        p.mesh.position.z += p.vz * dt;
      }
    }
  }

  _computeThrowFromSwipe(allowSoftPreview = false) {
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
    const dtS = Math.max(0.025, (end.t - anchor.t) / 1000);
    const totalDy = trail[0].y - end.y;
    const totalDx = end.x - trail[0].x;
    if (!allowSoftPreview && totalDy < 14) return null;

    const vyRel = Math.max(30, (anchor.y - end.y) / dtS);
    const vxRel = (end.x - anchor.x) / dtS;
    const rect = this._canvas.getBoundingClientRect();
    const hPx = Math.max(rect.height, 260);
    const vh = vyRel / hPx;
    const startOffset = (trail[0].x - rect.left) / Math.max(rect.width, 1) - 0.5;
    const tiltRatio = totalDx / Math.max(Math.abs(totalDy), 48);

    const aimX = Math.max(-0.55, Math.min(0.55, startOffset * 0.55 + tiltRatio * 0.85 + (vxRel / hPx) * 0.18));
    // Smooth, forgiving blend of swipe distance + release velocity so shots never fail with errors
    const distPart = Math.max(0, Math.min(1, Math.max(0, totalDy) / (hPx * 0.62)));
    const velPart = Math.max(0, Math.min(1, vh / 2.25));
    const power = allowSoftPreview
      ? Math.max(0.05, Math.min(0.98, distPart * 0.72 + velPart * 0.28))
      : Math.max(0.25, Math.min(0.95, distPart * 0.58 + velPart * 0.42));
    const loft = Math.max(0.25, Math.min(0.85, 0.38 + power * 0.34));
    return { aimX, power, loft };
  }

  _renderDOM(bp) {
    const myTurn = this._isMyTurn(bp);
    const active = bp.balls && bp.balls.length > 0;
    const activeBounced = active && bp.balls[0].bounced;
    const guestAlive = (bp.racks?.guest || []).filter((c) => c.alive).length;
    const hostAlive = (bp.racks?.host || []).filter((c) => c.alive).length;
    const streak = bp.streaks?.[bp.turn] || 0;
    const shotsLeft = bp.shotsLeft ?? 3;
    const keepCanvas = this._canvas && this._container.querySelector("#bp-3d-canvas");

    if (!keepCanvas) {
      this._container.innerHTML = `
        <div class="game-panel">
          <div class="hud-row">
            <span><strong id="bp-turn"></strong> · <span id="bp-shots" style="letter-spacing:2px;"></span></span>
            <span>Her <strong id="bp-gcups" style="color:var(--accent-pink);"></strong> · Him <strong id="bp-hcups" style="color:var(--accent-cyan);"></strong></span>
            <span id="bp-heat" style="color:var(--gold);font-weight:700;"></span>
          </div>
          <div class="canvas-frame" style="background:#0d0b0a;box-shadow:inset 0 0 36px rgba(0,0,0,0.72);">
            <canvas id="bp-3d-canvas" width="540" height="390" style="width:100%;height:390px;display:block;touch-action:none;"></canvas>
          </div>
          <div id="bp-power-wrap" style="position:relative;width:100%;height:28px;border-radius:10px;background:rgba(15,23,42,0.85);border:1px solid rgba(255,255,255,0.18);overflow:hidden;display:flex;align-items:center;justify-content:center;">
            <div id="bp-power-fill" style="position:absolute;left:0;top:0;bottom:0;width:0%;background:linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444);opacity:0.85;transition:width 0.04s;"></div>
            <span id="bp-power-label" style="position:relative;z-index:1;font-size:11px;font-weight:800;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.9);">SWIPE UP FROM ANYWHERE TO THROW · 0%</span>
          </div>
          <div id="bp-status" style="color:var(--gold);font-weight:700;text-align:center;font-size:13px;"></div>
          <div style="display:flex;gap:8px;width:100%;">
            <button class="btn-secondary" id="bp-rerack" style="flex:1;">Rerack</button>
            <button class="btn-cyan" id="bp-cups" style="flex:1;">${bp.cupCount === 10 ? "6 Cups" : "10 Cups"}</button>
            <button class="btn-secondary" id="bp-reset" style="flex:1;">Reset 1v1</button>
          </div>
          <button class="btn-primary" id="bp-swat" style="display:none;width:100%;">SWAT BOUNCE!</button>
          <div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center;font-size:11px;color:var(--muted);">
            <label><input type="checkbox" class="bp-rule" data-k="bounceDouble"> Bounce = 2 Cups</label>
            <label><input type="checkbox" class="bp-rule" data-k="redemption"> Redemption</label>
            <label><input type="checkbox" class="bp-rule" data-k="rerack"> 1 Rerack</label>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#bp-3d-canvas");
      this._initThree();
      this._wireSwipe();
      this._container.querySelector("#bp-rerack").addEventListener("click", () => this.ws.action("beer_pong", "rerack"));
      this._container.querySelector("#bp-swat").addEventListener("click", () => this.ws.action("beer_pong", "swat"));
      this._container.querySelector("#bp-cups").addEventListener("click", () =>
        this.ws.action("beer_pong", "reset", { cups: this._bp?.cupCount === 10 ? 6 : 10 })
      );
      this._container.querySelector("#bp-reset").addEventListener("click", () =>
        this.ws.action("beer_pong", "reset", { cups: this._bp?.cupCount || 6 })
      );
      this._container.querySelectorAll(".bp-rule").forEach((el) => {
        el.addEventListener("change", () => this.ws.action("beer_pong", "rule", { key: el.dataset.k, value: el.checked }));
      });
    }

    const turnTxt = bp.phase === "finished"
      ? (bp.winner === "guest" ? "HER WINS!" : "HIM WINS!")
      : myTurn
      ? `YOUR TURN (${bp.turn === "guest" ? "P1" : "P2"})`
      : (bp.turn === "host" ? "HIM'S TURN (P2)" : "HER TURN (P1)");
    this._container.querySelector("#bp-turn").textContent = turnTxt;
    const shotsEl = this._container.querySelector("#bp-shots");
    if (shotsEl) {
      shotsEl.textContent = shotsLeft > 6
        ? `${"⚪".repeat(6)} +${shotsLeft - 6}`
        : (shotsLeft > 0 ? "⚪".repeat(shotsLeft) : "0");
    }
    this._container.querySelector("#bp-gcups").textContent = String(guestAlive);
    this._container.querySelector("#bp-hcups").textContent = String(hostAlive);
    this._container.querySelector("#bp-heat").textContent = streak >= 2 ? `🔥 x${streak}` : "";
    const oppLbl = this.myRole() === "host" ? "Her" : "Him";
    this._container.querySelector("#bp-status").textContent =
      bp.status || (myTurn ? "Swipe upward fast — 3 shots a turn, +1 free shot per make" : `Watching ${oppLbl} shoot...`);
    this._container.querySelector("#bp-cups").textContent = bp.cupCount === 10 ? "6 Cups" : "10 Cups";
    const swatBtn = this._container.querySelector("#bp-swat");
    if (swatBtn) swatBtn.style.display = activeBounced ? "block" : "none";
    this._container.querySelectorAll(".bp-rule").forEach((el) => {
      el.checked = !!bp.rules?.[el.dataset.k];
    });
  }

  _wireSwipe() {
    const c = this._canvas;
    if (!c) return;
    c.addEventListener("pointerdown", (e) => {
      this.sfx.unlock();
      if (!this._bp || !this._isMyTurn(this._bp) || (this._bp.balls && this._bp.balls.length > 0)) return;
      if (performance.now() < this._throwCooldownUntil) return;
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
      if (this._swipeTrail.length > 24) this._swipeTrail.shift();
      const previewSpec = this._computeThrowFromSwipe(true);
      if (previewSpec) {
        this._updatePowerBar(previewSpec.power, "AIM");
        this._sendAimThrottled(previewSpec);
      }
      this._syncSceneMeshes(this._bp);
    });
    const finish = (e) => {
      if (!this._drag) return;
      const pt = { x: e.clientX, y: e.clientY, t: performance.now() };
      this._swipeTrail.push(pt);
      const spec = this._computeThrowFromSwipe(false);
      this._drag = null;
      this._swipeTrail = [];
      this._updatePowerBar(0);
      if (spec) {
        this._throwCooldownUntil = performance.now() + 250;
        this.ws.action("beer_pong", "throw", spec);
      }
      this._syncSceneMeshes(this._bp);
    };
    c.addEventListener("pointerup", finish);
    c.addEventListener("pointercancel", () => {
      this._drag = null;
      this._swipeTrail = [];
      this._syncSceneMeshes(this._bp);
    });
  }
}
