// 1:1 Krillion Vertical Ocean Plunge Engine (2px/m camera, depth creatures, tierlines, particles & shrimp colors)

export const TIER_SHRIMPS = {
  plankton:   { color: "#8fa3c4", glow: "rgba(143,163,196,0.65)", blub: "blub...", accent: "#5d7396" },
  too_clever: { color: "#ff9f43", glow: "rgba(255,159,67,0.75)",  blub: "bonk!",   accent: "#ffcf7d" },
  schooler:   { color: "#2dd4bf", glow: "rgba(45,212,191,0.78)",  blub: "glub!",   accent: "#99f6e4" },
  rare:       { color: "#ff5252", glow: "rgba(255,82,82,0.82)",   blub: "blorp!",  accent: "#ff9aa2" },
  deep_cut:   { color: "#9d7bff", glow: "rgba(157,123,255,0.85)", blub: "woah!",   accent: "#d6c4ff" },
  krillion:   { color: "#ffd166", glow: "rgba(255,209,102,0.98)", blub: "GOLD!!",  accent: "#fff1b8" },
  miss:       { color: "#64748b", glow: "rgba(100,116,139,0.55)", blub: "oops...", accent: "#94a3b8" },
};

const OCEAN_STOPS = [
  [0,    [29,  85,  128]],
  [150,  [18,  58,  94]],
  [350,  [11,  21,  38]],
  [800,  [8,   16,  32]],
  [1400, [5,   10,  20]],
  [2600, [3,   7,   15]],
  [5200, [2,   5,   11]],
];

const AMBIENT_LABELS = [
  [60,   "light begins to fade", "L"],
  [200,  "most sunlight stops here", "R"],
  [332,  "deepest scuba dive ever — 332m", "R"],
  [450,  "jellyfish belt", "L"],
  [620,  "sperm whales dive to hunt here", "L"],
  [800,  "siphonophore drift zone", "R"],
  [1040, "THE MIDNIGHT ZONE", "L", true],
  [1240, "anglerfish territory", "R"],
  [1850, "giant squid territory", "R"],
  [2500, "2°C water · utter darkness", "L"],
  [3000, "THE ABYSSAL ZONE", "L", true],
  [3200, "giant oarfish glide here", "R"],
  [3800, "the Titanic rests here — 3,800m", "R", true],
  [4400, "hydrothermal vents & cusk eels", "L"],
  [6000, "THE HADAL ZONE", "R", true],
];

