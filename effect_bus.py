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
        """Render aesthetic side-by-side 1v1 broadcast visuals onto `frame` before vcam."""
        g = state.get("activeGame", "lobby")
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        her_code = self._hud_ascii(str(state.get("herCode") or ""))
        your_code = self._hud_ascii(str(state.get("yourCode") or ""))
        cloud_st = str(state.get("cloudStatus") or "")
        roles_here = {str(p.get("role", "")) for p in state.get("players", [])}

        if g == "lobby":
            if not her_code and not your_code:
                return
            ly0, ly1 = 56, 128
            # Keep all 3 pills cleanly left of Effects drawer (w - 284 on preview) on 1280px frames
            right_limit = min(w - 18, max(760, w - 302))
            avail_w = right_limit - 18
            gap = 12
            side_w = min(286, max(195, int(avail_w * 0.285)))
            ctr_w = avail_w - side_w * 2 - gap * 2

            # Left Pill: HER CODE (P1)
            lx0, lx1 = 18, 18 + side_w
            self._blend_box(frame, lx0, ly0, lx1, ly1, col=(16, 18, 34), alpha=0.86, border=(195, 145, 255))
            cv2.putText(frame, "HER CODE (P1)", (lx0 + 12, ly0 + 21), font, 0.44, (205, 155, 255), 1, cv2.LINE_AA)
            h_stat = "JOINED" if "guest" in roles_here else "OPEN"
            h_col = (80, 230, 110) if "guest" in roles_here else (195, 145, 255)
            cv2.putText(frame, h_stat, (lx1 - 74, ly0 + 21), font, 0.39, h_col, 1, cv2.LINE_AA)
            cv2.putText(frame, her_code or "----", (lx0 + 14, ly0 + 58), font, 1.02, (255, 255, 255), 2, cv2.LINE_AA)

            # Center Pill: GitHub URL + Cloud Relay Status
            cx0 = lx1 + gap
            cx1 = cx0 + ctr_w
            relay_ok = (cloud_st == "connected")
            c_border = (110, 235, 255) if relay_ok else (85, 195, 240)
            self._blend_box(frame, cx0, ly0, cx1, ly1, col=(12, 18, 30), alpha=0.86, border=c_border)
            url_lbl = "squasa.github.io/pewpew"
            (uw, _), _ = cv2.getTextSize(url_lbl, font, 0.56, 2)
            cv2.putText(frame, url_lbl, (cx0 + max(10, (ctr_w - uw) // 2), ly0 + 28), font, 0.56, (110, 240, 255), 2, cv2.LINE_AA)
            sub_lbl = "1V1 CLOUD READY - ENTER CODE ON PHONE" if relay_ok else f"1V1 RELAY: {(cloud_st or 'READY').upper()}"
            (sw, _), _ = cv2.getTextSize(sub_lbl, font, 0.37, 1)
            sub_col = (115, 245, 160) if relay_ok else (220, 230, 245)
            cv2.putText(frame, sub_lbl, (cx0 + max(8, (ctr_w - sw) // 2), ly0 + 55), font, 0.37, sub_col, 1, cv2.LINE_AA)

            # Right Pill: YOUR CODE (P2)
            rx0 = cx1 + gap
            rx1 = rx0 + side_w
            self._blend_box(frame, rx0, ly0, rx1, ly1, col=(12, 22, 34), alpha=0.86, border=(110, 240, 255))
            cv2.putText(frame, "YOUR CODE (P2)", (rx0 + 12, ly0 + 21), font, 0.44, (110, 240, 255), 1, cv2.LINE_AA)
            y_stat = "JOINED" if "host" in roles_here else "OPEN"
            y_col = (80, 230, 110) if "host" in roles_here else (110, 240, 255)
            cv2.putText(frame, y_stat, (rx1 - 74, ly0 + 21), font, 0.39, y_col, 1, cv2.LINE_AA)
            cv2.putText(frame, your_code or "----", (rx0 + 14, ly0 + 58), font, 1.02, (255, 255, 255), 2, cv2.LINE_AA)
            return

        title_map = {
            "pool": "1V1 8-BALL POOL",
            "beer_pong": "1V1 CUP PONG",
            "classic_darts": "1V1 DARTS 301",
            "face_darts": "1V1 FACE DARTS",
            "mouth_catch": "1V1 MOUTH CATCH",
            "word_duel": "1V1 WORD DUEL",
            "rare_answer": "1V1 KRILLION JINX",
        }
        title = title_map.get(g, g.upper())
        center_sub = ""
        center_col = (110, 235, 255)
        her_stat = "Ready"
        you_stat = "Ready"
        her_badge = ("HER (P1)", (195, 145, 255), False)
        you_badge = ("YOU (P2)", (110, 240, 255), False)

        if g == "pool":
            pm = state.get("pool", {})
            gg = pm.get("groups", {}).get("guest") or "open"
            hg = pm.get("groups", {}).get("host") or "open"
            her_stat = f"Group: {gg}"
            you_stat = f"Group: {hg}"
            if pm.get("phase") == "finished":
                win = pm.get("winner")
                center_sub = "YOU WIN!" if win == "host" else "HER WINS!"
                center_col = (115, 245, 160) if win == "host" else (205, 145, 255)
            else:
                turn_g = pm.get("turn") == "guest"
                center_sub = pm.get("status") or ("HER TURN" if turn_g else "YOUR TURN")
                center_col = (205, 145, 255) if turn_g else (110, 240, 255)
                her_badge = ("SHOOTING" if turn_g else "WAITING", (80, 230, 110) if turn_g else (45, 215, 255), turn_g)
                you_badge = ("SHOOTING" if not turn_g else "WAITING", (80, 230, 110) if not turn_g else (45, 215, 255), not turn_g)
        elif g == "beer_pong":
            bp = state.get("beer_pong", {})
            g_alive = sum(1 for c in bp.get("racks", {}).get("guest", []) if c.get("alive"))
            h_alive = sum(1 for c in bp.get("racks", {}).get("host", []) if c.get("alive"))
            her_stat = f"Cups Left: {g_alive}"
            you_stat = f"Cups Left: {h_alive}"
            if bp.get("phase") == "finished":
                center_sub = "YOU WIN!" if bp.get("winner") == "host" else "HER WINS!"
                center_col = (115, 245, 160) if bp.get("winner") == "host" else (205, 145, 255)
            else:
                turn_g = bp.get("turn") == "guest"
                shots_left = bp.get("shotsLeft", 3)
                center_sub = bp.get("status") or (f"{'HER' if turn_g else 'YOUR'} TURN ({shots_left} shots)")
                her_badge = (f"{shots_left} SHOTS" if turn_g else "DEFEND", (80, 230, 110) if turn_g else (45, 215, 255), turn_g)
                you_badge = (f"{shots_left} SHOTS" if not turn_g else "SWAT OK", (80, 230, 110) if not turn_g else (45, 215, 255), not turn_g)
        elif g == "classic_darts":
            cd = state.get("classic_darts", {})
            sc = cd.get("scores", {})
            her_stat = f"Score: {sc.get('guest', 301)}"
            you_stat = f"Score: {sc.get('host', 301)}"
            if cd.get("phase") == "finished":
                center_sub = "YOU WIN!" if cd.get("winner") == "host" else "HER WINS!"
                center_col = (115, 245, 160) if cd.get("winner") == "host" else (205, 145, 255)
            else:
                turn_g = cd.get("turn") == "guest"
                d_left = cd.get("dartsLeft", 3)
                center_sub = cd.get("status") or (f"{'HER' if turn_g else 'YOUR'} TURN ({d_left} darts)")
                her_badge = (f"{d_left} DARTS" if turn_g else "WAIT", (80, 230, 110) if turn_g else (45, 215, 255), turn_g)
                you_badge = (f"{d_left} DARTS" if not turn_g else "WAIT", (80, 230, 110) if not turn_g else (45, 215, 255), not turn_g)
        elif g == "face_darts":
            fd = state.get("face_darts", {})
            wins = fd.get("roundWins", {})
            sc = fd.get("scores", {})
            her_stat = f"Pts {sc.get('guest', 0)} | Wins {wins.get('guest', 0)}"
            you_stat = f"Pts {sc.get('host', 0)} | Wins {wins.get('host', 0)}"
            center_sub = f"Round {fd.get('roundNum', 1)}/{fd.get('bestOf', 3)} | Darts {fd.get('dartsLeft', 0)}"
            her_badge = ("THROWING", (80, 230, 110), True)
            you_badge = ("PALM SHIELD", (45, 215, 255), False)
        elif g == "mouth_catch":
            mc = state.get("mouth_catch", {})
            her_stat = f"Tosses Left: {mc.get('throwsLeft', 0)}"
            you_stat = f"Caught {mc.get('catches', 0)} | {mc.get('score', 0)} pts"
            center_sub = f"COMBO {mc.get('combo', 0)}x"
            her_badge = ("TOSSING", (80, 230, 110), True)
            you_badge = ("OPEN MOUTH!", (45, 215, 255), True)
        elif g == "word_duel":
            wd = state.get("word_duel", {})
            opp_rows = len(wd.get("boards", {}).get("guest", {}).get("rows", []))
            you_rows = len(wd.get("boards", {}).get("host", {}).get("rows", []))
            her_stat = f"Guesses: {opp_rows}/6"
            you_stat = f"Guesses: {you_rows}/6"
            if wd.get("phase") == "finished":
                win = wd.get("winner")
                center_sub = f"{'YOU WIN' if win == 'host' else ('DRAW' if win == 'draw' else 'HER WINS')} ({wd.get('target') or ''})"
                center_col = (115, 245, 160) if win == "host" else (205, 145, 255)
                her_badge = ("WIN" if win == "guest" else "DONE", (80, 230, 110) if win == "guest" else (120, 130, 150), False)
                you_badge = ("WIN" if win == "host" else "DONE", (80, 230, 110) if win == "host" else (120, 130, 150), False)
            else:
                g_done = bool(wd.get("boards", {}).get("guest", {}).get("done"))
                h_done = bool(wd.get("boards", {}).get("host", {}).get("done"))
                center_sub = "LIVE 5-LETTER SPEED RACE"
                her_badge = ("LOCKED" if g_done else "RACING", (80, 230, 110) if g_done else (45, 215, 255), not g_done)
                you_badge = ("LOCKED" if h_done else "RACING", (80, 230, 110) if h_done else (45, 215, 255), not h_done)
        elif g == "rare_answer":
            kr = state.get("rare_answer", {})
            tot = kr.get("totals", {})
            her_lk = bool(kr.get("locked", {}).get("guest"))
            you_lk = bool(kr.get("locked", {}).get("host"))
            her_stat = f"{tot.get('guestPts', 0)} pts | -{tot.get('guestDepth', 0)}m"
            you_stat = f"{tot.get('hostPts', 0)} pts | -{tot.get('hostDepth', 0)}m"
            center_sub = f"Q{int(kr.get('roundIdx', 0)) + 1}/{kr.get('totalRounds', 5)} | {kr.get('phase', 'idle').upper()}"
            her_badge = ("LOCKED" if her_lk else "THINKING...", (80, 230, 110) if her_lk else (45, 215, 255), her_lk)
            you_badge = ("LOCKED" if you_lk else "THINKING...", (80, 230, 110) if you_lk else (45, 215, 255), you_lk)

        # 1. Side-by-side 1v1 Broadcast Pills (Left: HER P1 | Center: Title | Right: YOU P2)
        py0, py1 = 52, 110
        pill_w = min(272, (w - 400) // 2)
        # Left Pill (HER P1)
        lx0, lx1 = 18, 18 + pill_w
        self._blend_box(frame, lx0, py0, lx1, py1, col=(16, 18, 34), alpha=0.84, border=(195, 145, 255))
        her_hdr = f"HER (P1) #{her_code}" if her_code else "HER (P1)"
        cv2.putText(frame, her_hdr, (lx0 + 12, py0 + 22), font, 0.45, (205, 155, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, self._hud_ascii(her_stat)[:26], (lx0 + 12, py0 + 46), font, 0.42, (232, 238, 248), 1, cv2.LINE_AA)
        hb_txt, hb_col, _ = her_badge
        cv2.putText(frame, hb_txt, (lx1 - 102, py0 + 22), font, 0.39, hb_col, 1, cv2.LINE_AA)

        # Center Game Banner (compact so center face below stays wide open)
        cw = min(356, w - pill_w * 2 - 72)
        cx0 = (w - cw) // 2
        cx1 = cx0 + cw
        c_lines = self._wrap_text(center_sub, cw - 20, 0.40, 1, max_lines=2)
        c_y1 = py0 + (58 if len(c_lines) <= 1 else 72)
        self._blend_box(frame, cx0, py0, cx1, c_y1, col=(12, 18, 30), alpha=0.84, border=center_col)
        (tw, _), _ = cv2.getTextSize(title, font, 0.48, 2)
        cv2.putText(frame, title, (cx0 + max(10, (cw - tw) // 2), py0 + 22), font, 0.48, center_col, 2, cv2.LINE_AA)
        for i_l, cl in enumerate(c_lines):
            (clw, _), _ = cv2.getTextSize(cl, font, 0.40, 1)
            cv2.putText(frame, cl, (cx0 + max(8, (cw - clw) // 2), py0 + 44 + i_l * 17), font, 0.40, (225, 236, 248), 1, cv2.LINE_AA)

        # Right Pill (YOU P2)
        rx1 = w - 18
        rx0 = rx1 - pill_w
        self._blend_box(frame, rx0, py0, rx1, py1, col=(12, 22, 34), alpha=0.84, border=(110, 240, 255))
        you_hdr = f"YOU (P2) #{your_code}" if your_code else "YOU (P2)"
        cv2.putText(frame, you_hdr, (rx0 + 12, py0 + 22), font, 0.45, (110, 240, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, self._hud_ascii(you_stat)[:26], (rx0 + 12, py0 + 46), font, 0.42, (232, 238, 248), 1, cv2.LINE_AA)
        yb_txt, yb_col, _ = you_badge
        cv2.putText(frame, yb_txt, (rx1 - 102, py0 + 22), font, 0.39, yb_col, 1, cv2.LINE_AA)

        if (her_code or your_code) and len(roles_here) < 2:
            fy0, fy1 = h - 84, h - 58
            f_txt = f"squasa.github.io/pewpew | HER {her_code} | YOU {your_code}"
            (fw, _), _ = cv2.getTextSize(f_txt, font, 0.39, 1)
            fx1 = min(w - 18, 18 + fw + 24)
            self._blend_box(frame, 18, fy0, fx1, fy1, col=(12, 18, 30), alpha=0.78, border=(90, 155, 200))
            cv2.putText(frame, f_txt, (30, fy0 + 18), font, 0.39, (215, 236, 252), 1, cv2.LINE_AA)

        # 2. Live Green -> Yellow -> Red Power & Aim Meter on left rail (Pool / Cup Pong / Darts)
        aim = state.get("liveAim") or state.get("webcamAim")
        if aim and aim.get("game", aim.get("kind")) in ("pool", "beer_pong", "classic_darts"):
            pwr = max(0.0, min(1.0, float(aim.get("power", 0.0))))
            pcol = self._power_color_bgr(pwr)
            by_who = "YOU AIMING (P2)" if aim.get("by", "host") == "host" else "HER AIMING (P1)"
            gy0 = py1 + 12
            gx0, gx1, gy1 = 18, 326, gy0 + 54
            self._blend_box(frame, gx0, gy0, gx1, gy1, col=(12, 18, 30), alpha=0.84, border=pcol)
            zone_lbl = "SWEET SPOT" if 0.35 <= pwr <= 0.75 else ("MAX POWER" if pwr > 0.75 else "SOFT")
            cv2.putText(frame, f"{by_who} | {int(round(pwr * 100))}% ({zone_lbl})", (gx0 + 10, gy0 + 20), font, 0.41, pcol, 1, cv2.LINE_AA)
            bar_x0, bar_x1 = gx0 + 10, gx1 - 12
            bar_y0, bar_y1 = gy0 + 30, gy0 + 43
            cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (32, 42, 58), -1)
            fill_w = int((bar_x1 - bar_x0) * pwr)
            if fill_w > 0:
                cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x0 + fill_w, bar_y1), pcol, -1)
            cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (130, 150, 175), 1)

        # 3. Word Duel: Side-by-Side Flanked Left & Right 5x6 Green/Yellow/Gray Progress Grids (face open in center!)
        if g == "word_duel":
            wd = state.get("word_duel", {})
            finished = wd.get("phase") == "finished"
            boards = wd.get("boards", {})
            buf_len = len(str(state.get("hostTextBuf", ""))[:5])
            tcols = {
                "correct": (85, 195, 75),    # Green
                "present": (45, 205, 245),   # Yellow
                "absent": (58, 64, 76),      # Gray
            }
            tile_s, gap = 28, 4
            card_grid_w = 182
            py_grid = h - 252
            for side_idx, (role_k, label, col_lbl, gx_box) in enumerate([
                ("guest", "HER BOARD (P1)", (195, 145, 255), 18),
                ("host", "YOUR BOARD (P2)", (110, 240, 255), w - 18 - card_grid_w),
            ]):
                board = boards.get(role_k, {})
                rows = board.get("rows", [])
                self._blend_box(frame, gx_box, py_grid, gx_box + card_grid_w, py_grid + 236, col=(10, 16, 28), alpha=0.84, border=col_lbl)
                cv2.putText(frame, label, (gx_box + 12, py_grid + 20), font, 0.43, col_lbl, 2, cv2.LINE_AA)
                gx0 = gx_box + 13
                grid_y0 = py_grid + 30
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
                            bg = (36, 58, 86)
                            bd = (45, 215, 255)
                        cv2.rectangle(frame, (rx, ry), (rx + tile_s, ry + tile_s), bg, -1)
                        cv2.rectangle(frame, (rx, ry), (rx + tile_s, ry + tile_s), bd, 1, cv2.LINE_AA)
                        if ch:
                            cv2.putText(frame, ch, (rx + 7, ry + 21), font, 0.56, (245, 250, 255), 2, cv2.LINE_AA)
                        elif role_k == "host" and is_cur and c < buf_len:
                            cv2.circle(frame, (rx + tile_s // 2, ry + tile_s // 2), 4, (45, 220, 255), -1, cv2.LINE_AA)

        # 4. Krillion 1v1 Jinx: Auto-Wrapped Multi-Line Prompt + Green/Yellow Side-by-Side Status Pills
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
                cv2.putText(frame, "KRILLION 1v1 JINX (SIDE-BY-SIDE ON PHONES)", (bx0 + 22, by0 + 42), font, 0.56, (110, 235, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, "Tap Start Dive on either phone to plunge!", (bx0 + 22, by0 + 82), font, 0.48, (220, 234, 248), 1, cv2.LINE_AA)
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
                for p_lbl, is_lk, px_start in [
                    ("HER", her_locked, bx1 - 375),
                    ("YOU", you_locked, bx1 - 190),
                ]:
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
                    "YOU LOCKED IN! Waiting for Her phone..."
                    if you_locked
                    else "1v1 Phones: Lock your rarest answer before timer ends!"
                )
                cv2.putText(frame, foot_msg, (bx0 + 20, by1 - 22), font, 0.46, foot_col, 1, cv2.LINE_AA)

                cam = state.get("cam", {})
                if face_state is not None or cam.get("nose"):
                    if face_state is not None:
                        nx_px, ny_px = int(face_state.nose_px[0]), int(face_state.nose_px[1] - face_state.face_scale_px * 1.15)
                    else:
                        nx_px = int(float(cam["nose"][0]) * w)
                        ny_px = int(float(cam["nose"][1]) * h - max(70.0, float(cam.get("faceScale", 0.12)) * w * 1.15))
                    ny_px = max(120, min(by0 - 30, ny_px))
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
                cv2.putText(frame, "Tap Next Dive on phone for next question", (bx0 + 20, by1 - 14), font, 0.43, (195, 225, 245), 1, cv2.LINE_AA)
            elif phase == "surface":
                tot = kr.get("totals", {})
                cv2.putText(frame, f"FINAL 1v1 DIVE: You {tot.get('hostPts', 0)} pts vs Her {tot.get('guestPts', 0)} pts", (bx0 + 20, by0 + 48), font, 0.56, (110, 245, 190), 2, cv2.LINE_AA)
                ff = kr.get("forfeit") or "none"
                cv2.putText(frame, f"Forfeit: {ff.replace('_', ' ')} | Tap Rematch on phone!", (bx0 + 20, by0 + 90), font, 0.47, (225, 235, 248), 1, cv2.LINE_AA)

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
            if not buf and not err and not any(r.get("word") for r in rows):
                return
            card_grid_w = 182
            gx_box = w - 18 - card_grid_w
            py_grid = h - 252
            gx0 = gx_box + 13
            grid_y0 = py_grid + 30
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
            if buf or err:
                foot_txt = err if err else f"TYPE: {buf}_"
                foot_col = (95, 130, 255) if err else (160, 235, 255)
                self._blend_box(preview, gx_box, grid_y0 + 190, gx_box + card_grid_w, grid_y0 + 206, col=(14, 20, 32), alpha=0.90)
                cv2.putText(preview, foot_txt[:22], (gx_box + 8, grid_y0 + 202), font, 0.37, foot_col, 1, cv2.LINE_AA)

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

