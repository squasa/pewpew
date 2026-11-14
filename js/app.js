// Main PewPew Arcade Router + WebSocket Lifecycle

import { WsClient, SoundFX } from "./ws_client.js";
import { RareAnswerView } from "./rare_answer.js";
import { FaceDartsView } from "./face_darts.js";
import { MouthCatchView } from "./mouth_catch.js";
import { PoolView } from "./pool.js";
import { BeerPongView } from "./beer_pong.js";
import { ClassicDartsView } from "./classic_darts.js";
import { WordDuelView } from "./word_duel.js";

const stageEl = document.getElementById("stage");
const dotEl = document.getElementById("conn-dot");
const roomEl = document.getElementById("room-label");
const homeBtn = document.getElementById("btn-home");
const roleBtn = document.getElementById("btn-role-switch");
const soundBtn = document.getElementById("btn-sound");

const sfx = new SoundFX();
let latestState = null;
let mountedGame = null;
let mountedView = null;

const views = {
  rare_answer: new RareAnswerView(null, sfx, () => ws.selectGame("lobby")),
  face_darts: null,
  mouth_catch: null,
  pool: null,
  beer_pong: null,
  classic_darts: null,
  word_duel: null,
};

function initViews(wsClient) {
  views.rare_answer = new RareAnswerView(wsClient, sfx, () => wsClient.selectGame("lobby"));
  views.face_darts = new FaceDartsView(wsClient, sfx);
  views.mouth_catch = new MouthCatchView(wsClient, sfx);
  views.pool = new PoolView(wsClient, sfx, () => wsClient.role);
  views.beer_pong = new BeerPongView(wsClient, sfx, () => wsClient.role);
  views.classic_darts = new ClassicDartsView(wsClient, sfx, () => wsClient.role);
  views.word_duel = new WordDuelView(wsClient, sfx, () => wsClient.role);
}

function _formatPlayers(players) {
  if (!players?.length) return "Waiting on friends...";
  const items = players.map((p) => {
    const tag = p.role === "guest" ? "P1" : (p.role === "host" ? "P2" : "Viewer");
    const nm = (p.name || "").trim();
    const shown = nm || tag;
    return tag === "Viewer" ? `Viewer: ${shown}` : `${tag}: ${shown}`;
  });
  return `Online · ${items.join(" · ")}`;
}

