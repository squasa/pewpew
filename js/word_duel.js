// Word Duel (Stage 3) — 5-letter race, live rival silhouette, daily & rematch modes, emoji share

const KEY_ROWS = [
  ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
  ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
  ["ENTER", "Z", "X", "C", "V", "B", "N", "M", "⌫"],
];

export class WordDuelView {
  constructor(ws, sfx, myRole = () => "guest") {
    this.ws = ws;
    this.sfx = sfx;
    this.myRole = myRole;
    this._current = "";
    this._error = "";
    this._state = null;
    this._container = null;
    this._lastSig = "";
    this._onKeyDown = (e) => this._handlePhysKey(e);
  }

  mount(container, state) {
    this._container = container;
    this._current = "";
    this._error = "";
    this._lastSig = "";
    window.addEventListener("keydown", this._onKeyDown);
    this.update(state);
  }

  unmount() {
    window.removeEventListener("keydown", this._onKeyDown);
    this._container = null;
  }

  onAck(msg) {
    if (msg.type !== "word_ack" || !msg.res) return;
    if (msg.res.ok) {
      this._current = "";
      this._error = "";
      this.sfx.play(msg.res.solved ? "win" : "krill_ping");
    } else {
      this._error = msg.res.error || "Invalid word";
      this.sfx.play("krill_miss");
      this._render(this._state.word_duel);
    }
  }

  update(state) {
    this._state = state;
    const wd = state.word_duel;
    if (!wd || !this._container) return;
    const role = this.ws.role === "host" ? "host" : "guest";
    const opp = role === "guest" ? "host" : "guest";
    const myRows = wd.boards?.[role]?.rows?.length || 0;
    const oppRows = wd.boards?.[opp]?.rows?.length || 0;
    const sig = `${wd.mode}|${wd.phase}|${myRows}|${oppRows}|${wd.winner}|${role}`;
    if (sig !== this._lastSig) {
      if (this._lastSig && wd.phase === "finished" && wd.winner === role) this.sfx.play("win");
      this._lastSig = sig;
      this._render(wd);
    }
  }

