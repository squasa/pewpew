// 1:1 Krillion UI, UX, Animations, Sounds, Autofill Confirmation, Wardrobe, Keep Diving & Customizer
import { OceanDescentCanvas, TIER_SHRIMPS } from "./krill_ocean.js";

const KRILL_SHELLS = [
  { id: "coral", name: "Coral Classic", color: "#ff4d7e" },
  { id: "cyan", name: "Biolume Cyan", color: "#6ce5ff" },
  { id: "gold", name: "Reef Gold", color: "#ffd464" },
  { id: "violet", name: "Abyssal Violet", color: "#b98aff" },
  { id: "pearl", name: "Pearl Ghost", color: "#eef7ff" },
];

const KRILL_GEAR = [
  { id: "none", name: "Natural" },
  { id: "crown", name: "Crown" },
  { id: "helmet", name: "Dive Helmet" },
  { id: "shades", name: "Tiny Shades" },
  { id: "halo", name: "Biolume Halo" },
];

export class RareAnswerView {
  constructor(ws, sfx, onBackHome) {
    this.ws = ws;
    this.sfx = sfx;
    this.onBackHome = onBackHome;
    this.drawer = null; // null | "settings" | "menu" | "wardrobe" | "customize"
    this.modeChoice = "couples";
    this._lastPhaseKey = "";
    this._lastTimerSync = { serverTime: 0, wallMs: performance.now(), phase: "idle" };
    this._raf = null;
    this._autofilledValue = null;
    this._localFeedback = null;
    this._copiedAt = 0;
    this._root = null;
    this._state = null;
    this._howToOpen = false;
    this._wardrobe = this._loadWardrobe();
    this._preRevealTotals = { guest: { pts: 0, depth: 0 }, host: { pts: 0, depth: 0 } };
    this._lastRevealKey = "";
    this._submitPending = false;
    this._animTimers = [];
    this._countRaf = null;
    this._ocean = new OceanDescentCanvas();
    this._activeTierKey = null;
    this._lastUrgentSec = -1;
  }

  _clearAnimTimers() {
    while (this._animTimers.length) {
      clearTimeout(this._animTimers.pop());
    }
    if (this._countRaf) {
      cancelAnimationFrame(this._countRaf);
      this._countRaf = null;
    }
  }

  _zoneForDepth(depth) {
    if (depth < 200) return { name: "SUNLIT ZONE", top: "rgba(22, 92, 134, 0.48)", mid: "rgba(9, 34, 62, 0.45)", bot: "rgba(3, 12, 26, 0.72)" };
    if (depth < 1000) return { name: "REEF SHELF", top: "rgba(16, 70, 114, 0.46)", mid: "rgba(7, 26, 54, 0.50)", bot: "rgba(2, 9, 22, 0.76)" };
    if (depth < 2200) return { name: "TWILIGHT ZONE", top: "rgba(14, 46, 92, 0.44)", mid: "rgba(6, 19, 44, 0.56)", bot: "rgba(2, 7, 18, 0.82)" };
    if (depth < 3800) return { name: "MIDNIGHT ZONE", top: "rgba(14, 28, 72, 0.42)", mid: "rgba(5, 12, 32, 0.64)", bot: "rgba(1, 5, 13, 0.88)" };
    if (depth < 5400) return { name: "ABYSSAL ZONE", top: "rgba(24, 16, 62, 0.42)", mid: "rgba(6, 8, 26, 0.72)", bot: "rgba(1, 3, 9, 0.92)" };
    return { name: "HADAL TRENCH", top: "rgba(36, 10, 50, 0.44)", mid: "rgba(8, 5, 20, 0.78)", bot: "rgba(1, 2, 6, 0.96)" };
  }

  _loadWardrobe() {
    try {
      const saved = JSON.parse(localStorage.getItem("pewpew_krill_wardrobe") || "{}");
      return {
        shell: saved.shell || "#ff4d7e",
        gear: saved.gear || "none",
      };
    } catch (_) {
      return { shell: "#ff4d7e", gear: "none" };
    }
  }

  _saveWardrobe() {
    try {
      localStorage.setItem("pewpew_krill_wardrobe", JSON.stringify(this._wardrobe));
    } catch (_) {}
  }

  mount(container, state) {
    this._container = container;
    this._lastPhaseKey = "";
    this.update(state);
    this._startRaf();
  }

  unmount() {
    this._clearAnimTimers();
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    this._root = null;
  }