// Deterministic catalog of depth creatures across [0..7000m]
function buildCreatures() {
  const list = [];
  // Surface & Sunlit reef fish schools (35m - 300m)
  for (let i = 0; i < 16; i++) {
    list.push({
      kind: "reef_fish",
      d: 35 + i * 17 + (i % 3) * 6,
      xFrac: (0.12 + i * 0.19) % 0.88,
      dir: i % 2 === 0 ? 1 : -1,
      spd: 22 + (i % 5) * 9,
      sz: 12 + (i % 4) * 4,
      hue: i % 3 === 0 ? "#ff9f43" : i % 3 === 1 ? "#4de3ff" : "#ff6aa8",
    });
  }
  // Sea turtles (190m - 360m)
  list.push({ kind: "turtle", d: 210, xFrac: 0.25, dir: 1, spd: 14, sz: 28 });
  list.push({ kind: "turtle", d: 340, xFrac: 0.72, dir: -1, spd: 12, sz: 24 });
  // Pulsing jellyfish (410m - 740m)
  for (let i = 0; i < 9; i++) {
    list.push({
      kind: "jelly",
      d: 410 + i * 38,
      xFrac: (0.1 + i * 0.23) % 0.86,
      dir: i % 2 === 0 ? 1 : -1,
      spd: 6 + (i % 3) * 3,
      sz: 18 + (i % 3) * 6,
      hue: i % 2 === 0 ? "#8de8ff" : "#d896ff",
    });
  }
  // Sperm whale silhouettes (540m, 1520m)
  list.push({ kind: "whale", d: 580, xFrac: 0.3, dir: 1, spd: 18, sz: 115 });
  list.push({ kind: "whale", d: 1540, xFrac: 0.75, dir: -1, spd: 16, sz: 120 });
  // Siphonophores + lanternfish (780m - 1220m)
  for (let i = 0; i < 8; i++) {
    list.push({ kind: "lantern", d: 780 + i * 52, xFrac: (0.15 + i * 0.17) % 0.84, dir: i % 2 ? 1 : -1, spd: 20, sz: 16 });
  }
  // Anglerfish (1180m - 1650m)
  list.push({ kind: "angler", d: 1220, xFrac: 0.78, dir: -1, spd: 13, sz: 34 });
  list.push({ kind: "angler", d: 1440, xFrac: 0.22, dir: 1, spd: 15, sz: 38 });
  // Giant squid (1780m - 2450m)
  list.push({ kind: "squid", d: 1860, xFrac: 0.32, dir: 1, spd: 21, sz: 68 });
  list.push({ kind: "squid", d: 2320, xFrac: 0.70, dir: -1, spd: 18, sz: 62 });
  // Oarfish & Titanic & Vents (2800m - 5200m)
  list.push({ kind: "oarfish", d: 3180, xFrac: 0.5, dir: 1, spd: 24, sz: 95 });
  list.push({ kind: "titanic", d: 3800, xFrac: 0.5, dir: 1, spd: 0, sz: 220 });
  list.push({ kind: "vents", d: 4420, xFrac: 0.3, dir: 1, spd: 0, sz: 60 });
  list.push({ kind: "vents", d: 4460, xFrac: 0.72, dir: 1, spd: 0, sz: 60 });
  // Roaming abyssal eels in deep cuts
  for (let d = 2600; d <= 6800; d += 380) {
    list.push({ kind: "lantern", d, xFrac: ((d * 17) % 80) / 100 + 0.1, dir: d % 760 === 0 ? 1 : -1, spd: 18, sz: 15 });
  }
  return list;
}

export class OceanDescentCanvas {
  constructor() {
    this.sea = null;
    this.fore = null;
    this.world = null;
    this.cameraDepth = 0;      // current visible depth center (m)
    this.targetDepth = 0;      // eases smoothly to targetDepth
    this.plungeSpeed = 0;
    this.plungeMode = null;    // null | "plunge" | "surface"
    this.particles = [];
    this.snow = Array.from({ length: 58 }, (_, i) => ({
      x: Math.random(),
      y: Math.random(),
      r: 0.8 + (i % 3) * 0.7,
      vy: 6 + (i % 4) * 5,
      a: 0.14 + (i % 5) * 0.05,
    }));
    this.swarm = [];           // horizontal darting fish for "too_clever"
    this.orbitFish = [];       // circling school around shrimp for "schooler"
    this.vortexAngle = 0;
    this.activeTier = "plankton";
    this.creatures = buildCreatures();
    this._tierlines = [];
    this._passedSet = new Set();
    this._plungeMeta = null;
    this._onTierCross = null;
    this._onPlungeEnd = null;
    this._lastTs = performance.now();
  }

  attach(seaEl, foreEl, worldEl) {
    this.sea = seaEl;
    this.fore = foreEl;
    this.world = worldEl;
    this._syncSizes();
  }

