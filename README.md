# pewpew — finger-gun pistol, lightsaber & multiplayer camera games

Make a finger gun 👉 and a pistol appears in your hand. Flick your thumb
down (like a hammer falling), say **"pew!"** sharply into the mic, or press
SPACE to fire: muzzle flash, tracer, ejecting shell casing, recoil, screen
shake — and a gunshot mixed into your microphone feed.

Close your **fist** ✊ and a real 3D lightsaber ignites instead: the blade
*slides out* of `models3d/hilt.glb` over ~0.45 s with an ignition sweep,
rotates 1:1 with your hand roll and camera-pointing angle (with an anti-flip
guard so it doesn't snap upside down), hums with Doppler pitch/whoosh from
swing speed, crackles with clash sparks + screen shake on snap stops, and
retracts when you open your hand. Sounds are synthesized in
`make_saber_sounds.py` & `make_game_sounds.py` and mixed with your real
microphone into BlackHole 2ch.

## Run

```sh
./run.sh            # or: .venv/bin/python app.py
.venv/bin/python app.py --mic "MacBook" --monitor sfx   # hear SFX in headphones
.venv/bin/python app.py --tunnel                        # expose QR/link via cloudflared
```

A preview window opens with a clickable **Effects** menu (`1` Finger Gun, `2`
3D Lightsaber, `3` Face Tracking, `m` hide/show menu), live `MIC` / `BH` dBFS
meters, `g` to toggle the phone games QR invite card, `v` to cycle local
headphone monitor (`OFF` -> `SFX ONLY` -> `SELF+SFX`), `a` to cycle input mics,
`SPACE` to fire, and `q` / `Esc` to quit. The OBS Virtual Camera feed stays
HUD-free while compositing active Stage 2–3 camera game effects (stuck darts,
food splats, clown nose, ocean forfeits, confetti). Only one app can read the
hardware webcam at a time — stop other camera apps first if needed.

## Play Multiplayer Games on Phone (`games-web/`)

pewpew launches a built-in single-port HTTP + WebSocket games server (`:8770`)
and prints two join links in the terminal (press `g` in the preview window to
display the scannable QR card):

- **Same Wi-Fi (LAN):** scan the QR code or open the printed `http://<lan-ip>:8770/?room=CODE` link on her phone.
- **Over the internet:** install Cloudflare Tunnel (`brew install cloudflared`) and run `.venv/bin/python app.py --tunnel` (or pass `--public-url https://...`).
- **2-Phone Controller:** open `&role=host` on your own phone to play head-to-head games (`Krillion — Couples Dive`, `Word Duel`, `8-Ball Pool`, `Beer Pong`, `301 Darts`) together.

### Included Games

1. **Krillion — Daily, Unlimited & Couples Dive (`rare_answer`):** Non-repeating 60-prompt (1,552-answer) ocean-radar quiz with CRT scanlines, unambiguous half-answer & conservative typo autofill confirmation (`schnauz` -> `Schnauzer`), 25s circular sonar timer, vertical ocean descent after every revealed answer (`#krill-sea` / `#krill-fore` with surface waves, sea creatures from reef fish to Giant Squid/Titanic/vents, dashed horizontal tier lines, and dynamic tier-colored shrimp mascot), plus a 3D articulated shrimp rendered onto the webcam! Includes Couples Jinx penalty, camera forfeits, Wardrobe, Keep Diving, and 🎨 Live Customizer.
2. **3D Face Darts:** First-person Three.js WebGL + ModernGL webcam AR; suction darts stick to your live tracked face, open palm raises a 3D hex shield (`+20`), head movement dodges (`+10`), zero guide circles.
3. **3D Mouth Catch (Co-op):** First-person 3D frosted donuts & live jaw-synced avatar; open mouth (`jaw_open > 0.28`) catches for combos, misses splat onto face.
4. **3D 8-Ball Pool:** Three.js PBR mahogany table + 16 rolling numbered spheres, behind-cue & overhead camera toggle, GamePigeon-style cue aim ray terminating at first ball/rail contact plus shorter struck-ball trajectory preview, English spin selector, recorded WAV break/clack/pot audio, and pinch-flick webcam play.
5. **3D Cup Pong:** First-person Three.js 3D Red Solo cups on bar wood, physical cup rim torus & cone wall bounces with rim wobble, blind GamePigeon-style high-sensitivity swipe flick (no trajectory preview line), bounce = 2x, palm swat defense & recorded ping-pong audio.
6. **3D Darts 301:** First-person Three.js 20-sector sisal bristle dartboard with impact camera zoom, blind upward swipe/pinch throws (no guide circle), bust handling & Double-Out toggle.
7. **Word Duel:** 5-letter race (`Duel` & `Daily` modes) backed by a 12,769-word English 5-letter dictionary (`777` targets) with live rival color grid & emoji share.

## Use it in FaceTime / Zoom / Discord

1. Start pewpew and confirm the terminal `[audio]` log and preview `MIC` / `BH`
   meters move when you speak. If the top red warning banner shows all-zeros or
   fallback warnings, press `a` (or click the mic row in `Effects`) to switch
   input mics or check macOS **Privacy & Security -> Microphone**.
2. Video / Camera: pick **OBS Virtual Camera** (FaceTime: Video menu).
3. Microphone: pick **BlackHole 2ch**. pewpew runs separate native-rate input and
   BlackHole output streams (resampling automatically so 24 kHz Bluetooth mics
   and 48 kHz BlackHole don't collide) and mixes SFX cleanly.
4. In FaceTime, set macOS Control Center **Mic Mode** to **Standard** (not Voice
   Isolation, which can gate SFX or fight the synthetic feed).
5. Leave your speakers/headphones as output so you hear the other person normally.

No BlackHole? Install with `brew install --cask blackhole-2ch`, or run with
`--no-audio` / let the fallback alert show.

## How it works

- `app.py` — webcam -> MediaPipe HandLandmarker (`models/hand_landmarker.task`)
  -> 2D finger-gun FX + 3D `SaberFX` + `FaceTracker` + `GamesEngine` ->
  `EffectBus` composited BEFORE `pyvirtualcam` -> preview window HUD. CLI flags:
  `--camera`, `--mic`, `--monitor`, `--port`, `--room`, `--public-url`,
  `--tunnel`, `--no-games`, `--no-vcam`, `--no-audio`, `--selftest`.
- `game_server.py` / `games_engine.py` / `krillion_engine.py` / `table_physics.py` —
  Single-port asyncio HTTP + RFC6455 WebSocket server, ISO 18004 QR generator,
  authoritative deterministic physics/scoring, Krillion normalization/autofill/Jinx
  & persistent `data/streaks.json`.
- `games_ar3d.py` — ModernGL PBR 3D AR overlay renderer drawing 3D Red Solo cups,
  3D emerald pool table & spheres, 3D dartboard/darts, 3D palm shield, 3D donut,
  and 3D tier-colored shrimp directly onto the live webcam & OBS Virtual Camera.
- `effect_bus.py` — thread-safe face-anchored stuck darts, food splats, clown nose,
  ocean forfeit crowns, splashes, callouts & confetti composited pre-vcam.
- `games-web/` — modular Three.js r170 (`vendor/three.module.min.js`) & dual-canvas
  Krillion (`krill_ocean.js`) browser client (`index.html`, `styles.css`, `js/*.js`,
  `sounds/*.wav`, `data/rare_answer_theme.json`) with recorded WAV + WebAudio SFX.
- `hand_orientation.py` — gesture classifiers (including open-palm blocker),
  One-Euro filters, and 3D `(0, 5, 17)` palm basis with anti-flip guard.
- `hand_occlusion.py` — anatomical + Lab skin-color hand matte so your real
  hand & curled fingers sit in front of the gripped lightsaber hilt/blade.
- `renderer3d.py` — `Hilt3DRenderer` (`moderngl` 4x MSAA offscreen renderer)
  drawing `models3d/hilt.glb` + depth-occluded 3D core/outer glow blade,
  3D trail ribbons, near-plane tip clamp, bloom, and tight-ROI composite.
- `face_tracker.py` — MediaPipe `FaceLandmarker` (`models/face_landmarker.task`)
  active on `[3]` or when face games run, exposing landmarks, `jaw_open`,
  `nose_px`, `mouth_px`, and `face_scale_px`.
- `audio_engine.py` — separate native `InputStream` + `OutputStream` (`BlackHole
  2ch`) bridged by `ResamplingRingBuffer`, automatic `0.0` mic fallback,
  CoreAudio stall auto-reconnect, local headphone monitor (`off` / `sfx` /
  `mic_sfx`), polyphonic SFX mixer, live `mic_peak`/`bh_peak`, and `"pew!"`.
- `ui_overlay.py` — `PreviewUI` FaceTime-style clickable Effects drawer, `MIC` /
  `BH` dBFS meters, preview-only `[g]` QR Invite Card, and audio warning banner.
- `models3d/build_hilt.py` — Blender procedural hilt (`hilt.blend` / `hilt.glb`).
- `models3d/live_reload.py` / `tools/blender_live_mcp.py` — live Blender GUI
  auto-reload + TCP/MCP bridge for real-time step-by-step 3D modeling.
- `tools/live_stage.py` — live SSE auto-reload local server for web/3D previews.
- `make_assets.py` / `make_saber_sounds.py` / `make_game_sounds.py` — regenerate
  pistol, flash, lightsaber, and Stage 2–3 game WAV assets.
- `.venv/bin/python app.py --selftest` — full Stage 1–3 offline & local HTTP+WS
  verification suite.

## Watch the 3D model live while it changes

```sh
open -a Blender --args "$PWD/models3d/hilt.blend" --python "$PWD/models3d/live_reload.py"
```

Blender opens on the hilt and both **auto-reloads on `.blend` save** AND runs
the live `127.0.0.1:9876` bridge (`tools/blender_live_mcp.py`, wired in
`~/.gemini/config/mcp_config.json` as `blender-live`) so every 3D modeling step
renders immediately in front of you in the open Blender viewport.

## Ideas to add next

Dual-wield sabers (tracks 2 hands already), blade colours (open-palm
cycle: blue → green → red), palm repulsor blast, Kamehameha two-hand
charge, arm/pose tracking for wings.
