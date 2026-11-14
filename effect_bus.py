"""Unified thread-safe camera visual + audio effect bus for Stage 2B, 2C, and 3 games."""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np


@dataclass
class StuckDart:
    dx_norm: float
    dy_norm: float
    color_bgr: tuple[int, int, int]
    angle_deg: float
    created: float
    ttl: float = 5.0
    fallback_xy: tuple[float, float] = (640.0, 360.0)
    fall_y: float = 0.0
    fall_vy: float = 0.0


@dataclass
class FlyingSprite:
    kind: str  # "dart" | "donut" | "taco" | "berry" | "burger" | "sushi" | "pong_ball"
    x: float
    y: float
    z: float  # 1.0 = far (phone), 0.0 = camera plane
    color_bgr: tuple[int, int, int] = (90, 120, 255)
    spin: float = 0.0


@dataclass
class FoodSplat:
    dx_norm: float
    dy_norm: float
    kind: str
    color_bgr: tuple[int, int, int]
    created: float
    ttl: float = 3.2
    fallback_xy: tuple[float, float] = (640.0, 360.0)
    seed: int = 0


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    size: float
    color_bgr: tuple[int, int, int]
    life: float
    max_life: float
    kind: str = "confetti"  # "confetti" | "splash" | "bubble"
    angle: float = 0.0
    spin: float = 0.0


@dataclass
class Callout:
    text: str
    subtext: str
    x_norm: float
    y_norm: float
    color_bgr: tuple[int, int, int]
    created: float
    ttl: float = 2.2
    tiles: list[str] | None = None  # optional Wordle states ["correct","present","absent"]


@dataclass
class ForfeitState:
    kind: str  # "" | "crown" | "seaweed" | "bubble_helmet" | "shrimp_partner" | "neon_glow"
    expires_at: float = 0.0  # 0.0 = persistent until cleared