  _handlePhysKey(e) {
    if (!this._container) return;
    if (document.activeElement && ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    if (e.key === "Enter") {
      this._press("ENTER");
    } else if (e.key === "Backspace") {
      this._press("⌫");
    } else if (/^[a-zA-Z]$/.test(e.key)) {
      this._press(e.key.toUpperCase());
    }
  }

  _press(key) {
    const wd = this._state?.word_duel;
    const role = this.ws.role === "host" ? "host" : "guest";
    if (!wd || wd.phase !== "playing" || wd.boards?.[role]?.done) return;
    this.sfx.unlock();
    if (key === "⌫") {
      this._current = this._current.slice(0, -1);
      this._error = "";
      this._render(wd);
    } else if (key === "ENTER") {
      if (this._current.length < 5) {
        this._error = "Need 5 letters";
        this._render(wd);
        return;
      }
      this.ws.action("word_duel", "guess", { word: this._current });
    } else if (this._current.length < 5) {
      this._current += key;
      this._error = "";
      this._render(wd);
    }
  }

  _keyStates(rows) {
    const rank = { absent: 1, present: 2, correct: 3 };
    const map = {};
    rows.forEach((r) => {
      for (let i = 0; i < 5; i++) {
        const ch = r.word[i];
        const st = r.states[i];
        if (!map[ch] || rank[st] > rank[map[ch]]) map[ch] = st;
      }
    });
    return map;
  }

  _render(wd) {
    const role = this.ws.role === "host" ? "host" : "guest";
    const opp = role === "guest" ? "host" : "guest";
    const myBoard = wd.boards?.[role] || { rows: [], done: false, solved: false };
    const oppBoard = wd.boards?.[opp] || { rows: [], done: false, solved: false };
    const kStates = this._keyStates(myBoard.rows || []);

    const rowsHtml = Array.from({ length: 6 }, (_, r) => {
      const doneRow = myBoard.rows[r];
      const isActive = !doneRow && !myBoard.done && r === myBoard.rows.length;
      return `<div class="wd-row">${Array.from({ length: 5 }, (_, c) => {
        const ch = doneRow ? doneRow.word[c] : (isActive ? (this._current[c] || "") : "");
        const st = doneRow ? doneRow.states[c] : "";
        return `<div class="wd-tile ${st}">${ch}</div>`;
      }).join("")}</div>`;
    }).join("");

    const oppMiniHtml = `<div class="wd-mini-grid" style="gap:3px;">${Array.from({ length: 6 }, (_, r) => {
      const rr = oppBoard.rows[r];
      return `<div class="wd-mini-row" style="gap:3px;">${Array.from({ length: 5 }, (_, c) => `<div class="wd-mini-cell ${rr ? rr.states[c] : ""}" style="width:12px;height:12px;border-radius:3px;"></div>`).join("")}</div>`;
    }).join("")}</div>`;

    const oppLabel = opp === "host" ? "Him (Webcam)" : "Her (Phone)";
    const oppBadge = oppBoard.solved ? "✅ SOLVED" : (oppBoard.done ? "❌ DONE" : `${oppBoard.rows.length}/6`);
    const statusLine = wd.phase === "finished"
      ? `Target: ${wd.target} · ${wd.winner === role ? "YOU WIN! 🏆" : (wd.winner === "draw" ? "DRAW" : `${oppLabel.toUpperCase()} WINS`)}`
      : (this._error || (myBoard.done ? `Waiting for ${oppLabel} to finish...` : "1v1 Race — Green/Yellow tiles live on cam & phone!"));

    this._container.innerHTML = `
      <div class="game-panel">
        <div class="hud-row">
          <span style="font-weight:700;color:var(--accent-pink);">1V1 RACE · HER VS HIM</span>
          <div style="display:flex;align-items:center;gap:10px;font-size:12px;color:var(--text);">
            <div style="display:flex;flex-direction:column;align-items:flex-end;line-height:1.2;">
              <strong style="color:var(--accent-cyan);">${oppLabel}</strong>
              <span style="font-size:11px;color:var(--muted);">${oppBadge}</span>
            </div>
            ${oppMiniHtml}
          </div>
        </div>

        <div style="font-size:13px;font-weight:700;color:${this._error ? "var(--danger)" : "var(--accent-cyan)"};min-height:18px;">
          ${statusLine}
        </div>

        <div class="wd-grid">${rowsHtml}</div>

        <div class="wd-kbd">
          ${KEY_ROWS.map((row) => `
            <div class="wd-kbd-row">
              ${row.map((k) => {
                const cls = kStates[k] || "";
                const wide = (k === "ENTER" || k === "⌫") ? "wide" : "";
                return `<button class="wd-key ${cls} ${wide}" data-wd-key="${k}">${k}</button>`;
              }).join("")}
            </div>
          `).join("")}
        </div>

        <div style="display:flex;gap:8px;width:100%;max-width:340px;">
          <button class="btn-cyan" id="wd-copy-btn" style="flex:1;">Copy Grid 📋</button>
          <button class="btn-primary" id="wd-rematch-btn" style="flex:1;">New Word</button>
        </div>
      </div>
    `;

    this._container.querySelectorAll("[data-wd-key]").forEach((btn) => {
      btn.addEventListener("click", () => this._press(btn.getAttribute("data-wd-key")));
    });
    this._container.querySelector("#wd-rematch-btn")?.addEventListener("click", () => this.ws.action("word_duel", "start", { mode: "duel" }));
    this._container.querySelector("#wd-copy-btn")?.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(wd.shareText || ""); } catch (_) {}
      const b = this._container.querySelector("#wd-copy-btn");
      if (b) b.textContent = "Copied ✓";
    });
  }
}
