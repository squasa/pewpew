# pewpew — Decision Record

**Status: Draft** (interview in progress; nothing here is final until accepted)

## Where things stand (facts, verified in this session)

- Stage 1 is now implemented (`app.py`, `hand_orientation.py`, `renderer3d.py`,
  `face_tracker.py`, `audio_engine.py`, `ui_overlay.py`):
  - **Lightsaber (real 3D + under-hand occlusion):** `Hilt3DRenderer`
    (`renderer3d.py`) renders `models3d/hilt.glb` + depth-occluded 3D
    core/outer-glow blade and 3D trails offscreen with `moderngl` (4x MSAA) and
    tight-ROI composites onto the webcam frame (`hilt_side.png` sprite path
    retired). `hand_occlusion.py` builds a fast Lab skin-refined hand matte so
    the hand/curled fingers sit in front of the gripped hilt and blade unless
    steeply pointed at the lens. Pistol remains 2D until Stage 4.
  - **1:1 3D hand rotation:** `HandOrientationTracker` (`hand_orientation.py`)
    constructs an orthonormal palm basis from landmarks `(0, 5, 17)` with
    blade along `17 -> 5`, One-Euro quaternion smoothing, and an edge-on
    depth-mirror anti-flip guard so the blade never snaps upside down unless
    the hand truly inverts. Pointing at the camera uses real 3D perspective
    with near-plane tip clamping (`z <= -0.11`).
  - **Face tracking & menu:** `FaceTracker` (`face_tracker.py`) loads
    `models/face_landmarker.task` behind toggle `[3]` in `PreviewUI`, which adds
    a preview-only FaceTime-style Effects drawer (`1`–`3`, `[m]`, clickable)
    while keeping `pyvirtualcam` output HUD-free.
  - **Audio root-cause & fix:** Live macOS inspection showed `rongmao’s AirPods
    Pro #3` exposes `1ch @ 48000 Hz` returning exact `0.0` while in-case,
    switches to `1ch @ 24000 Hz` HFP when worn, and shifts `MacBook Pro
    Microphone` dynamically between `3ch` (index 1) and `1ch` (index 3). The
    previous single cross-device `sd.Stream(device=(real_in, bh_out))` ignored
    `default_in`, collided on mismatched CoreAudio rates/clocks, and failed
    silently. `audio_engine.py` replaces it with separate native `InputStream`
    and `OutputStream` (`BlackHole 2ch`) joined by `ResamplingRingBuffer`,
    respects `default_in` and `--mic`, auto-falls back if an external mic stays
    at exact `0.0` >2 s, reconnects stalled CoreAudio streams, logs exact
    devices at startup, drives live `MIC`/`BH` dBFS meters + a loud warning
    banner in `PreviewUI`, and adds a lock-free local headphone monitor toggle
    (`[v]` / `--monitor`: `off` / `sfx` / `mic_sfx`) so the user can choose to
    hear only SFX or their own voice + SFX. Gate 1 follow-up confirmed Stage 1
    audio & rotation worked; user requested under-hand saber occlusion and the
    local hear option (both now added), plus Blender MCP/live preview tooling.

## What the user is asking for (reported, not yet decided)

1. 3D model only — real 3D weapons, no flat sprites.
2. Track hand rotation so the blade can be rotated (roll with the hand).
3. Make the gun 3D too, with better tracking; never upside down; when
   pointing (at the camera / across), it must not look flat.
4. Fix the BlackHole mic problem, whatever it is.
5. Brainstorm effects "my girl would like" together before building them.

## Settled decisions

1. **Staging (Q1, user chose A):** Stage it.
   - **Stage 1 (implemented, awaiting Gate 1 call test):** real-time 3D
     lightsaber (`models3d/hilt.glb`) + 1:1 rotation/pointing tracking fixes +
     BlackHole mic fix + `FaceLandmarker` plumbing + FaceTime-style Effects
     toggles.
   - **Stage 2–4 order (confirmed by user, "yes order is fine"):** interactive
     web games on his face (`Stage 2A`–`2C`), then `Stage 3` Rare Answer
     (couples dive) + customizer, then `Stage 4` 3D pistol. Each stage still
     waits for the previous stage gate before starting.
2. **Microphone (Q2, user: "i want blackhole fix it"):** Keep BlackHole and
   fix it (option A). Stage 1 mic work must include safeguards so failure is
   visible, not silent: live mic level meter in the preview, exact device
   names printed at startup, loud warning on passthrough failure. Exact
   failure symptom still unreported — diagnosis in Stage 1 must reproduce
   in a real call app, not only in capture probes.
3. **Filter menu (Q3, user chose B):** Separate filters as **on/off toggles**
   in a FaceTime-style menu in the pewpew window. Every enabled effect stays
   gesture-auto (any gesture works any time), and effects may overlap
   (e.g. gun in one hand, saber in the other). The menu does not gate
   gestures behind a single active filter.
