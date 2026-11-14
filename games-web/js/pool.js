// Real Three.js WebGL 3D 8-Ball Pool with pull-back cue stick, camera toggle, spin selector & real audio WAVs
import {
  THREE,
  createPubRenderer,
  makeFeltTexture,
  makePoolBallTexture,
  makeWoodTexture,
} from "./three_helpers.js";

const BALL_R = 0.028;

const POCKETS = [
  [-0.965, -0.465], [0.0, -0.495], [0.965, -0.465],
  [-0.965,  0.465], [0.0,  0.495], [0.965,  0.465],
];

function powerHexColor(p) {
  const t = Math.max(0, Math.min(1, p));
  if (t <= 0.5) {
    const k = t * 2;
    const r = Math.round(34 + (234 - 34) * k);
    const g = Math.round(197 + (179 - 197) * k);
    const b = Math.round(94 + (8 - 94) * k);
    return (r << 16) | (g << 8) | b;
  }
  const k = (t - 0.5) * 2;
  const r = Math.round(234 + (239 - 234) * k);
  const g = Math.round(179 + (68 - 179) * k);
  const b = Math.round(8 + (68 - 8) * k);
  return (r << 16) | (g << 8) | b;
}

export class PoolView {
  constructor(ws, sfx, myRole = () => "guest") {
    this.ws = ws;
    this.sfx = sfx;
    this.myRole = myRole;
    this._angle = 0.0;
    this._spinY = 0.0;
    this._pool = null;
    this._liveAim = null;
    this._simBalls = [];
    this._container = null;
    this._canvas = null;
    this._lastSig = "";
    this._lastAimSend = 0;

    this._raf = 0;
    this._pub = null;
    this._ballMeshes = new Map();
    this._prevBallState = new Map();
    this._cueGroup = null;
    this._cueStickMesh = null;
    this._aimLine = null;
    this._ghostCircle = null;
    this._targetLine = null;
    this._deflectLine = null;
    this._pullBack = 0.0;
    this._draggingMode = null; // "aim" | "pull"
    this._dragStart = null;
    this._dragPointerId = null;
    this._raycaster = new THREE.Raycaster();
    this._feltPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  }

  mount(container, state) {
    this._container = container;
    this._lastSig = "";
    this.update(state);
  }

