"""pewpew - webcam CGI effects & BlackHole mic passthrough for video calls + 1v1 Phone-vs-Webcam Games.

Pipeline: webcam -> MediaPipe HandLandmarker (+ FaceLandmarker) ->
  - Closed fist -> real-time 3D lightsaber (models3d/hilt.glb in moderngl)
    with dual-hand support, blade-to-blade clash, 6 colors, & depth-occluded glow blade
  - Optional [3] Affection Pack -> finger-heart sparkler + kiss-pucker rising hearts + cheek shimmer
  - 1v1 Games (Her on Phone vs Him in Webcam) rendered directly on webcam & OBS Virtual Camera
Outputs:
  video: pyvirtualcam device ("OBS Virtual Camera") at 1280x720
  audio: real mic + SFX/saber -> BlackHole 2ch via resampling ring buffer

Run:   .venv/bin/python app.py [--camera N] [--mic NAME_OR_IDX] [--monitor off|sfx|mic_sfx] [--no-vcam] [--no-audio]
Keys:  1-3 toggle effects | c blade color | m menu | g QR games | v hear | a switch mic | q quit
Test:  .venv/bin/python app.py --selftest
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from affection_fx import AffectionFX
from audio_engine import MONITOR_MODES, AudioEngine, ResamplingRingBuffer
from effect_bus import EffectBus
from face_tracker import FaceState, FaceTracker
from game_server import GameServer
from games_ar3d import GamesAR3DRenderer
from games_engine import GamesEngine
from hand_occlusion import extract_hand_occlusion
from hand_orientation import (
    HandOrientationTracker,
    OneEuro,
    OneEuro2,
    hand_scale,
    is_finger_gun,
    is_finger_heart,
    is_fist,
    is_open_palm,
    mat3_to_quat,
    palm_center_radius,
    saber_dir,
    thumb_is_up,
)
from renderer3d import (
    BLADE_COLORS,
    BLADE_COLOR_ORDER,
    EMITTER_LOCAL_Y,
    Hilt3DRenderer,
)
from ui_overlay import PreviewUI

ROOT = Path(__file__).parent
HAND_MODEL_PATH = ROOT / "models" / "hand_landmarker.task"
FACE_MODEL_PATH = ROOT / "models" / "face_landmarker.task"
HILT_GLB_PATH = ROOT / "models3d" / "hilt.glb"
ASSETS_DIR = ROOT / "assets"
WEB_DIR = ROOT / "games-web"
DATA_DIR = ROOT / "data"

WIDTH, HEIGHT, FPS = 1280, 720, 30


# ---------------------------------------------------------------------------
# Real-time 3D Lightsaber FX (hilt.glb + 1:1 3D hand rotation + clash/hum).
# ---------------------------------------------------------------------------


class SaberFX:
    """Real-time 3D lightsaber backed by Hilt3DRenderer & HandOrientationTracker."""

    IGNITE_S = 0.45
    RETRACT_S = 0.32

    def __init__(self, renderer: Hilt3DRenderer):
        self.renderer = renderer
        self.orient = HandOrientationTracker()
        self.f_pos = OneEuro2(min_cutoff=1.8, beta=1.2)
        self.f_scale = OneEuro(min_cutoff=1.6, beta=0.8)

        self.pos: tuple[float, float] | None = None
        self.hand_scale_px: float = 100.0
        self.world_pos: np.ndarray | None = None
        self.rot3: np.ndarray = np.eye(3, dtype=np.float64)

        self.ext = 0.0
        self.ext_target = 0.0
        self.gripped = False
        self.lost_since: float | None = None

        self.tip_px: tuple[float, float] | None = None
        self.base_px: tuple[float, float] | None = None
        self.tip_vel = (0.0, 0.0)
        self.tip_speed = 0.0
        self.trail_world: list[tuple[np.ndarray, np.ndarray]] = []
        self.sparks: list[dict] = []
        self.shake = 0.0
        self.clash_until = 0.0
        self.clash_flash_until = 0.0
        self.clash_at = (0.0, 0.0)
        self.hand_occ: tuple[int, int, int, int, np.ndarray] | None = None

    def set_grip(self, gripped: bool, audio) -> None:
        if gripped and not self.gripped:
            if self.ext_target == 0.0:
                audio.play("on")
            self.ext_target = 1.0
            self.lost_since = None
        elif not gripped and self.gripped:
            self.lost_since = time.monotonic()
        self.gripped = gripped

    def update(
        self,
        lm,
        world_lm,
        handedness: str,
        now: float,
        dt: float,
        audio,
        frame_bgr: np.ndarray | None = None,
        occ_lm=None,
        set_audio: bool = True,
    ) -> None:
        if lm is not None:
            # Center grip inside curled fist (knuckles 5,17 + PIPs 6,18)
            px = ((lm[5][0] + lm[17][0] + lm[6][0] + lm[18][0]) * 0.25 * WIDTH,
                  (lm[5][1] + lm[17][1] + lm[6][1] + lm[18][1]) * 0.25 * HEIGHT)
            self.pos = self.f_pos(px[0], px[1], now)
            hs_raw = hand_scale(lm) * ((WIDTH + HEIGHT) / 2.0)
            self.hand_scale_px = self.f_scale(hs_raw, now)
            self.rot3 = self.orient.update(lm, world_lm, now, handedness=handedness)
            self.world_pos, _ = self.renderer.grip_world_pos(
                self.pos[0], self.pos[1], self.hand_scale_px
            )
        elif self.pos is not None:
            self.world_pos, _ = self.renderer.grip_world_pos(
                self.pos[0], self.pos[1], self.hand_scale_px
            )

        mask_lm = lm if lm is not None else occ_lm
        if frame_bgr is not None and mask_lm is not None and self.world_pos is not None:
            self.hand_occ = extract_hand_occlusion(frame_bgr, mask_lm)
        else:
            self.hand_occ = None

        if (not self.gripped and self.lost_since is not None
                and now - self.lost_since > 0.25 and self.ext_target == 1.0):
            self.ext_target = 0.0
            audio.play("off")

        if self.ext_target > self.ext:
            self.ext = min(1.0, self.ext + dt / self.IGNITE_S)
        elif self.ext_target < self.ext:
            self.ext = max(0.0, self.ext - dt / self.RETRACT_S)
            if self.ext == 0.0:
                self.pos = None
                self.world_pos = None
                self.f_pos.reset()
                self.f_scale.reset()
                self.orient.reset()
                self.trail_world.clear()
                self.tip_px = None
                self.base_px = None
                self.tip_vel = (0.0, 0.0)
                self.tip_speed = 0.0

        # Compute 3D endpoints & projected tip kinematics for Doppler hum + clash
        tip_px = None
        base_px = None
        if self.world_pos is not None and self.ext > 0.01:
            e = 1.0 - (1.0 - self.ext) ** 2
            blade_len = 0.88 * e
            hilt_m = self.renderer.hilt_world_matrix(self.world_pos, self.rot3)
            base_w = (hilt_m @ np.array([0.0, EMITTER_LOCAL_Y, 0.0, 1.0], dtype=np.float32))[:3]
            tip_w = (hilt_m @ np.array([0.0, EMITTER_LOCAL_Y + blade_len, 0.0, 1.0], dtype=np.float32))[:3]
            self.trail_world.append((base_w, tip_w))
            self.trail_world = self.trail_world[-6:]
            base_px = self.renderer.project_point(base_w)
            tip_px = self.renderer.project_point(tip_w)

            if tip_px is not None and self.tip_px is not None and dt > 0:
                vx = (tip_px[0] - self.tip_px[0]) / dt
                vy = (tip_px[1] - self.tip_px[1]) / dt
                ax = (vx - self.tip_vel[0]) / dt
                ay = (vy - self.tip_vel[1]) / dt
                prev_speed = math.hypot(*self.tip_vel)
                self.tip_vel = (vx, vy)
                self.tip_speed = self.tip_speed * 0.6 + math.hypot(vx, vy) * 0.4
                if (self.ext > 0.9 and prev_speed > 1250
                        and math.hypot(ax, ay) > 30000 and now > self.clash_until):
                    self.clash_until = now + 0.35
                    self.clash_flash_until = now + 0.09
                    bx, by = base_px or self.pos
                    self.clash_at = ((bx + tip_px[0]) / 2.0, (by + tip_px[1]) / 2.0)
                    self.shake = 0.9
                    for _ in range(22):
                        a = np.random.uniform(0, 2 * math.pi)
                        sp = np.random.uniform(120, 640)
                        self.sparks.append({
                            "x": self.clash_at[0], "y": self.clash_at[1],
                            "vx": math.cos(a) * sp, "vy": math.sin(a) * sp,
                            "ttl": np.random.uniform(0.18, 0.45),
                        })
                    audio.play("clash")
        self.tip_px = tip_px
        self.base_px = base_px
        self.shake = max(0.0, self.shake - dt * 5.0)
        if set_audio:
            audio.set_saber(self.ext > 0.02, min(self.tip_speed / 2600.0, 1.0))

    def trigger_clash(self, px: tuple[float, float], now: float, audio) -> None:
        if now <= self.clash_until:
            return
        self.clash_until = now + 0.35
        self.clash_flash_until = now + 0.11
        self.clash_at = px
        self.shake = 1.0
        for _ in range(22):
            a = np.random.uniform(0, 2 * math.pi)
            sp = np.random.uniform(120, 640)
            self.sparks.append({
                "x": px[0], "y": px[1],
                "vx": math.cos(a) * sp, "vy": math.sin(a) * sp,
                "ttl": np.random.uniform(0.18, 0.45),
            })
        audio.play("clash")

    def render(self, frame: np.ndarray, now: float, dt: float, color_key: str = "blue") -> None:
        if self.world_pos is not None:
            jitter = float(np.random.uniform(0.92, 1.10)) if self.ext > 0.01 else 1.0
            flash = max(0.0, (self.clash_flash_until - now) / 0.11) if now < self.clash_flash_until else 0.0
            self.base_px, self.tip_px = self.renderer.render_saber(
                frame,
                self.world_pos,
                self.rot3,
                self.ext,
                self.trail_world,
                jitter_rad=jitter,
                clash_flash=flash,
                clash_px=self.clash_at if flash > 0.0 else None,
                hand_occ=self.hand_occ,
                color_key=color_key,
            )

        spark_col = (140, 200, 255)
        pal = BLADE_COLORS.get(color_key, BLADE_COLORS["blue"])
        gb, gg, gr = pal["glow_bgr"]
        spark_col = (min(255, int(gb * 180 + 75)), min(255, int(gg * 180 + 75)), min(255, int(gr * 180 + 75)))

        alive = []
        for s in self.sparks:
            s["ttl"] -= dt
            if s["ttl"] <= 0:
                continue
            s["vy"] += 900 * dt
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            alive.append(s)
            cv2.line(frame, (int(s["x"]), int(s["y"])),
                     (int(s["x"] - s["vx"] * 0.02), int(s["y"] - s["vy"] * 0.02)),
                     spark_col, 2, cv2.LINE_AA)
        self.sparks = alive


def _seg_seg_dist_and_pt(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> tuple[float, tuple[float, float]]:
    """Minimum Euclidean distance & closest midpoint between two 2D blade segments."""
    p0 = np.array(a0, dtype=np.float64)
    p1 = np.array(a1, dtype=np.float64)
    q0 = np.array(b0, dtype=np.float64)
    q1 = np.array(b1, dtype=np.float64)
    u = p1 - p0
    v = q1 - q0
    w = p0 - q0
    a = float(np.dot(u, u))
    b = float(np.dot(u, v))
    c = float(np.dot(v, v))
    d = float(np.dot(u, w))
    e = float(np.dot(v, w))
    denom = a * c - b * b
    if denom < 1e-6:
        sc, tc = 0.0, (e / c if c > 1e-6 else 0.0)
    else:
        sc = (b * e - c * d) / denom
        tc = (a * e - b * d) / denom
    sc = min(max(sc, 0.0), 1.0)
    tc = min(max(tc, 0.0), 1.0)
    pa = p0 + sc * u
    qb = q0 + tc * v
    if sc <= 0.0 or sc >= 1.0:
        if c > 1e-6:
            tc = min(max(float(np.dot(pa - q0, v)) / c, 0.0), 1.0)
            qb = q0 + tc * v
    elif tc <= 0.0 or tc >= 1.0:
        if a > 1e-6:
            sc = min(max(float(np.dot(qb - p0, u)) / a, 0.0), 1.0)
            pa = p0 + sc * u
    mid = ((float(pa[0]) + float(qb[0])) * 0.5, (float(pa[1]) + float(qb[1])) * 0.5)
    return float(np.linalg.norm(pa - qb)), mid


def apply_shake(frame: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0.01:
        return frame
    dx = int(np.random.uniform(-9, 9) * amount)
    dy = int(np.random.uniform(-7, 7) * amount)
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(frame, m, (WIDTH, HEIGHT), borderMode=cv2.BORDER_REFLECT)


def make_hand_landmarker():
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions
    opts = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(HAND_MODEL_PATH)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2, min_hand_detection_confidence=0.45,
        min_hand_presence_confidence=0.45, min_tracking_confidence=0.45)
    return mp, vision.HandLandmarker.create_from_options(opts)


def run(
    camera: int,
    use_vcam: bool,
    use_audio: bool,
    mic_selector: str | None,
    monitor_mode: str,
    port: int = 8770,
    use_games: bool = True,
    tunnel: bool = False,
    public_url: str | None = None,
    room_code: str | None = None,
) -> int:
    if not HILT_GLB_PATH.exists():
        print("models3d/hilt.glb missing - run: blender -b --factory-startup "
              "--python-exit-code 1 -P models3d/build_hilt.py")
        return 2

    mp, hand_lm = make_hand_landmarker()
    face_tracker = FaceTracker(FACE_MODEL_PATH) if FACE_MODEL_PATH.exists() else None
    renderer3d = Hilt3DRenderer(HILT_GLB_PATH, WIDTH, HEIGHT, load_pistol=False)
    games_ar3d = GamesAR3DRenderer(renderer3d)
    audio = AudioEngine(
        ASSETS_DIR,
        enabled=use_audio,
        mic_selector=mic_selector,
        monitor_mode=monitor_mode,
    )
    effect_bus = EffectBus(sfx_fn=audio.play)
    game_server = None
    games_engine = None
    if use_games and WEB_DIR.exists():
        game_server = GameServer(
            web_dir=WEB_DIR,
            data_dir=DATA_DIR,
            port=port,
            room_code=room_code,
            public_url=public_url,
            enable_tunnel=tunnel,
        )
        games_engine = GamesEngine(DATA_DIR, WEB_DIR / "data", effect_bus, server=game_server)
        game_server.start()
        print(f"[games] 1v1 Phone link (Her):  {game_server.share_url}")
        print("[games] Webcam mode (Him):      Play directly right here in the pewpew webcam window!")
        if game_server.tunnel_error:
            print(f"[games] Tunnel note: {game_server.tunnel_error}")

    sabers = {"Left": SaberFX(renderer3d), "Right": SaberFX(renderer3d)}
    affection = AffectionFX()
    color_idx = 0
    palm_hold_start: float | None = None
    palm_cooldown_until = 0.0
    ui = PreviewUI()

    cap = cv2.VideoCapture(camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    if not cap.isOpened():
        print(f"could not open camera {camera} (is FaceSwap still using it?)")
        if game_server is not None:
            game_server.stop()
        audio.close()
        renderer3d.close()
        if face_tracker:
            face_tracker.close()
        hand_lm.close()
        return 2

    vcam = None
    if use_vcam:
        try:
            import pyvirtualcam
            vcam = pyvirtualcam.Camera(width=WIDTH, height=HEIGHT, fps=FPS)
            print(f"[video] virtual camera: {vcam.device}")
        except Exception as exc:
            print(f"[video] virtual cam unavailable ({exc}); preview only")

    cv2.namedWindow("pewpew")

    def on_window_mouse(event: int, x: int, y: int, flags: int, param=None) -> None:
        now_m = time.monotonic()
        if event == cv2.EVENT_LBUTTONDOWN and ui.consume_click(x, y):
            return
        if games_engine is not None:
            if event == cv2.EVENT_LBUTTONDOWN:
                games_engine.handle_host_mouse("down", x / WIDTH, y / HEIGHT, now_m)
            elif event == cv2.EVENT_MOUSEMOVE:
                games_engine.handle_host_mouse("move", x / WIDTH, y / HEIGHT, now_m)
            elif event == cv2.EVENT_LBUTTONUP:
                games_engine.handle_host_mouse("up", x / WIDTH, y / HEIGHT, now_m)

    cv2.setMouseCallback("pewpew", on_window_mouse)

    print("Effects ON/OFF toggles: [1] Lightsaber, [2] Face Track, [3] Affection | "
          "[c] blade color | [m] menu | [g] QR code | [v] hear | [a] switch mic | q quits.")
    t0 = time.monotonic()
    prev = t0
    frame_ms_ema = 16.0

    try:
        while True:
            t_loop = time.perf_counter()
            ok, frame = cap.read()
            if not ok:
                break
            now = time.monotonic()
            dt = min(now - prev, 0.1)
            prev = now
            frame = cv2.flip(cv2.resize(frame, (WIDTH, HEIGHT)), 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts_ms = int((now - t0) * 1000)

            saber_inputs: dict[str, tuple[list, list | None, str]] = {}
            occ_inputs: dict[str, list] = {}
            all_hands_lm: list[list[tuple[float, float]]] = []
            open_palms: list[tuple[float, float, float]] = []
            need_hands = (
                ui.filters["saber"]
                or ui.filters["affection"]
                or (games_engine is not None and games_engine.active_game in ("face_darts", "beer_pong", "pool", "classic_darts"))
            )
            if need_hands:
                hres = hand_lm.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts_ms
                )
                if hres.hand_landmarks:
                    worlds = hres.hand_world_landmarks or [None] * len(hres.hand_landmarks)
                    hands_meta = hres.handedness or [None] * len(hres.hand_landmarks)
                    used_slots: set[str] = set()
                    in_hand_game = games_engine is not None and games_engine.active_game in ("beer_pong", "pool", "classic_darts", "face_darts")
                    for hand, world, meta in zip(hres.hand_landmarks, worlds, hands_meta):
                        lm = [(p.x, p.y) for p in hand]
                        all_hands_lm.append(lm)
                        raw_side = meta[0].category_name if meta else "Right"
                        slot = raw_side if raw_side in ("Left", "Right") and raw_side not in used_slots else (
                            "Left" if "Left" not in used_slots else "Right"
                        )
                        used_slots.add(slot)
                        occ_inputs[slot] = lm
                        is_palm = is_open_palm(lm)
                        if is_palm:
                            open_palms.append(palm_center_radius(lm))
                        if ui.filters["affection"] and is_finger_heart(lm):
                            continue
                        pinch_d = math.hypot(lm[4][0] - lm[8][0], lm[4][1] - lm[8][1])
                        if in_hand_game and (is_palm or pinch_d < 0.08):
                            continue
                        w_pts = [(p.x, p.y, p.z) for p in world] if world else None
                        if ui.filters["saber"] and is_fist(lm):
                            saber_inputs[slot] = (lm, w_pts, slot)

            # Open-palm hold gesture cycles saber blade color outside active blocker game
            if (
                ui.filters["saber"]
                and open_palms
                and not saber_inputs
                and (games_engine is None or games_engine.active_game == "lobby")
            ):
                if now >= palm_cooldown_until:
                    if palm_hold_start is None:
                        palm_hold_start = now
                    elif now - palm_hold_start >= 1.15:
                        color_idx = (color_idx + 1) % len(BLADE_COLOR_ORDER)
                        palm_hold_start = None
                        palm_cooldown_until = now + 2.2
                        audio.play("on", gain=0.45)
            else:
                palm_hold_start = None

            face_state = None
            need_face = (
                ui.filters["face"]
                or ui.filters["affection"]
                or (games_engine is not None and games_engine.needs_face_tracking())
            )
            if need_face and face_tracker is not None:
                face_state = face_tracker.detect(rgb, ts_ms, WIDTH, HEIGHT)

            for slot, sb in sabers.items():
                s_in = saber_inputs.get(slot)
                gripped = s_in is not None and ui.filters["saber"]
                sb.set_grip(gripped, audio)
                if s_in is not None and ui.filters["saber"]:
                    lm, w_pts, handed = s_in
                    sb.update(lm, w_pts, handed, now, dt, audio, frame_bgr=frame, occ_lm=occ_inputs.get(slot), set_audio=False)
                else:
                    sb.update(None, None, slot, now, dt, audio, frame_bgr=frame, occ_lm=occ_inputs.get(slot), set_audio=False)

            active_sabers = [sb for sb in sabers.values() if sb.ext > 0.02]
            max_speed_norm = max((min(sb.tip_speed / 2600.0, 1.0) for sb in active_sabers), default=0.0)
            audio.set_saber(bool(active_sabers), max_speed_norm, active_count=len(active_sabers))

            # Dual-saber blade-to-blade clash sparks
            s_left, s_right = sabers["Left"], sabers["Right"]
            if (
                s_left.ext > 0.72
                and s_right.ext > 0.72
                and s_left.base_px is not None
                and s_left.tip_px is not None
                and s_right.base_px is not None
                and s_right.tip_px is not None
            ):
                dist, clash_pt = _seg_seg_dist_and_pt(
                    s_left.base_px, s_left.tip_px, s_right.base_px, s_right.tip_px
                )
                if dist < 28.0:
                    s_left.trigger_clash(clash_pt, now, audio)
                    s_right.trigger_clash(clash_pt, now, audio)

            color_key = BLADE_COLOR_ORDER[color_idx]
            for sb in sabers.values():
                sb.render(frame, now, dt, color_key=color_key)

            affection.update_and_render(
                frame,
                all_hands_lm,
                face_state,
                now,
                dt,
                enabled=ui.filters["affection"],
            )

            hud_snap = None
            if games_engine is not None:
                games_engine.process_webcam_hands(all_hands_lm, now)
                games_engine.step(dt, face_state, open_palms, WIDTH, HEIGHT)
                games_ar3d.render(frame, games_engine, face_state, open_palms, now)
                effect_bus.render(frame, face_state, dt)
                hud_snap = games_engine.hud_state()
                effect_bus.draw_game_hud(frame, hud_snap, now, face_state=face_state)
            max_shake = max(sb.shake for sb in sabers.values())
            frame = apply_shake(frame, max_shake)

            if vcam is not None:
                vcam.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                vcam.sleep_until_next_frame()

            frame_ms = (time.perf_counter() - t_loop) * 1000.0
            frame_ms_ema = frame_ms_ema * 0.85 + frame_ms * 0.15

            preview = frame.copy()
            if hud_snap is not None:
                effect_bus.draw_host_private_hud(preview, hud_snap, now)
            if ui.filters["face"] and face_tracker is not None:
                face_tracker.draw_preview_debug(preview, face_state)
            warning = audio.check_health()
            game_info = None
            if game_server is not None and games_engine is not None:
                game_info = {
                    "room": game_server.room_code,
                    "url": game_server.share_url,
                    "players": game_server.active_counts()["total"],
                    "game": games_engine.active_game,
                    "qr_bgr": game_server.qr_bgr(176) if ui.qr_open else None,
                }
            gb, gg, gr = BLADE_COLORS[color_key]["glow_bgr"]
            swatch_bgr = (int(gb * 255), int(gg * 255), int(gr * 255))
            ui.draw(
                preview,
                audio,
                0,
                max(sb.ext for sb in sabers.values()),
                frame_ms_ema,
                warning,
                game_info=game_info,
                blade_color=color_key,
                blade_bgr=swatch_bgr,
            )
            cv2.imshow("pewpew", preview)
            if cv2.getWindowProperty("pewpew", cv2.WND_PROP_VISIBLE) < 1:
                break

            for act in ui.pop_actions():
                if act == "toggle_menu":
                    ui.menu_open = not ui.menu_open
                elif act == "toggle_qr":
                    ui.qr_open = not ui.qr_open
                elif act == "cycle_color":
                    color_idx = (color_idx + 1) % len(BLADE_COLOR_ORDER)
                elif act == "cycle_monitor":
                    audio.cycle_monitor()
                elif act == "cycle_mic":
                    audio.cycle_mic()
                elif act == "game_reset" and games_engine is not None:
                    games_engine.host_reset_or_next()
                elif act.startswith("game:") and games_engine is not None:
                    games_engine.select_game_host(act.split(":", 1)[1])
                elif act.startswith("filter:"):
                    ui.toggle(act.split(":", 1)[1])

            key = cv2.waitKey(1) & 0xFF
            if key == 255:
                continue
            if games_engine is not None and games_engine.wants_keyboard():
                if games_engine.handle_host_key(key):
                    continue
            if key in (ord("q"), 27):
                break
            elif key == ord("1"):
                ui.toggle("saber")
            elif key == ord("2"):
                ui.toggle("face")
            elif key == ord("3"):
                ui.toggle("affection")
            elif key == ord("c"):
                color_idx = (color_idx + 1) % len(BLADE_COLOR_ORDER)
            elif key == ord("m"):
                ui.menu_open = not ui.menu_open
            elif key == ord("g"):
                ui.qr_open = not ui.qr_open
            elif key == ord("v"):
                audio.cycle_monitor()
            elif key == ord("a"):
                audio.cycle_mic()
    finally:
        cap.release()
        if game_server is not None:
            game_server.stop()
        if vcam is not None:
            vcam.close()
        audio.close()
        renderer3d.close()
        if face_tracker is not None:
            face_tracker.close()
        hand_lm.close()
        cv2.destroyAllWindows()
    return 0


# ---------------------------------------------------------------------------
# Selftest: classifiers, 3D orientation + anti-flip, 3D hilt+blade renders,
# FaceLandmarker, resampling ring buffer, and BlackHole audio safeguards.
# ---------------------------------------------------------------------------


def _synthetic_hand(thumb_tip):
    lm = [(0.30, 0.60)] * 21
    lm[0] = (0.30, 0.60)
    lm[2], lm[3], lm[4] = (0.37, 0.49), (0.39, 0.44), thumb_tip
    lm[5], lm[6], lm[8] = (0.42, 0.52), (0.50, 0.50), (0.62, 0.49)
    lm[9], lm[10], lm[12] = (0.43, 0.56), (0.48, 0.57), (0.44, 0.60)
    lm[13], lm[14], lm[16] = (0.42, 0.60), (0.46, 0.61), (0.42, 0.63)
    lm[17], lm[18], lm[20] = (0.40, 0.63), (0.435, 0.645), (0.41, 0.66)
    return lm


def _make_world_fist(rot_gl: np.ndarray) -> tuple[list, list]:
    """Generate consistent 3D world landmarks & 2D image landmarks for a fist rotated by `rot_gl`."""
    # Canonical upright fist in GL space: wrist=(0,-0.06,-0.02), index_mcp=(0,+0.04,0), pinky_mcp=(0,-0.04,0)
    canon_gl = {
        0: np.array([0.00, -0.06, -0.025]),
        5: np.array([0.00, 0.042, 0.00]),
        9: np.array([0.012, 0.015, 0.00]),
        17: np.array([0.00, -0.042, 0.00]),
    }
    world = [(0.0, 0.0, 0.0)] * 21
    lm = [(0.5, 0.5)] * 21
    for idx, pt in canon_gl.items():
        r = rot_gl @ pt
        # GL (+X, +Y_up, +Z_cam) -> MediaPipe (+X, -Y_down, -Z_away)
        world[idx] = (float(r[0]), float(-r[1]), float(-r[2]))
        lm[idx] = (0.5 + float(r[0]) * 1.6, 0.5 - float(r[1]) * 1.6)
    return lm, world


def selftest() -> int:
    # 1. Gesture classifiers + OneEuro
    gun_up = _synthetic_hand((0.40, 0.38))
    gun_down = _synthetic_hand((0.43, 0.53))
    fist = _synthetic_hand((0.43, 0.53))
    fist[8] = (0.46, 0.55)
    assert is_finger_gun(gun_up), "finger gun not detected"
    assert thumb_is_up(gun_up), "thumb-up not detected"
    assert is_finger_gun(gun_down) and not thumb_is_up(gun_down), "thumb-down wrong"
    assert not is_finger_gun(fist), "fist misclassified as gun"
    assert is_fist(fist), "fist (saber grip) not detected"
    print("PASS classifier: gun+thumb-up, gun+thumb-down, fist rejected, fist=grip")

    oe = OneEuro()
    v = 0.0
    for i in range(60):
        v = oe(100.0, i / 30)
    assert abs(v - 100.0) < 2.0, f"OneEuro did not converge: {v}"
    print("PASS OneEuro filter converges")

    # 2. 3D orientation math + anti-flip continuity + genuine inversion
    tracker = HandOrientationTracker()
    prev_q = None
    # Smooth 360-degree roll around Y blade axis: never snaps!
    for step in range(37):
        ang = math.radians(step * 10.0)
        ry = np.array([
            [math.cos(ang), 0.0, math.sin(ang)],
            [0.0, 1.0, 0.0],
            [-math.sin(ang), 0.0, math.cos(ang)],
        ])
        lm_r, w_r = _make_world_fist(ry)
        r_out = tracker.update(lm_r, w_r, step / 30.0, handedness="Right")
        assert abs(float(np.linalg.det(r_out)) - 1.0) < 1e-4, "rotation matrix not proper SO(3)"
        q = mat3_to_quat(r_out)
        if prev_q is not None:
            # Angle step between consecutive smoothed frames must be small (< 25 deg), never a 180 snap!
            dot = min(1.0, abs(float(np.dot(q, prev_q))))
            step_deg = math.degrees(2.0 * math.acos(dot))
            assert step_deg < 25.0, f"spurious orientation jump {step_deg:.1f} deg at roll {step * 10}"
        prev_q = q

    # Anti-flip edge-on Z-inversion spike test: mirror world Z in 1 frame when palm edge-on
    tracker_edge = HandOrientationTracker()
    ang_edge = math.radians(88.0)  # nearly edge-on palm
    ry_edge = np.array([
        [math.cos(ang_edge), 0.0, math.sin(ang_edge)],
        [0.0, 1.0, 0.0],
        [-math.sin(ang_edge), 0.0, math.cos(ang_edge)],
    ])
    lm_e, w_e = _make_world_fist(ry_edge)
    r_before = tracker_edge.update(lm_e, w_e, 0.0, handedness="Right")
    # Simulate MediaPipe single-frame depth Z sign flip on wrist/knuckles
    w_flipped = [(x, y, -z) for (x, y, z) in w_e]
    r_after = tracker_edge.update(lm_e, w_flipped, 1 / 30.0, handedness="Right")
    assert float(np.dot(r_after[:, 2], r_before[:, 2])) > 0.5, "edge-on depth mirror caused 180 flip!"

    # Genuine upside-down inversion when fist is truly held inverted
    tracker_inv = HandOrientationTracker()
    rx_180 = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
    lm_i, w_i = _make_world_fist(rx_180)
    r_inv = tracker_inv.update(lm_i, w_i, 0.0, handedness="Right")
    assert r_inv[1, 1] < -0.9, f"inverted fist did not invert saber Y={r_inv[:, 1]}"
    print("PASS 3D orientation: SO(3), 360 roll continuous, edge-on anti-flip, true inversion")

    # 3. 3D Saber slide-out + angled render + pointing-at-camera render
    assert HAND_MODEL_PATH.exists(), "hand_landmarker.task missing"
    assert HILT_GLB_PATH.exists(), "hilt.glb missing (run build_hilt.py)"
    renderer = Hilt3DRenderer(HILT_GLB_PATH, WIDTH, HEIGHT, load_pistol=False)
    ar3d_test = GamesAR3DRenderer(renderer)

    class _SilentSaber:
        def play(self, key): pass
        def set_saber(self, active, speed=0.0, active_count=1): pass
    saber = SaberFX(renderer)
    saber.pos = (480.0, 500.0)
    saber.hand_scale_px = 100.0
    a = math.radians(28.0)
    saber.rot3 = np.array([
        [math.cos(a), -math.sin(a), 0.0],
        [math.sin(a), math.cos(a), 0.0],
        [0.0, 0.0, 1.0],
    ])
    saber.ext_target = 1.0
    sil = _SilentSaber()
    now = time.monotonic()
    for i in range(5):
        saber.update(None, None, "Right", now + i / 30, 1 / 30, sil)
    assert 0.15 < saber.ext < 0.65, f"blade not sliding (ext={saber.ext:.2f} at 5 frames)"
    for i in range(5, 40):
        saber.update(None, None, "Right", now + i / 30, 1 / 30, sil)
    assert saber.ext == 1.0, "blade never fully extended"

    sframe = np.full((HEIGHT, WIDTH, 3), (36, 34, 40), dtype=np.uint8)
    saber.render(sframe, now + 2, 1 / 30)
    sout = ROOT / "tests" / "saber_preview.png"
    cv2.imwrite(str(sout), sframe)
    bright = int(np.sum(np.all(sframe > 200, axis=2)))
    assert bright > 400, f"3D blade core too faint ({bright} bright px)"

    # Pointing straight at camera test (+Z_gl)
    pframe = np.full((HEIGHT, WIDTH, 3), (36, 34, 40), dtype=np.uint8)
    saber.pos = (640.0, 420.0)
    saber.rot3 = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.05, -0.9987],
        [0.0, 0.9987, 0.05],
    ])
    saber.world_pos, _ = renderer.grip_world_pos(640.0, 420.0, 100.0)
    saber.trail_world.clear()
    saber.hand_occ = None
    saber.render(pframe, now + 2.1, 1 / 30)
    pout = ROOT / "tests" / "saber_pointing_preview.png"
    cv2.imwrite(str(pout), pframe)
    assert int(np.sum(np.all(pframe > 200, axis=2))) > 200, "pointing-at-camera blade missing"

    # Under-hand occlusion test: draw synthetic skin fist over dark studio bg
    hframe = np.full((HEIGHT, WIDTH, 3), (36, 34, 40), dtype=np.uint8)
    skin = (128, 160, 212)  # BGR skin tone
    fist_lm = [(0.50, 0.65)] * 21
    fist_lm[0] = (0.50, 0.72)
    fist_lm[1], fist_lm[2], fist_lm[3], fist_lm[4] = (0.46, 0.69), (0.45, 0.63), (0.48, 0.58), (0.51, 0.56)
    fist_lm[5], fist_lm[6], fist_lm[7], fist_lm[8] = (0.47, 0.56), (0.50, 0.55), (0.52, 0.58), (0.51, 0.61)
    fist_lm[9], fist_lm[10], fist_lm[11], fist_lm[12] = (0.49, 0.59), (0.52, 0.58), (0.53, 0.61), (0.51, 0.63)
    fist_lm[13], fist_lm[14], fist_lm[15], fist_lm[16] = (0.50, 0.62), (0.52, 0.62), (0.53, 0.64), (0.51, 0.66)
    fist_lm[17], fist_lm[18], fist_lm[19], fist_lm[20] = (0.50, 0.65), (0.52, 0.65), (0.53, 0.67), (0.51, 0.68)
    pts_px = np.array([(int(x * WIDTH), int(y * HEIGHT)) for x, y in fist_lm], np.int32)
    cv2.fillConvexPoly(hframe, pts_px[[0, 1, 2, 5, 9, 13, 17]], skin)
    cv2.fillConvexPoly(hframe, pts_px[[5, 6, 10, 14, 18, 17]], skin)
    for b0, b1 in ((1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (9, 10), (10, 11), (13, 14), (17, 18), (18, 19)):
        cv2.line(hframe, tuple(pts_px[b0]), tuple(pts_px[b1]), skin, 22, cv2.LINE_AA)
    saber2 = SaberFX(renderer)
    saber2.ext = 1.0
    saber2.ext_target = 1.0
    saber2.gripped = True
    saber2.update(fist_lm, None, "Right", now + 3.0, 1 / 30, sil, frame_bgr=hframe)
    saber2.render(hframe, now + 3.0, 1 / 30)
    hout = ROOT / "tests" / "saber_under_hand_preview.png"
    cv2.imwrite(str(hout), hframe)
    # Middle of gripped palm/knuckles must keep skin tone rather than gray/black hilt
    gx, gy = int(saber2.pos[0]), int(saber2.pos[1])
    patch = hframe[gy - 4:gy + 5, gx - 4:gx + 5].mean(axis=(0, 1))
    assert abs(float(patch[2]) - skin[2]) < 25 and patch[2] > patch[0], f"hand not occluding hilt: patch={patch}"
    # Above index knuckle blade must still shine brightly
    assert int(np.sum(np.all(hframe[:int(pts_px[5][1]) - 35] > 200, axis=2))) > 200, "blade above fist missing"

    # 3D blade colors + dual-saber clash helper check
    assert len(BLADE_COLOR_ORDER) >= 6
    cframe = np.full((HEIGHT, WIDTH, 3), (24, 24, 24), dtype=np.uint8)
    a_col = math.radians(28.0)
    saber.rot3 = np.array([
        [math.cos(a_col), -math.sin(a_col), 0.0],
        [math.sin(a_col), math.cos(a_col), 0.0],
        [0.0, 0.0, 1.0],
    ])
    saber.pos = (480.0, 500.0)
    saber.world_pos, _ = renderer.grip_world_pos(480.0, 500.0, 100.0)
    saber.render(cframe, now + 3.1, 1 / 30, color_key="emerald")
    assert float(cframe[:, :, 1].mean()) > float(cframe[:, :, 2].mean()) + 0.5, "emerald blade green channel not dominant"
    cdist, _ = _seg_seg_dist_and_pt((300, 300), (500, 500), (300, 500), (500, 300))
    assert cdist < 1.0, f"expected intersecting segments dist<1, got {cdist}"

    # Finger-heart + Stage 4 Affection Pack render check
    heart_lm = _synthetic_hand((0.45, 0.44))
    heart_lm[5], heart_lm[6], heart_lm[8] = (0.42, 0.52), (0.43, 0.50), (0.46, 0.45)
    assert is_finger_heart(heart_lm), "finger heart not detected"
    assert not is_finger_heart(fist), "fist misclassified as finger heart"
    aff_test = AffectionFX()
    aframe_off = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
    aframe_on = aframe_off.copy()
    pucker_face = FaceState(
        landmarks=[(0.5, 0.5, 0.0)] * 478,
        blendshapes={"mouthPucker": 0.85, "mouthSmileLeft": 0.72, "mouthSmileRight": 0.72},
        matrix=None,
        nose_px=(640.0, 340.0),
        mouth_px=(640.0, 405.0),
        face_scale_px=150.0,
    )
    assert aff_test.update_and_render(aframe_off, [heart_lm], pucker_face, now + 5.0, 1 / 30, enabled=False) == 0
    assert int(np.sum(aframe_off != 30)) == 0, "AffectionFX drew while disabled"
    assert aff_test.update_and_render(aframe_on, [heart_lm], pucker_face, now + 5.1, 1 / 30, enabled=True) == 1
    assert len(aff_test.hearts) >= 1 and int(np.sum(aframe_on != 30)) > 800, "AffectionFX did not render hearts"

    # Top-View 3D Pool AR overlay check (saved into tests/top_pool_ar_preview.png)
    from table_physics import PoolMatch
    pm_test = PoolMatch()
    p_ar = np.full((HEIGHT, WIDTH, 3), 32, dtype=np.uint8)
    ar3d_test.ctx.enable(ar3d_test.ctx.DEPTH_TEST)
    ar3d_test.ctx.disable(ar3d_test.ctx.BLEND)
    ar3d_test.fbo.use()
    ar3d_test.fbo.clear(0.0, 0.0, 0.0, 0.0)
    ar3d_test._render_pool(pm_test, now + 5.2, {"kind": "pool", "angle": 0.0, "power": 0.6})
    ar3d_test._composite_fbo(p_ar)
    pool_out = ROOT / "tests" / "top_pool_ar_preview.png"
    cv2.imwrite(str(pool_out), p_ar)
    assert int(np.sum(p_ar != 32)) > 4000, "top-view Pool AR table did not render"

    renderer.close()
    print(f"PASS 3D saber (dual + 6 colors), Top-View Pool AR -> {pool_out}, AffectionFX")

    # 5. FaceLandmarker plumbing check
    assert FACE_MODEL_PATH.exists(), "face_landmarker.task missing"
    ft = FaceTracker(FACE_MODEL_PATH)
    res = ft.detect(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), 0, WIDTH, HEIGHT)
    assert res is None
    ft.close()
    print("PASS FaceLandmarker plumbing initialized")

    # 6. Audio resampling ring buffer + AudioEngine safeguards
    rb = ResamplingRingBuffer(24000, 48000)
    t_in = np.arange(2400, dtype=np.float32) / 24000.0
    sine_24k = (0.5 * np.sin(2.0 * np.pi * 440.0 * t_in)).astype(np.float32)[:, None]
    rb.push(sine_24k)
    out_48k = rb.pop(1024, out_ch=2)
    assert out_48k.shape == (1024, 2) and float(np.max(np.abs(out_48k))) > 0.35, "ring buffer resample failed"

    eng = AudioEngine(ASSETS_DIR, enabled=True)
    assert "hum" in eng._bufs and len(eng._bufs["hum"]) > 1000, "saber hum not loaded"
    expected_game_sfx = (
        "dart_throw", "dart_hit", "dart_block", "catch", "splat",
        "pool_hit", "pool_pot", "pong_cup", "word_win",
        "krill_ping", "krill_deep", "krill_miss",
    )
    missing_sfx = [k for k in expected_game_sfx if k not in eng._bufs]
    assert not missing_sfx, f"missing game SFX wavs: {missing_sfx}"
    # Verify monitor mode cycling (off -> sfx -> mic_sfx -> off)
    assert eng.cycle_monitor() == "sfx"
    assert eng.cycle_monitor() == "mic_sfx"
    assert eng.cycle_monitor() == "off"
    # Verify zero-input safeguard raises loud warning after threshold
    eng._zero_since = time.monotonic() - 3.0
    eng._mic_pinned = True
    if eng.mode == "blackhole":
        warn = eng.check_health()
        assert warn is not None and "ALL ZEROS" in warn, f"expected zero-input warning, got {warn}"
    eng.close()
    print(f"PASS audio engine + 12 game SFX + monitor + safeguards (mode={eng.mode})")

    # 7. Stage 2A/2B/2C/3 Game Engine, Krillion Autofill, Physics & Live HTTP+WS Roundtrip
    import base64
    import json
    import socket
    import tempfile
    import urllib.request
    from game_server import render_qr_bgr, ws_encode_frame

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_data = Path(tmpdir)
        for fname in ("rare_answer_prompts.json", "word_duel_words.json"):
            (tmp_data / fname).write_bytes((DATA_DIR / fname).read_bytes())

        bus = EffectBus()
        srv = GameServer(web_dir=WEB_DIR, data_dir=tmp_data, host="127.0.0.1", port=0, room_code="T3ST")
        geng = GamesEngine(tmp_data, WEB_DIR / "data", bus, server=srv)

        assert len(geng.krillion.prompts) >= 50, f"expected >=50 Krillion prompts, got {len(geng.krillion.prompts)}"
        assert len(geng.word_duel.targets) >= 200, "word duel targets too small"

        # Krillion strict 1v1 Jinx (5 prompts, Her on Phone + Him in Webcam)
        assert geng.krillion.mode == "couples"
        snap_def = geng.krillion.snapshot()
        assert snap_def["totalRounds"] == 5
        geng.krillion.start(mode="couples")
        assert len(geng.krillion.selected_prompts) == 5 and geng.krillion.phase == "preview"
        geng.krillion.step(3.5, {"guest"})
        assert geng.krillion.phase == "answering"
        # Her submits first; stays in answering waiting for Him in webcam until BOTH lock!
        first_ans = geng.krillion.selected_prompts[0]["answers"][0][0]
        r_d1 = geng.krillion.submit_answer("guest", first_ans, {"guest"})
        assert r_d1["status"] == "scored" and geng.krillion.phase == "answering"

        # Krillion exact / autofill confirm / no_echo / couples jinx verification
        p01 = geng.krillion.prompts[0]
        geng.krillion.selected_prompts = [p01, geng.krillion.prompts[1]]
        geng.krillion.round_idx = 0
        geng.krillion.mode = "couples"
        geng.krillion.phase = "answering"
        geng.krillion.phase_timer = 25.0
        geng.krillion.history = []
        geng.krillion.pending_round_answers = {}

        res_confirm = geng.krillion.evaluate_guess("oxigen", p01, answer_corrections=True, clear_rejected=False)
        assert res_confirm["status"] == "confirm" and res_confirm["suggested"] == "Oxygen", res_confirm
        res_direct = geng.krillion.evaluate_guess("oxigen", p01, answer_corrections=False, clear_rejected=False)
        assert res_direct["status"] == "scored" and res_direct["canonical"] == "Oxygen", res_direct
        res_miss = geng.krillion.evaluate_guess("zxqzvqp", p01, answer_corrections=True, clear_rejected=True)
        assert res_miss["status"] == "no_echo" and res_miss["clearInput"] is True, res_miss

        # Couples Jinx collision test via phone guest + webcam host typing
        r1 = geng.krillion.submit_answer("guest", "Selenium", {"guest"})
        assert r1["status"] == "scored" and r1["pts"] == 100
        geng.active_game = "rare_answer"
        for ch in "se":
            geng.handle_host_key(ord(ch))
        geng.handle_host_key(13)  # Enter -> confirm or score
        if geng.krillion.phase == "answering":
            geng.handle_host_key(13)  # Enter second time confirms autofill
        assert geng.krillion.phase == "reveal" and geng.krillion.history[-1]["jinx"] is True
        assert geng.krillion.history[-1]["guest"]["pts"] == 5

        # Word Duel duplicate-letter scoring + Webcam host keyboard typing
        wd_score = geng.word_duel.score_word("ALLEY", "APPLE")
        assert wd_score == ["correct", "present", "absent", "present", "absent"], wd_score
        geng.active_game = "word_duel"
        for ch in geng.word_duel.target:
            geng.handle_host_key(ord(ch))
        geng.handle_host_key(13)
        assert geng.word_duel.boards["host"]["solved"] is True

        # Face Darts hit vs palm block + Mouth Catch catch vs splat
        fake_face = FaceState(
            landmarks=[(0.5, 0.5, 0.0)] * 478,
            blendshapes={"jawOpen": 0.65},
            matrix=None,
            nose_px=(640.0, 360.0),
            mouth_px=(640.0, 415.0),
            face_scale_px=150.0,
        )
        geng.active_game = "face_darts"
        geng.face_darts.throw_dart("guest", 0.5, 0.5, 1.0)
        for _ in range(15):
            geng.step(0.04, fake_face, [], WIDTH, HEIGHT)
        assert geng.face_darts.scores["guest"] == 50, f"expected bullseye 50, got {geng.face_darts.scores}"
        geng.face_darts.throw_dart("guest", 0.5, 0.5, 1.0)
        for _ in range(15):
            geng.step(0.04, fake_face, [(0.5, 0.5, 0.14)], WIDTH, HEIGHT)
        assert geng.face_darts.scores["host"] >= 20, "open-palm block failed"

        geng.active_game = "mouth_catch"
        geng.mouth_catch.throw_food(640.0 / WIDTH, 415.0 / HEIGHT, 0.9)
        for _ in range(25):
            geng.step(0.04, fake_face, [], WIDTH, HEIGHT)
        assert geng.mouth_catch.catches == 1 and geng.mouth_catch.score >= 10, "mouth catch failed"

        # 8-Ball Pool strict 1v1 + host mouse aim/shoot + Classic Darts + Beer Pong 1v1 + 3 shots/+1 on make
        assert geng.pool.practice_mode is False
        geng.pool.shoot("guest", 0.0, 0.9)
        for _ in range(90):
            geng.pool.step(1 / 60)
        assert any(b.x != -0.52 for b in geng.pool.balls[:1]), "cue ball didn't move"
        assert geng.classic_darts.score_coord(0.0, -0.59)[:2] == (60, "T20")
        assert geng.classic_darts.throw("host", 0.0, 0.0).get("ok") is False, "ClassicDarts must reject off-turn"
        assert geng.beer_pong.practice_mode is False and geng.beer_pong.shots_left == 3
        assert geng.beer_pong.throw("host", 0.0, 0.55, 0.55).get("ok") is False, "BeerPong 1v1 must reject off-turn"
        assert geng.beer_pong.throw("guest", 0.0, 0.55, 0.55).get("ok") is True
        for _ in range(40):
            geng.beer_pong.step(0.03)

        # EffectBus render + on-cam HUD smoke check + QR decode check
        eframe = np.full((HEIGHT, WIDTH, 3), 40, dtype=np.uint8)
        bus.set_clown_nose(5.0)
        bus.set_forfeit("seaweed", 5.0)
        bus.render(eframe, fake_face, 1 / 30)
        geng.select_game_host("pool")
        hud_t = geng.hud_state()
        bus.draw_game_hud(eframe, hud_t, time.monotonic())
        bus.draw_host_private_hud(eframe, hud_t, time.monotonic())
        geng.process_webcam_hands([], time.monotonic())  # regression check: zero NameError/crash
        qr_img = render_qr_bgr("http://192.168.1.42:8770/?room=T3ST", 240)
        decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(qr_img)
        assert "room=T3ST" in decoded, f"QR decode failed: {decoded}"

        # Live single-port HTTP + RFC6455 WebSocket roundtrip
        srv.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/api/info", timeout=3.0) as r:
                info = json.loads(r.read().decode("utf-8"))
                assert info["room"] == "T3ST"
            with socket.create_connection(("127.0.0.1", srv.port), timeout=3.0) as ws_sock:
                key_b64 = base64.b64encode(b"0123456789abcdef").decode("ascii")
                ws_sock.sendall((
                    f"GET /ws?room=T3ST&role=guest HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{srv.port}\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {key_b64}\r\n"
                    f"Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode("ascii"))
                hdr = ws_sock.recv(2048)
                assert b"101 Switching Protocols" in hdr
                # Send masked select_game frame
                payload = json.dumps({"type": "select_game", "game": "rare_answer"}).encode("utf-8")
                mask = b"\x12\x34\x56\x78"
                masked = bytes(payload[i] ^ mask[i & 3] for i in range(len(payload)))
                ws_sock.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + masked)
                time.sleep(0.15)
                assert geng.active_game == "rare_answer", f"WS select_game did not update: {geng.active_game}"
        finally:
            srv.stop()

    print("PASS Stage 2A/2B/2C/3 engine, Krillion autofill & Jinx, QR decode, EffectBus & live HTTP+WS")
    print("SELFTEST OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="pewpew CGI camera effects, BlackHole mic mixer & multiplayer games")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--mic", type=str, default=None, help="Input mic name substring or device index")
    ap.add_argument(
        "--monitor",
        choices=MONITOR_MODES,
        default="off",
        help="Local monitor output on headphones/speakers: off, sfx (only SFX), mic_sfx (hear self + SFX)",
    )
    ap.add_argument("--port", type=int, default=8770, help="HTTP+WebSocket port for phone games server")
    ap.add_argument("--room", type=str, default=None, help="Optional fixed 4-char room code")
    ap.add_argument("--public-url", type=str, default=None, help="Optional custom HTTPS tunnel/relay origin")
    ap.add_argument("--tunnel", action="store_true", help="Launch cloudflared quick tunnel if installed")
    ap.add_argument("--no-games", action="store_true", help="Disable Stage 2/3 phone games server")
    ap.add_argument("--no-vcam", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run(
        args.camera,
        not args.no_vcam,
        not args.no_audio,
        args.mic,
        args.monitor,
        port=args.port,
        use_games=not args.no_games,
        tunnel=args.tunnel,
        public_url=args.public_url,
        room_code=args.room,
    )


if __name__ == "__main__":
    sys.exit(main())