4. **Hand rotation (Q4, user chose A):** True 1:1 rotation from 3D hand
   orientation, continuously tracked with an anti-flip guard — the model
   never snaps or glitches upside down; it is only inverted when the hand
   truly is. Pointing behavior comes from real 3D rendering (blade/gun
   pointed at the camera genuinely turns toward the viewer, not flat).
5. **Girlfriend effects direction (Q5, user redirected):** Not static cute
   filters first — **interactive games**. She gets a website link (as
   natural as possible: tap link, play in phone browser, no install/account)
   and plays *on his face / against his camera*: GamePigeon-style feel
   ("capture the oomph", not a clone) — darts, 8-ball style mini-games,
   quick juicy rounds where hits, wins, and losses visibly affect his
   FaceTime camera (darts stick to face, win/lose effects, punishments).
   Q5's affection pack (blow-kiss hearts, finger-heart, sparkler) parked
   as later filler filters. Placement/order vs other stages = Q6.
6. **Multigames library (user added):** Generic versions of familiar games
   are wanted too — 8-ball, beer pong, darts, "etc" — as a multigames menu
   she picks from, alongside the on-face originals. User asked for physics
   "exact same as GamePigeon": recorded as the *feel target* (same rules,
   table/ball behavior tuned to play indistinguishably close in normal
   play). Honest constraint: GamePigeon's physics code/parameters are
   proprietary and unpublished, so bit-exact parity cannot be promised or
   verified — games will be original implementations of the standard rules
   with feel tuned against reference play, no copied assets or branding.
   Which titles are in v1 vs later = Q7 (games slate).
7. **Stage 3 Rare Answer / Couples Dive (Krillion mechanics spec — NOT yet built):**
   Public mechanics researched to match the feel of Krillion without scraping,
   decompiling, or copying proprietary third-party datasets:
   - **Flow & timing:** Daily Krillion runs 7 prompts; pewpew Couples Dive runs
     5 short rounds per head-to-head match with a 3 s prompt preview followed by
     a 25 s answer timer (`0` pts on timeout). Wrong/unlisted answers cost only
     time (no score penalty), and the **first valid guess locks in** for the
     round.
   - **Rarity tiers & depth (`1 pt = 10 m`):** 6 named tiers: *Plankton* (`10` pts
     / `100 m`, most obvious), *Too Clever* (`15` pts / `150 m`, popular trap/trick
     answers people overthink into guessing), *Schooler* (`30` pts / `300 m`),
     *Rare* (`60` pts / `600 m`), *Deep Cut* (`85` pts / `850 m`), and *One in a
     Krillion* (`100` pts / `1000 m`, obscure valid or rare unlisted answers).
   - **Non-hinty matching / Krillion autofill confirmation:** Verified
     directly against live `krillion.io` UX: no predictive dropdown or letter
     hints before submit. Instead, under Settings -> **Answer Corrections**
     (default ON), submitting a close spelling/alias typo triggers an inline
     sonar confirmation banner (`“oxigen” → “Oxygen” · submit again to confirm ·
     or edit`) and autofills the canonical answer into the input while the 25s
     clock continues; pressing `DIVE`/Enter again scores it cleanly (and turning
     Answer Corrections OFF scores fuzzy matches immediately). Under
     Settings -> **Clear Rejected Entries** (default OFF), unaccepted answers
     show `"<word>": no echo. try again` without scoring penalties.
   - **Couples Dive Jinx & Forfeits:** Five shared prompts, 3s preview countdown
     + 25s sonar timer, simultaneous locking, and a Couples Jinx rule (if both
     players submit the same canonical answer, both drop to `5` pts / `-50m`!).
     Surface screen renders total pts/depth, vertical dive profile, percentile
     bell curve, **The Bearing**, **The Catch**, `COPY RESULT`, and camera
     forfeits (`seaweed`, `bubble_helmet`, `shrimp_partner`, `neon_glow`).
   - **Data constraint:** Original offline JSON prompt banks + calibrated
     rarity weights and aliases authored in `data/rare_answer_prompts.json` +
     user-customizable `games-web/data/rare_answer_theme.json` & custom prompts;
     no scraped or copied data.

## Stage 2–3 implementation status (built & verified; awaiting Gate 2/3 live call signoff)

- **Stage 2A Join Layer (`game_server.py`):** Single-port pure-Python `asyncio`
  HTTP + RFC6455 WebSocket server (`0.0.0.0:8770`, `/ws` + REST `/api/info`,
  `/api/theme`, `/api/custom-prompts`), 4-character room codes, LAN auto-detect
  + optional `--tunnel` (`cloudflared`) / `--public-url` support, plus built-in
  ISO 18004 QR code generator (`[g]` preview toggle).