  unmount() {
    if (this._boundWinMove) window.removeEventListener("pointermove", this._boundWinMove);
    if (this._boundWinUp) {
      window.removeEventListener("pointerup", this._boundWinUp);
      window.removeEventListener("pointercancel", this._boundWinCancel || this._boundWinUp);
    }
    this._boundWinMove = null;
    this._boundWinUp = null;
    this._boundWinCancel = null;
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = 0;
    }
    if (this._pub) {
      this._pub.renderer.dispose();
      this._pub = null;
    }
    this._ballMeshes.clear();
    this._prevBallState.clear();
    this._canvas = null;
    this._container = null;
  }

  _isMyTurn(p) {
    return !!p && p.phase !== "finished" && p.phase !== "moving" && p.phase !== "shooting" && p.turn === this.myRole();
  }

  _sendAimThrottled(force = false) {
    const now = performance.now();
    if (!force && now - this._lastAimSend < 45) return;
    this._lastAimSend = now;
    if (this._pool && this._isMyTurn(this._pool) && this._pool.phase === "aiming") {
      this.ws.action("pool", "aim", { angle: this._angle, power: this._pullBack });
    }
  }

  update(state) {
    const p = state.pool;
    if (!p || !this._container) return;
    this._liveAim = state.liveAim && state.liveAim.game === "pool" ? state.liveAim : null;

    // Detect real collision velocities, rail rebounds, and pockets cleanly
    let clacked = false;
    let pottedNow = false;
    for (const b of p.balls) {
      const prev = this._prevBallState.get(b.n);
      if (prev) {
        if (!prev.potted && b.potted) {
          pottedNow = true;
        } else if (!b.potted) {
          const dv = Math.hypot(b.x - prev.x, b.y - prev.y);
          if (dv > 0.014 && prev.dv > 0.008) {
            const dot = (b.x - prev.x) * prev.dx + (b.y - prev.y) * prev.dy;
            if (dot < prev.dv * dv * 0.72) clacked = true;
          }
          const dx = b.x - prev.x;
          const dy = b.y - prev.y;
          this._prevBallState.set(b.n, { x: b.x, y: b.y, potted: b.potted, dv, dx, dy });
          continue;
        }
      }
      this._prevBallState.set(b.n, { x: b.x, y: b.y, potted: b.potted, dv: 0, dx: 0, dy: 0 });
    }
    if (pottedNow) this.sfx.play("pool_pot");
    else if (clacked && (p.phase === "moving" || p.phase === "shooting")) this.sfx.play("pool_clack");

    if (this._pool && this._pool.phase !== "finished" && p.phase === "finished") {
      this.sfx.play("win");
    }
    this._pool = p;
    this._simBalls = (p.balls || []).map((b) => ({
      n: b.n,
      x: Number(b.x),
      y: Number(b.y),
      vx: Number(b.vx || 0),
      vy: Number(b.vy || 0),
      potted: !!b.potted,
    }));

    const sig = `${p.phase}|${p.turn}|${p.status}|${p.winner}|${p.groups.guest}|${p.groups.host}|${this.myRole()}`;
    if (sig !== this._lastSig || !this._canvas) {
      this._lastSig = sig;
      this._renderDOM(p);
    }
    if (!this._isMyTurn(p) && this._liveAim && this._liveAim.by !== this.myRole()) {
      if (Number.isFinite(this._liveAim.angle)) this._angle = Number(this._liveAim.angle);
      if (Number.isFinite(this._liveAim.power)) this._pullBack = Number(this._liveAim.power);
      this._updateRivalStrikeBar();
    }
    this._syncMeshes(p);
  }

  _initThree() {
    const c = this._canvas;
    if (!c) return;
    if (this._pub) this._pub.renderer.dispose();
    const pub = createPubRenderer(c, {
      ortho: true,
      camPos: [0, 3.0, 0],
      lookAt: [0, 0.0, 0.0],
    });
    const { scene, keySpot } = pub;
    keySpot.position.set(0, 2.8, 0.1);
    keySpot.target.position.set(0, 0, 0);

    // Emerald wool baize surface (width 2.00 = x[-1..1], height 1.00 = z[-0.5..0.5])
    const feltMat = new THREE.MeshStandardMaterial({
      map: makeFeltTexture(),
      roughness: 0.88,
      metalness: 0.0,
    });
    const felt = new THREE.Mesh(new THREE.BoxGeometry(2.04, 0.04, 1.04), feltMat);
    felt.position.y = -0.02;
    felt.receiveShadow = true;
    scene.add(felt);

    // Mahogany rails & cushioned rubber bumpers
    const woodMat = new THREE.MeshStandardMaterial({
      map: makeWoodTexture("#542b16", "#2c1308"),
      roughness: 0.32,
      metalness: 0.05,
    });
    const cushionMat = new THREE.MeshStandardMaterial({ color: 0x10663b, roughness: 0.72 });
    const railTop = new THREE.Mesh(new THREE.BoxGeometry(2.28, 0.09, 0.14), woodMat);
    railTop.position.set(0, 0.025, -0.57);
    const railBot = railTop.clone();
    railBot.position.z = 0.57;
    const railL = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.09, 1.02), woodMat);
    railL.position.set(-1.07, 0.025, 0);
    const railR = railL.clone();
    railR.position.x = 1.07;
    [railTop, railBot, railL, railR].forEach((r) => { r.castShadow = true; r.receiveShadow = true; scene.add(r); });

    // Silver rail diamond sights
    const diamGeo = new THREE.OctahedronGeometry(0.011, 0);
    const diamMat = new THREE.MeshStandardMaterial({ color: 0xdfe7f2, metalness: 0.85, roughness: 0.18 });
    for (const dx of [-0.72, -0.36, 0.36, 0.72]) {
      for (const dz of [-0.57, 0.57]) {
        const d = new THREE.Mesh(diamGeo, diamMat);
        d.scale.set(1.2, 0.4, 0.7);
        d.position.set(dx, 0.072, dz);
        scene.add(d);
      }
    }

    // 6 dark pocket leather wells & brass castings
    const wellGeo = new THREE.CylinderGeometry(0.054, 0.054, 0.045, 24);
    const wellMat = new THREE.MeshStandardMaterial({ color: 0x07080a, roughness: 0.95 });
    const brassGeo = new THREE.TorusGeometry(0.057, 0.009, 10, 24, Math.PI);
    const brassMat = new THREE.MeshStandardMaterial({ color: 0xc99c3c, metalness: 0.85, roughness: 0.25 });
    for (const [px, pz] of POCKETS) {
      const well = new THREE.Mesh(wellGeo, wellMat);
      well.position.set(px, -0.015, pz);
      scene.add(well);
      const collar = new THREE.Mesh(brassGeo, brassMat);
      collar.rotation.x = Math.PI / 2;
      collar.position.set(px, 0.042, pz);
      scene.add(collar);
    }

    // 16 glossy billiard ball meshes (oriented so crisp numbers face straight up to top-down camera)
    this._ballMeshes.clear();
    const bGeo = new THREE.SphereGeometry(BALL_R, 28, 22);
    for (let n = 0; n <= 15; n++) {
      const mat = new THREE.MeshPhysicalMaterial({
        map: makePoolBallTexture(n),
        roughness: 0.10,
        metalness: 0.04,
        clearcoat: 1.0,
        clearcoatRoughness: 0.08,
      });
      const m = new THREE.Mesh(bGeo, mat);
      m.rotation.set(-Math.PI / 2, 0, 0);
      m.castShadow = true;
      m.receiveShadow = true;
      scene.add(m);
      this._ballMeshes.set(n, m);
    }

    // 3D Tapered Wooden Cue Stick (pivot at cue tip near ball)
    this._cueGroup = new THREE.Group();
    const stick = new THREE.Group();
    const tip = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.007, 0.014, 12), new THREE.MeshStandardMaterial({ color: 0x2f88e8, roughness: 0.8 }));
    tip.rotation.z = Math.PI / 2;
    tip.position.x = -0.055;
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.007, 0.010, 0.48, 14), new THREE.MeshStandardMaterial({ color: 0xe6c89a, roughness: 0.28 }));
    shaft.rotation.z = Math.PI / 2;
    shaft.position.x = -0.30;
    const butt = new THREE.Mesh(new THREE.CylinderGeometry(0.010, 0.014, 0.44, 14), new THREE.MeshStandardMaterial({ color: 0x3b1b0e, roughness: 0.22 }));
    butt.rotation.z = Math.PI / 2;
    butt.position.x = -0.76;
    const ring = new THREE.Mesh(new THREE.CylinderGeometry(0.0105, 0.0105, 0.016, 14), brassMat);
    ring.rotation.z = Math.PI / 2;
    ring.position.x = -0.54;
    stick.add(tip, shaft, ring, butt);
    stick.castShadow = true;
    stick.rotation.z = -0.06;
    this._cueStickMesh = stick;
    this._cueGroup.add(stick);
    scene.add(this._cueGroup);

    // GamePigeon PoolScene mMove aim guide: raycast line + ghost ball + dual post-collision forks
    const aimGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0.5, 0, 0)]);
    this._aimLine = new THREE.Line(
      aimGeo,
      new THREE.LineBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.92 })
    );
    this._aimLine.frustumCulled = false;
    scene.add(this._aimLine);

    this._ghostCircle = new THREE.Mesh(
      new THREE.RingGeometry(BALL_R - 0.004, BALL_R + 0.002, 28),
      new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.90, side: THREE.DoubleSide })
    );
    this._ghostCircle.rotation.x = -Math.PI / 2;
    this._ghostCircle.position.y = 0.008;
    scene.add(this._ghostCircle);

    const tgtGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0.25, 0, 0)]);
    this._targetLine = new THREE.Line(
      tgtGeo,
      new THREE.LineBasicMaterial({ color: 0x6ce5ff, transparent: true, opacity: 0.96 })
    );
    this._targetLine.frustumCulled = false;
    scene.add(this._targetLine);

    const defGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0.18, 0, 0)]);
    this._deflectLine = new THREE.Line(
      defGeo,
      new THREE.LineBasicMaterial({ color: 0xfacc15, transparent: true, opacity: 0.90 })
    );
    this._deflectLine.frustumCulled = false;
    scene.add(this._deflectLine);

    this._pub = pub;
    if (!this._raf) {
      let lastT = performance.now();
      const loop = (now) => {
        if (!this._pub) return;
        const dt = Math.min(0.05, (now - lastT) / 1000);
        lastT = now;
        this._updateCamera(dt);
        this._stepLocalBalls(dt);
        this._pub.syncSize();
        this._pub.renderer.render(this._pub.scene, this._pub.camera);
        this._raf = requestAnimationFrame(loop);
      };
      this._raf = requestAnimationFrame(loop);
    }
  }

  _updateCamera(_dt) {
    if (!this._pub || !this._canvas) return;
    const cam = this._pub.camera;
    const cw = Math.max(this._canvas.clientWidth || this._canvas.width || 540, 1);
    const ch = Math.max(this._canvas.clientHeight || this._canvas.height || 320, 1);
    const aspect = cw / ch;
    if (cam.isOrthographicCamera) {
      let hh = 0.68;
      let hw = hh * aspect;
      if (hw < 1.20) {
        hw = 1.20;
        hh = hw / aspect;
      }
      if (Math.abs(cam.right - hw) > 0.005 || Math.abs(cam.top - hh) > 0.005) {
        cam.left = -hw;
        cam.right = hw;
        cam.top = hh;
        cam.bottom = -hh;
        cam.updateProjectionMatrix();
        this._pub.renderer.setSize(cw, ch, false);
      }
      cam.position.set(0, 3.0, 0);
      cam.up.set(0, 0, -1);
      cam.lookAt(0, 0, 0);
    }
  }

  _stepLocalBalls(dt) {
    if (!this._pool || !this._simBalls.length) return;
    if (this._pool.phase !== "moving" && this._pool.phase !== "shooting") return;
    const maxX = 1.0 - BALL_R;
    const maxY = 0.5 - BALL_R;
    let moved = false;
    for (const b of this._simBalls) {
      if (b.potted) continue;
      if (Math.hypot(b.vx, b.vy) < 0.005) continue;
      b.x += b.vx * dt;
      b.y += b.vy * dt;
      b.vx *= Math.pow(0.992, dt * 60);
      b.vy *= Math.pow(0.992, dt * 60);
      if (b.x < -maxX) { b.x = -maxX; b.vx = Math.abs(b.vx) * 0.84; }
      else if (b.x > maxX) { b.x = maxX; b.vx = -Math.abs(b.vx) * 0.84; }
      if (b.y < -maxY) { b.y = -maxY; b.vy = Math.abs(b.vy) * 0.84; }
      else if (b.y > maxY) { b.y = maxY; b.vy = -Math.abs(b.vy) * 0.84; }
      const m = this._ballMeshes.get(b.n);
      if (m) {
        const nx = b.x;
        const nz = -b.y;
        const dx = nx - m.position.x;
        const dz = nz - m.position.z;
        const dist = Math.hypot(dx, dz);
        if (dist > 1e-4) {
          const axis = new THREE.Vector3(dz / dist, 0, -dx / dist).normalize();
          m.rotateOnWorldAxis(axis, dist / BALL_R);
        }
        m.position.set(nx, BALL_R, nz);
      }
      moved = true;
    }
    if (moved) return;
  }

  _syncMeshes(p) {
    if (!this._pub) return;
    let cuePos = null;
    const isBreakReset = (p.status || "").includes("Break");
    for (const b of p.balls) {
      const m = this._ballMeshes.get(b.n);
      if (!m) continue;
      m.visible = !b.potted;
      if (!b.potted) {
        const nx = b.x;
        const nz = -b.y;
        if (isBreakReset && !b.vx && !b.vy && p.phase === "aiming") {
          m.rotation.set(-Math.PI / 2, 0, 0);
        } else {
          const dx = nx - m.position.x;
          const dz = nz - m.position.z;
          const dist = Math.hypot(dx, dz);
          if (dist > 1e-4) {
            const axis = new THREE.Vector3(dz / dist, 0, -dx / dist).normalize();
            m.rotateOnWorldAxis(axis, dist / BALL_R);
          }
        }
        m.position.set(nx, BALL_R, nz);
        if (b.n === 0) cuePos = m.position;
      }
    }

    const mine = this._isMyTurn(p);
    const rivalAim = !mine && p.phase === "aiming" && this._liveAim && this._liveAim.game === "pool" ? this._liveAim : null;
    const effAngle = mine ? this._angle : rivalAim ? Number(rivalAim.angle || 0) : 0;
    const effPower = mine ? this._pullBack : rivalAim ? Number(rivalAim.power || 0) : 0;

    if (this._cueGroup) {
      const showCue = p.phase === "aiming" && cuePos && (mine || !!rivalAim);
      this._cueGroup.visible = !!showCue;
      if (showCue && cuePos) {
        this._cueGroup.position.set(cuePos.x, BALL_R, cuePos.z);
        this._cueGroup.rotation.y = effAngle;
        if (this._cueStickMesh) {
          this._cueStickMesh.position.x = -effPower * 0.34;
        }
      }
    }
    this._updateAimGuide(p, effAngle, effPower, mine || !!rivalAim);
  }

  _updateAimGuide(p, angle, power, active) {
    if (!this._aimLine || !this._ghostCircle || !this._targetLine || !this._deflectLine) return;
    const cue = p?.balls?.find((b) => b.n === 0 && !b.potted);
    const show = p && p.phase === "aiming" && cue && active;
    this._aimLine.visible = !!show;
    this._ghostCircle.visible = !!show;
    if (!show) {
      this._targetLine.visible = false;
      this._deflectLine.visible = false;
      return;
    }

    const hex = power > 0.02 ? powerHexColor(power) : 0x22c55e;
    this._aimLine.material.color.setHex(hex);
    this._ghostCircle.material.color.setHex(hex);

    const r = BALL_R;
    const minD = r * 2.0;
    const maxX = 1.0 - r;
    const maxY = 0.5 - r;
    const cx = cue.x;
    const cy = cue.y;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);

    let tBest = Infinity;
    if (dx > 1e-6) tBest = Math.min(tBest, (maxX - cx) / dx);
    else if (dx < -1e-6) tBest = Math.min(tBest, (-maxX - cx) / dx);
    if (dy > 1e-6) tBest = Math.min(tBest, (maxY - cy) / dy);
    else if (dy < -1e-6) tBest = Math.min(tBest, (-maxY - cy) / dy);
    if (!Number.isFinite(tBest) || tBest < 0.01) tBest = 0.05;

    let hitBall = null;
    for (const b of p.balls) {
      if (b.n === 0 || b.potted) continue;
      const rx = b.x - cx;
      const ry = b.y - cy;
      const proj = rx * dx + ry * dy;
      if (proj <= 0) continue;
      const perp2 = rx * rx + ry * ry - proj * proj;
      const minD2 = minD * minD;
      if (perp2 > minD2) continue;
      const thc = Math.sqrt(Math.max(0, minD2 - perp2));
      const tHit = proj - thc;
      if (tHit >= 0 && tHit < tBest) {
        tBest = tHit;
        hitBall = b;
      }
    }

    const gx = cx + dx * tBest;
    const gy = cy + dy * tBest;

    const sx = cx + dx * r;
    const sy = cy + dy * r;
    const posAttr = this._aimLine.geometry.attributes.position;
    posAttr.setXYZ(0, sx, 0.008, -sy);
    posAttr.setXYZ(1, gx, 0.008, -gy);
    posAttr.needsUpdate = true;

    this._ghostCircle.position.set(gx, 0.008, -gy);

    // GamePigeon PoolScene mMove: dual post-collision forks (object ball + 90deg cue deflection)
    if (hitBall) {
      const nx = hitBall.x - gx;
      const ny = hitBall.y - gy;
      const nLen = Math.hypot(nx, ny) || 1;
      const ux = nx / nLen;
      const uy = ny / nLen;
      const cosT = Math.max(0, dx * ux + dy * uy);
      const pathLen = 0.14 + 0.24 * cosT;
      const tAttr = this._targetLine.geometry.attributes.position;
      tAttr.setXYZ(0, hitBall.x, 0.009, -hitBall.y);
      tAttr.setXYZ(1, hitBall.x + ux * pathLen, 0.009, -(hitBall.y + uy * pathLen));
      tAttr.needsUpdate = true;
      this._targetLine.visible = true;

      // 90-degree tangent deflection vector for cue ball
      const dot = dx * ux + dy * uy;
      const tx = dx - dot * ux;
      const ty = dy - dot * uy;
      const sinT = Math.hypot(tx, ty);
      if (sinT > 0.05) {
        const dLen = 0.10 + 0.22 * sinT;
        const tux = tx / sinT;
        const tuy = ty / sinT;
        const dAttr = this._deflectLine.geometry.attributes.position;
        dAttr.setXYZ(0, gx, 0.009, -gy);
        dAttr.setXYZ(1, gx + tux * dLen, 0.009, -(gy + tuy * dLen));
        dAttr.needsUpdate = true;
        this._deflectLine.visible = true;
      } else {
        this._deflectLine.visible = false;
      }
    } else {
      this._targetLine.visible = false;
      this._deflectLine.visible = false;
    }
  }

  _updateRivalStrikeBar() {
    const fill = this._container?.querySelector("#pool-power-fill");
    const labelEl = this._container?.querySelector("#pool-strike-label");
    if (!fill || !labelEl || !this._liveAim) return;
    const pwr = Math.max(0, Math.min(1, Number(this._liveAim.power || 0)));
    const pct = Math.round(pwr * 100);
    const opp = this.myRole() === "host" ? "HER" : "HIM";
    fill.style.width = `${pct}%`;
    fill.style.background = pwr <= 0.5 ? "linear-gradient(90deg,#22c55e,#eab308)" : "linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444)";
    labelEl.textContent = pwr > 0.02 ? `${opp} AIMING · POWER ${pct}%` : `${opp} AIMING ON PHONE...`;
  }

  _renderDOM(p) {
    const keepCanvas = this._canvas && this._container.querySelector("#pool-3d-canvas");
    if (!keepCanvas) {
      this._container.innerHTML = `
        <div class="game-panel">
          <div class="hud-row">
            <span><strong id="pool-turn"></strong></span>
            <span>Her: <strong id="pool-gg" style="color:var(--accent-pink);"></strong> · Him: <strong id="pool-hg" style="color:var(--accent-cyan);"></strong></span>
          </div>
          <div class="canvas-frame" style="background:#0d0b0a;position:relative;">
            <canvas id="pool-3d-canvas" width="540" height="320" style="width:100%;aspect-ratio:540/320;height:auto;display:block;touch-action:none;"></canvas>
          </div>
          <div id="pool-strike-bar" style="position:relative;width:100%;height:56px;border-radius:14px;background:linear-gradient(90deg,rgba(83,215,105,0.18),rgba(255,212,100,0.22) 55%,rgba(255,77,77,0.24));border:1.5px solid rgba(255,255,255,0.24);overflow:hidden;touch-action:none;user-select:none;-webkit-user-select:none;display:flex;align-items:center;justify-content:center;cursor:grab;">
            <div id="pool-power-fill" style="position:absolute;left:0;top:0;bottom:0;width:0%;background:linear-gradient(90deg,#53d769,#ffd464,#ff4d4d);opacity:0.82;pointer-events:none;transition:width 0.04s;"></div>
            <span id="pool-strike-label" style="position:relative;z-index:1;font-weight:800;font-size:13px;letter-spacing:0.35px;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,0.85);pointer-events:none;">DRAG HERE TO PULL CUE &amp; SHOOT · 0%</span>
          </div>
          <div id="pool-status" style="color:var(--gold);font-weight:700;text-align:center;font-size:13px;"></div>
          <div style="display:flex;gap:8px;width:100%;align-items:center;">
            <button class="btn-secondary" id="pool-spin" style="flex:1;">Spin: Center</button>
            <button class="btn-secondary" id="pool-reset" style="flex:1;">Re-Rack 1v1</button>
          </div>
        </div>
      `;
      this._canvas = this._container.querySelector("#pool-3d-canvas");
      this._initThree();
      this._wireControls();
      this._container.querySelector("#pool-spin").addEventListener("click", () => {
        this._spinY = this._spinY === 0 ? 0.55 : this._spinY > 0 ? -0.55 : 0.0;
        const label = this._spinY > 0 ? "Top (Follow)" : this._spinY < 0 ? "Bottom (Draw)" : "Center";
        this._container.querySelector("#pool-spin").textContent = `Spin: ${label}`;
      });
      this._container.querySelector("#pool-reset").addEventListener("click", () =>
        this.ws.action("pool", "reset")
      );
    }

    const mine = this._isMyTurn(p);
    const turnLabel =
      p.phase === "finished"
        ? (p.winner === "guest" ? "HER WINS!" : p.winner === "host" ? "HIM WINS!" : "GAME OVER")
        : mine
        ? `YOUR TURN (${p.turn === "guest" ? "P1 HER" : "P2 HIM"})`
        : (p.turn === "host" ? "HIM'S TURN (P2)" : "HER TURN (P1)");

    this._container.querySelector("#pool-turn").textContent = turnLabel;
    this._container.querySelector("#pool-gg").textContent = p.groups.guest || "open";
    this._container.querySelector("#pool-hg").textContent = p.groups.host || "open";
    this._container.querySelector("#pool-status").textContent =
      p.status || (p.phase === "ball_in_hand" ? "Tap table to place cue ball!" : mine ? "Tap felt to aim · Drag green/gold cue bar to shoot!" : "Watching opponent's aim live...");

    const bar = this._container.querySelector("#pool-strike-bar");
    const labelEl = this._container.querySelector("#pool-strike-label");
    if (bar && labelEl && this._draggingMode !== "pull") {
      bar.style.opacity = mine && p.phase === "aiming" ? "1" : "0.62";
      labelEl.textContent =
        p.phase === "shooting"
          ? "BALLS ROLLING..."
          : p.phase === "ball_in_hand"
          ? "TAP FELT ABOVE TO PLACE CUE BALL"
          : mine
          ? "DRAG HERE TO PULL CUE & SHOOT · 0%"
          : `${p.turn === "host" ? "HIM'S TURN (P2)" : "HER TURN (P1)"} · WATCHING`;
    }
  }

  _wireControls() {
    const c = this._canvas;
    const bar = this._container.querySelector("#pool-strike-bar");
    const fill = this._container.querySelector("#pool-power-fill");
    const labelEl = this._container.querySelector("#pool-strike-label");

    // 1. Wide Cue Pull-Back Strike Bar (mobile touch + mouse safe: drag in any direction & release)
    bar?.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.sfx.unlock();
      if (!this._pool || !this._isMyTurn(this._pool) || this._pool.phase !== "aiming") return;
      try { bar.setPointerCapture(e.pointerId); } catch (_) {}
      this._draggingMode = "pull";
      this._dragPointerId = e.pointerId;
      this._dragStart = { x: e.clientX, y: e.clientY };
      this._pullBack = 0.0;
      if (fill) fill.style.width = "0%";
      if (labelEl) labelEl.textContent = "PULLING CUE: 0% — SLIDE & RELEASE TO SHOOT";
    });

    const onPullMove = (e) => {
      if (this._draggingMode !== "pull" || !this._dragStart) return;
      const dist = Math.hypot(e.clientX - this._dragStart.x, e.clientY - this._dragStart.y);
      const pull = Math.max(0, Math.min(1, dist / 140));
      this._pullBack = pull;
      const pct = Math.round(pull * 100);
      if (fill) {
        fill.style.width = `${pct}%`;
        fill.style.background = pull <= 0.5 ? "linear-gradient(90deg,#22c55e,#eab308)" : "linear-gradient(90deg,#22c55e,#eab308 55%,#ef4444)";
      }
      if (labelEl) {
        const zone = pull < 0.08 ? "(PULL FURTHER)" : pull <= 0.50 ? "GREEN · SOFT" : pull <= 0.80 ? "YELLOW · MED" : "RED · BREAK";
        labelEl.textContent = pull >= 0.08
          ? `PULLING CUE: ${pct}% (${zone}) — RELEASE TO SHOOT`
          : `PULLING CUE: ${pct}% ${zone}`;
      }
      this._sendAimThrottled();
      this._syncMeshes(this._pool);
    };

    const finishPull = (shouldShoot) => {
      if (this._draggingMode !== "pull") return;
      const pwr = this._pullBack;
      this._draggingMode = null;
      this._dragPointerId = null;
      this._dragStart = null;
      this._pullBack = 0;
      if (fill) fill.style.width = "0%";
      if (shouldShoot && pwr >= 0.08) {
        this.sfx.play(pwr > 0.72 ? "pool_break" : "pool_clack");
        this.ws.action("pool", "shoot", { angle: this._angle, power: pwr, spinX: 0, spinY: this._spinY });
      } else {
        this._sendAimThrottled(true);
      }
      if (this._pool) {
        this._renderDOM(this._pool);
        this._syncMeshes(this._pool);
      }
    };

    this._boundWinMove = onPullMove;
    this._boundWinUp = (e) => {
      if (this._draggingMode === "pull") finishPull(true);
      if (this._draggingMode === "aim") this._draggingMode = null;
    };
    this._boundWinCancel = () => {
      if (this._draggingMode === "pull") finishPull(false);
      if (this._draggingMode === "aim") this._draggingMode = null;
    };
    window.addEventListener("pointermove", this._boundWinMove);
    window.addEventListener("pointerup", this._boundWinUp);
    window.addEventListener("pointercancel", this._boundWinCancel);

    // 2. Top-view Canvas touch/drag: raycast felt for Ball-In-Hand OR rotate aim toward finger
    c.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      this.sfx.unlock();
      if (!this._pool || !this._isMyTurn(this._pool) || !this._pub) return;
      try { c.setPointerCapture(e.pointerId); } catch (_) {}
      const rect = c.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      this._raycaster.setFromCamera(ndc, this._pub.camera);
      const hit = new THREE.Vector3();
      if (this._raycaster.ray.intersectPlane(this._feltPlane, hit)) {
        if (this._pool.phase === "ball_in_hand") {
          const px = Math.max(-0.92, Math.min(0.92, hit.x));
          const py = Math.max(-0.44, Math.min(0.44, -hit.z));
          this.ws.action("pool", "place", { x: px, y: py });
          return;
        }
        const cue = this._pool.balls.find((b) => b.n === 0);
        if (cue) {
          this._draggingMode = "aim";
          this._dragStart = { x: e.clientX, y: e.clientY, hitX: hit.x, hitZ: hit.z };
          this._angle = Math.atan2(-(hit.z + cue.y), hit.x - cue.x);
          this._sendAimThrottled(true);
          this._syncMeshes(this._pool);
        }
      }
    });
    c.addEventListener("pointermove", (e) => {
      if (this._draggingMode !== "aim" || !this._pool || !this._pub) return;
      const rect = c.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      this._raycaster.setFromCamera(ndc, this._pub.camera);
      const hit = new THREE.Vector3();
      if (this._raycaster.ray.intersectPlane(this._feltPlane, hit)) {
        const cue = this._pool.balls.find((b) => b.n === 0);
        if (cue) {
          this._angle = Math.atan2(-(hit.z + cue.y), hit.x - cue.x);
          this._sendAimThrottled();
          this._syncMeshes(this._pool);
        }
      }
    });
  }
}