function renderLobby(state) {
  const pSummary = _formatPlayers(state?.players);
  stageEl.innerHTML = `
    <div class="hub-wrap">
      <div class="hub-hero">
        <h1>PEWPEW ARCADE</h1>
        <p>${pSummary}</p>
      </div>

      <div class="profile-bar">
        <input id="hub-name-inp" placeholder="Your nickname…" value="${ws.name || ""}" maxlength="20" />
        <button class="btn-cyan" id="hub-save-name">Save</button>
      </div>

      <div class="game-grid">
        <button class="game-card featured" data-pick="rare_answer">
          <span class="g-tag">1V1 JINX</span>
          <div class="g-icon">🦐</div>
          <div class="g-title">Krillion</div>
          <div class="g-desc">Pick the weirdest valid answer — 1v1 side-by-side Phones with live Ocean AR on FaceTime.</div>
        </button>

        <button class="game-card" data-pick="face_darts">
          <span class="g-tag">1V1 AR FACE</span>
          <div class="g-icon">🎯</div>
          <div class="g-title">3D Face Darts</div>
          <div class="g-desc">Throw suction darts at the live webcam avatar — an open palm on cam raises a glowing hex shield.</div>
        </button>

        <button class="game-card" data-pick="mouth_catch">
          <span class="g-tag">1V1 CAM CATCH</span>
          <div class="g-icon">🍩</div>
          <div class="g-title">3D Mouth Catch</div>
          <div class="g-desc">Toss frosted donuts toward the webcam — open wide to catch or take a live forehead splat.</div>
        </button>

        <button class="game-card" data-pick="pool">
          <span class="g-tag">1V1 TOP VIEW</span>
          <div class="g-icon">🎱</div>
          <div class="g-title">3D 8-Ball Pool</div>
          <div class="g-desc">Top-down GamePigeon-style 8-ball on both phones — tap felt to aim, pull cue bar to shoot with live AR table.</div>
        </button>

        <button class="game-card" data-pick="beer_pong">
          <span class="g-tag">1V1 TURN PONG</span>
          <div class="g-icon">🥤</div>
          <div class="g-title">3D Cup Pong</div>
          <div class="g-desc">2-phone flick to sink 6 or 10 Solo cups — 3 shots per turn, +1 free shot on every make.</div>
        </button>

        <button class="game-card" data-pick="classic_darts">
          <span class="g-tag">1V1 301</span>
          <div class="g-icon">🎯</div>
          <div class="g-title">3D Darts 301</div>
          <div class="g-desc">2-phone 301 showdown — flick toward the board and watch live aim &amp; stuck darts on cam.</div>
        </button>

        <button class="game-card" data-pick="word_duel">
          <span class="g-tag">1V1 RACE</span>
          <div class="g-icon">🟩</div>
          <div class="g-title">Word Duel</div>
          <div class="g-desc">Same 5-letter word 1v1 race on both phones with live side-by-side boards on FaceTime.</div>
        </button>
      </div>
    </div>
  `;

  stageEl.querySelectorAll("[data-pick]").forEach((btn) => {
    btn.addEventListener("click", () => {
      sfx.unlock();
      ws.selectGame(btn.getAttribute("data-pick"));
    });
  });

  stageEl.querySelector("#hub-save-name")?.addEventListener("click", () => {
    const val = stageEl.querySelector("#hub-name-inp")?.value || "";
    ws.setProfile(val);
  });
}

function _refreshHeaderRole() {
  if (!roleBtn) return;
  if (ws.role === "spectator") {
    roleBtn.textContent = "Viewer ⇄";
  } else {
    const pTag = ws.role === "host" ? "P2" : "P1";
    const nm = ws.playerName(ws.role);
    roleBtn.textContent = nm && nm !== pTag ? `${pTag}: ${nm} ⇄` : `${pTag} (You) ⇄`;
  }
}

function syncUI(state) {
  latestState = state;
  _refreshHeaderRole();
  const target = state?.activeGame || "lobby";
  homeBtn.style.visibility = target === "lobby" ? "hidden" : "visible";

  if (target !== mountedGame) {
    if (mountedView?.unmount) mountedView.unmount();
    mountedView = null;
    mountedGame = target;

    if (target === "lobby") {
      renderLobby(state);
      return;
    }
    const v = views[target];
    if (v) {
      mountedView = v;
      v.mount(stageEl, state);
      return;
    }
  }

  if (target === "lobby") {
    // Only refresh player summary text if name input isn't focused
    const inp = stageEl.querySelector("#hub-name-inp");
    if (!inp || document.activeElement !== inp) {
      const pEl = stageEl.querySelector(".hub-hero p");
      if (pEl) {
        pEl.textContent = _formatPlayers(state.players);
      }
    }
  } else if (mountedView?.update) {
    mountedView.update(state);
  }
}