- **Stage 2B–2C Camera + Tabletop Arcade (`effect_bus.py`, `table_physics.py`):**
  - *Face Darts*: best-of-3, 6 suction darts/round, face-tracked stuck darts
    (`5.0s`), open-palm blocking, head-movement dodges, loser crown forfeit.
  - *Mouth Catch (Co-op)*: arcing treats caught via `FaceState.jaw_open > 0.28`,
    combo multiplier, miss goo splats.
  - *8-Ball Pool*, *Beer Pong*, and *Classic Darts 301-lite*: fixed-timestep
    simulation in Python with scratch Clown Nose foul, Cup Splashes + open-palm
    swat, rerack/redemption/house rules, and checkout confetti.
- **Stage 3 (`krillion_engine.py`, `games-web/`):** Complete modular HTML/CSS/ES
  module phone UI with 1:1 Krillion CRT scanline prompt cards, rising bubbles,
  scrolling depth gauge, circular radar timer + bottom bar, WebAudio procedural
  sonar & game SFX, Settings/Menu drawers, Live Customizer drawer, Word Duel
  with rival colored silhouette, and persistent `data/streaks.json`. Stage 4
  (3D pistol, parked affection pack, blade colors, dual sabers) remains untouched.

## Unresolved

- [x] Scope/staging: real-time 3D for both weapons at once, or staged? → A
- [x] Mic route: keep-and-fix BlackHole or drop it? → keep and fix (A).
      Root causes isolated and fixed in Stage 1 `audio_engine.py`.
- [x] Filter menu shape: separate filters how? (Q3) → B, toggles + gesture-auto.
- [x] Rotation/pointing behavior details → 1:1 roll + anti-flip guard (A);
      pointing handled by real 3D rendering.
- [x] Which "girlfriend" effects to build? → interactive web games on his
      face/camera (Decision 5); affection pack parked.
- [x] Games placement: order vs Stage 1 / 3D gun (Q6) → confirmed
      Stage 2/3 (games + Rare Answer) before Stage 4 (3D gun).
- [x] Stage 2A transport choice: single-port HTTP+WS server (`game_server.py`)
      works directly on LAN (`http://<lan-ip>:8770/?room=CODE`) and behind one
      `cloudflared tunnel --url http://127.0.0.1:8770` (`--tunnel`) / custom relay
      (`--public-url`).
- **Dual-Device 3D AR & Krillion Overhaul (verified offline & headless browser):**
  - *Dual-Device 3D Rendering (`games_ar3d.py`, `games-web/vendor/three.module.min.js`, `games-web/js/three_helpers.js`):* Host Mac webcam + OBS Virtual Camera renders real ModernGL PBR 3D geometry (`Red Solo cups`, `emerald pool table & 16 balls`, `pub dartboard & darts`, `3D palm hex shield`, `frosted donut`, and a `3D articulated tier-colored shrimp`) with MediaPipe pinch-flick host gestures (`process_webcam_hands`), while partner's phone runs locally vendored `Three.js r170` WebGL 3D across all 5 action games (`pool`, `beer_pong`, `classic_darts`, `face_darts`, `mouth_catch`) with GamePigeon-style ball/rail raycast aim lines on 8-Ball Pool and no guide rings on Darts/Cup Pong/Mouth Catch.
  - *GamePigeon Cup Pong Physics (`BeerPongMatch`, `games-web/js/beer_pong.js`):* Sub-stepped 3D cup rim torus (`e = 0.66`) & tapered outer plastic cone (`e = 0.62`) collisions with cup wobble, table spin bounce (`pong_table_bounce`), blind `85ms` release-vector swipe mechanics, and no cartoonish guide rings or table ripples.
  - *Recorded WAV + Underwater Audio (`game_server.py`, `games-web/sounds/*.wav`, `games-web/js/ws_client.js`):* Serves recorded `.wav` buffers for Pool (`pool_clack`, `pool_break`, `pool_pot`), Cup Pong (`pong_bounce`, `pong_cup`), and Darts (`thud`), plus synthesized Krillion underwater plunge & sonar cues.
  - *Krillion Ocean Plunge & Dictionary Expansion (`krill_ocean.js`, `rare_answer.js`, `krillion_engine.py`, `data/rare_answer_prompts.json`, `data/word_duel_words.json`):* Non-repeating Daily/Unlimited/Couples prompts (`_dive_seq` + `_recent_ids`), unambiguous half-answer prefix + conservative typo autofill confirmation (`schnauz` -> `Schnauzer`), 60 prompts (1,552 answers), 12,769 valid 5-letter Word Duel words, and a 2px/m dual-canvas vertical ocean plunge triggered on every reveal with depth creatures, horizontal `.krill-tierline` crossings, and dynamic tier-colored shrimp recoloring.
- [ ] Gate 2/3 live FaceTime call signoff (Stage 4 remains gated until approved).
- [ ] Done-means checklist + explicit acceptance of scope contract.