  _syncSizes() {
    for (const c of [this.sea, this.fore]) {
      if (!c) continue;
      const w = c.clientWidth || 440;
      const h = c.clientHeight || 620;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
        c.width = Math.round(w * dpr);
        c.height = Math.round(h * dpr);
      }
    }
  }

  screenYOfDepth(d, h) {
    // Anchor dive focus in the upper open water (0.24*h) so card at bottom never collides
    return (d - this.cameraDepth) * 2.0 + h * 0.24;
  }

  _oceanColorAt(depth) {
    const d = Math.max(0, depth);
    for (let i = 1; i < OCEAN_STOPS.length; i++) {
      const [d1, c1] = OCEAN_STOPS[i];
      const [d0, c0] = OCEAN_STOPS[i - 1];
      if (d <= d1) {
        const f = Math.max(0, Math.min(1, (d - d0) / Math.max(1, d1 - d0)));
        return [
          Math.round(c0[0] + (c1[0] - c0[0]) * f),
          Math.round(c0[1] + (c1[1] - c0[1]) * f),
          Math.round(c0[2] + (c1[2] - c0[2]) * f),
        ];
      }
    }
    return OCEAN_STOPS[OCEAN_STOPS.length - 1][1];
  }

  setStationaryDepth(depth) {
    this.targetDepth = depth;
    if (Math.abs(this.cameraDepth - depth) > 600) {
      this.cameraDepth = Math.max(0, depth - 140);
    }
  }

  startPlunge({ fromDepth, toDepth, deltaDepth, answerText, tierKey, ladder, onTierCross, onEnd }) {
    this.cameraDepth = fromDepth;
    this.targetDepth = toDepth;
    this.activeTier = tierKey || "miss";
    this._onTierCross = onTierCross;
    this._onPlungeEnd = onEnd;
    this._passedSet.clear();
    this.swarm = [];
    this.orbitFish = [];

    const tierInfo = TIER_SHRIMPS[this.activeTier] || TIER_SHRIMPS.plankton;
    const durMs = this.activeTier === "krillion" ? 3600 : this.activeTier === "deep_cut" ? 3200 : deltaDepth > 0 ? 2400 : 1200;

    // Build horizontal dashed tierlines in world container!
    if (this.world) {
      this.world.innerHTML = "";
      this._tierlines = [];
      if (deltaDepth > 0) {
        for (const t of ladder) {
          const td = fromDepth + t.depth;
          const el = document.createElement("div");
          el.className = "krill-tierline";
          el.style.setProperty("--tc", t.color);
          el.innerHTML = `<div class="tag">${t.label} · ${t.pts}</div>`;
          this.world.appendChild(el);
          this._tierlines.push({ d: td, el, tier: t.key, color: t.color });
        }
      }
      if (answerText) {
        const chip = document.createElement("div");
        chip.className = "krill-plunge-chip";
        chip.style.setProperty("--cc", tierInfo.color);
        chip.textContent = `“${String(answerText).toUpperCase()}”`;
        this.world.appendChild(chip);
        this._chipEl = chip;
      } else {
        this._chipEl = null;
      }
    }

    // Tier creature special FX
    if (this.activeTier === "too_clever") {
      for (let i = 0; i < 12; i++) {
        this.swarm.push({
          x: i % 2 ? -0.1 : 1.1,
          y: 0.25 + Math.random() * 0.5,
          vx: (i % 2 ? 1 : -1) * (0.45 + Math.random() * 0.55),
          hue: "#ff9f43",
          life: 2.8,
        });
      }
    } else if (this.activeTier === "schooler") {
      for (let i = 0; i < 6; i++) {
        this.orbitFish.push({ angle: (i / 6) * Math.PI * 2, r: 58 + (i % 2) * 14, life: 3.0 });
      }
    }

    this._plungeMeta = {
      startMs: performance.now(),
      durMs,
      fromDepth,
      toDepth,
      tierColor: tierInfo.color,
    };
  }

  burst(xPx, yPx, colorHex, count = 16) {
    for (let i = 0; i < count && this.particles.length < 180; i++) {
      const a = Math.random() * Math.PI * 2;
      const sp = 40 + Math.random() * 140;
      this.particles.push({
        x: xPx,
        y: yPx,
        vx: Math.cos(a) * sp,
        vy: Math.sin(a) * sp - 25,
        r: 2 + Math.random() * 3,
        col: colorHex,
        life: 0.6 + Math.random() * 0.5,
        maxLife: 1.1,
      });
    }
  }

  tick(nowMs) {
    const dt = Math.min(0.05, Math.max(0.001, (nowMs - this._lastTs) / 1000));
    this._lastTs = nowMs;
    this._syncSizes();
    if (!this.sea || !this.fore) return;

    const seaCtx = this.sea.getContext("2d");
    const foreCtx = this.fore.getContext("2d");
    const w = this.sea.width;
    const h = this.sea.height;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = w / dpr;
    const cssH = h / dpr;

    // 1. Advance camera plunge / ease
    let plungeProgress = 1;
    let plunging = false;
    if (this._plungeMeta) {
      plunging = true;
      plungeProgress = Math.min(1, (nowMs - this._plungeMeta.startMs) / this._plungeMeta.durMs);
      const e = plungeProgress < 0.5
        ? 4 * plungeProgress * plungeProgress * plungeProgress
        : 1 - Math.pow(-2 * plungeProgress + 2, 3) / 2;
      this.cameraDepth = this._plungeMeta.fromDepth + (this._plungeMeta.toDepth - this._plungeMeta.fromDepth) * e;

      // Bubble wake behind diving shrimp!
      if (plungeProgress < 0.92 && Math.random() < 0.72) {
        this.particles.push({
          x: cssW * 0.5 + (Math.random() - 0.5) * 34,
          y: cssH * 0.24,
          vx: (Math.random() - 0.5) * 26,
          vy: -45 - Math.random() * 65,
          r: 2 + Math.random() * 3.5,
          col: this._plungeMeta.tierColor,
          life: 0.9,
          maxLife: 0.9,
        });
      }

      if (plungeProgress >= 1) {
        const doneCb = this._onPlungeEnd;
        this._plungeMeta = null;
        this._onPlungeEnd = null;
        if (doneCb) doneCb();
      }
    } else {
      this.cameraDepth += (this.targetDepth - this.cameraDepth) * Math.min(1, dt * 4.5);
    }

    // 2. Render Ocean Background Canvas (#krill-sea)
    seaCtx.save();
    seaCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const topD = this.cameraDepth - (cssH * 0.45) / 2;
    const botD = this.cameraDepth + (cssH * 0.55) / 2;
    const cTop = this._oceanColorAt(topD);
    const cBot = this._oceanColorAt(botD);
    const bgGrad = seaCtx.createLinearGradient(0, 0, 0, cssH);
    bgGrad.addColorStop(0, `rgb(${cTop[0]},${cTop[1]},${cTop[2]})`);
    bgGrad.addColorStop(1, `rgb(${cBot[0]},${cBot[1]},${cBot[2]})`);
    seaCtx.fillStyle = bgGrad;
    seaCtx.fillRect(0, 0, cssW, cssH);

    // Sunlit Sky & Animated Surface Waves when 0m is near viewport!
    const surfY = this.screenYOfDepth(0, cssH);
    if (surfY > -30) {
      const skyGrad = seaCtx.createLinearGradient(0, 0, 0, Math.max(20, surfY));
      skyGrad.addColorStop(0, "#79c7eb");
      skyGrad.addColorStop(1, "#cdeeff");
      seaCtx.fillStyle = skyGrad;
      seaCtx.fillRect(0, 0, cssW, Math.max(0, surfY));

      seaCtx.beginPath();
      seaCtx.moveTo(0, cssH);
      for (let x = 0; x <= cssW + 12; x += 12) {
        const wy = surfY + Math.sin(x * 0.025 + nowMs * 0.0024) * 5 + Math.cos(x * 0.045 - nowMs * 0.0018) * 3;
        seaCtx.lineTo(x, wy);
      }
      seaCtx.lineTo(cssW, cssH);
      seaCtx.closePath();
      seaCtx.fillStyle = bgGrad;
      seaCtx.fill();

      // Sunbeam shafts descending into shallow water
      const rayAlpha = Math.max(0, Math.min(0.16, 1 - this.cameraDepth / 180));
      if (rayAlpha > 0.01) {
        seaCtx.fillStyle = `rgba(175, 240, 255, ${rayAlpha.toFixed(3)})`;
        for (let r = 0; r < 4; r++) {
          const rx = cssW * (0.15 + r * 0.24) + Math.sin(nowMs * 0.0007 + r) * 14;
          seaCtx.beginPath();
          seaCtx.moveTo(rx, surfY);
          seaCtx.lineTo(rx + 26, surfY);
          seaCtx.lineTo(rx + 120, Math.min(cssH, surfY + 340));
          seaCtx.lineTo(rx + 42, Math.min(cssH, surfY + 340));
          seaCtx.closePath();
          seaCtx.fill();
        }
      }
    }

    // Floating Left/Right Ambient Zone Captions at real depths (inset left of right depth ruler)
    seaCtx.font = "700 11px ui-monospace, monospace";
    for (const [d, label, side, bold] of AMBIENT_LABELS) {
      const sy = this.screenYOfDepth(d, cssH);
      if (sy < -30 || sy > cssH + 30) continue;
      seaCtx.fillStyle = bold ? "rgba(108, 229, 255, 0.72)" : "rgba(160, 185, 218, 0.45)";
      seaCtx.textAlign = side === "R" ? "right" : "left";
      seaCtx.fillText(label, side === "R" ? cssW - 56 : 16, sy);
    }
    seaCtx.restore();

    // 3. Position HTML world tierlines & chip at exact depth*2
    if (this.world) {
      for (const tl of this._tierlines) {
        const ly = this.screenYOfDepth(tl.d, cssH);
        tl.el.style.top = `${ly.toFixed(1)}px`;
        tl.el.style.opacity = (ly > -40 && ly < cssH + 40) ? "1" : "0";
        if (!this._passedSet.has(tl.tier) && ly <= cssH * 0.24) {
          this._passedSet.add(tl.tier);
          tl.el.classList.add("is-passed");
          this.burst(cssW * 0.5, cssH * 0.24, tl.color, 18);
          if (this._onTierCross) this._onTierCross(tl.tier);
        }
      }
      if (this._chipEl) {
        this._chipEl.style.top = `${(cssH * 0.24 + 34).toFixed(1)}px`;
        this._chipEl.style.opacity = plunging ? "1" : "0";
      }
    }

    // 4. Foreground Ocean Canvas: Marine Snow + Depth Sea Creatures + Tier VFX + Particles
    foreCtx.save();
    foreCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    foreCtx.clearRect(0, 0, cssW, cssH);

    // Marine snow drifting gently opposite plunge velocity
    for (const s of this.snow) {
      s.y = (s.y - (s.vy * dt) / Math.max(cssH, 400) + 1) % 1;
      const px = (s.x * cssW + Math.sin(nowMs * 0.001 + s.x * 10) * 8) % cssW;
      const py = ((s.y * cssH - (this.cameraDepth * 0.8)) % cssH + cssH) % cssH;
      foreCtx.fillStyle = `rgba(205, 232, 255, ${s.a})`;
      foreCtx.beginPath();
      foreCtx.arc(px, py, s.r, 0, Math.PI * 2);
      foreCtx.fill();
    }

    // Distinct Depth-Specific Fish & Landmarks
    const tS = nowMs * 0.001;
    for (const cr of this.creatures) {
      const sy = this.screenYOfDepth(cr.d, cssH);
      if (sy < -140 || sy > cssH + 140) continue;
      let cx = ((cr.xFrac * cssW + cr.dir * cr.spd * tS) % (cssW + 160));
      if (cx < -80) cx += cssW + 160;
      else cx -= 80;

      if (cr.kind === "titanic") cx = cssW * 0.5;
      if (cr.kind === "vents") cx = cr.xFrac * cssW;
      this._drawCreature(foreCtx, cr, cx, sy, tS);
    }

    // Too-Clever horizontal clown-orange fish swarm
    for (let i = this.swarm.length - 1; i >= 0; i--) {
      const f = this.swarm[i];
      f.life -= dt;
      f.x += f.vx * dt;
      if (f.life <= 0) { this.swarm.splice(i, 1); continue; }
      this._drawSmallFish(foreCtx, f.x * cssW, f.y * cssH, 13, f.vx > 0 ? 1 : -1, f.hue, tS + i);
    }

    // Schooler orbiting fish school around shrimp center
    for (let i = this.orbitFish.length - 1; i >= 0; i--) {
      const of = this.orbitFish[i];
      of.life -= dt;
      of.angle += dt * 3.1;
      if (of.life <= 0) { this.orbitFish.splice(i, 1); continue; }
      const fx = cssW * 0.5 + Math.cos(of.angle) * of.r;
      const fy = cssH * 0.45 + Math.sin(of.angle) * (of.r * 0.55);
      this._drawSmallFish(foreCtx, fx, fy, 11, -Math.sin(of.angle) >= 0 ? 1 : -1, "#2dd4bf", tS + i);
    }

    // Krillion 24k Gold Vortex swirling rings
    if (this._plungeMeta && this.activeTier === "krillion") {
      this.vortexAngle += dt * 4.5;
      foreCtx.strokeStyle = "rgba(255, 209, 102, 0.55)";
      foreCtx.lineWidth = 2.5;
      for (let r = 0; r < 3; r++) {
        foreCtx.beginPath();
        foreCtx.arc(cssW * 0.5, cssH * 0.45, 36 + r * 22, this.vortexAngle + r * 2.1, this.vortexAngle + r * 2.1 + 1.8);
        foreCtx.stroke();
      }
    }

    // Particles (bubbles & tierline burst sparks)
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      p.life -= dt;
      if (p.life <= 0) { this.particles.splice(i, 1); continue; }
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      foreCtx.globalAlpha = Math.max(0, p.life / p.maxLife);
      foreCtx.fillStyle = p.col || "#4de3ff";
      foreCtx.beginPath();
      foreCtx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      foreCtx.fill();
    }
    foreCtx.globalAlpha = 1;
    foreCtx.restore();
  }

  _drawSmallFish(ctx, x, y, sz, dir, color, phase) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(dir, 1);
    const wag = Math.sin(phase * 10) * 0.35;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.ellipse(0, 0, sz, sz * 0.48, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(-sz * 0.85, 0);
    ctx.lineTo(-sz * 1.45, -sz * 0.42 + wag * sz);
    ctx.lineTo(-sz * 1.45, sz * 0.42 + wag * sz);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#081222";
    ctx.beginPath();
    ctx.arc(sz * 0.45, -sz * 0.1, Math.max(1.5, sz * 0.14), 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  _drawCreature(ctx, cr, x, y, tS) {
    ctx.save();
    if (cr.kind === "reef_fish") {
      this._drawSmallFish(ctx, x, y + Math.sin(tS * 2 + cr.d) * 5, cr.sz, cr.dir, cr.hue, tS + cr.d);
    } else if (cr.kind === "turtle") {
      ctx.translate(x, y);
      ctx.scale(cr.dir, 1);
      ctx.fillStyle = "#48b58a";
      ctx.beginPath();
      ctx.ellipse(0, 0, cr.sz, cr.sz * 0.56, 0, Math.PI, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#6ed6a8";
      const flap = Math.sin(tS * 3) * 6;
      ctx.beginPath();
      ctx.ellipse(cr.sz * 0.35, 4 + flap, cr.sz * 0.38, 6, 0.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(cr.sz * 1.05, -2, 7, 0, Math.PI * 2);
      ctx.fill();
    } else if (cr.kind === "jelly") {
      const pulse = Math.sin(tS * 3 + cr.d) * 0.16;
      ctx.translate(x, y + Math.sin(tS * 1.5 + cr.d) * 10);
      ctx.strokeStyle = cr.hue;
      ctx.globalAlpha = 0.65;
      ctx.lineWidth = 1.6;
      for (let t = -2; t <= 2; t++) {
        ctx.beginPath();
        ctx.moveTo(t * 5, 4);
        ctx.quadraticCurveTo(t * 7 + Math.sin(tS * 4 + t) * 8, cr.sz * 0.9, t * 6, cr.sz * 1.7);
        ctx.stroke();
      }
      ctx.fillStyle = cr.hue;
      ctx.globalAlpha = 0.52;
      ctx.beginPath();
      ctx.ellipse(0, 0, cr.sz * (1 - pulse), cr.sz * (0.65 + pulse), 0, Math.PI, Math.PI * 2);
      ctx.fill();
    } else if (cr.kind === "whale") {
      ctx.translate(x, y);
      ctx.scale(cr.dir, 1);
      ctx.fillStyle = "rgba(18, 36, 68, 0.72)";
      ctx.beginPath();
      ctx.ellipse(0, 0, cr.sz * 0.6, cr.sz * 0.22, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(-cr.sz * 0.55, 0);
      ctx.lineTo(-cr.sz * 0.85, -cr.sz * 0.18);
      ctx.lineTo(-cr.sz * 0.80, cr.sz * 0.18);
      ctx.closePath();
      ctx.fill();
    } else if (cr.kind === "lantern") {
      this._drawSmallFish(ctx, x, y, cr.sz, cr.dir, "#365480", tS + cr.d);
      ctx.fillStyle = "#6ce5ff";
      ctx.beginPath();
      ctx.arc(x + cr.dir * cr.sz * 0.45, y - 2, 2.8, 0, Math.PI * 2);
      ctx.fill();
    } else if (cr.kind === "angler") {
      ctx.translate(x, y);
      ctx.scale(cr.dir, 1);
      ctx.fillStyle = "#4c356e";
      ctx.beginPath();
      ctx.ellipse(0, 0, cr.sz * 0.7, cr.sz * 0.55, 0, 0, Math.PI * 2);
      ctx.fill();
      // Lit dangling esca lure
      ctx.strokeStyle = "#b98aff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cr.sz * 0.35, -cr.sz * 0.45);
      ctx.quadraticCurveTo(cr.sz * 0.9, -cr.sz * 0.95, cr.sz * 1.15, -cr.sz * 0.2);
      ctx.stroke();
      ctx.fillStyle = "#ffd166";
      ctx.shadowColor = "#ffd166";
      ctx.shadowBlur = 14;
      ctx.beginPath();
      ctx.arc(cr.sz * 1.15, -cr.sz * 0.2, 4.8, 0, Math.PI * 2);
      ctx.fill();
    } else if (cr.kind === "squid") {
      ctx.translate(x, y);
      ctx.scale(cr.dir, 1);
      ctx.fillStyle = "rgba(180, 70, 95, 0.75)";
      ctx.beginPath();
      ctx.ellipse(cr.sz * 0.2, 0, cr.sz * 0.48, cr.sz * 0.16, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(215, 95, 120, 0.7)";
      ctx.lineWidth = 2.4;
      for (let t = -2; t <= 2; t++) {
        ctx.beginPath();
        ctx.moveTo(-cr.sz * 0.22, t * 4);
        ctx.quadraticCurveTo(-cr.sz * 0.65, t * 6 + Math.sin(tS * 4 + t) * 10, -cr.sz * 1.05, t * 5);
        ctx.stroke();
      }
    } else if (cr.kind === "oarfish") {
      ctx.translate(x, y);
      ctx.strokeStyle = "#d8e6f8";
      ctx.lineWidth = 6;
      ctx.beginPath();
      for (let i = -cr.sz; i <= cr.sz; i += 8) {
        const oy = Math.sin(i * 0.08 + tS * 5) * 9;
        if (i === -cr.sz) ctx.moveTo(i, oy);
        else ctx.lineTo(i, oy);
      }
      ctx.stroke();
      ctx.fillStyle = "#ff4f6e";
      ctx.beginPath();
      ctx.arc(cr.sz, Math.sin(cr.sz * 0.08 + tS * 5) * 9 - 4, 6, 0, Math.PI * 2);
      ctx.fill();
    } else if (cr.kind === "titanic") {
      ctx.translate(x, y);
      ctx.fillStyle = "rgba(25, 36, 56, 0.85)";
      ctx.beginPath();
      ctx.moveTo(-110, 12);
      ctx.lineTo(120, -4);
      ctx.lineTo(95, 32);
      ctx.lineTo(-98, 32);
      ctx.closePath();
      ctx.fill();
      // Funnels
      for (const fx of [-45, -12, 22]) {
        ctx.fillRect(fx, -28, 12, 26);
      }
    } else if (cr.kind === "vents") {
      ctx.translate(x, y);
      ctx.fillStyle = "rgba(38, 22, 22, 0.9)";
      ctx.beginPath();
      ctx.moveTo(-20, 24);
      ctx.lineTo(-8, -16);
      ctx.lineTo(8, -16);
      ctx.lineTo(20, 24);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = `rgba(255, 110, 40, ${0.4 + Math.sin(tS * 6) * 0.25})`;
      ctx.beginPath();
      ctx.arc(0, -18, 9, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }
}