class EffectBus:
    """Thread-safe queue of face-anchored & screen-space camera overlays plus SFX dispatch."""

    def __init__(self, sfx_fn: Callable[[str, float], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._sfx_fn = sfx_fn
        self._stuck_darts: list[StuckDart] = []
        self._splats: list[FoodSplat] = []
        self._flying: list[FlyingSprite] = []
        self._particles: list[Particle] = []
        self._callouts: list[Callout] = []
        self._clown_nose_until: float = 0.0
        self._forfeit: ForfeitState | None = None
        self._rng = random.Random(42)

    def set_sfx_fn(self, fn: Callable[[str, float], None] | None) -> None:
        self._sfx_fn = fn

    def play_sfx(self, key: str, gain: float = 1.0) -> None:
        fn = self._sfx_fn
        if fn is not None:
            try:
                fn(key, gain)
            except Exception:
                pass

    def reset_transient(self) -> None:
        with self._lock:
            self._stuck_darts.clear()
            self._splats.clear()
            self._flying.clear()
            self._particles.clear()
            self._callouts.clear()
            self._clown_nose_until = 0.0

    def set_forfeit(self, kind: str | None, duration_s: float = 0.0) -> None:
        with self._lock:
            if not kind:
                self._forfeit = None
            else:
                exp = (time.monotonic() + duration_s) if duration_s > 0.0 else 0.0
                self._forfeit = ForfeitState(kind=kind, expires_at=exp)

    def set_clown_nose(self, duration_s: float = 10.0) -> None:
        with self._lock:
            self._clown_nose_until = max(self._clown_nose_until, time.monotonic() + duration_s)

    def has_face_fx(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now < self._clown_nose_until:
                return True
            if self._forfeit is not None and (self._forfeit.expires_at == 0.0 or now < self._forfeit.expires_at):
                return True
            return bool(self._stuck_darts or self._splats)

    def update_flying(self, sprites: list[FlyingSprite]) -> None:
        with self._lock:
            self._flying = list(sprites)

    def add_stuck_dart(
        self,
        dx_norm: float,
        dy_norm: float,
        fallback_xy: tuple[float, float],
        color_bgr: tuple[int, int, int] = (90, 95, 255),
        ttl: float = 5.0,
    ) -> None:
        with self._lock:
            self._stuck_darts.append(
                StuckDart(
                    dx_norm=dx_norm,
                    dy_norm=dy_norm,
                    color_bgr=color_bgr,
                    angle_deg=self._rng.uniform(-22.0, 22.0),
                    created=time.monotonic(),
                    ttl=ttl,
                    fallback_xy=fallback_xy,
                )
            )
            if len(self._stuck_darts) > 12:
                self._stuck_darts = self._stuck_darts[-12:]

    def add_food_splat(
        self,
        dx_norm: float,
        dy_norm: float,
        fallback_xy: tuple[float, float],
        kind: str = "donut",
        color_bgr: tuple[int, int, int] = (170, 95, 255),
        ttl: float = 3.2,
    ) -> None:
        with self._lock:
            self._splats.append(
                FoodSplat(
                    dx_norm=dx_norm,
                    dy_norm=dy_norm,
                    kind=kind,
                    color_bgr=color_bgr,
                    created=time.monotonic(),
                    ttl=ttl,
                    fallback_xy=fallback_xy,
                    seed=self._rng.randint(1, 99999),
                )
            )
            if len(self._splats) > 8:
                self._splats = self._splats[-8:]

    def spawn_confetti(self, w: int = 1280, h: int = 720, count: int = 44, kind: str = "confetti") -> None:
        palette = (
            [(255, 220, 90), (255, 110, 180), (90, 240, 255), (120, 255, 140), (255, 175, 80)]
            if kind == "confetti"
            else [(255, 235, 160), (255, 210, 90), (255, 255, 255), (220, 175, 60)]
        )
        new_p: list[Particle] = []
        for _ in range(count):
            if kind == "splash":
                cx = w * self._rng.uniform(0.32, 0.68)
                cy = h * self._rng.uniform(0.55, 0.78)
                vx = self._rng.uniform(-280.0, 280.0)
                vy = self._rng.uniform(-520.0, -180.0)
                sz = self._rng.uniform(4.0, 11.0)
                life = self._rng.uniform(0.75, 1.35)
            elif kind == "bubble":
                cx = w * self._rng.uniform(0.15, 0.85)
                cy = h * self._rng.uniform(0.75, 0.98)
                vx = self._rng.uniform(-35.0, 35.0)
                vy = self._rng.uniform(-220.0, -90.0)
                sz = self._rng.uniform(6.0, 16.0)
                life = self._rng.uniform(1.4, 2.4)
            else:
                cx = w * self._rng.uniform(0.15, 0.85)
                cy = h * self._rng.uniform(-0.02, 0.28)
                vx = self._rng.uniform(-220.0, 220.0)
                vy = self._rng.uniform(110.0, 340.0)
                sz = self._rng.uniform(6.0, 12.0)
                life = self._rng.uniform(1.2, 2.2)
            new_p.append(
                Particle(
                    x=cx,
                    y=cy,
                    vx=vx,
                    vy=vy,
                    size=sz,
                    color_bgr=self._rng.choice(palette),
                    life=life,
                    max_life=life,
                    kind=kind,
                    angle=self._rng.uniform(0.0, math.tau),
                    spin=self._rng.uniform(-8.0, 8.0),
                )
            )
        with self._lock:
            self._particles.extend(new_p)
            if len(self._particles) > 140:
                self._particles = self._particles[-140:]

    def add_callout(
        self,
        text: str,
        subtext: str = "",
        x_norm: float = 0.5,
        y_norm: float = 0.16,
        color_bgr: tuple[int, int, int] = (255, 225, 110),
        ttl: float = 2.2,
        tiles: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._callouts.append(
                Callout(
                    text=text,
                    subtext=subtext,
                    x_norm=x_norm,
                    y_norm=y_norm,
                    color_bgr=color_bgr,
                    created=time.monotonic(),
                    ttl=ttl,
                    tiles=tiles,
                )
            )
            if len(self._callouts) > 4:
                self._callouts = self._callouts[-4:]

    def render(self, frame: np.ndarray, face_state, dt: float) -> None:
        """Composite active game effects directly onto BGR camera frame (runs before vcam)."""
        now = time.monotonic()
        h, w = frame.shape[:2]

        with self._lock:
            # Prune expired
            if self._forfeit is not None and self._forfeit.expires_at > 0.0 and now >= self._forfeit.expires_at:
                self._forfeit = None
            forfeit = self._forfeit
            clown_active = now < self._clown_nose_until

            # Copy snapshots and advance physics cleanly under lock
            alive_darts: list[StuckDart] = []
            for d in self._stuck_darts:
                age = now - d.created
                if age < d.ttl + 0.65:
                    if age >= d.ttl:
                        d.fall_vy += 1200.0 * max(dt, 1e-3)
                        d.fall_y += d.fall_vy * max(dt, 1e-3)
                    alive_darts.append(d)
            self._stuck_darts = alive_darts

            self._splats = [s for s in self._splats if (now - s.created) < s.ttl]
            splats = list(self._splats)
            darts = list(self._stuck_darts)
            flying = list(self._flying)

            alive_p: list[Particle] = []
            for p in self._particles:
                p.life -= max(dt, 1e-3)
                if p.life > 0.0:
                    if p.kind == "splash":
                        p.vy += 880.0 * dt
                    elif p.kind == "bubble":
                        p.x += math.sin(now * 5.0 + p.angle) * 18.0 * dt
                    else:
                        p.vy += 260.0 * dt
                    p.x += p.vx * dt
                    p.y += p.vy * dt
                    p.angle += p.spin * dt
                    alive_p.append(p)
            self._particles = alive_p
            particles = list(alive_p)

            self._callouts = [c for c in self._callouts if (now - c.created) < c.ttl]
            callouts = list(self._callouts)

        # Render splats first (under stuck darts)
        for s in splats:
            self._draw_splat(frame, s, face_state, now, w, h)

        # Clown nose foul overlay
        if clown_active and face_state is not None:
            nx, ny = int(face_state.nose_px[0]), int(face_state.nose_px[1])
            rad = max(12, min(42, int(face_state.face_scale_px * 0.165)))
            cv2.circle(frame, (nx, ny), rad + 2, (25, 25, 110), -1, cv2.LINE_AA)
            cv2.circle(frame, (nx, ny), rad, (42, 42, 240), -1, cv2.LINE_AA)
            cv2.circle(
                frame,
                (nx - max(3, rad // 3), ny - max(3, rad // 3)),
                max(3, rad // 4),
                (235, 235, 255),
                -1,
                cv2.LINE_AA,
            )

        # Forfeit overlays (crown / Krillion ocean forfeits)
        if forfeit is not None:
            self._draw_forfeit(frame, forfeit.kind, face_state, now, w, h)

        # Stuck suction darts
        for d in darts:
            self._draw_stuck_dart(frame, d, face_state, now, w, h)

        # In-flight objects (incoming suction darts or arcing food)
        for f in flying:
            self._draw_flying(frame, f, w, h)

        # Particles (confetti / beer pong splashes / Krillion bubbles)
        for p in particles:
            alpha = min(1.0, p.life / max(p.max_life * 0.35, 0.15))
            ix, iy = int(p.x), int(p.y)
            if not (0 <= ix < w and 0 <= iy < h):
                continue
            c = tuple(int(ch * alpha) for ch in p.color_bgr)
            if p.kind == "bubble":
                cv2.circle(frame, (ix, iy), max(2, int(p.size)), c, 2, cv2.LINE_AA)
                cv2.circle(frame, (ix - 2, iy - 2), max(1, int(p.size * 0.25)), (255, 255, 255), -1, cv2.LINE_AA)
            elif p.kind == "splash":
                cv2.circle(frame, (ix, iy), max(2, int(p.size * 0.55)), c, -1, cv2.LINE_AA)
            else:
                dx = math.cos(p.angle) * p.size
                dy = math.sin(p.angle) * p.size * 0.65
                pts = np.array(
                    [
                        [ix - dx, iy - dy],
                        [ix + dy, iy - dx * 0.5],
                        [ix + dx, iy + dy],
                        [ix - dy, iy + dx * 0.5],
                    ],
                    dtype=np.int32,
                )
                cv2.fillConvexPoly(frame, pts, c, cv2.LINE_AA)

        # Brief transient callouts / Wordle tile strip / Krillion depth pull banner
        for c in callouts:
            self._draw_callout(frame, c, now, w, h)

    @staticmethod
    def _anchor_px(dx_norm: float, dy_norm: float, fallback: tuple[float, float], face_state) -> tuple[float, float, float]:
        if face_state is not None:
            sc = face_state.face_scale_px
            cx = face_state.nose_px[0] + dx_norm * sc
            cy = face_state.nose_px[1] + dy_norm * sc
            return cx, cy, sc
        return fallback[0], fallback[1], 145.0

    def _draw_stuck_dart(self, frame: np.ndarray, d: StuckDart, face_state, now: float, w: int, h: int) -> None:
        age = now - d.created
        cx, cy, sc = self._anchor_px(d.dx_norm, d.dy_norm, d.fallback_xy, face_state)
        cy += d.fall_y
        if cy > h + 80:
            return
        wobble = math.sin(age * 38.0) * math.exp(-age * 6.5) * 14.0
        ang = math.radians(d.angle_deg + wobble - 35.0)
        stick_len = max(28.0, sc * 0.42)
        tx = int(cx + math.cos(ang) * stick_len)
        ty = int(cy + math.sin(ang) * stick_len)
        ix, iy = int(cx), int(cy)
        # Suction cup disc
        cv2.circle(frame, (ix, iy), max(6, int(sc * 0.065)), (35, 35, 45), -1, cv2.LINE_AA)
        cv2.circle(frame, (ix, iy), max(4, int(sc * 0.045)), (90, 90, 110), 1, cv2.LINE_AA)
        # Foam shaft
        cv2.line(frame, (ix, iy), (tx, ty), (20, 20, 24), max(7, int(sc * 0.055)), cv2.LINE_AA)
        cv2.line(frame, (ix, iy), (tx, ty), d.color_bgr, max(5, int(sc * 0.04)), cv2.LINE_AA)
        # Tail fins
        perp_x = -math.sin(ang) * max(7.0, sc * 0.08)
        perp_y = math.cos(ang) * max(7.0, sc * 0.08)
        back_x = tx - math.cos(ang) * 10.0
        back_y = ty - math.sin(ang) * 10.0
        fin_pts = np.array(
            [
                [tx + int(perp_x), ty + int(perp_y)],
                [tx - int(perp_x), ty - int(perp_y)],
                [int(back_x), int(back_y)],
            ],
            dtype=np.int32,
        )
        cv2.fillConvexPoly(frame, fin_pts, (250, 245, 235), cv2.LINE_AA)

    def _draw_splat(self, frame: np.ndarray, s: FoodSplat, face_state, now: float, w: int, h: int) -> None:
        age = now - s.created
        alpha = max(0.0, min(0.78, 1.0 - (age / s.ttl) ** 2))
        if alpha <= 0.02:
            return
        cx, cy, sc = self._anchor_px(s.dx_norm, s.dy_norm, s.fallback_xy, face_state)
        drip = age * 14.0
        rad = max(16, int(sc * 0.24))
        ix, iy = int(cx), int(cy + drip * 0.35)
        x0 = max(0, ix - rad - 8)
        y0 = max(0, iy - rad - 8)
        x1 = min(w, ix + rad + 12)
        y1 = min(h, iy + rad + int(drip) + 22)
        if x1 <= x0 or y1 <= y0:
            return
        roi = frame[y0:y1, x0:x1]
        overlay = roi.copy()
        lx, ly = ix - x0, iy - y0
        cv2.circle(overlay, (lx, ly), rad, s.color_bgr, -1, cv2.LINE_AA)
        rng = random.Random(s.seed)
        for _ in range(5):
            ox = int(rng.uniform(-rad * 0.85, rad * 0.85))
            oy = int(rng.uniform(-rad * 0.7, rad * 0.9) + drip * rng.uniform(0.3, 1.0))
            sr = max(4, int(rad * rng.uniform(0.22, 0.42)))
            cv2.circle(overlay, (lx + ox, ly + oy), sr, s.color_bgr, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0.0, dst=roi)

    def _draw_flying(self, frame: np.ndarray, f: FlyingSprite, w: int, h: int) -> None:
        z = max(0.0, min(1.0, f.z))
        scale = 0.28 + (1.0 - z) * 0.95
        ix = int(f.x * w)
        iy = int(f.y * h)
        r = max(8, int(28 * scale))
        if f.kind == "dart":
            cv2.circle(frame, (ix, iy), r, (25, 25, 35), -1, cv2.LINE_AA)
            cv2.circle(frame, (ix, iy), max(4, int(r * 0.72)), f.color_bgr, -1, cv2.LINE_AA)
            cv2.circle(frame, (ix, iy), max(2, int(r * 0.30)), (255, 245, 240), -1, cv2.LINE_AA)
            return
        if f.kind == "donut":
            cv2.circle(frame, (ix, iy), r, (105, 165, 215), -1, cv2.LINE_AA)
            cv2.circle(frame, (ix, iy), max(5, int(r * 0.84)), (185, 110, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (ix, iy), max(3, int(r * 0.34)), (40, 35, 35), -1, cv2.LINE_AA)
        elif f.kind == "taco":
            pts = np.array([[ix - r, iy + r // 3], [ix, iy - r], [ix + r, iy + r // 3]], dtype=np.int32)
            cv2.fillConvexPoly(frame, pts, (80, 210, 245), cv2.LINE_AA)
            cv2.line(frame, (ix - int(r * 0.7), iy), (ix + int(r * 0.7), iy), (85, 200, 95), max(2, r // 4), cv2.LINE_AA)
        elif f.kind == "burger":
            cv2.ellipse(frame, (ix, iy - r // 4), (r, r // 2), 0, 180, 360, (85, 170, 235), -1, cv2.LINE_AA)
            cv2.rectangle(frame, (ix - r, iy - r // 6), (ix + r, iy + r // 4), (45, 70, 125), -1)
            cv2.ellipse(frame, (ix, iy + r // 3), (r, r // 3), 0, 0, 180, (95, 175, 235), -1, cv2.LINE_AA)
        elif f.kind == "sushi":
            cv2.circle(frame, (ix, iy), r, (245, 245, 248), -1, cv2.LINE_AA)
            cv2.circle(frame, (ix, iy), r, (30, 45, 35), max(2, r // 5), cv2.LINE_AA)
            cv2.circle(frame, (ix, iy), max(3, r // 2), (90, 130, 255), -1, cv2.LINE_AA)
        else:  # berry / default
            cv2.circle(frame, (ix, iy), r, (145, 55, 225), -1, cv2.LINE_AA)
            cv2.circle(frame, (ix - r // 3, iy - r // 3), max(2, r // 5), (235, 210, 255), -1, cv2.LINE_AA)

    def _draw_forfeit(self, frame: np.ndarray, kind: str, face_state, now: float, w: int, h: int) -> None:
        if face_state is not None:
            sc = face_state.face_scale_px
            hx = int(face_state.nose_px[0])
            hy = int(face_state.nose_px[1] - sc * 0.92)
        else:
            sc = 150.0
            hx = w // 2
            hy = int(h * 0.22)

        if kind == "crown":
            cw = max(36, int(sc * 0.44))
            ch = max(24, int(sc * 0.28))
            pts = np.array(
                [
                    [hx - cw, hy + ch // 2],
                    [hx - cw, hy - ch // 2],
                    [hx - cw // 2, hy],
                    [hx, hy - ch],
                    [hx + cw // 2, hy],
                    [hx + cw, hy - ch // 2],
                    [hx + cw, hy + ch // 2],
                ],
                dtype=np.int32,
            )
            cv2.fillConvexPoly(frame, pts, (50, 205, 255), cv2.LINE_AA)
            cv2.polylines(frame, [pts], True, (25, 130, 195), 2, cv2.LINE_AA)
        elif kind == "seaweed":
            for i in range(-3, 4):
                sway = math.sin(now * 3.4 + i * 0.9) * (sc * 0.08)
                bx = hx + int(i * sc * 0.14)
                by = hy + int(sc * 0.18)
                tx = bx + int(sway)
                ty = hy - int(sc * (0.36 + (i % 2) * 0.12))
                cv2.line(frame, (bx, by), (tx, ty), (65, 195, 85), max(4, int(sc * 0.045)), cv2.LINE_AA)
                cv2.line(frame, (bx, by), (tx, ty), (130, 240, 145), max(2, int(sc * 0.02)), cv2.LINE_AA)
        elif kind == "bubble_helmet":
            if face_state is not None:
                cx, cy = int(face_state.nose_px[0]), int(face_state.nose_px[1] - sc * 0.12)
            else:
                cx, cy = hx, hy + 80
            rad = max(70, int(sc * 0.98))
            overlay = frame.copy()
            cv2.circle(overlay, (cx, cy), rad, (255, 225, 120), 4, cv2.LINE_AA)
            cv2.ellipse(overlay, (cx, cy), (int(rad * 0.86), int(rad * 0.86)), 0, 210, 265, (255, 255, 240), 3, cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0.0, dst=frame)
        elif kind == "shrimp_partner":
            sx = hx + int(sc * 0.85 + math.cos(now * 2.2) * 14.0)
            sy = hy + int(sc * 0.55 + math.sin(now * 3.1) * 12.0)
            cv2.ellipse(frame, (sx, sy), (20, 11), -15, 0, 360, (130, 105, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (sx - 12, sy - 4), 3, (15, 15, 20), -1, cv2.LINE_AA)
            cv2.line(frame, (sx - 18, sy - 6), (sx - 34, sy - 16), (220, 195, 255), 1, cv2.LINE_AA)
            cv2.line(frame, (sx - 18, sy - 2), (sx - 34, sy - 4), (220, 195, 255), 1, cv2.LINE_AA)
        elif kind == "neon_glow":
            if face_state is not None:
                cx, cy = int(face_state.nose_px[0]), int(face_state.nose_px[1] - sc * 0.1)
                rad = max(65, int(sc * 0.92))
                cv2.circle(frame, (cx, cy), rad, (255, 220, 90), 2, cv2.LINE_AA)
                cv2.circle(frame, (cx, cy), rad + 5, (180, 95, 255), 1, cv2.LINE_AA)

    def _draw_callout(self, frame: np.ndarray, c: Callout, now: float, w: int, h: int) -> None:
        age = now - c.created
        alpha = min(1.0, age / 0.16) * min(1.0, (c.ttl - age) / 0.32)
        if alpha <= 0.03:
            return
        cx = int(c.x_norm * w)
        cy = int(c.y_norm * h - age * 12.0)
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(c.text, font, 0.85, 2)
        (sw, sh), _ = cv2.getTextSize(c.subtext, font, 0.50, 1) if c.subtext else ((0, 0), 0)
        bw = max(tw, sw, (len(c.tiles) * 34 if c.tiles else 0)) + 34
        bh = th + (sh + 12 if c.subtext else 0) + (40 if c.tiles else 0) + 22
        x0 = max(12, min(w - bw - 12, cx - bw // 2))
        y0 = max(12, min(h - bh - 12, cy - bh // 2))
        roi = frame[y0:y0 + bh, x0:x0 + bw]
        panel = roi.copy()
        cv2.rectangle(panel, (0, 0), (bw - 1, bh - 1), (18, 22, 34), -1)
        cv2.rectangle(panel, (0, 0), (bw - 1, bh - 1), c.color_bgr, 2)
        cv2.addWeighted(panel, 0.78 * alpha, roi, 1.0 - 0.78 * alpha, 0.0, dst=roi)

        tx = (bw - tw) // 2
        ty = th + 12
        cv2.putText(roi, c.text, (tx, ty), font, 0.85, c.color_bgr, 2, cv2.LINE_AA)
        if c.subtext:
            sx = (bw - sw) // 2
            ty += sh + 10
            cv2.putText(roi, c.subtext, (sx, ty), font, 0.50, (220, 232, 245), 1, cv2.LINE_AA)
        if c.tiles:
            tile_map = {
                "correct": (95, 195, 95),
                "present": (60, 190, 225),
                "absent": (65, 68, 78),
            }
            start_x = (bw - len(c.tiles) * 30 + 6) // 2
            ty += 12
            for i, st in enumerate(c.tiles):
                rx = start_x + i * 30
                cv2.rectangle(roi, (rx, ty), (rx + 24, ty + 24), tile_map.get(st, (65, 68, 78)), -1)
                cv2.rectangle(roi, (rx, ty), (rx + 24, ty + 24), (200, 210, 220), 1)

    @staticmethod
    def _blend_box(frame: np.ndarray, x0: int, y0: int, x1: int, y1: int, col=(14, 20, 32), alpha: float = 0.78, border=None) -> None:
        h, w = frame.shape[:2]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        roi = frame[y0:y1, x0:x1]
        overlay = roi.copy()
        overlay[:] = col
        cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0.0, dst=roi)
        if border is not None:
            cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), border, 1, cv2.LINE_AA)

    @staticmethod
    def _hud_ascii(text: str) -> str:
        return "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in str(text)).strip()

    @classmethod
    def _wrap_text(cls, text: str, max_px: int, scale: float, thickness: int = 1, max_lines: int = 4) -> list[str]:
        clean = cls._hud_ascii(text)
        if not clean:
            return []
        font = cv2.FONT_HERSHEY_SIMPLEX
        words = clean.split()
        lines: list[str] = []
        cur = ""
        for w_tok in words:
            cand = f"{cur} {w_tok}".strip() if cur else w_tok
            tw = cv2.getTextSize(cand, font, scale, thickness)[0][0]
            if tw <= max_px or not cur:
                if tw > max_px and not cur:
                    # Break very long single token cleanly
                    chunk = ""
                    for ch in w_tok:
                        if cv2.getTextSize(chunk + ch, font, scale, thickness)[0][0] > max_px and chunk:
                            lines.append(chunk)
                            chunk = ch
                        else:
                            chunk += ch
                    cur = chunk
                else:
                    cur = cand
            else:
                lines.append(cur)
                cur = w_tok
            if len(lines) >= max_lines:
                break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        elif cur and lines:
            last = lines[-1]
            while len(last) > 3 and cv2.getTextSize(last + "...", font, scale, thickness)[0][0] > max_px:
                last = last[:-1].rstrip()
            lines[-1] = last + "..."
        return lines

    @staticmethod
    def _power_color_bgr(power: float) -> tuple[int, int, int]:
        """Smooth Green -> Yellow -> Red indicator in BGR for [0..1] power."""
        p = max(0.0, min(1.0, float(power)))
        if p <= 0.5:
            t = p * 2.0
            b = int(75 + (35 - 75) * t)
            g = int(225 + (220 - 225) * t)
            r = int(65 + (255 - 65) * t)
            return (b, g, r)
        t = (p - 0.5) * 2.0
        b = int(35 + (60 - 35) * t)
        g = int(220 + (65 - 220) * t)
        r = int(255 + (255 - 255) * t)
        return (b, g, r)

    def draw_game_hud(self, frame: np.ndarray, state: dict, now: float, face_state=None) -> None:
        """Render spoiler-free 1v1 webcam AR score/turn/board HUD onto `frame` before vcam."""
        g = state.get("activeGame", "lobby")
        if g == "lobby":
            return
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX

        # 1. Top-left 1v1 game & turn card (auto-wrapped so nothing cuts off)
        title_map = {
            "pool": "1v1 TOP-VIEW POOL",
            "beer_pong": "1v1 CUP PONG",
            "classic_darts": "1v1 DARTS 301",
            "face_darts": "1v1 FACE DARTS",
            "mouth_catch": "1v1 MOUTH CATCH",
            "word_duel": "1v1 WORD DUEL",
            "rare_answer": "1v1 KRILLION JINX",
        }
        title = title_map.get(g, g.upper())
        turn_txt = ""
        turn_col = (110, 235, 255)
        sub_txt = ""
        hint_txt = ""

        if g == "pool":
            pm = state.get("pool", {})
            if pm.get("phase") == "finished":
                win = pm.get("winner")
                turn_txt = "YOU WIN!" if win == "host" else "HER WINS!"
                turn_col = (115, 245, 160) if win == "host" else (165, 125, 255)
            else:
                my_t = pm.get("turn") == "host"
                turn_txt = "YOUR TURN (WEBCAM)" if my_t else "HER TURN (PHONE)"
                turn_col = (110, 240, 255) if my_t else (170, 120, 255)
                if my_t:
                    hint_txt = "Hover cue to aim, drag back & release to shoot" if pm.get("phase") != "ball_in_hand" else "Click table to place cue ball"
            gg = pm.get("groups", {}).get("guest") or "open"
            hg = pm.get("groups", {}).get("host") or "open"
            sub_txt = f"You:{hg} | Her:{gg} | {pm.get('status', '')}"
        elif g == "beer_pong":
            bp = state.get("beer_pong", {})
            g_alive = sum(1 for c in bp.get("racks", {}).get("guest", []) if c.get("alive"))
            h_alive = sum(1 for c in bp.get("racks", {}).get("host", []) if c.get("alive"))
            if bp.get("phase") == "finished":
                turn_txt = "YOU WIN!" if bp.get("winner") == "host" else "HER WINS!"
                turn_col = (115, 245, 160) if bp.get("winner") == "host" else (165, 125, 255)
            else:
                my_t = bp.get("turn") == "host"
                turn_txt = f"YOUR TURN ({bp.get('shotsLeft', 3)} shots)" if my_t else f"HER TURN ({bp.get('shotsLeft', 3)} shots)"
                turn_col = (110, 240, 255) if my_t else (170, 120, 255)
                hint_txt = "Mouse drag / pinch to shoot!" if my_t else "Open palm to SWAT bounced shots!"
            sub_txt = f"Cups You:{g_alive} | Her:{h_alive} | {bp.get('status', '')}"
        elif g == "classic_darts":
            cd = state.get("classic_darts", {})
            if cd.get("phase") == "finished":
                turn_txt = "YOU WIN!" if cd.get("winner") == "host" else "HER WINS!"
                turn_col = (115, 245, 160) if cd.get("winner") == "host" else (165, 125, 255)
            else:
                my_t = cd.get("turn") == "host"
                turn_txt = f"YOUR TURN ({cd.get('dartsLeft', 3)} darts)" if my_t else f"HER TURN ({cd.get('dartsLeft', 3)} darts)"
                turn_col = (110, 240, 255) if my_t else (170, 120, 255)
                hint_txt = "Mouse aim & drag over board to throw!" if my_t else "Watching Her throws live..."
            sc = cd.get("scores", {})
            sub_txt = f"Her {sc.get('guest', 301)} vs You {sc.get('host', 301)} | {cd.get('status', '')}"
        elif g == "face_darts":
            fd = state.get("face_darts", {})
            wins = fd.get("roundWins", {})
            sc = fd.get("scores", {})
            turn_txt = f"DEFEND! Round {fd.get('roundNum', 1)}/{fd.get('bestOf', 3)}"
            turn_col = (110, 240, 255)
            sub_txt = f"Wins Her:{wins.get('guest', 0)} You:{wins.get('host', 0)} | Darts:{fd.get('dartsLeft', 0)} | Pts H:{sc.get('guest', 0)} Y:{sc.get('host', 0)}"
            hint_txt = "Raise OPEN PALM for 3D Hex-Shield or dodge!"
        elif g == "mouth_catch":
            mc = state.get("mouth_catch", {})
            turn_txt = f"CATCH SNACKS! ({mc.get('throwsLeft', 0)} left)"
            turn_col = (120, 250, 170)
            sub_txt = f"Score:{mc.get('score', 0)} | Combo:{mc.get('combo', 0)}x | Catches:{mc.get('catches', 0)}"
            hint_txt = "Open mouth wide when Her tosses snacks!"
        elif g == "word_duel":
            wd = state.get("word_duel", {})
            if wd.get("phase") == "finished":
                win = wd.get("winner")
                turn_txt = f"{'YOU WIN' if win == 'host' else ('DRAW' if win == 'draw' else 'HER WINS')} ({wd.get('target') or ''})"
                turn_col = (115, 245, 160) if win == "host" else (165, 125, 255)
                hint_txt = "Press ENTER in pewpew for new 1v1 Word"
            else:
                turn_txt = "1v1 SPEED RACE"
                hint_txt = "Type secretly in pewpew window + ENTER"
            opp_rows = len(wd.get("boards", {}).get("guest", {}).get("rows", []))
            you_rows = len(wd.get("boards", {}).get("host", {}).get("rows", []))
            sub_txt = f"Her: {opp_rows}/6 guesses  |  You: {you_rows}/6 guesses"
        elif g == "rare_answer":
            kr = state.get("rare_answer", {})
            tot = kr.get("totals", {})
            turn_txt = f"SCORE You {tot.get('hostPts', 0)} - Her {tot.get('guestPts', 0)}"
            sub_txt = f"Q{int(kr.get('roundIdx', 0)) + 1}/{kr.get('totalRounds', 5)} | {kr.get('phase', 'idle').upper()}"

        card_w = min(500, w - 320)
        sub_lines = self._wrap_text(sub_txt, card_w - 24, 0.43, 1, max_lines=2)
        hint_lines = self._wrap_text(hint_txt, card_w - 24, 0.41, 1, max_lines=2)
        card_h = 34 + len(sub_lines) * 20 + (len(hint_lines) * 19 + 4 if hint_lines else 0) + 10
        card_y0, card_y1 = 56, 56 + card_h
        self._blend_box(frame, 14, card_y0, 14 + card_w, card_y1, col=(12, 18, 30), alpha=0.82, border=turn_col)
        cv2.putText(frame, f"{title}  |  {turn_txt}", (24, card_y0 + 23), font, 0.49, turn_col, 2, cv2.LINE_AA)
        cy = card_y0 + 46
        for sl in sub_lines:
            cv2.putText(frame, sl, (24, cy), font, 0.43, (225, 234, 245), 1, cv2.LINE_AA)
            cy += 20
        for hl in hint_lines:
            cv2.putText(frame, hl, (24, cy), font, 0.41, (145, 220, 245), 1, cv2.LINE_AA)
            cy += 19

        # 2. Live Green -> Yellow -> Red Power & Aim Meter for BOTH players (Host webcam OR Her phone)
        aim = state.get("liveAim") or state.get("webcamAim")
        if aim and aim.get("game", aim.get("kind")) in ("pool", "beer_pong", "classic_darts"):
            pwr = max(0.0, min(1.0, float(aim.get("power", 0.0))))
            pcol = self._power_color_bgr(pwr)
            by_who = "YOU AIMING" if aim.get("by", "host") == "host" else "HER AIMING (PHONE)"
            if "sx" in aim and "cx" in aim and pwr > 0.04:
                p0 = (int(aim["sx"] * w), int(aim["sy"] * h))
                p1 = (int(aim["cx"] * w), int(aim["cy"] * h))
                cv2.line(frame, p0, p1, pcol, 3, cv2.LINE_AA)
                cv2.circle(frame, p0, 7, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(frame, p1, 10, pcol, 2, cv2.LINE_AA)
                cv2.putText(frame, f"{int(round(pwr * 100))}%", (p1[0] + 14, max(26, p1[1] - 8)), font, 0.55, pcol, 2, cv2.LINE_AA)
            if aim.get("kind") == "classic_darts":
                tx = int(w * (0.5 + 0.175 + float(aim.get("nx", 0.0)) * 0.13))
                ty = int(h * (0.37 + float(aim.get("ny", 0.0)) * 0.18))
                cv2.circle(frame, (tx, ty), 15, pcol, 2, cv2.LINE_AA)
                cv2.circle(frame, (tx, ty), 4, pcol, -1, cv2.LINE_AA)
            # Segmented Green -> Yellow -> Red Gauge right below top-left card
            gy0 = card_y1 + 10
            gx0, gx1, gy1 = 14, 340, gy0 + 54
            self._blend_box(frame, gx0, gy0, gx1, gy1, col=(12, 18, 30), alpha=0.82, border=pcol)
            zone_lbl = "SWEET SPOT" if 0.35 <= pwr <= 0.75 else ("MAX POWER" if pwr > 0.75 else "SOFT")
            cv2.putText(frame, f"{by_who}  |  {int(round(pwr * 100))}% ({zone_lbl})", (gx0 + 10, gy0 + 20), font, 0.42, pcol, 1, cv2.LINE_AA)
            bar_x0, bar_x1 = gx0 + 10, gx1 - 12
            bar_y0, bar_y1 = gy0 + 30, gy0 + 43
            cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (32, 42, 58), -1)
            fill_w = int((bar_x1 - bar_x0) * pwr)
            if fill_w > 0:
                cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x0 + fill_w, bar_y1), pcol, -1)
            cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (130, 150, 175), 1)

        # 3. Word Duel: Side-by-Side Spoiler-Free 5x6 Green/Yellow/Gray Progress Grids for BOTH Players
        if g == "word_duel":
            wd = state.get("word_duel", {})
            finished = wd.get("phase") == "finished"
            boards = wd.get("boards", {})
            buf_len = len(str(state.get("hostTextBuf", ""))[:5])
            panel_w = 392
            px0 = w // 2 - panel_w // 2
            py0 = h - 242
            self._blend_box(frame, px0, py0, px0 + panel_w, h - 14, col=(10, 16, 28), alpha=0.84, border=(108, 229, 255))
            tcols = {
                "correct": (85, 195, 75),    # Green
                "present": (45, 205, 245),   # Yellow
                "absent": (58, 64, 76),      # Gray
            }
            tile_s, gap = 28, 4
            for side_idx, (role_k, label, col_lbl) in enumerate([
                ("guest", "HER (PHONE)", (190, 145, 255)),
                ("host", "YOU (WEBCAM)", (110, 238, 255)),
            ]):
                board = boards.get(role_k, {})
                rows = board.get("rows", [])
                gx0 = px0 + 18 + side_idx * 196
                cv2.putText(frame, label, (gx0, py0 + 20), font, 0.44, col_lbl, 2, cv2.LINE_AA)
                grid_y0 = py0 + 28
                for r in range(6):
                    ry = grid_y0 + r * (tile_s + gap)
                    done_row = rows[r] if r < len(rows) else None
                    is_cur = (r == len(rows)) and not board.get("done")
                    for c in range(5):
                        rx = gx0 + c * (tile_s + gap)
                        bg = (28, 36, 52)
                        bd = (72, 90, 118)
                        ch = ""
                        if done_row is not None:
                            bg = tcols.get(done_row["states"][c], bg)
                            bd = bg
                            if finished and done_row.get("word"):
                                ch = done_row["word"][c]
                        elif role_k == "host" and is_cur and c < buf_len:
                            # Show tile active dot only (no letters leaked onto FaceTime cam!)
                            bg = (36, 58, 86)
                            bd = (45, 215, 255)
                        cv2.rectangle(frame, (rx, ry), (rx + tile_s, ry + tile_s), bg, -1)
                        cv2.rectangle(frame, (rx, ry), (rx + tile_s, ry + tile_s), bd, 1, cv2.LINE_AA)
                        if ch:
                            cv2.putText(frame, ch, (rx + 7, ry + 21), font, 0.56, (245, 250, 255), 2, cv2.LINE_AA)
                        elif role_k == "host" and is_cur and c < buf_len:
                            cv2.circle(frame, (rx + tile_s // 2, ry + tile_s // 2), 4, (45, 220, 255), -1, cv2.LINE_AA)

        # 4. Krillion 1v1 Jinx: Auto-Wrapped Multi-Line Prompt + Green/Yellow Status Pills (Spoiler-Free)
        elif g == "rare_answer":
            kr = state.get("rare_answer", {})
            phase = kr.get("phase", "idle")
            her_locked = bool(kr.get("locked", {}).get("guest"))
            you_locked = bool(kr.get("locked", {}).get("host"))
            card_w = min(800, w - 60)
            bx0 = (w - card_w) // 2
            bx1 = bx0 + card_w
            prompt_lines = self._wrap_text(kr.get("prompt", ""), card_w - 40, 0.55, 2, max_lines=3)
            card_h = 108 + max(1, len(prompt_lines)) * 26
            by1 = h - 18
            by0 = by1 - card_h
            self._blend_box(frame, bx0, by0, bx1, by1, col=(10, 18, 32), alpha=0.85, border=(108, 229, 255))

            if phase == "idle":
                cv2.putText(frame, "KRILLION 1v1 JINX (HER PHONE vs YOU WEBCAM)", (bx0 + 22, by0 + 42), font, 0.56, (110, 235, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, "Press ENTER on Mac (or Start on Phone) to begin!", (bx0 + 22, by0 + 82), font, 0.48, (220, 234, 248), 1, cv2.LINE_AA)
            elif phase == "preview":
                sec = max(1, int(math.ceil(float(kr.get("timer", 3.0)))))
                cv2.putText(frame, f"QUESTION IN {sec}s - GET READY", (bx0 + 22, by0 + 30), font, 0.50, (100, 235, 255), 2, cv2.LINE_AA)
                py = by0 + 62
                for pl in prompt_lines:
                    cv2.putText(frame, pl, (bx0 + 22, py), font, 0.55, (245, 250, 255), 2, cv2.LINE_AA)
                    py += 26
            elif phase == "answering":
                sec = max(0, int(math.ceil(float(kr.get("timer", 0.0)))))
                cv2.putText(frame, f"Q{int(kr.get('roundIdx', 0)) + 1}/{kr.get('totalRounds', 5)}  ({sec}s left)", (bx0 + 20, by0 + 26), font, 0.47, (110, 235, 255), 1, cv2.LINE_AA)
                # Green (LOCKED) vs Yellow (THINKING) Status Pills for BOTH Her & You
                for p_idx, (p_lbl, is_lk, px_start) in enumerate([
                    ("HER", her_locked, bx1 - 375),
                    ("YOU", you_locked, bx1 - 190),
                ]):
                    pcol = (80, 225, 85) if is_lk else (45, 215, 255)
                    ptxt = f"{p_lbl}: {'LOCKED' if is_lk else 'THINKING...'}"
                    self._blend_box(frame, px_start, by0 + 8, px_start + 172, by0 + 32, col=(20, 48, 32) if is_lk else (42, 42, 18), alpha=0.88, border=pcol)
                    cv2.putText(frame, ptxt, (px_start + 10, by0 + 25), font, 0.41, pcol, 1, cv2.LINE_AA)

                py = by0 + 58
                for pl in prompt_lines:
                    cv2.putText(frame, pl, (bx0 + 20, py), font, 0.55, (245, 250, 255), 2, cv2.LINE_AA)
                    py += 26

                foot_col = (80, 230, 85) if you_locked else (45, 215, 255)
                foot_msg = (
                    "YOU LOCKED IN! Waiting for Her answer..."
                    if you_locked
                    else "Secret typing in pewpew window (hidden from FaceTime camera)"
                )
                cv2.putText(frame, foot_msg, (bx0 + 20, by1 - 22), font, 0.46, foot_col, 1, cv2.LINE_AA)

                # Face-tracked THINKING (Yellow) / LOCKED (Green) badge near face
                cam = state.get("cam", {})
                if face_state is not None or cam.get("nose"):
                    if face_state is not None:
                        nx_px, ny_px = int(face_state.nose_px[0]), int(face_state.nose_px[1] - face_state.face_scale_px * 1.15)
                    else:
                        nx_px = int(float(cam["nose"][0]) * w)
                        ny_px = int(float(cam["nose"][1]) * h - max(70.0, float(cam.get("faceScale", 0.12)) * w * 1.15))
                    ny_px = max(84, min(by0 - 30, ny_px))
                    b_col = (80, 225, 85) if you_locked else (45, 215, 255)
                    b_txt = "LOCKED IN" if you_locked else "THINKING..."
                    self._blend_box(frame, nx_px - 68, ny_px - 18, nx_px + 68, ny_px + 10, col=(14, 24, 34), alpha=0.82, border=b_col)
                    cv2.putText(frame, b_txt, (nx_px - 52, ny_px + 2), font, 0.44, b_col, 2, cv2.LINE_AA)
            elif phase == "reveal":
                hist = kr.get("history", [])
                last = hist[-1] if hist else {}
                g_row = last.get("guest", {})
                h_row = last.get("host", {})
                jinx_note = "JINX! SAME PICK (+5 each)" if last.get("jinx") else "1v1 REVEAL"
                cv2.putText(frame, f"{jinx_note}  |  Deepest: {self._hud_ascii(last.get('sampleDeep', ''))[:32]}", (bx0 + 20, by0 + 28), font, 0.47, (100, 235, 255), 1, cv2.LINE_AA)
                cv2.putText(frame, f"Her: {self._hud_ascii(g_row.get('canonical') or '--')} (+{g_row.get('pts', 0)})", (bx0 + 20, by0 + 62), font, 0.52, (190, 145, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, f"You: {self._hud_ascii(h_row.get('canonical') or '--')} (+{h_row.get('pts', 0)})", (bx0 + 20, by0 + 92), font, 0.52, (115, 240, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, "Press ENTER for next question", (bx0 + 20, by1 - 14), font, 0.43, (195, 225, 245), 1, cv2.LINE_AA)
            elif phase == "surface":
                tot = kr.get("totals", {})
                cv2.putText(frame, f"FINAL 1v1 DIVE: You {tot.get('hostPts', 0)} pts vs Her {tot.get('guestPts', 0)} pts", (bx0 + 20, by0 + 48), font, 0.56, (110, 245, 190), 2, cv2.LINE_AA)
                ff = kr.get("forfeit") or "none"
                cv2.putText(frame, f"Forfeit: {ff.replace('_', ' ')} | Press ENTER to play again!", (bx0 + 20, by0 + 90), font, 0.47, (225, 235, 248), 1, cv2.LINE_AA)

    def draw_host_private_hud(self, preview: np.ndarray, state: dict, now: float) -> None:
        """Render private local-only host typing HUD onto `preview` AFTER vcam.send()."""
        g = state.get("activeGame", "lobby")
        h, w = preview.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX

        if g == "word_duel":
            wd = state.get("word_duel", {})
            board = wd.get("boards", {}).get("host", {})
            rows = board.get("rows", [])
            buf = self._hud_ascii(state.get("hostTextBuf", ""))[:5].upper()
            err = self._hud_ascii(state.get("hostTextErr", ""))
            # Overlay Host's secret letters onto the YOU (WEBCAM) grid + show typing bar locally
            panel_w = 392
            px0 = w // 2 - panel_w // 2
            py0 = h - 242
            gx0 = px0 + 18 + 196
            grid_y0 = py0 + 28
            tile_s, gap = 28, 4
            tcols = {
                "correct": (85, 195, 75),
                "present": (45, 205, 245),
                "absent": (58, 64, 76),
            }
            for r in range(6):
                ry = grid_y0 + r * (tile_s + gap)
                done_row = rows[r] if r < len(rows) else None
                is_cur = (r == len(rows)) and not board.get("done")
                for c in range(5):
                    rx = gx0 + c * (tile_s + gap)
                    ch = ""
                    if done_row is not None and done_row.get("word"):
                        ch = done_row["word"][c]
                        bg = tcols.get(done_row["states"][c], (58, 64, 76))
                        cv2.rectangle(preview, (rx + 1, ry + 1), (rx + tile_s - 1, ry + tile_s - 1), bg, -1)
                    elif is_cur and c < len(buf):
                        ch = buf[c]
                        cv2.rectangle(preview, (rx + 1, ry + 1), (rx + tile_s - 1, ry + tile_s - 1), (42, 62, 92), -1)
                    if ch:
                        cv2.putText(preview, ch, (rx + 7, ry + 21), font, 0.56, (248, 252, 255), 2, cv2.LINE_AA)
            foot_txt = err if err else (f"TYPE: {buf}_  (ENTER)" if not board.get("done") else "Round complete!")
            foot_col = (95, 130, 255) if err else (160, 235, 255)
            self._blend_box(preview, gx0 - 4, grid_y0 + 192, gx0 + 178, grid_y0 + 212, col=(14, 20, 32), alpha=0.90)
            cv2.putText(preview, foot_txt[:26], (gx0, grid_y0 + 206), font, 0.39, foot_col, 1, cv2.LINE_AA)

        elif g == "rare_answer":
            kr = state.get("rare_answer", {})
            if kr.get("phase") == "answering" and not kr.get("locked", {}).get("host"):
                card_w = min(800, w - 60)
                bx0 = (w - card_w) // 2
                bx1 = bx0 + card_w
                prompt_lines = self._wrap_text(kr.get("prompt", ""), card_w - 40, 0.55, 2, max_lines=3)
                card_h = 108 + max(1, len(prompt_lines)) * 26
                by1 = h - 18
                by0 = by1 - card_h
                buf = self._hud_ascii(state.get("hostTextBuf", ""))
                err = self._hud_ascii(state.get("hostTextErr", ""))
                self._blend_box(preview, bx0 + 18, by1 - 44, bx1 - 18, by1 - 8, col=(20, 32, 50), alpha=0.96, border=(108, 229, 255))
                shown = f"> {buf}_" if buf else "Type your private answer here & press ENTER..."
                col = (250, 253, 255) if buf else (140, 175, 210)
                cv2.putText(preview, shown[:68], (bx0 + 28, by1 - 21), font, 0.49, col, 1, cv2.LINE_AA)
                if err:
                    self._blend_box(preview, bx0 + 18, by0 - 30, bx1 - 18, by0 - 4, col=(28, 30, 56), alpha=0.92, border=(80, 215, 255))
                    cv2.putText(preview, err[:76], (bx0 + 26, by0 - 11), font, 0.43, (110, 225, 255), 1, cv2.LINE_AA)

