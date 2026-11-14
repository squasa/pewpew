# HANDOFF BRIEF — pewpew: FaceTime effects + multigames (staged plan)

You are taking over an existing macOS project. Work in stages exactly as
below. Do NOT skip stage gates. Do NOT start a later stage without the
user's explicit approval. First task after reading this: confirm you
understand the stage plan, then implement STAGE 1 ONLY when the user says go.

## 1. What this is

pewpew is a Python app the user runs on his Mac during FaceTime calls
with his girlfriend. Webcam frames are processed with MediaPipe hand
tracking, composited with CGI effects, and sent to a virtual camera
(OBS Virtual Camera via pyvirtualcam) that FaceTime uses as his camera.
His real microphone + effect sounds are mixed into BlackHole 2ch, which
FaceTime uses as his microphone. She needs nothing installed for the
effects; for games (Stage 2+) she only opens a website link on her phone.

Project root: /Users/rmclol/Downloads/fo/pewpew
Run: ./run.sh  (or .venv/bin/python app.py [--camera N] [--no-vcam] [--no-audio])
Test: .venv/bin/python app.py --selftest   (must stay green; extend it)
Python 3.10 venv in .venv (opencv, mediapipe 1.2 Tasks API, pyvirtualcam,
sounddevice, numpy, pillow). No legacy mediapipe.solutions — Tasks only.
Hand model: models/hand_landmarker.task (Google free model, present).

FaceTime setup (user side): Camera = OBS Virtual Camera,
Microphone = BlackHole 2ch (already installed: BlackHole2ch.driver).
Only one app can hold the camera: a sibling project
/Users/rmclol/Downloads/fo/live-faceswap (Flask face-swap on port 8765,
same pyvirtualcam pattern, see its app.py ~line 736) must not be running
simultaneously.

## 2. Current state (verified)

- app.py (~950 lines): finger-gun -> procedural 2D pistol sprite
  (make_assets.py generates assets/pistol.png, muzzle_flash.png,
  gunshot.wav synthesized in code). Thumb-flick / mic-pop ("pew!") /
  SPACE fires: flash, tracer, casing, recoil, shake; gunshot mixed to
  BlackHole. Mic passthrough verified end-to-end by recording BlackHole
  via ffmpeg AVFoundation (gunshot peak 0.92).
- Fist -> lightsaber: hilt is a REAL Blender 3D model
  (models3d/build_hilt.py -> hilt.blend + hilt.glb + hilt_beauty.png;
  app uses rendered side sprite assets/hilt_side.png). Blade slides out
  over 0.45s with ignition sweep, retracts 0.32s; hum loop with
  speed-driven Doppler (+3 semitones) + whoosh; clash on swing-stop
  (sparks + shake). Sounds synthesized Ben-Burtt-style (detuned motor
  hums + buzz) by make_saber_sounds.py. Verified via BlackHole capture
  (hum RMS 0.201, clash peak 1.0). Emitter alignment measured good
  (127.6px vs 126.8px target). Known gotcha: Blender shadow-catcher
  Floor pollutes sprite alpha — build_hilt.py hides it for sprite render.
- Tracking: HandLandmarker VIDEO mode, 2 hands, One-Euro filters,
  world-landmark foreshortening for saber. Mirrored 1280x720@30.
  Preview window has HUD; vcam feed is HUD-free.
- Blender 5.3 installed (/Applications/Blender.app). Headless build:
  blender -b --factory-startup --python-exit-code 1 -P models3d/build_hilt.py
  Live view: open -a Blender --args "$PWD/models3d/hilt.blend" --python
  "$PWD/models3d/live_reload.py" (viewport auto-reloads on rebuild).
- DECISIONS.md (Draft) is the governing decision record. Read it first.
  README.md documents user-facing behavior. Keep both updated.

LIMITATIONS driving this plan: sprites are flat (no hand roll, can look
upside down, pointing at camera only foreshortens). User reports mic
"sometimes doesn't work" with BlackHole in real calls (exact symptom
unknown; classic cause: call app mic set to BlackHole while pewpew not
running = silence).

## 3. Settled decisions (from DECISIONS.md — do not relitigate)

1. STAGED. Stage 1: real-time 3D saber + rotation/pointing tracking +
   mic fix. Stage 2 was 3D gun, now overtaken by games (see §5 order).
   Later stages are deferred proposals needing separate user approval.