  _startRaf() {
    const tick = (now) => {
      this._tickTimerVisuals();
      if (this._ocean) {
        this._ocean.tick(now || performance.now());
      }
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  _tickTimerVisuals() {
    if (!this._root || !this._state) return;
    const ra = this._state.rare_answer;
    if (!ra) return;
    const elapsed = (performance.now() - this._lastTimerSync.wallMs) / 1000.0;
    const rem = Math.max(0, this._lastTimerSync.serverTime - elapsed);

    if (ra.phase === "preview") {
      this._lastUrgentSec = -1;
      const countEl = this._root.querySelector("#krill-preview-num");
      if (countEl) {
        countEl.textContent = String(Math.max(1, Math.ceil(rem)));
      }
    } else if (ra.phase === "answering") {
      const total = ra.mode === "puffer"
        ? Math.max(1, ra.puffer?.fuse || ra.answerTotal || 10.5)
        : Math.max(1, ra.answerTotal || 25);
      const frac = Math.max(0, Math.min(1, rem / total));
      const numEl = this._root.querySelector("#krill-radar-num");
      const ringEl = this._root.querySelector("#krill-radar-ring");
      const barEl = this._root.querySelector("#krill-bottom-fill");
      const bombEl = this._root.querySelector("#krill-puffer-bomb");
      if (bombEl) {
        bombEl.style.setProperty("--puffer-heat", (1 - frac).toFixed(3));
      }
      if (rem > 0.05 && rem <= 5.0) {
        const sec = Math.ceil(rem);
        if (sec !== this._lastUrgentSec) {
          this._lastUrgentSec = sec;
          this.sfx.play("krill_tick");
        }
      } else if (rem > 5.0) {
        this._lastUrgentSec = -1;
      }
      if (numEl) {
        numEl.textContent = String(Math.ceil(rem));
        numEl.classList.toggle("urgent", rem <= 5.0);
      }
      if (ringEl) {
        const circ = 2 * Math.PI * 27;
        ringEl.setAttribute("stroke-dasharray", String(circ));
        ringEl.setAttribute("stroke-dashoffset", String(circ * (1 - frac)));
        ringEl.setAttribute("stroke", rem <= 5.0 ? "var(--accent-pink)" : (rem <= 10 ? "#ffd464" : "var(--accent-cyan)"));
      }
      if (barEl) {
        barEl.style.width = `${(frac * 100).toFixed(2)}%`;
      }
    }
  }

  _applyThemeVars(theme) {
    if (!theme) return;
    const rootStyle = document.documentElement.style;
    if (theme.accentCyan) rootStyle.setProperty("--accent-cyan", theme.accentCyan);
    if (theme.accentPink) rootStyle.setProperty("--accent-pink", theme.accentPink);
    if (theme.mascotAccent) rootStyle.setProperty("--mascot-accent", theme.mascotAccent);
    if (theme.bgSurface) rootStyle.setProperty("--bg-surface", theme.bgSurface);
    if (theme.bgAbyss) rootStyle.setProperty("--bg-abyss", theme.bgAbyss);
  }

  onAck(msg) {
    if (msg.type !== "krill_ack" || !msg.res) return;
    this._submitPending = false;
    const res = msg.res;
    this._localFeedback = res;
    if (res.status === "confirm") {
      this.sfx.play("krill_ping");
      const inp = this._root?.querySelector("#krill-ans-input");
      if (inp && res.suggested) {
        this._autofilledValue = res.suggested;
        inp.value = res.suggested;
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
      }
      this._renderFeedbackBanner(res);
      this._syncSubmitBtn();
    } else if (res.status === "no_echo") {
      this.sfx.play("krill_reject");
      const inp = this._root?.querySelector("#krill-ans-input");
      const form = this._root?.querySelector("#krill-form");
      if (form) {
        form.classList.remove("is-shake");
        void form.offsetWidth;
        form.classList.add("is-shake");
      }
      if (inp && res.clearInput) {
        inp.value = "";
        this._autofilledValue = null;
      }
      if (inp) inp.focus();
      this._renderFeedbackBanner(res);
      this._syncSubmitBtn();
    } else if (res.status === "scored") {
      this._autofilledValue = null;
      this._localFeedback = null;
      const inp = this._root?.querySelector("#krill-ans-input");
      if (inp && this._state?.rare_answer?.mode === "puffer") {
        inp.value = "";
        inp.focus();
      }
      this.sfx.play("krill_ping");
    }
  }

  update(state) {
    this._state = state;
    const ra = state.rare_answer;
    if (!ra || !this._container) return;

    this._applyThemeVars(ra.theme);
    this._lastTimerSync = {
      serverTime: Number(ra.timer || 0),
      wallMs: performance.now(),
      phase: ra.phase,
    };

    const role = this.ws.role === "host" ? "host" : "guest";
    const oppRole = role === "guest" ? "host" : "guest";
    const settings = (ra.settings && ra.settings[role]) || {};

    if (ra.phase === "idle" || ra.phase === "preview" || ra.phase === "answering") {
      const ptsKey = role === "host" ? "hostPts" : "guestPts";
      const depthKey = role === "host" ? "hostDepth" : "guestDepth";
      this._preRevealTotals[role] = {
        pts: ra.totals?.[ptsKey] || 0,
        depth: ra.totals?.[depthKey] || 0,
      };
      if (ra.phase === "idle") {
        this._lastRevealKey = "";
        this._activeTierKey = null;
        this._lastUrgentSec = -1;
      }
    }

    const pf = ra.puffer || null;
    const pfKey = pf
      ? `${pf.turnIdx}|${(pf.used || []).length}|${(pf.players || []).map((p) => p.hearts).join(",")}|${pf.lastEvent?.type || ""}|${pf.winner || ""}`
      : "";

    // Notice: do NOT include opponent lock status in phaseKey so typing mid-round is never interrupted!
    const phaseKey = [
      ra.phase,
      ra.roundIdx,
      ra.mode,
      ra.totalRounds,
      ra.locked?.[role] ? "L" : "U",
      this.drawer || "",
      settings.lowPower ? "LP" : "",
      settings.colorblind ? "CB" : "",
      settings.couplesJinx === false ? "NJ" : "JN",
      this.modeChoice,
      this.pufferPlayers,
      pfKey,
      this._howToOpen ? "HT" : "",
      this._wardrobe.shell,
      this._wardrobe.gear,
      ra.forfeit || "",
    ].join("|");

    if (phaseKey !== this._lastPhaseKey) {
      this._submitPending = false;
      if (ra.phase === "preview" && !this._lastPhaseKey.startsWith("preview|")) {
        this._lastUrgentSec = -1;
        this.sfx.play("bubble");
      } else if (ra.phase === "answering" && this._lastPhaseKey.startsWith("preview|")) {
        this._lastUrgentSec = -1;
        this.sfx.play("krill_ping");
        this._localFeedback = null;
        this._autofilledValue = null;
      } else if (ra.phase === "reveal" && !this._lastPhaseKey.startsWith("reveal|")) {
        if (settings.lowPower) {
          const row = ra.history?.[ra.history.length - 1];
          const mine = row?.[role] || {};
          const tk = (row?.jinx || !mine.tierKey || mine.tierKey === "timeout" || (mine.depth || 0) <= 0) ? "miss" : mine.tierKey;
          this._activeTierKey = tk;
          if (row?.jinx) this.sfx.play("jinx");
          else if (tk === "krillion") this.sfx.play("krill_gold");
          else if (tk === "rare" || tk === "deep_cut") this.sfx.play("krill_land_big");
          else if (tk === "miss") this.sfx.play("krill_miss");
          else this.sfx.play("krill_land_small");
        }
      } else if (ra.phase === "surface" && !this._lastPhaseKey.startsWith("surface|")) {
        this.sfx.play("krill_surface");
        this.sfx.play("win");
      }
      this._lastPhaseKey = phaseKey;
      this._renderFull(ra, role, settings);
    } else if (ra.phase === "answering") {
      const oppEl = this._root?.querySelector("#krill-opp-status");
      if (oppEl && ra.mode === "couples") {
        const oppLocked = Boolean(ra.locked?.[oppRole]);
        oppEl.textContent = oppLocked ? "PARTNER: LOCKED ✓" : "PARTNER: THINKING…";
        oppEl.style.color = oppLocked ? "var(--green)" : "var(--accent-cyan)";
      }
    }
  }

  _krillMascotSvg(theme, size = 54, tierKey = null) {
    const tierInfo = tierKey ? TIER_SHRIMPS[tierKey] : null;
    const body = tierInfo?.color || this._wardrobe.shell || theme?.mascotAccent || "#ff4d7e";
    const accent = tierInfo?.accent || "#6ce5ff";
    const isGold = tierKey === "krillion";
    const isMiss = tierKey === "miss" || tierKey === "timeout" || tierKey === "jinx";
    const gear = this._wardrobe.gear || "none";
    let gearSvg = "";
    if (gear === "crown") {
      gearSvg = `<path d="M26 21 L29 12 L34 18 L39 11 L43 20 Z" fill="#ffd464" stroke="#996b00" stroke-width="1.2"/>`;
    } else if (gear === "helmet") {
      gearSvg = `<circle cx="38" cy="32" r="19" fill="rgba(108,229,255,0.14)" stroke="#6ce5ff" stroke-width="2" stroke-dasharray="4,2"/>`;
    } else if (gear === "shades") {
      gearSvg = `<rect x="40" y="25" width="11" height="5" rx="1.5" fill="#101828" stroke="#6ce5ff" stroke-width="1"/>`;
    } else if (gear === "halo") {
      gearSvg = `<ellipse cx="38" cy="15" rx="11" ry="3.5" fill="none" stroke="#ffd464" stroke-width="2.2"/>`;
    }
    const eyeSvg = isMiss
      ? `<path d="M44 26 L48 30 M48 26 L44 30" stroke="#081222" stroke-width="1.9" stroke-linecap="round"/>`
      : isGold
        ? `<circle cx="46" cy="28" r="3" fill="#071224"/><circle cx="47" cy="27" r="1.2" fill="#fff7b8"/><path d="M53 20 L55 16 L57 20 L61 22 L57 24 L55 28 L53 24 L49 22 Z" fill="#ffe580" opacity="0.9"/>`
        : `<circle cx="46" cy="28" r="2.7" fill="#030914"/><circle cx="46.8" cy="27.2" r="1.0" fill="#fff"/>`;

    return `
      <svg width="${size}" height="${size}" viewBox="0 0 64 64" fill="none" aria-hidden="true">
        <!-- Articulated uropod tail fan -->
        <path d="M12 37 C5 31, 4 40, 12 40 Z" fill="${body}" opacity="0.88"/>
        <path d="M13 39 C6 42, 8 49, 16 44 Z" fill="${accent}" opacity="0.82"/>
        <!-- Segmented curved shrimp abdomen & carapace -->
        <ellipse cx="20" cy="39" rx="6.5" ry="5.5" fill="${body}" opacity="0.9"/>
        <ellipse cx="27" cy="35" rx="8" ry="7.2" fill="${body}" opacity="0.94"/>
        <ellipse cx="36" cy="32" rx="10.5" ry="9" fill="${body}"/>
        <ellipse cx="44" cy="30" rx="8.5" ry="7.5" fill="${body}"/>
        <!-- Shell ridge & sheen lines -->
        <path d="M23 30 Q26 35 23 41 M30 26 Q33 33 30 40 M37 24 Q40 31 37 38" stroke="${accent}" stroke-width="1.35" stroke-opacity="0.55" stroke-linecap="round"/>
        <ellipse cx="38" cy="26.5" rx="7" ry="2.2" fill="#ffffff" opacity="${isGold ? 0.42 : 0.22}"/>
        <!-- Dual sweeping whiskers / antennae -->
        <path d="M51 27 C57 20, 60 14, 62 10" stroke="${accent}" stroke-width="2" stroke-linecap="round"/>
        <path d="M51 31 C58 27, 61 25, 63 21" stroke="${accent}" stroke-width="1.6" stroke-linecap="round"/>
        <!-- Swimmeret pleopod legs -->
        <path d="M25 43 L22 50 M31 43 L29 51 M37 41 L36 50 M42 39 L43 47" stroke="${body}" stroke-width="2" stroke-linecap="round"/>
        ${eyeSvg}
        ${gearSvg}
      </svg>`;
  }

  _bubbleHtml(lowPower) {
    if (lowPower) return "";
    const specs = [
      { left: "8%", sz: 7, dur: "7.5s", del: "0s" },
      { left: "24%", sz: 12, dur: "10s", del: "1.4s" },
      { left: "46%", sz: 6, dur: "6.8s", del: "2.8s" },
      { left: "68%", sz: 10, dur: "9.2s", del: "0.8s" },
      { left: "86%", sz: 14, dur: "11s", del: "3.2s" },
    ];
    return `<div class="krill-bubbles">${specs.map(
      (b) => `<span class="krill-bubble" style="left:${b.left};width:${b.sz}px;height:${b.sz}px;animation-duration:${b.dur};animation-delay:${b.del};"></span>`
    ).join("")}</div>`;
  }

  _buildTilesAndLabel(ra, role) {
    if (ra.mode === "puffer") {
      const players = ra.puffer?.players || [];
      const alive = players.filter((p) => p.alive).length;
      const pips = players.map((p) => {
        const cls = !p.alive ? "done-timeout" : p.idx === ra.puffer?.turnIdx ? "active" : "done-rare";
        return `<span class="krill-tile ${cls}"></span>`;
      }).join("");
      const label = ra.phase === "surface"
        ? "CIRCLE OVER"
        : `CIRCLE PARTY · ${alive} LEFT`;
      return `
        <div class="krill-tiles-col">
          <div class="krill-tiles-row">${pips}</div>
          <div class="krill-prompt-meta">${label}</div>
        </div>
      `;
    }

    const total = ra.totalRounds || 7;
    const hist = ra.history || [];
    const tiles = Array.from({ length: total }, (_, idx) => {
      if (idx < hist.length) {
        const tk = hist[idx]?.[role]?.tierKey || "timeout";
        return `<span class="krill-tile done-${tk}"></span>`;
      }
      if (idx === ra.roundIdx && (ra.phase === "preview" || ra.phase === "answering" || ra.phase === "reveal")) {
        return `<span class="krill-tile active"></span>`;
      }
      return `<span class="krill-tile"></span>`;
    }).join("");

    let label = `${total} QUESTIONS · ${ra.answerTotal || 25}S`;
    if (ra.phase === "surface") label = "ALL DONE";
    else if (ra.phase !== "idle") label = `QUESTION ${(ra.roundIdx || 0) + 1} OF ${total}`;

    return `
      <div class="krill-tiles-col">
        <div class="krill-tiles-row">${tiles}</div>
        <div class="krill-prompt-meta">${label}</div>
      </div>
    `;
  }

  _diveStreaksHtml(lowPower) {
    if (lowPower) return "";
    let html = `<div class="krill-dive-streaks" aria-hidden="true">`;
    for (let i = 0; i < 14; i++) {
      const left = (4 + ((i * 7) % 92)).toFixed(1);
      const h = 42 + ((i * 19) % 72);
      const delay = (-(i * 0.09)).toFixed(2);
      const dur = (0.48 + (i % 4) * 0.11).toFixed(2);
      html += `<span class="krill-streak-line" style="left:${left}%;height:${h}px;animation-delay:${delay}s;animation-duration:${dur}s;"></span>`;
    }
    return html + `</div>`;
  }

  _renderFull(ra, role, settings) {
    this._clearAnimTimers();
    const theme = ra.theme || {};
    const ptsKey = role === "host" ? "hostPts" : "guestPts";
    const depthKey = role === "host" ? "hostDepth" : "guestDepth";
    const curPts = ra.totals?.[ptsKey] || 0;
    const curDepth = ra.totals?.[depthKey] || 0;
    const maxDepth = Math.max(1000, (ra.totalRounds || 7) * 1000);

    const prevTotals = this._preRevealTotals[role] || { pts: curPts, depth: curDepth };
    const revealKey = `${ra.mode}|${ra.roundIdx}|${(ra.history || []).length}`;
    const shouldAnimateReveal = (ra.phase === "reveal") && !settings.lowPower && (revealKey !== this._lastRevealKey);

    const startDepth = shouldAnimateReveal ? prevTotals.depth : curDepth;
    const startPts = shouldAnimateReveal ? prevTotals.pts : curPts;
    const gaugePct = Math.max(3, Math.min(94, (startDepth / maxDepth) * 90 + 3));
    const fillPct = Math.max(2, Math.min(98, (startDepth / maxDepth) * 96));

    // Preserve active draft when re-rendering mid-answering (e.g. toggling sound/wardrobe)
    let savedDraft = null;
    if (ra.phase === "answering") {
      const oldInp = this._root?.querySelector("#krill-ans-input");
      if (oldInp) {
        savedDraft = {
          value: oldInp.value,
          selStart: oldInp.selectionStart,
          selEnd: oldInp.selectionEnd,
          hadFocus: document.activeElement === oldInp,
        };
      }
    }

    const zone = this._zoneForDepth(startDepth);
    const root = document.createElement("div");
    root.className = `krill-root${settings.lowPower ? " low-power" : ""}${settings.colorblind ? " colorblind" : ""}`;
    root.style.setProperty("--krill-ocean-top", zone.top);
    root.style.setProperty("--krill-ocean-mid", zone.mid);
    root.style.setProperty("--krill-ocean-bot", zone.bot);

    let midHtml = "";
    let dockHtml = "";
    if (ra.phase === "idle") {
      midHtml = this._buildStartCard(ra, theme);
    } else if (ra.phase === "preview") {
      midHtml = this._buildPreviewCard(ra);
    } else if (ra.phase === "answering") {
      midHtml = this._buildAnsweringPromptCard(ra, role);
      dockHtml = this._buildAnsweringDock(ra, role);
    } else if (ra.phase === "reveal") {
      midHtml = this._buildRevealCard(ra, role, !shouldAnimateReveal);
    } else if (ra.phase === "surface") {
      midHtml = this._buildSurfaceCard(ra, role, theme);
    }

    const stepTick = Math.round(maxDepth / 1000);
    const ticks = ["0m", `-${Math.round(stepTick * 0.25 * 1000)}`, `-${Math.round(stepTick * 0.5 * 1000)}`, `-${Math.round(stepTick * 0.75 * 1000)}`, `-${maxDepth}m`];
    const mascotTier = (ra.phase === "reveal" || ra.phase === "answering" || ra.phase === "surface") ? this._activeTierKey : null;
    const tierMeta = mascotTier ? (TIER_SHRIMPS[mascotTier] || TIER_SHRIMPS.plankton) : null;
    const mascotGlow = tierMeta ? tierMeta.glow : "rgba(255, 77, 126, 0.48)";

    root.innerHTML = `
      <canvas class="krill-ocean-sea" id="krill-sea"></canvas>
      <div class="krill-dim" id="krill-dim"></div>
      <div class="krill-world-layer" id="krill-world"></div>
      <canvas class="krill-ocean-fore" id="krill-fore"></canvas>
      ${this._bubbleHtml(settings.lowPower)}
      ${this._diveStreaksHtml(settings.lowPower)}
      <div class="krill-header">
        <div class="krill-hdr-col">
          <div class="krill-hud-box" id="krill-hud-depth-box">
            <div class="lbl">DEPTH</div>
            <div class="val-cyan" id="krill-hud-depth-val">${startDepth ? `-${startDepth.toLocaleString()}m` : "0m"}</div>
          </div>
          <div class="krill-zone-pill" id="krill-zone-pill">${zone.name}</div>
          <button class="krill-icon-btn" id="krill-btn-menu" title="Dive Logbook & Modes">☰</button>
        </div>

        ${this._buildTilesAndLabel(ra, role)}

        <div class="krill-hdr-col right">
          <div class="krill-hud-box" id="krill-hud-score-box">
            <div class="lbl">SCORE</div>
            <div class="val-pink" id="krill-hud-score-val">${startPts}</div>
          </div>
          <div class="krill-icon-row">
            <button class="krill-icon-btn" id="krill-btn-snd" title="Toggle Sound">${this.sfx.enabled ? "🔊" : "🔇"}</button>
            <button class="krill-icon-btn" id="krill-btn-settings" title="Settings">⚙</button>
            <button class="krill-icon-btn" id="krill-btn-wardrobe" title="Krill Wardrobe">👕</button>
            <button class="krill-icon-btn" id="krill-btn-custom" title="Customize Theme & Prompts">🎨</button>
          </div>
        </div>
      </div>

      <div class="krill-gauge" aria-hidden="true">
        <div class="krill-gauge-track" id="krill-gauge-track" style="height:${fillPct}%;"></div>
        <span class="krill-gauge-marker" id="krill-gauge-marker" style="top:${gaugePct}%;">YOU</span>
        ${ticks.map((t) => `<span>${t}</span>`).join("")}
      </div>

      ${ra.phase !== "idle" && ra.phase !== "surface" ? `
        <div class="krill-mascot-float${mascotTier ? ` tier-${mascotTier}` : ""}" id="krill-mascot-tap" title="Open Wardrobe" style="--dsm-glow:${mascotGlow};">
          ${this._krillMascotSvg(theme, 56, mascotTier)}
        </div>
      ` : ""}

      <div class="krill-stage-mid">
        ${midHtml}
      </div>

      ${dockHtml}

      ${this.drawer ? this._buildDrawerHtml(ra, role, settings, theme) : ""}
    `;

    this._container.innerHTML = "";
    this._container.appendChild(root);
    this._root = root;

    this._ocean.attach(
      root.querySelector("#krill-sea"),
      root.querySelector("#krill-fore"),
      root.querySelector("#krill-world")
    );
    if (!(ra.phase === "reveal" && shouldAnimateReveal)) {
      const restDepth = (ra.phase === "idle" || ra.phase === "surface") ? 0 : curDepth;
      this._ocean.setStationaryDepth(restDepth);
      this._ocean.tick(performance.now());
    }

    if (savedDraft && ra.phase === "answering") {
      const newInp = root.querySelector("#krill-ans-input");
      if (newInp && !newInp.disabled) {
        newInp.value = savedDraft.value;
        if (savedDraft.hadFocus) newInp.focus();
        try {
          newInp.setSelectionRange(savedDraft.selStart ?? newInp.value.length, savedDraft.selEnd ?? newInp.value.length);
        } catch (_) {}
      }
    }

    this._wireEvents(ra, role, settings, theme);
    this._tickTimerVisuals();

    if (ra.phase === "reveal") {
      this._lastRevealKey = revealKey;
      if (shouldAnimateReveal) {
        this._runRevealSinkAnimation(ra, role, startDepth, curDepth, startPts, curPts, maxDepth);
      }
    }
  }

  _buildStartCard(ra, theme) {
    const stats = ra.stats || {};
    const cRounds = theme.couplesRounds || 5;
    return `
      <div class="krill-crt" style="text-align:center;">
        <div style="display:flex;justify-content:center;margin-bottom:6px;">
          ${this._krillMascotSvg(theme, 62)}
        </div>
        <h1 class="krill-title">${this._esc(theme.title || "KRILLION")}</h1>
        <div class="krill-sub">1V1 JINX · ${this._esc(this.ws.playerName("guest").toUpperCase())} VS ${this._esc(this.ws.playerName("host").toUpperCase())}</div>
        <p style="font-size:12px;color:var(--text-dim);margin:8px 0 12px;">
          ${this._esc(theme.tagline || "weirder answers go deeper")}
        </p>

        <div class="krill-mode-blurb">${cRounds} rounds head-to-head. Out-weird each other — pick the same answer and you both jinx down to 5 pts.</div>

        <button class="btn-primary" id="krill-begin-btn" style="width:100%;font-size:15px;">
          START 1V1 JINX
        </button>

        <button class="krill-icon-btn" id="krill-howto-btn" style="margin-top:10px;width:100%;">
          ${this._howToOpen ? "▾ how it works" : "▸ how it works"}
        </button>
        ${this._howToOpen ? `
          <div style="text-align:left;font-family:var(--font-sans);font-size:12px;color:#b8cee6;margin-top:8px;padding:10px 12px;background:rgba(0,0,0,0.34);border-radius:8px;line-height:1.5;">
            Pick any real answer that fits — 1v1 head-to-head on your phones &amp; webcam. Obscure true answers can hit <strong>+100 pts (-1,000m)</strong> while obvious picks only get +10 pts, and matching answers jinx you both to 5 pts.
          </div>
        ` : ""}

        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px;font-size:11px;color:var(--text-dim);">
          <div class="krill-stat-box"><div>GAMES</div><strong>${stats.dives || 0}</strong></div>
          <div class="krill-stat-box"><div>BEST</div><strong>${stats.bestScore || 0}</strong></div>
          <div class="krill-stat-box"><div>STREAK</div><strong style="color:var(--accent-pink);">${stats.currentStreak || 0}🔥</strong></div>
        </div>
      </div>
    `;
  }

  _buildPreviewCard(ra) {
    return `
      <div class="krill-crt" style="text-align:center;">
        <div class="krill-prompt-kicker">
          ${ra.mode === "puffer" ? "CIRCLE PARTY · GET READY" : `QUESTION ${(ra.roundIdx || 0) + 1} OF ${ra.totalRounds || 7}`}
        </div>
        <div class="krill-prompt-text">${this._esc(ra.prompt || "")}</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:8px;">
          ${ra.mode === "puffer" ? "don't repeat anyone · rare answers heal a heart" : "say something weird that still counts"}
        </div>
        <div style="margin-top:18px;font-size:12px;color:var(--text-dim);">
          starting in <span id="krill-preview-num" style="color:var(--accent-cyan);font-weight:800;font-size:18px;">3</span>
        </div>
      </div>
    `;
  }

  _buildCirclePartyCard(ra) {
    const pf = ra.puffer || {};
    const players = pf.players || [];
    const active = players[pf.turnIdx] || players[0] || { name: "You", idx: 0 };
    const used = pf.used || [];
    const ev = pf.lastEvent || null;

    let toastHtml = "";
    if (ev?.type === "pass") {
      toastHtml = `
        <div class="krill-puffer-toast">
          <strong>${this._esc(ev.by)}</strong> said “${this._esc(ev.canon)}” (${this._esc(ev.tierLabel)}) → passed to <strong>${this._esc(ev.to)}</strong>${ev.healed ? ' · <span style="color:var(--green);">+1 ♥ healed!</span>' : ""}
        </div>
      `;
    } else if (ev?.type === "pop" && ev.rotated) {
      toastHtml = `
        <div class="krill-puffer-toast" style="border-color:rgba(244,93,134,0.4);color:#ffd3df;">
          Fresh prompt for ${this._esc(active.name)} — keep the circle moving!
        </div>
      `;
    }

    const seatsHtml = players.map((p) => {
      const isTurn = p.alive && p.idx === pf.turnIdx;
      const heartsHtml = Array.from({ length: 3 }, (_, i) => (
        i < p.hearts ? "♥" : '<span class="lost">♥</span>'
      )).join("");
      return `
        <div class="krill-puffer-seat ${isTurn ? "is-turn" : ""} ${!p.alive ? "is-out" : ""}">
          <div class="p-name">${isTurn ? "🐡 " : ""}${this._esc(p.name)}</div>
          <div class="p-hearts">${p.alive ? heartsHtml : "OUT"}</div>
        </div>
      `;
    }).join("");

    const usedHtml = used.length
      ? `<div class="krill-used-chips">${used.map((u) => {
          const isRare = u.tierKey === "rare" || u.tierKey === "deep_cut" || u.tierKey === "krillion";
          return `<span class="krill-used-chip ${isRare ? "is-rare" : ""}">${this._esc(u.canon)}</span>`;
        }).join("")}</div>`
      : `<div style="font-size:11px;color:var(--text-dim);margin-top:6px;">nobody has answered yet — name anything that fits</div>`;

    return `
      <div class="krill-crt" style="text-align:center;">
        <div class="krill-puffer-ring">${seatsHtml}</div>
        <div class="krill-puffer-bomb" id="krill-puffer-bomb" style="--puffer-heat:0;">
          <span>🐡 ${this._esc(active.name)}'s turn</span>
          <span style="color:var(--accent-cyan);">· ${used.length} played</span>
        </div>
        ${toastHtml}
        <div class="krill-prompt-text" style="margin:6px 0 4px;">${this._esc(ra.prompt || "")}</div>
        ${usedHtml}
      </div>
    `;
  }

  _buildAnsweringPromptCard(ra, role) {
    if (ra.mode === "puffer") {
      return this._buildCirclePartyCard(ra);
    }
    const oppRole = role === "guest" ? "host" : "guest";
    const oppLocked = Boolean(ra.locked?.[oppRole]);
    return `
      <div class="krill-crt">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span class="krill-prompt-kicker" style="margin:0;">QUESTION ${(ra.roundIdx || 0) + 1} OF ${ra.totalRounds || 7}</span>
          ${ra.mode === "couples" ? `<span id="krill-opp-status" style="font-size:10px;color:${oppLocked ? "var(--green)" : "var(--accent-cyan)"}">${oppLocked ? "PARTNER: LOCKED ✓" : "PARTNER: THINKING…"}</span>` : ""}
        </div>
        <div class="krill-prompt-text">${this._esc(ra.prompt || "")}</div>
        <div style="font-size:11px;color:var(--text-dim);">
          pick something real that isn't everyone's first guess
        </div>
      </div>
    `;
  }

  _buildAnsweringDock(ra, role) {
    const locked = Boolean(ra.locked?.[role]);
    const fb = this._localFeedback || ra.feedback?.[role] || {};
    const bannerHtml = this._formatFeedbackInner(fb, locked);
    const circ = (2 * Math.PI * 27).toFixed(2);
    const isPuffer = ra.mode === "puffer";
    const activePlayer = isPuffer ? (ra.puffer?.players?.[ra.puffer?.turnIdx] || {}).name : "";
    const placeholder = isPuffer && activePlayer
      ? `${activePlayer}: say one & pass…`
      : "type one answer…";

    return `
      <div class="krill-composer-dock">
        <div id="krill-feedback-box" class="krill-feedback ${locked ? "locked" : (fb.status || "")}">
          ${bannerHtml}
        </div>

        <div class="krill-input-dock-row">
          <div class="krill-radar-wrap">
            <svg viewBox="0 0 68 68">
              <circle cx="34" cy="34" r="27" fill="rgba(6,13,26,0.9)" stroke="rgba(108,229,255,0.18)" stroke-width="4.5" />
              <circle id="krill-radar-ring" cx="34" cy="34" r="27" fill="none" stroke="var(--accent-cyan)" stroke-width="4.5" stroke-linecap="round" stroke-dasharray="${circ}" stroke-dashoffset="0" />
            </svg>
            <span id="krill-radar-num" class="krill-radar-num">${isPuffer ? Math.ceil(ra.puffer?.fuse || 10) : (ra.answerTotal || 25)}</span>
          </div>

          <form id="krill-form" class="krill-input-row" autocomplete="off">
            <input
              id="krill-ans-input"
              type="text"
              autocomplete="off"
              autocorrect="off"
              autocapitalize="off"
              spellcheck="false"
              enterkeyhint="send"
              placeholder="${this._esc(placeholder)}"
              ${locked ? "disabled" : ""}
            />
            <button id="krill-dive-btn" class="krill-dive-btn" type="submit" ${locked ? "disabled" : ""}>
              ${isPuffer ? "PASS 🐡" : "SEND"}
            </button>
          </form>
        </div>

        <div class="krill-bottom-bar">
          <div id="krill-bottom-fill" class="krill-bottom-fill" style="width:100%;"></div>
        </div>
      </div>
    `;
  }

  _formatFeedbackInner(fb, locked) {
    if (locked) return "LOCKED IN · WAITING FOR OTHER PLAYER…";
    if (fb?.status === "confirm" && fb.inputRaw && fb.suggested) {
      return `
        <div>did you mean <strong style="color:var(--accent-cyan);">“${this._esc(fb.suggested)}”</strong>?</div>
        <button type="button" class="krill-confirm-btn" id="krill-confirm-pill">Tap or hit Enter to use “${this._esc(fb.suggested)}” ✓</button>
        <div class="sub-hint">or keep typing to edit</div>
      `;
    }
    if (fb?.status === "no_echo" && fb.message) {
      return this._esc(fb.message);
    }
    return "type any real answer — weirder answers score higher";
  }

  _tierLadderMeta() {
    return [
      { key: "plankton", label: "PLANKTON", depth: 100, pts: 10, color: "#9ab3cc", pct: 14 },
      { key: "too_clever", label: "TOO CLEVER", depth: 150, pts: 15, color: "#f6cf66", pct: 24 },
      { key: "schooler", label: "SCHOOLER", depth: 300, pts: 30, color: "#67e6a3", pct: 42 },
      { key: "rare", label: "RARE", depth: 600, pts: 60, color: "#6ce5ff", pct: 66 },
      { key: "deep_cut", label: "DEEP CUT", depth: 850, pts: 85, color: "#b98aff", pct: 86 },
      { key: "krillion", label: "ONE IN A KRILLION", depth: 1000, pts: 100, color: "#ff6aa8", pct: 100 },
    ];
  }

  _buildRevealCard(ra, role, settled = false) {
    if (ra.mode === "puffer") {
      const pf = ra.puffer || {};
      const ev = pf.lastEvent || {};
      const players = pf.players || [];
      const seatsHtml = players.map((p) => {
        const heartsHtml = Array.from({ length: 3 }, (_, i) => (
          i < p.hearts ? "♥" : '<span class="lost">♥</span>'
        )).join("");
        return `
          <div class="krill-puffer-seat ${!p.alive ? "is-out" : ""}">
            <div class="p-name">${this._esc(p.name)}</div>
            <div class="p-hearts">${p.alive ? heartsHtml : "OUT"}</div>
          </div>
        `;
      }).join("");
      return `
        <div class="krill-crt" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">
            ${this._esc(ra.prompt || ev.prompt || "")}
          </div>
          <div><span class="tier-badge tier-jinx">🐡 PUFFER POPPED!</span></div>
          <h2 style="margin:10px 0 4px;font-family:var(--font-mono);font-size:24px;color:#fff;">
            ${this._esc(ev.player || "Time's up")} lost a heart
          </h2>
          <p style="font-family:var(--font-sans);font-size:12px;color:var(--text-dim);margin:4px 0 10px;">
            ${ev.eliminated ? "Knocked out of the circle!" : `${ev.heartsLeft ?? 0} ♥ remaining`} · ${ev.passes || 0} passes on that prompt
          </p>
          ${ev.sampleDeep ? `
            <div class="krill-puffer-toast" style="margin-bottom:10px;">
              Could've played: <strong>${this._esc(ev.sampleDeep)}</strong>
            </div>
          ` : ""}
          <div class="krill-puffer-ring">${seatsHtml}</div>
          <button class="btn-primary" id="krill-next-btn" style="width:100%;">
            NEXT PROMPT →
          </button>
        </div>
      `;
    }

    const row = ra.history?.[ra.history.length - 1];
    if (!row) return "";
    const mine = row[role] || {};
    const partner = row[role === "guest" ? "host" : "guest"] || {};
    const isLast = (ra.roundIdx + 1) >= (ra.totalRounds || 7);
    const ladder = this._tierLadderMeta();
    const myTier = ladder.find((t) => t.key === mine.tierKey);
    const tierGlow = myTier?.color || (mine.tierKey === "jinx" ? "#ff5b6e" : "#74849a");

    return `
      <div class="krill-crt" style="text-align:center;--tier-glow:${tierGlow};">
        <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">
          ${this._esc(row.prompt)}
        </div>

        ${row.jinx ? `<div class="krill-warn" style="margin-bottom:8px;font-weight:800;">🕸️ ${this._esc(mine.tierLabel)}</div>` : ""}

        <div class="krill-reveal-hero${settled ? "" : " is-anim"}">
          <div class="krill-sonar-burst"></div>
          <div class="krill-sonar-burst b2"></div>
          <div><span class="tier-badge tier-${mine.tierKey || "timeout"}">${this._esc(mine.tierLabel || "RESULT")}</span></div>
          <h2 style="margin:10px 0 4px;font-family:var(--font-mono);font-size:26px;color:#fff;">
            ${mine.canonical ? `“${this._esc(mine.canonical)}”` : "No Echo"}
          </h2>
          <div class="krill-drop-pill${settled ? "" : " is-plunging"}" id="krill-drop-pill">
            <span>▼ ${(mine.depth || 0) > 0 ? `-${mine.depth}m` : "0m"}</span>
            <span style="color:var(--accent-cyan);">· +${mine.pts || 0} PTS</span>
          </div>
        </div>

        <p style="font-family:var(--font-sans);font-size:12px;color:var(--text-dim);margin:6px 0 8px;">
          “${this._esc(mine.note || "")}”
        </p>

        <div class="krill-tier-ladder" id="krill-tier-ladder">
          ${ladder.map((t, idx) => {
            const isMine = (mine.tierKey === t.key);
            const isPartner = (ra.mode === "couples" && partner.tierKey === t.key);
            const hitCls = settled && isMine ? " is-hit" : "";
            const barW = settled ? t.pct : 0;
            return `
              <div class="krill-tier-row${hitCls}" data-tier="${t.key}" data-tier-idx="${idx}" data-bar="${t.pct}" style="--tier-color:${t.color};">
                <span class="t-name">${t.label}</span>
                <div class="t-bar-wrap"><div class="t-bar" style="width:${barW}%;"></div></div>
                <span class="t-depth">-${t.depth}m${isMine || isPartner ? `<span class="krill-tier-tags">${isMine ? '<span class="krill-chip-you">YOU</span>' : ''}${isPartner ? '<span class="krill-chip-opp">P</span>' : ''}</span>` : ""}</span>
              </div>
            `;
          }).join("")}
        </div>

        ${ra.mode === "couples" ? `
          <div style="background:rgba(255,255,255,0.04);border-radius:10px;padding:7px 10px;margin-bottom:10px;font-size:12px;display:flex;justify-content:space-between;">
            <span style="color:var(--text-dim);">Other player:</span>
            <strong style="color:#fff;">${partner.canonical ? `“${this._esc(partner.canonical)}” (-${partner.depth}m · +${partner.pts})` : "Time out (+0)"}</strong>
          </div>
        ` : ""}

        <button class="btn-primary" id="krill-next-btn" style="width:100%;">
          ${isLast ? "SEE RESULTS ▲" : "NEXT QUESTION ▼"}
        </button>
      </div>
    `;
  }

  _runRevealSinkAnimation(ra, role, prevDepth, curDepth, prevPts, curPts, maxDepth) {
    if (!this._root) return;
    const row = ra.history?.[ra.history.length - 1];
    if (!row) return;
    const mine = row[role] || {};
    const deltaDepth = mine.depth || 0;
    const tierKey = (row.jinx || !mine.tierKey || mine.tierKey === "timeout" || deltaDepth <= 0)
      ? "miss"
      : mine.tierKey;
    const tierMeta = TIER_SHRIMPS[tierKey] || TIER_SHRIMPS.plankton;
    this._activeTierKey = tierKey;

    const mascot = this._root.querySelector("#krill-mascot-tap");
    if (mascot) {
      mascot.className = `krill-mascot-float is-plunging tier-${tierKey}`;
      mascot.style.setProperty("--dsm-glow", tierMeta.glow);
      mascot.innerHTML = this._krillMascotSvg(ra.theme || {}, 60, tierKey);
    }
    this._root.classList.add("is-plunging", `tier-${tierKey}`);
    if (deltaDepth > 0) this._root.classList.add("is-sinking");
    if (tierKey === "deep_cut" || tierKey === "krillion") this._root.classList.add("is-deepcut");

    const ladder = this._tierLadderMeta();
    const targetIdx = Math.max(0, ladder.findIndex((t) => t.key === mine.tierKey));
    const rows = Array.from(this._root.querySelectorAll(".krill-tier-row"));

    // Animate bars sweeping in & scanning down rarity ladder until landing on your tier
    rows.forEach((el, idx) => {
      const bar = el.querySelector(".t-bar");
      const targetBar = el.getAttribute("data-bar") || "20";
      if (bar) {
        const tBar = setTimeout(() => { bar.style.width = `${targetBar}%`; }, 60 + idx * 45);
        this._animTimers.push(tBar);
      }
      if (idx <= targetIdx) {
        const tScan = setTimeout(() => {
          rows.forEach((r) => r.classList.remove("is-scanning"));
          el.classList.add("is-scanning");
        }, 70 + idx * 85);
        this._animTimers.push(tScan);
      }
    });

    const lockDelay = 120 + targetIdx * 90;
    const tLock = setTimeout(() => {
      rows.forEach((r) => r.classList.remove("is-scanning"));
      const hitEl = rows.find((r) => r.getAttribute("data-tier") === mine.tierKey);
      if (hitEl) hitEl.classList.add("is-hit");
    }, lockDelay);
    this._animTimers.push(tLock);

    // Start 1:1 vertical ocean plunge after EVERY revealed answer!
    this.sfx.play(deltaDepth > 0 ? "krill_sink" : "krill_miss");
    this._ocean.startPlunge({
      fromDepth: prevDepth,
      toDepth: curDepth,
      deltaDepth,
      answerText: mine.canonical || mine.raw || (row.jinx ? "JINX" : "NO ECHO"),
      tierKey,
      ladder,
      onTierCross: () => {
        this.sfx.play("krill_tierline");
      },
      onEnd: () => {
        if (!this._root) return;
        this._root.classList.remove("is-sinking", "is-plunging", "is-deepcut");
        const m = this._root.querySelector("#krill-mascot-tap");
        if (m) {
          m.classList.remove("is-plunging", "is-diving", "anim-faint", "anim-dart", "anim-jet", "anim-celebrate");
          const mood = tierKey === "miss" ? "faint" : tierKey === "too_clever" ? "dart" : tierKey === "krillion" ? "celebrate" : "jet";
          m.classList.add(`anim-${mood}`);
        }
        if (tierKey === "krillion") this.sfx.play("krill_gold");
        else if (tierKey === "rare" || tierKey === "deep_cut") this.sfx.play("krill_land_big");
        else if (tierKey === "miss") this.sfx.play(row.jinx ? "jinx" : "krill_miss");
        else this.sfx.play("krill_land_small");
      },
    });
    this._ocean.tick(performance.now());

    // Synchronize HUD odometer, zone color & right-edge ruler gauge with the plunge
    const zone = this._zoneForDepth(curDepth);
    this._root.style.setProperty("--krill-ocean-top", zone.top);
    this._root.style.setProperty("--krill-ocean-mid", zone.mid);
    this._root.style.setProperty("--krill-ocean-bot", zone.bot);
    const zonePill = this._root.querySelector("#krill-zone-pill");
    if (zonePill) zonePill.textContent = zone.name;

    const marker = this._root.querySelector("#krill-gauge-marker");
    const track = this._root.querySelector("#krill-gauge-track");
    const targetGaugePct = Math.max(3, Math.min(94, (curDepth / maxDepth) * 90 + 3));
    const targetFillPct = Math.max(2, Math.min(98, (curDepth / maxDepth) * 96));
    if (marker) marker.style.top = `${targetGaugePct}%`;
    if (track) track.style.height = `${targetFillPct}%`;

    const depthBox = this._root.querySelector("#krill-hud-depth-box");
    const scoreBox = this._root.querySelector("#krill-hud-score-box");
    const depthVal = this._root.querySelector("#krill-hud-depth-val");
    const scoreVal = this._root.querySelector("#krill-hud-score-val");
    depthBox?.classList.add("is-bumping");
    scoreBox?.classList.add("is-bumping");

    const t0 = performance.now();
    const dur = tierKey === "krillion" ? 3100 : tierKey === "deep_cut" ? 2700 : deltaDepth > 0 ? 2100 : 900;
    const stepCount = (now) => {
      if (!this._root) return;
      const p = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      const dNow = Math.round(prevDepth + (curDepth - prevDepth) * e);
      const pNow = Math.round(prevPts + (curPts - prevPts) * e);
      if (depthVal) depthVal.textContent = dNow ? `-${dNow.toLocaleString()}m` : "0m";
      if (scoreVal) scoreVal.textContent = String(pNow);
      if (p < 1) {
        this._countRaf = requestAnimationFrame(stepCount);
      } else {
        depthBox?.classList.remove("is-bumping");
        scoreBox?.classList.remove("is-bumping");
      }
    };
    this._countRaf = requestAnimationFrame(stepCount);
  }

  _buildSurfaceCard(ra, role, theme) {
    const copiedRecently = (performance.now() - this._copiedAt) < 2500;
    if (ra.mode === "puffer") {
      const pf = ra.puffer || {};
      const players = [...(pf.players || [])].sort((a, b) => (b.hearts - a.hearts) || (b.passes - a.passes));
      return `
        <div class="krill-crt" style="max-height:76dvh;overflow-y:auto;text-align:center;">
          <div style="font-size:10px;color:var(--accent-cyan);letter-spacing:0.16em;">
            CIRCLE PARTY OVER
          </div>
          <div style="font-size:28px;font-weight:900;color:#fff;margin:8px 0 4px;">
            🏆 ${this._esc(pf.winner || "Survivor")} wins!
          </div>
          <p style="font-family:var(--font-sans);font-size:12px;color:var(--text-dim);margin:0 0 12px;">
            Last player holding hearts when the puffer stopped popping.
          </p>

          <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:14px;text-align:left;">
            ${players.map((p) => `
              <div class="bearing-row ${p.alive ? "active" : ""}" style="grid-template-columns:1fr auto auto;">
                <strong>${this._esc(p.name)}</strong>
                <span style="color:var(--accent-pink);">${p.alive ? "♥".repeat(p.hearts) : "OUT"}</span>
                <span style="color:var(--text-dim);">${p.passes} passes · ${p.rares} rare</span>
              </div>
            `).join("")}
          </div>

          <div style="display:flex;flex-direction:column;gap:8px;margin:10px 0;">
            <button class="btn-primary" id="krill-copy-btn" style="width:100%;">
              ${copiedRecently ? "COPIED ✓" : "COPY RESULT"}
            </button>
            <button class="btn-cyan" id="krill-keep-diving-btn" style="width:100%;font-weight:800;letter-spacing:0.08em;">
              PLAY CIRCLE AGAIN 🐡
            </button>
            <div style="display:flex;gap:8px;">
              <button class="krill-icon-btn" id="krill-surface-wardrobe" style="flex:1;">👕 WARDROBE</button>
              <button class="krill-icon-btn" id="krill-surface-couples" style="flex:1;">💞 1V1 JINX</button>
            </div>
          </div>
        </div>
      `;
    }

    const tot = ra.totals || {};
    const minePts = role === "host" ? (tot.hostPts || 0) : (tot.guestPts || 0);
    const mineDepth = role === "host" ? (tot.hostDepth || 0) : (tot.guestDepth || 0);
    const oppPts = role === "host" ? (tot.guestPts || 0) : (tot.hostPts || 0);
    const bearing = (role === "host" ? tot.hostBearing : tot.guestBearing) || { name: "Plankton", desc: "" };
    const pct = (role === "host" ? tot.hostPercentile : tot.guestPercentile) || 50;
    const stats = ra.stats || {};
    const brackets = theme.bearing || [];

    return `
      <div class="krill-crt" style="max-height:76dvh;overflow-y:auto;">
        <div style="text-align:center;">
          <div style="font-size:10px;color:var(--accent-cyan);letter-spacing:0.18em;">
            ${this._esc(theme.title || "KRILLION")} · ${ra.mode === "couples" ? "1V1 JINX" : (ra.mode === "daily" ? "DAILY GAME" : "FREE PLAY")} COMPLETE
          </div>
          <div style="display:flex;justify-content:center;align-items:baseline;gap:14px;margin:6px 0;">
            <span style="font-size:32px;font-weight:900;color:#fff;">${minePts}</span>
            <span style="font-size:18px;font-weight:800;color:var(--accent-pink);">-${mineDepth.toLocaleString()}m</span>
          </div>
          <div style="font-size:11px;color:var(--accent-cyan);letter-spacing:0.08em;">
            BEAT ${pct}% OF PLAYERS
          </div>
          ${ra.mode === "couples" ? `<div style="font-size:12px;color:var(--text-dim);margin-top:4px;">Score: You ${minePts} vs Opponent ${oppPts}</div>` : ""}
        </div>

        <div style="margin:10px 0;background:rgba(0,0,0,0.3);border-radius:10px;padding:8px;">
          ${this._bellCurveSvg(pct)}
          ${this._depthChartSvg(ra.history || [], role)}
        </div>

        <div style="font-size:10px;color:var(--text-dim);letter-spacing:0.14em;margin-top:8px;">WHERE YOU LANDED</div>
        <div class="bearing-table">
          ${brackets.map((b) => {
            const isActive = b.name === bearing.name;
            const rangeLbl = b.max >= 9000 ? `${b.min}+` : `${b.min}-${b.max}`;
            return `
              <div class="bearing-row ${isActive ? "active" : ""}">
                <span style="color:${isActive ? "var(--accent-cyan)" : "var(--text-dim)"};">${rangeLbl}</span>
                <span><strong>${this._esc(b.name)}.</strong> ${this._esc(b.desc)}</span>
              </div>
            `;
          }).join("")}
        </div>

        ${ra.mode === "couples" && ra.forfeit ? `
          <div style="border:1px solid rgba(244,93,134,0.45);border-radius:10px;padding:10px;margin:10px 0;font-size:12px;">
            <div style="color:var(--accent-pink);font-weight:800;">CAMERA FORFEIT ACTIVE</div>
            <div style="margin:4px 0 8px;">${this._esc(this.ws.playerName(ra.loserRole === "guest" ? "guest" : "host"))} wears <strong>${this._esc(ra.forfeit.replace("_", " "))}</strong> on cam!</div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              ${["seaweed", "bubble_helmet", "shrimp_partner", "neon_glow"].map((fk) => `
                <button class="pill-btn ${ra.forfeit === fk ? "active" : ""}" data-krill-forfeit="${fk}">${fk.replace("_", " ")}</button>
              `).join("")}
              <button class="pill-btn" id="krill-clear-forfeit">Clear</button>
            </div>
          </div>
        ` : ""}

        <div style="display:flex;flex-direction:column;gap:8px;margin:12px 0;">
          <button class="btn-primary" id="krill-copy-btn" style="width:100%;">
            ${copiedRecently ? "COPIED ✓" : "COPY RESULT"}
          </button>
          <button class="btn-cyan" id="krill-keep-diving-btn" style="width:100%;font-weight:800;letter-spacing:0.1em;">
            PLAY AGAIN ∞
          </button>
          <div style="display:flex;gap:8px;">
            <button class="krill-icon-btn" id="krill-surface-wardrobe" style="flex:1;">👕 WARDROBE</button>
            <button class="krill-icon-btn" id="krill-surface-couples" style="flex:1;">💞 1V1 JINX</button>
          </div>
        </div>

        <div style="margin-top:10px;">
          <div style="font-size:10px;color:var(--text-dim);letter-spacing:0.12em;margin-bottom:6px;">YOUR PICKS</div>
          ${(ra.history || []).map((row) => {
            const sl = row[role] || {};
            return `
              <div style="padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.08);font-size:11px;">
                <div style="color:var(--text-dim);">${row.round}. ${this._esc(row.prompt)}</div>
                <div style="display:flex;justify-content:space-between;margin-top:2px;">
                  <strong style="color:#fff;">${sl.canonical ? this._esc(sl.canonical) : "—"} ${row.jinx ? "🕸️" : ""}</strong>
                  <span style="color:var(--accent-cyan);">+${sl.pts || 0} · -${sl.depth || 0}m</span>
                </div>
              </div>`;
          }).join("")}
        </div>

        <div style="margin-top:10px;font-size:10px;color:var(--text-dim);text-align:center;">
          streak ${stats.currentStreak || 0} · played ${stats.dives || 0} · avg ${stats.avgScore || 0} · best ${stats.bestScore || 0}
        </div>
      </div>
    `;
  }

  _bellCurveSvg(pct) {
    const xPos = 16 + (pct / 100) * 268;
    return `
      <svg viewBox="0 0 300 66" style="width:100%;height:60px;">
        <path d="M12 56 Q70 54 105 28 Q150 4 195 28 Q230 54 288 56" fill="rgba(108,229,255,0.12)" stroke="#6ce5ff" stroke-width="2" />
        <line x1="${xPos}" y1="8" x2="${xPos}" y2="56" stroke="#f45d86" stroke-width="2" stroke-dasharray="3,2" />
        <circle cx="${xPos}" cy="24" r="5" fill="#f45d86" />
        <text x="${Math.min(256, Math.max(24, xPos))}" y="12" fill="#f45d86" font-size="9" font-weight="bold" text-anchor="middle">YOU (${pct}%)</text>
      </svg>`;
  }

  _depthChartSvg(history, role) {
    if (!history.length) return "";
    const stepW = 280 / Math.max(1, history.length);
    const pts = history.map((r, i) => {
      const d = Number(r[role]?.depth || 0);
      const y = 10 + (d / 1000) * 40;
      const x = 16 + i * stepW + stepW * 0.5;
      return { x, y, d, r: r.round };
    });
    const poly = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    return `
      <svg viewBox="0 0 300 62" style="width:100%;height:56px;">
        <polyline points="${poly}" fill="none" stroke="#6ce5ff" stroke-width="2" />
        ${pts.map((p) => `<circle cx="${p.x}" cy="${p.y}" r="3.5" fill="#f45d86" /><text x="${p.x}" y="${Math.min(59, p.y + 11)}" fill="#8ab" font-size="8" text-anchor="middle">-${p.d}m</text>`).join("")}
      </svg>`;
  }

  _buildDrawerHtml(ra, role, settings, theme) {
    let title = "MENU";
    let inner = "";
    const timerNotice = ra.phase === "answering"
      ? `<div class="krill-warn">⏱ Your timer keeps running while this drawer is open.</div>`
      : "";

    if (this.drawer === "settings") {
      title = "SETTINGS";
      const rows = [
        ["lowPower", "LOW-POWER MODE", "Turns off extra ocean effects if your device runs hot."],
        ["colorblind", "COLORBLIND MODE", "Higher-contrast colors on the scoreboard."],
        ["answerCorrections", "TYPO SUGGESTIONS", "Show a tap-to-confirm fix when you misspell something by a letter."],
        ["clearRejected", "CLEAR REJECTED PICKS", "Wipe the box automatically when an answer doesn't count."],
        ["shareLink", "INCLUDE JOIN LINK", "Add the room URL when you copy results."],
        ["couplesJinx", "1V1 JINX PENALTY", "Same answer in 1v1 cuts both of you to 5 pts."],
      ];
      inner = `
        ${rows.map(([k, lbl, desc]) => `
          <div class="setting-row">
            <div>
              <div class="s-title">${lbl}</div>
              <div class="s-desc">${desc}</div>
            </div>
            <input type="checkbox" class="toggle-switch" data-krill-set="${k}" ${settings[k] ? "checked" : ""} />
          </div>
        `).join("")}
        <div class="setting-row">
          <div>
            <div class="s-title">SOUND EFFECTS</div>
            <div class="s-desc">Timer ticks, splashes, and reveal chimes.</div>
          </div>
          <input type="checkbox" class="toggle-switch" id="krill-sound-toggle" ${this.sfx.enabled ? "checked" : ""} />
        </div>
      `;
    } else if (this.drawer === "menu") {
      title = "GAME MENU";
      const st = ra.stats || {};
      inner = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;">
          <div class="krill-stat-box"><div>GAMES</div><strong>${st.dives || 0}</strong></div>
          <div class="krill-stat-box"><div>AVG SCORE</div><strong>${st.avgScore || 0}</strong></div>
          <div class="krill-stat-box"><div>BEST DEPTH</div><strong>${(st.bestDepth || 0) > 0 ? `-${st.bestDepth}m` : "0m"}</strong></div>
          <div class="krill-stat-box"><div>STREAK</div><strong>${st.currentStreak || 0}🔥</strong></div>
        </div>
        <button class="btn-cyan" id="krill-launch-daily">Daily (${theme.dailyRounds || 7})</button>
        <button class="btn-cyan" id="krill-launch-unlimited">Free play ∞</button>
        <button class="pill-btn" id="krill-launch-couples">1v1 Jinx (${theme.couplesRounds || 5})</button>
        <button class="pill-btn" id="krill-launch-puffer">Circle Party 🐡 (${this.pufferPlayers} players)</button>
        <button class="pill-btn" id="krill-open-wardrobe">👕 Krill Wardrobe</button>
        <button class="pill-btn" id="krill-open-customize">🎨 Theme & Custom Prompts</button>
        <button class="pill-btn" id="krill-back-arcade">◀ Back to Games</button>
      `;
    } else if (this.drawer === "wardrobe") {
      title = "KRILL WARDROBE";
      inner = `
        <div style="display:flex;justify-content:center;padding:8px;background:rgba(0,0,0,0.3);border-radius:10px;">
          ${this._krillMascotSvg(theme, 84)}
        </div>
        <div style="font-size:11px;color:var(--accent-cyan);">SHELL COLOR</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${KRILL_SHELLS.map((s) => `
            <button class="pill-btn ${this._wardrobe.shell === s.color ? "active" : ""}" data-krill-shell="${s.color}">
              <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${s.color};margin-right:4px;"></span>${s.name}
            </button>
          `).join("")}
        </div>
        <div style="font-size:11px;color:var(--accent-cyan);">ACCESSORY</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${KRILL_GEAR.map((g) => `
            <button class="pill-btn ${this._wardrobe.gear === g.id ? "active" : ""}" data-krill-gear="${g.id}">
              ${g.name}
            </button>
          `).join("")}
        </div>
      `;
    } else if (this.drawer === "customize") {
      title = "CUSTOMIZE KRILLION";
      inner = `
        <div class="custom-field-grid">
          <label class="custom-field">Title<input id="cust-title" value="${this._esc(theme.title || "KRILLION")}" /></label>
          <label class="custom-field">Subtitle<input id="cust-sub" value="${this._esc(theme.subtitle || "THE DAILY DIVE")}" /></label>
          <label class="custom-field">Tagline<input id="cust-tag" value="${this._esc(theme.tagline || "rarer answers sink deeper")}" /></label>
          <label class="custom-field">Mascot Color<input id="cust-mascot" type="color" value="${theme.mascotAccent || "#ff4d7e"}" /></label>
          <label class="custom-field">Sonar Cyan<input id="cust-cyan" type="color" value="${theme.accentCyan || "#6ce5ff"}" /></label>
          <label class="custom-field">Dive Pink<input id="cust-pink" type="color" value="${theme.accentPink || "#f45d86"}" /></label>
          <label class="custom-field">Normal Rounds<input id="cust-drounds" type="number" min="3" max="15" value="${theme.dailyRounds || 7}" /></label>
          <label class="custom-field">Timer (sec)<input id="cust-asec" type="number" min="10" max="60" value="${theme.answerSeconds || 25}" /></label>
        </div>
        <button class="btn-cyan" id="cust-save-theme">Save Look & Rules</button>

        <div style="border-top:1px solid rgba(255,255,255,0.1);padding-top:10px;">
          <div style="font-size:11px;color:var(--accent-cyan);margin-bottom:6px;">ADD CUSTOM PROMPT (SAVES TO REPO)</div>
          <label class="custom-field">Question<input id="cust-q-text" placeholder="Name a coffee order..." /></label>
          <label class="custom-field" style="margin-top:6px;">Answers (Answer:tier, comma-separated)
            <textarea id="cust-q-ans" rows="3" placeholder="Matcha Latte:plankton, Cortado:schooler, Einspanner:krillion"></textarea>
          </label>
          <button class="btn-primary" id="cust-add-prompt" style="margin-top:8px;width:100%;padding:9px;">Add Custom Prompt</button>
        </div>
      `;
    }

    return `
      <div class="krill-drawer-backdrop" id="krill-backdrop">
        <div class="krill-drawer">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong style="color:var(--accent-cyan);letter-spacing:0.12em;">${title}</strong>
            <button class="krill-icon-btn" id="krill-close-drawer">✕ CLOSE</button>
          </div>
          ${timerNotice}
          ${inner}
        </div>
      </div>
    `;
  }

  _renderFeedbackBanner(res) {
    const box = this._root?.querySelector("#krill-feedback-box");
    if (!box) return;
    box.className = `krill-feedback ${res.status || ""}`;
    box.innerHTML = this._formatFeedbackInner(res, false);
    const pill = box.querySelector("#krill-confirm-pill");
    if (pill && res.suggested) {
      pill.addEventListener("click", () => {
        const inp = this._root?.querySelector("#krill-ans-input");
        if (inp) inp.value = res.suggested;
        this._submitGuess(res.suggested);
      });
    }
  }

  _submitGuess(rawText) {
    const val = String(rawText || "").trim();
    if (!val || this._submitPending) return;
    this._submitPending = true;
    clearTimeout(this._submitPendingTimer);
    this._submitPendingTimer = setTimeout(() => { this._submitPending = false; }, 1400);
    this.sfx.unlock();
    this.sfx.play("krill_submit");
    this.ws.action("rare_answer", "submit", { text: val });
  }

  _syncSubmitBtn() {
    const inp = this._root?.querySelector("#krill-ans-input");
    const btn = this._root?.querySelector("#krill-dive-btn");
    if (inp && btn) {
      btn.disabled = !inp.value.trim();
    }
  }

  _wireEvents(ra, role, settings, theme) {
    const q = (sel) => this._root.querySelector(sel);

    q("#krill-btn-menu")?.addEventListener("click", () => { this.drawer = "menu"; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-btn-settings")?.addEventListener("click", () => { this.drawer = "settings"; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-btn-wardrobe")?.addEventListener("click", () => { this.drawer = "wardrobe"; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-mascot-tap")?.addEventListener("click", () => { this.drawer = "wardrobe"; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-surface-wardrobe")?.addEventListener("click", () => { this.drawer = "wardrobe"; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-btn-custom")?.addEventListener("click", () => { this.drawer = "customize"; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-btn-snd")?.addEventListener("click", () => {
      this.sfx.enabled = !this.sfx.enabled;
      if (this.sfx.enabled) this.sfx.unlock();
      this._lastPhaseKey = "";
      this.update(this._state);
    });
    q("#krill-close-drawer")?.addEventListener("click", () => { this.drawer = null; this._lastPhaseKey = ""; this.update(this._state); });
    q("#krill-backdrop")?.addEventListener("click", (e) => {
      if (e.target.id === "krill-backdrop") { this.drawer = null; this._lastPhaseKey = ""; this.update(this._state); }
    });

    this._root.querySelectorAll("[data-krill-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.modeChoice = btn.getAttribute("data-krill-mode");
        this._lastPhaseKey = "";
        this.update(this._state);
      });
    });

    this._root.querySelectorAll("[data-puffer-seats]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.pufferPlayers = Number(btn.getAttribute("data-puffer-seats") || 3);
        this._lastPhaseKey = "";
        this.update(this._state);
      });
    });

    q("#krill-howto-btn")?.addEventListener("click", () => {
      this._howToOpen = !this._howToOpen;
      this._lastPhaseKey = "";
      this.update(this._state);
    });

    q("#krill-begin-btn")?.addEventListener("click", () => {
      this.sfx.unlock();
      const payload = { mode: this.modeChoice };
      if (this.modeChoice === "puffer") {
        payload.players = this.pufferPlayers;
      }
      this.ws.action("rare_answer", "start", payload);
    });

    const inp = q("#krill-ans-input");
    const form = q("#krill-form");
    if (inp && form) {
      inp.focus();
      if (this._autofilledValue && !inp.value) {
        inp.value = this._autofilledValue;
      }
      this._syncSubmitBtn();
      const existingPill = q("#krill-confirm-pill");
      if (existingPill && this._autofilledValue) {
        existingPill.addEventListener("click", () => {
          inp.value = this._autofilledValue;
          this._submitGuess(this._autofilledValue);
        });
      }
      inp.addEventListener("input", () => {
        const curTrim = inp.value.trim().toLowerCase();
        if (this._autofilledValue && curTrim !== this._autofilledValue.trim().toLowerCase()) {
          this._autofilledValue = null;
          this._localFeedback = null;
          this._renderFeedbackBanner({ status: "" });
        }
        this._syncSubmitBtn();
      });
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        this._submitGuess(inp.value);
      });
    }

    q("#krill-next-btn")?.addEventListener("click", () => {
      this.sfx.unlock();
      if (!settings.lowPower && this._root) {
        this._root.classList.add("is-sinking");
        this._root.querySelector("#krill-mascot-tap")?.classList.add("is-diving");
        setTimeout(() => this.ws.action("rare_answer", "next"), 180);
      } else {
        this.ws.action("rare_answer", "next");
      }
    });

    q("#krill-keep-diving-btn")?.addEventListener("click", () => {
      this.sfx.unlock();
      if (ra.mode === "puffer") {
        this.modeChoice = "puffer";
        this.ws.action("rare_answer", "start", { mode: "puffer", players: this.pufferPlayers });
      } else {
        this.modeChoice = "unlimited";
        this.ws.action("rare_answer", "start", { mode: "unlimited" });
      }
    });

    q("#krill-surface-couples")?.addEventListener("click", () => {
      this.sfx.unlock();
      this.modeChoice = "couples";
      this.ws.action("rare_answer", "start", { mode: "couples" });
    });

    q("#krill-copy-btn")?.addEventListener("click", async () => {
      let text = ra.shareText?.[role] || "";
      if (settings.shareLink) {
        text += `\n${window.location.href}`;
      }
      try {
        await navigator.clipboard.writeText(text);
      } catch (_) {}
      this._copiedAt = performance.now();
      this._lastPhaseKey = "";
      this.update(this._state);
    });

    this._root.querySelectorAll("[data-krill-forfeit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.ws.action("rare_answer", "trigger_forfeit", { kind: btn.getAttribute("data-krill-forfeit") });
      });
    });
    q("#krill-clear-forfeit")?.addEventListener("click", () => {
      this.ws.action("rare_answer", "clear_forfeit");
    });

    this._root.querySelectorAll("[data-krill-set]").forEach((chk) => {
      chk.addEventListener("change", () => {
        this.ws.action("rare_answer", "setting", {
          key: chk.getAttribute("data-krill-set"),
          value: chk.checked,
        });
      });
    });

    q("#krill-sound-toggle")?.addEventListener("change", (e) => {
      this.sfx.enabled = e.target.checked;
    });

    this._root.querySelectorAll("[data-krill-shell]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._wardrobe.shell = btn.getAttribute("data-krill-shell");
        this._saveWardrobe();
        this._lastPhaseKey = "";
        this.update(this._state);
      });
    });
    this._root.querySelectorAll("[data-krill-gear]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._wardrobe.gear = btn.getAttribute("data-krill-gear");
        this._saveWardrobe();
        this._lastPhaseKey = "";
        this.update(this._state);
      });
    });

    q("#krill-launch-daily")?.addEventListener("click", () => {
      this.drawer = null;
      this.modeChoice = "daily";
      this.ws.action("rare_answer", "start", { mode: "daily" });
    });
    q("#krill-launch-unlimited")?.addEventListener("click", () => {
      this.drawer = null;
      this.modeChoice = "unlimited";
      this.ws.action("rare_answer", "start", { mode: "unlimited" });
    });
    q("#krill-launch-couples")?.addEventListener("click", () => {
      this.drawer = null;
      this.modeChoice = "couples";
      this.ws.action("rare_answer", "start", { mode: "couples" });
    });
    q("#krill-launch-puffer")?.addEventListener("click", () => {
      this.drawer = null;
      this.modeChoice = "puffer";
      this.ws.action("rare_answer", "start", { mode: "puffer", players: this.pufferPlayers });
    });
    q("#krill-open-wardrobe")?.addEventListener("click", () => {
      this.drawer = "wardrobe";
      this._lastPhaseKey = "";
      this.update(this._state);
    });
    q("#krill-open-customize")?.addEventListener("click", () => {
      this.drawer = "customize";
      this._lastPhaseKey = "";
      this.update(this._state);
    });
    q("#krill-back-arcade")?.addEventListener("click", () => {
      this.drawer = null;
      this.onBackHome();
    });

    q("#cust-save-theme")?.addEventListener("click", async () => {
      const updated = {
        ...theme,
        title: q("#cust-title").value.trim() || "KRILLION",
        subtitle: q("#cust-sub").value.trim() || "THE DAILY DIVE",
        tagline: q("#cust-tag").value.trim() || "rarer answers sink deeper",
        mascotAccent: q("#cust-mascot").value,
        accentCyan: q("#cust-cyan").value,
        accentPink: q("#cust-pink").value,
        dailyRounds: Number(q("#cust-drounds").value || 7),
        answerSeconds: Number(q("#cust-asec").value || 25),
      };
      await fetch("/api/theme", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      this.drawer = null;
      this._lastPhaseKey = "";
    });

    q("#cust-add-prompt")?.addEventListener("click", async () => {
      const pText = q("#cust-q-text").value.trim();
      const rawAns = q("#cust-q-ans").value.trim();
      if (!pText || !rawAns) return;
      const answers = rawAns.split(",").map((item) => {
        const [wordPart, tierPart] = item.split(":").map((s) => s.trim());
        const tier = ["plankton", "too_clever", "schooler", "rare", "deep_cut", "krillion"].includes(tierPart)
          ? tierPart
          : "rare";
        return [wordPart, [], tier];
      }).filter((a) => a[0]);
      if (!answers.length) return;
      const cur = await fetch("/api/custom-prompts").then((r) => r.json()).catch(() => ({ prompts: [] }));
      const list = Array.isArray(cur.prompts) ? cur.prompts : [];
      list.push({ id: `custom_${Date.now()}`, prompt: pText, answers });
      await fetch("/api/custom-prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompts: list }),
      });
      q("#cust-q-text").value = "";
      q("#cust-q-ans").value = "";
      this.sfx.play("win");
    });
  }

  _esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
}
