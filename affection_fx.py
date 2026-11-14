"""Stage 4 Affection Pack: finger-heart sparkler, kiss-pucker rising hearts, & smile cheek shimmer."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from hand_orientation import hand_scale, is_finger_heart


def _heart_poly(cx: float, cy: float, size: float) -> np.ndarray:
    """Return integer polygon vertices (N, 1, 2) for a crisp symmetric heart centered near (cx, cy)."""
    ts = np.linspace(0.0, 2.0 * math.pi, 28, endpoint=False)
    xs = 16.0 * (np.sin(ts) ** 3)
    ys = -(13.0 * np.cos(ts) - 5.0 * np.cos(2.0 * ts) - 2.0 * np.cos(3.0 * ts) - np.cos(4.0 * ts))
    scale = size / 32.0
    pts = np.stack([cx + xs * scale, cy + ys * scale], axis=-1).astype(np.int32)
    return pts.reshape(-1, 1, 2)


def _draw_alpha_heart(
    frame: np.ndarray,
    cx: float,
    cy: float,
    size: float,
    bgr: tuple[int, int, int],
    alpha: float,
) -> None:
    if alpha <= 0.02 or size < 4.0:
        return
    fh, fw = frame.shape[:2]
    pad = int(size * 0.85) + 4
    x0, y0 = max(0, int(cx) - pad), max(0, int(cy) - pad)
    x1, y1 = min(fw, int(cx) + pad + 1), min(fh, int(cy) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return
    poly = _heart_poly(cx - x0, cy - y0, size)
    roi = frame[y0:y1, x0:x1]
    overlay = roi.copy()
    cv2.fillPoly(overlay, [poly], bgr, cv2.LINE_AA)
    highlight_col = (
        min(255, int(bgr[0] * 0.5 + 128)),
        min(255, int(bgr[1] * 0.5 + 128)),
        min(255, int(bgr[2] * 0.5 + 128)),
    )
    cv2.polylines(overlay, [poly], True, highlight_col, 1, cv2.LINE_AA)
    a = float(min(max(alpha, 0.0), 1.0))
    cv2.addWeighted(overlay, a, roi, 1.0 - a, 0.0, dst=roi)


@dataclass
class AffectionFX:
    """Renders finger-heart sparklers + blendshape kiss-hearts / cheek shimmer when enabled."""

    hearts: list[dict] = field(default_factory=list)
    sparkles: list[dict] = field(default_factory=list)
    _last_pucker_spawn: float = 0.0
    _last_heart_sparkle: float = 0.0
    _rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(17))

    def clear(self) -> None:
        self.hearts.clear()
        self.sparkles.clear()

    def spawn_heart(self, x: float, y: float, size: float = 26.0, vy: float = -105.0, ttl: float = 1.65) -> None:
        if len(self.hearts) >= 56:
            self.hearts.pop(0)
        palette = (
            (175, 110, 255),
            (150, 90, 248),
            (195, 155, 255),
            (130, 80, 235),
        )
        col = palette[int(self._rng.integers(0, len(palette)))]
        self.hearts.append({
            "x": float(x),
            "y": float(y),
            "vx": float(self._rng.uniform(-24.0, 24.0)),
            "vy": float(vy * self._rng.uniform(0.88, 1.15)),
            "phase": float(self._rng.uniform(0.0, 6.28)),
            "size": float(size),
            "bgr": col,
            "ttl": float(ttl),
            "max_ttl": float(ttl),
        })

    def update_and_render(
        self,
        frame: np.ndarray,
        hands_lm: list[list[tuple[float, float]]],
        face_state,
        now: float,
        dt: float,
        enabled: bool,
    ) -> int:
        """Advance particles and draw affection visuals. Returns count of active finger-hearts."""
        if not enabled:
            if self.hearts or self.sparkles:
                self.clear()
            return 0

        fh, fw = frame.shape[:2]
        active_hand_hearts: list[tuple[float, float, float]] = []

        # 1. Hand finger-heart detection + halo + sparkles
        for lm in hands_lm:
            if is_finger_heart(lm):
                sc_px = hand_scale(lm) * ((fw + fh) * 0.5)
                hx = (lm[4][0] + lm[8][0]) * 0.5 * fw
                hy = (lm[4][1] + lm[8][1]) * 0.5 * fh - max(12.0, sc_px * 0.34)
                active_hand_hearts.append((hx, hy, sc_px))

        if active_hand_hearts and now - self._last_heart_sparkle > 0.055:
            self._last_heart_sparkle = now
            for hx, hy, sc_px in active_hand_hearts:
                for _ in range(2):
                    if len(self.sparkles) >= 96:
                        self.sparkles.pop(0)
                    ang = float(self._rng.uniform(0.0, 2.0 * math.pi))
                    spd = float(self._rng.uniform(25.0, 90.0))
                    self.sparkles.append({
                        "x": hx + float(self._rng.uniform(-8.0, 8.0)),
                        "y": hy + float(self._rng.uniform(-8.0, 8.0)),
                        "vx": math.cos(ang) * spd,
                        "vy": math.sin(ang) * spd - 45.0,
                        "ttl": float(self._rng.uniform(0.45, 0.85)),
                        "max_ttl": 0.85,
                    })

        # 2. Face blendshape triggers (kiss/pucker -> rising hearts, warm smile -> cheek shimmer)
        if face_state is not None:
            bs = face_state.blendshapes
            pucker = float(bs.get("mouthPucker", 0.0))
            funnel = float(bs.get("mouthFunnel", 0.0))
            if pucker > 0.42 or (pucker > 0.30 and funnel > 0.35):
                if now - self._last_pucker_spawn > 0.16:
                    self._last_pucker_spawn = now
                    mx, my = face_state.mouth_px
                    sz = max(18.0, min(42.0, face_state.face_scale_px * 0.16))
                    self.spawn_heart(
                        mx + float(self._rng.uniform(-10.0, 10.0)),
                        my - sz * 0.35,
                        size=sz,
                    )

            smile = 0.5 * (float(bs.get("mouthSmileLeft", 0.0)) + float(bs.get("mouthSmileRight", 0.0)))
            if smile > 0.56 and len(face_state.landmarks) > 454:
                shimmer_a = min(0.28, (smile - 0.56) * 0.65)
                lms = face_state.landmarks
                nose = (lms[1][0] * fw, lms[1][1] * fh)
                rad = max(8, int(face_state.face_scale_px * 0.11))
                for ear_idx in (234, 454):
                    ex, ey = lms[ear_idx][0] * fw, lms[ear_idx][1] * fh
                    cx = int(nose[0] * 0.58 + ex * 0.42)
                    cy = int(nose[1] * 0.62 + ey * 0.38 + face_state.face_scale_px * 0.06)
                    x0, y0 = max(0, cx - rad), max(0, cy - rad)
                    x1, y1 = min(fw, cx + rad), min(fh, cy + rad)
                    if x1 > x0 and y1 > y0:
                        roi = frame[y0:y1, x0:x1]
                        ov = roi.copy()
                        cv2.circle(ov, (cx - x0, cy - y0), rad, (170, 130, 255), -1, cv2.LINE_AA)
                        cv2.addWeighted(ov, shimmer_a, roi, 1.0 - shimmer_a, 0.0, dst=roi)

        # 3. Draw finger-heart emblems
        pulse = 1.0 + 0.12 * math.sin(now * 7.5)
        for hx, hy, sc_px in active_hand_hearts:
            size = max(24.0, min(58.0, sc_px * 0.38)) * pulse
            _draw_alpha_heart(frame, hx, hy, size * 1.28, (215, 165, 255), 0.32)
            _draw_alpha_heart(frame, hx, hy, size, (165, 105, 255), 0.90)

        # 4. Step and render rising hearts
        alive_hearts: list[dict] = []
        for h in self.hearts:
            h["ttl"] -= dt
            if h["ttl"] <= 0.0:
                continue
            h["y"] += h["vy"] * dt
            h["x"] += (h["vx"] + math.sin(now * 4.5 + h["phase"]) * 28.0) * dt
            frac = h["ttl"] / max(h["max_ttl"], 1e-3)
            alpha = min(1.0, frac * 1.45) * 0.90
            _draw_alpha_heart(frame, h["x"], h["y"], h["size"] * (0.85 + 0.25 * (1.0 - frac)), h["bgr"], alpha)
            alive_hearts.append(h)
        self.hearts = alive_hearts

        # 5. Step and render golden-pink sparkles
        alive_sp: list[dict] = []
        for sp in self.sparkles:
            sp["ttl"] -= dt
            if sp["ttl"] <= 0.0:
                continue
            sp["x"] += sp["vx"] * dt
            sp["y"] += sp["vy"] * dt
            frac = sp["ttl"] / max(sp["max_ttl"], 1e-3)
            px, py = int(sp["x"]), int(sp["y"])
            if 2 <= px < fw - 2 and 2 <= py < fh - 2:
                rad = max(1, int(3.2 * frac))
                col = (int(190 * frac + 60), int(185 * frac + 55), int(255 * frac))
                cv2.circle(frame, (px, py), rad, col, -1, cv2.LINE_AA)
            alive_sp.append(sp)
        self.sparkles = alive_sp

        return len(active_hand_hearts)