2. MIC: keep BlackHole, fix it. Mandatory safeguards: live mic level
   meter in preview, exact device names at startup, loud failure warning
   (never fail silent). Reproduce the real failure in an actual call app.
3. FILTERS: separate filters as independent ON/OFF TOGGLES in a
   FaceTime-style menu inside the pewpew window. Enabled effects stay
   gesture-auto; effects may overlap (gun one hand, saber other).
   (macOS has no API to add filters to FaceTime's own menu.)
4. ROTATION: true 1:1 hand rotation from 3D hand orientation with
   anti-flip guard (continuous, never snaps; inverted only if hand is).
5. GIRLFRIEND FEATURES = interactive games via website link played on
   his face/camera, GamePigeon-style oomph (not a clone). Affection
   filters (blow-kiss hearts, finger-heart, sparkler) parked for later.
6. MULTIGAMES: generic 8-ball, beer pong, darts etc. wanted in a menu.
   Physics target = feels like GamePigeon. HARD CONSTRAINT: their
   physics parameters are proprietary/unpublished — promise "tuned to
   feel indistinguishable in normal play" via blind comparison, never
   bit-exact. Original implementations of standard rules only; no
   copied assets, art, sounds, or branding from any existing game.

## 4. Design research (why these games — cite in your reasoning)

- GamePigeon: lives inside the existing conversation; invite = install;
  short turn-based rounds resumable over hours. => Our games live inside
  the FaceTime call; one link tap to join; 1-3 min rounds; rematch 1 tap.
- Wordle (https://howitspread.com/cases/wordle): same puzzle for all,
  once daily (scarcity), spoiler-free emoji share grid. => Daily layer
  with shareable result cards = retention + spread outside calls.
- Krillion (https://krillion.wiki/how-to-play): 7 same daily prompts,
  ~25s each, rarity tiers scoring to 700 ("dive depth"), no account.
  => Couples version: both answer, rarity from curated tiers, MATCHING
  answers score worst (mind-reading tension), daily share badge.
- Jackbox (https://builtin.com/articles/jackbox-games-design-party-pack):
  phone-as-controller + room code = lowest friction; host runs game,
  shared screen shows state. => His Mac/camera is the shared screen;
  her phone is only a controller; for generic games he also joins by
  phone as player 2.
- Hard constraints: FaceTime latency kills twitch fairness (turn-based
  wins); BOTH players need agency (he dodges/catches/blocks via tracked
  head+hands, never a passive target); effects must read in FaceTime
  picture-in-picture; every game action needs phone-side juice AND a
  camera-side consequence within ~1s perceived.
- Honest virality limit: clips/share cards can spread, but another
  couple needs a pewpew host. Optimize for this couple's retention loop.

## 5. Staged plan with gates (do not advance until gate passes)

STAGE 1 — Foundation: real-time 3D saber.
- Render hilt.glb live in 3D (e.g. moderngl offscreen -> composite);
  hilt + blade follow 3D hand orientation (Decision 4); keep slide-out
  ignition, hum/Doppler/clash, trails, shake. Retire saber sprite path.
- Still serve the pistol as-is this stage (3D gun is deferred).
- Add MediaPipe FaceLandmarker plumbing (landmarks + blendshapes) —
  every face game needs it; land it now behind a toggle.
- Filter toggle menu in preview (Decision 3): per-effect on/off, keys.
- Mic fix (Decision 2): meter, device reporting, failure alarm;
  reproduce and diagnose the real-call failure before claiming fixed.
GATE 1: real FaceTime call test — saber rotates 1:1 incl. pointing at
camera, never flips; mic meter moves with voice; selftest green with
new coverage (orientation math, audio safeguards).

STAGE 2A — Join layer ("natural for her").
- Room created by pewpew: short code + QR + textable link; ONE guest;
  code expires with session; phone-browser client, no account/install.
- Transport: choose at kickoff against current docs — outbound tunnel
  from his Mac (zero hosting) vs free-tier hosted relay. Must work
  across different networks (she is remote on FaceTime). WebSocket
  events -> pewpew effect bus; his phone can also join as player 2.
GATE 2A: she goes tap -> connected in <15s on cellular/different Wi-Fi;
test event visibly effects his camera; reconnect on drop works.

STAGE 2B — Face Darts (flagship original), then Mouth Catch.
- Face Darts rules: she flick-throws 6 suction darts/round (swipe
  physics, slight wobble); scoring rings on his tracked face (nose
  bullseye 50); darts stick ~5s then drop; he gains dodge points on
  clean misses; open palm in dart path = block; best-of-3; loser
  sticker/punishment until rematch. Keep it cute, not violent.
- Mouth Catch (co-op): she arcs food; he catches with head movement +
  jawOpen blendshape; misses splat; shared combo streak + score.
GATE 2B: full match played on a real FaceTime call (PiP readable);
hit registration judged fair by both at call latency; selftests for
scoring/physics determinism.

STAGE 2C — Generic multigames (Decision 6).
- 8-ball: standard rules, simplified fouls; both on phones; pockets,
  scratches, win/loss fire camera effects on his feed (confetti burst,
  clown nose on scratch until next pot, loser filter). Tune cloth
  friction, cushion restitution, ball spin decay by blind A/B vs
  GamePigeon reference play; document parameters + tuning notes.
- Beer pong: flick-arc throws, 6/10-cup triangle, bounce-in = 2 cups,
  redemption shot, rerack at 3/2/1 (house rules toggleable, default
  GamePigeon-like). Splash effects on camera per cup.
- Classic darts: 301-lite (no double-in/out v1), swipe throw with
  release-velocity physics; distinct from Face Darts.
GATE 2C: blind feel test — regular GamePigeon player rates physics
"same game" apart from nitpicks; full games complete without desync
(authoritative host state, phones are inputs only).

STAGE 3 — Daily/viral layer.
- Word Duel: same daily 5-letter word, both play, fewest guesses wins;
  spoiler-free emoji grid share card (paste into iMessage). Tiles or
  splats can decorate his camera during calls.
- Rare Answer (couples dive): 5 shared daily prompts, 20-25s each,
  curated rarity tiers authored offline in versioned JSON (no live
  scraping), matches score lowest, total = "depth" badge + streaks;
  loser carries a forfeit filter into the next call.
GATE 3: share card pastes perfectly into iMessage; streak survives
restart; answers judged fairly on a 50-prompt trial set.

STAGE 4 — Deferred (separate user approval required): 3D gun model in
Blender integrated like the saber; parked affection filters; dual
sabers; blade colors. Do not start.

## 6. Engineering rules for whoever builds this

- Host-authoritative state for all games; phones send inputs only.
- Effects go through one effect bus into the existing composite
  pipeline (clean feed -> vcam; HUD only on local preview).
- Every stage extends --selftest (pure logic: scoring, physics step,
  orientation, audio buffers) and keeps it green. Audio changes get a
  BlackHole AVFoundation capture check (see /tmp probe pattern:
  ffmpeg -f avfoundation -i ":0" while firing events; assert RMS/peak).
  NOTE: PortAudio input from BlackHole starves in tests — verify via
  AVFoundation/ffmpeg, which is how FaceTime reads it.
- Browser game code lives in its own folder (e.g. games-web/) with
  entry/styles/code in separate files; never one giant HTML file.
  Virtual camera device name stays "OBS Virtual Camera" (pyvirtualcam).
- Performance budget: 1280x720@30 on Apple Silicon while FaceTime runs;
  tracking + 3D render + game logic must hold frame time; measure, don't
  guess. One process must never steal the camera from live-faceswap.
- Update DECISIONS.md as decisions settle (it is Draft; only the user
  can mark Final) and README.md for user-facing changes.
- Sounds: synthesize in code (existing pattern) or properly licensed
  free SFX only; no ripped game audio. Art: original/procedural only.

## 7. Open items for the user (ask, don't assume)

- Confirm staging order in §5 (games as Stage 2, 3D gun deferred).
- Hosting route choice at Stage 2A (tunnel vs hosted relay).
- Exact mic failure symptom (needed to close the Stage 1 mic fix).
- House rules defaults for beer pong / 8-ball fouls if he cares.

## 8. Definition of done per stage

Gate evidence recorded (command output, capture stats, or playtest
notes) + selftest green + README/DECISIONS updated + user told how to
run it (exact command; FaceTime camera/mic selections; her join steps).
"Works on localhost" is never done for Stage 2+ — her phone on a
different network is the test.