function renderConnectPrompt(reason, errMsg = "") {
  if (mountedView?.unmount) mountedView.unmount();
  mountedView = null;
  mountedGame = null;
  const errHtml = errMsg
    ? `<div style="padding:10px 12px;border-radius:10px;background:rgba(239,68,68,0.16);border:1px solid rgba(248,113,113,0.45);color:#fecaca;font-size:13px;font-weight:700;text-align:center;">${errMsg}</div>`
    : "";
  stageEl.innerHTML = `
    <div class="hub-wrap" style="max-width:420px;margin:28px auto;">
      <div class="hub-hero">
        <h1>PEWPEW 1V1</h1>
        <p>Enter your 4-character player code shown on the webcam and choose a nickname.</p>
      </div>
      <div class="game-panel" style="gap:12px;">
        ${errHtml}
        <label style="font-size:12px;color:var(--text-dim);letter-spacing:0.06em;">YOUR NICKNAME</label>
        <input id="gh-name-inp" placeholder="e.g. Alex" value="${(ws.name || "").replace(/"/g, "&quot;")}" maxlength="16" autocomplete="off" style="width:100%;padding:12px;border-radius:12px;border:1px solid rgba(148,163,184,0.35);background:#0f172a;color:#fff;font-size:16px;font-weight:700;" />
        <label style="font-size:12px;color:var(--text-dim);letter-spacing:0.06em;">PLAYER CODE</label>
        <input id="gh-code-inp" placeholder="e.g. K7M1" value="${ws.room || ""}" maxlength="6" autocomplete="off" autocapitalize="characters" style="width:100%;padding:14px 12px;border-radius:12px;border:1px solid rgba(103,232,249,0.45);background:#0f172a;color:#fff;text-transform:uppercase;text-align:center;font-size:26px;font-weight:900;letter-spacing:0.24em;" />
        <button class="btn-primary" id="gh-connect-btn" style="width:100%;padding:14px;font-size:16px;">Join 1v1 Room</button>
      </div>
    </div>
  `;
  const nameInp = stageEl.querySelector("#gh-name-inp");
  const inp = stageEl.querySelector("#gh-code-inp");
  const submit = () => {
    const code = (inp?.value || "").trim().toUpperCase();
    if (code.length < 3) return;
    const nick = (nameInp?.value || "").trim().slice(0, 16);
    if (nick) {
      ws.name = nick;
      localStorage.setItem("pewpew_name", nick);
    }
    latestState = null;
    ws.setCode(code);
    renderConnecting(code);
  };
  stageEl.querySelector("#gh-connect-btn")?.addEventListener("click", submit);
  inp?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
  inp?.focus();
}

function renderConnecting(code) {
  if (mountedView || latestState) return;
  stageEl.innerHTML = `
    <div class="hub-wrap" style="max-width:420px;margin:32px auto;text-align:center;">
      <div class="hub-hero">
        <h1>JOINING ${code}…</h1>
        <p>Connecting to Mac webcam 1v1 room via cloud relay.</p>
      </div>
      <div class="game-panel" style="gap:10px;align-items:center;">
        <button class="btn-cyan" id="gh-change-code" style="width:100%;">Change Code</button>
      </div>
    </div>
  `;
  stageEl.querySelector("#gh-change-code")?.addEventListener("click", () => {
    renderConnectPrompt("MISSING CODE");
  });
}

const ws = new WsClient(
  (state) => syncUI(state),
  (online, label, meta = {}) => {
    dotEl.className = `dot ${online ? "online" : "offline"}`;
    roomEl.textContent = `CODE ${label || "----"} ✎`;
    _refreshHeaderRole();
    if (online && latestState && mountedView?.update) {
      mountedView.update(latestState);
    }
    const errCode = meta?.code;
    if (!online && (errCode === "missing_code" || errCode === "bad_room" || errCode === "expired")) {
      if (errCode === "bad_room" || errCode === "expired") latestState = null;
      renderConnectPrompt(label, errCode === "missing_code" ? "" : (meta?.message || label));
    } else if (!online && !latestState && errCode === "connecting") {
      renderConnecting(label);
    }
  },
  (ack) => {
    if (mountedView?.onAck) mountedView.onAck(ack);
  }
);

roomEl.style.cursor = "pointer";
roomEl.title = "Tap to change 4-character player code";
roomEl.addEventListener("click", () => {
  renderConnectPrompt("MISSING CODE");
});

initViews(ws);
ws.connect();

homeBtn.addEventListener("click", () => ws.selectGame("lobby"));
roleBtn.addEventListener("click", () => {
  const nextRole = ws.role === "guest" ? "host" : "guest";
  ws.setProfile(ws.name, nextRole);
});
soundBtn.addEventListener("click", () => {
  sfx.enabled = !sfx.enabled;
  soundBtn.textContent = sfx.enabled ? "🔊" : "🔇";
  if (sfx.enabled) sfx.unlock();
});
