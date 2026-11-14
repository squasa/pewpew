"""Preview-only FaceTime-style filter toggle menu, live audio meters, and loud failure banner."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np


def _ascii(s: str) -> str:
    """Normalize smart quotes/punctuation so OpenCV Hershey fonts render cleanly."""
    return (
        s.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .encode("ascii", "replace")
        .decode("ascii")
    )


def _level_norm(amp: float) -> float:
    """Map linear amplitude [0..1] to dBFS meter fraction [0..1] (-54dB .. 0dB)."""
    if amp <= 1e-6:
        return 0.0
    db = 20.0 * math.log10(min(amp, 1.0))
    return float(min(max((db + 54.0) / 54.0, 0.0), 1.0))


def _blend_panel(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], alpha: float) -> None:
    h, w = img.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1]
    overlay = np.empty_like(roi)
    overlay[:] = color
    cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0.0, dst=roi)


@dataclass
class PreviewUI:
    filters: dict[str, bool] = field(default_factory=lambda: {
        "saber": True,
        "face": False,
        "affection": False,
    })
    menu_open: bool = True
    qr_open: bool = True
    _hitboxes: list[tuple[int, int, int, int, str]] = field(default_factory=list)
    _pending_actions: list[str] = field(default_factory=list)

    def toggle(self, key: str) -> None:
        if key in self.filters:
            self.filters[key] = not self.filters[key]

    def consume_click(self, x: int, y: int) -> bool:
        for x0, y0, x1, y1, action in self._hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._pending_actions.append(action)
                return True
        return False

    def on_mouse(self, event: int, x: int, y: int, flags: int, param=None) -> None:  # noqa: ARG002
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        self.consume_click(x, y)

    def pop_actions(self) -> list[str]:
        acts = list(self._pending_actions)
        self._pending_actions.clear()
        return acts

    def draw(
        self,
        preview: np.ndarray,
        audio,
        shots: int,
        saber_ext: float,
        frame_ms: float,
        warning: str | None,
        game_info: dict | None = None,
        blade_color: str = "blue",
        blade_bgr: tuple[int, int, int] = (255, 173, 71),
    ) -> None:
        h, w = preview.shape[:2]
        self._hitboxes.clear()

        # Compute right-side menu bounds first so top warning never overlaps it
        px1 = w - 16
        px0 = px1 - 268
        py0 = 16

        # 0. Top-left/center clickable 1v1 Games Switcher Strip (preview only)
        if game_info is not None:
            cur_g = str(game_info.get("game", "lobby"))
            tabs = [
                ("lobby", "Hub"),
                ("pool", "Pool"),
                ("beer_pong", "Pong"),
                ("classic_darts", "301"),
                ("face_darts", "FaceDarts"),
                ("mouth_catch", "Catch"),
                ("rare_answer", "Krillion"),
                ("word_duel", "Words"),
            ]
            tx = 14
            ty0, ty1 = 14, 44
            for gid, glbl in tabs:
                (tw, _), _ = cv2.getTextSize(glbl, cv2.FONT_HERSHEY_SIMPLEX, 0.43, 1)
                bw = tw + 18
                if tx + bw >= px0 - 110:
                    break
                active = (gid == cur_g)
                _blend_panel(preview, tx, ty0, tx + bw, ty1, (38, 92, 118) if active else (24, 28, 38), 0.88)
                cv2.rectangle(preview, (tx, ty0), (tx + bw, ty1), (110, 235, 255) if active else (80, 92, 112), 1, cv2.LINE_AA)
                cv2.putText(preview, glbl, (tx + 9, ty0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (255, 255, 255) if active else (200, 212, 228), 1, cv2.LINE_AA)
                self._hitboxes.append((tx, ty0, tx + bw, ty1, f"game:{gid}"))
                tx += bw + 6
            _blend_panel(preview, tx, ty0, tx + 54, ty1, (38, 86, 108) if self.qr_open else (26, 32, 44), 0.88)
            cv2.rectangle(preview, (tx, ty0), (tx + 54, ty1), (110, 235, 255) if self.qr_open else (90, 102, 124), 1, cv2.LINE_AA)
            cv2.putText(preview, "QR", (tx + 16, ty0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (240, 248, 255), 1, cv2.LINE_AA)
            self._hitboxes.append((tx, ty0, tx + 54, ty1, "toggle_qr"))
            tx += 60
            if cur_g != "lobby" and tx + 68 < px0 - 8:
                _blend_panel(preview, tx, ty0, tx + 66, ty1, (34, 42, 60), 0.88)
                cv2.rectangle(preview, (tx, ty0), (tx + 66, ty1), (130, 165, 210), 1, cv2.LINE_AA)
                cv2.putText(preview, "Reset", (tx + 12, ty0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (235, 242, 252), 1, cv2.LINE_AA)
                self._hitboxes.append((tx, ty0, tx + 66, ty1, "game_reset"))

        # 1. Loud warning banner (centered left of Effects drawer) if audio/BlackHole has ANY issue
        if warning:
            avail = max(240, px0 - 30)
            bw = min(avail, 820)
            bx0 = 16 + (avail - bw) // 2
            _blend_panel(preview, bx0, 52, bx0 + bw, 92, (28, 28, 200), 0.88)
            cv2.rectangle(preview, (bx0, 52), (bx0 + bw, 92), (110, 110, 255), 2, cv2.LINE_AA)
            cv2.putText(
                preview,
                f"! {_ascii(warning)}",
                (bx0 + 16, 78),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.53,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        # 2. Top-right FaceTime-style Effects menu pill / popover
        # Header pill ("Effects [m]")
        _blend_panel(preview, px0, py0, px1, py0 + 36, (26, 28, 34), 0.80)
        cv2.rectangle(preview, (px0, py0), (px1, py0 + 36), (90, 96, 112), 1, cv2.LINE_AA)
        cv2.putText(preview, "Effects", (px0 + 14, py0 + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (245, 248, 255), 1, cv2.LINE_AA)
        state_lbl = "HIDE [m]" if self.menu_open else "SHOW [m]"
        cv2.putText(preview, state_lbl, (px1 - 88, py0 + 23), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (165, 180, 205), 1, cv2.LINE_AA)
        self._hitboxes.append((px0, py0, px1, py0 + 36, "toggle_menu"))

        if self.menu_open:
            rows = [
                ("saber", "[1] 3D Lightsaber"),
                ("face", "[2] Face Tracking"),
                ("affection", "[3] Affection FX"),
            ]
            row_h = 34
            panel_y0 = py0 + 42
            extra_g = 34 if game_info else 0
            panel_y1 = panel_y0 + len(rows) * row_h + 110 + extra_g
            _blend_panel(preview, px0, panel_y0, px1, panel_y1, (22, 24, 30), 0.78)
            cv2.rectangle(preview, (px0, panel_y0), (px1, panel_y1), (78, 84, 98), 1, cv2.LINE_AA)

            for idx, (key, label) in enumerate(rows):
                ry0 = panel_y0 + 6 + idx * row_h
                ry1 = ry0 + row_h - 4
                on = self.filters.get(key, False)
                if on:
                    _blend_panel(preview, px0 + 8, ry0, px1 - 8, ry1, (54, 74, 52), 0.55)
                cv2.putText(preview, label, (px0 + 16, ry0 + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 244, 250), 1, cv2.LINE_AA)
                pill_x0, pill_x1 = px1 - 62, px1 - 14
                pill_col = (70, 200, 110) if on else (82, 86, 94)
                cv2.rectangle(preview, (pill_x0, ry0 + 5), (pill_x1, ry1 - 5), pill_col, -1, cv2.LINE_AA)
                cv2.putText(
                    preview,
                    "ON" if on else "OFF",
                    (pill_x0 + (12 if on else 9), ry0 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.40,
                    (18, 22, 24) if on else (210, 215, 225),
                    1,
                    cv2.LINE_AA,
                )
                self._hitboxes.append((px0 + 8, ry0, px1 - 8, ry1, f"filter:{key}"))

            # Saber blade color selector row
            cy0 = panel_y0 + 6 + len(rows) * row_h + 2
            cy1 = cy0 + 28
            cv2.line(preview, (px0 + 10, cy0 - 2), (px1 - 10, cy0 - 2), (65, 70, 82), 1)
            cv2.putText(preview, f"[c] Blade: {blade_color.title()}", (px0 + 16, cy0 + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 232, 250), 1, cv2.LINE_AA)
            cv2.rectangle(preview, (px1 - 46, cy0 + 5), (px1 - 14, cy1 - 5), blade_bgr, -1, cv2.LINE_AA)
            cv2.rectangle(preview, (px1 - 46, cy0 + 5), (px1 - 14, cy1 - 5), (235, 240, 250), 1, cv2.LINE_AA)
            self._hitboxes.append((px0 + 8, cy0, px1 - 8, cy1, "cycle_color"))

            # Local monitor mode row: OFF / SFX ONLY / SELF+SFX
            mon_mode = getattr(audio, "monitor_mode", "off")
            hy0 = cy1 + 4
            hy1 = hy0 + 30
            cv2.line(preview, (px0 + 10, hy0 - 2), (px1 - 10, hy0 - 2), (65, 70, 82), 1)
            cv2.putText(preview, "[v] Hear", (px0 + 16, hy0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 235, 245), 1, cv2.LINE_AA)
            mon_meta = {
                "off": ("OFF", (82, 86, 94), (210, 215, 225), px1 - 62),
                "sfx": ("SFX ONLY", (70, 200, 110), (18, 22, 24), px1 - 92),
                "mic_sfx": ("SELF+SFX", (60, 185, 245), (18, 22, 24), px1 - 96),
            }
            m_txt, m_col, m_fg, mp_x0 = mon_meta.get(mon_mode, mon_meta["off"])
            cv2.rectangle(preview, (mp_x0, hy0 + 4), (px1 - 14, hy1 - 4), m_col, -1, cv2.LINE_AA)
            cv2.putText(preview, m_txt, (mp_x0 + 8, hy0 + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.39, m_fg, 1, cv2.LINE_AA)
            self._hitboxes.append((px0 + 8, hy0, px1 - 8, hy1, "cycle_monitor"))

            # Mic selector row in Effects drawer
            my0 = hy1 + 4
            my1 = my0 + 30
            mic_name = _ascii(audio.in_device_name)
            short_mic = mic_name[:20] + (".." if len(mic_name) > 20 else "")
            cv2.line(preview, (px0 + 10, my0 - 2), (px1 - 10, my0 - 2), (65, 70, 82), 1)
            cv2.putText(
                preview,
                f"[a] Mic: {short_mic}",
                (px0 + 14, my0 + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.44,
                (175, 215, 255),
                1,
                cv2.LINE_AA,
            )
            self._hitboxes.append((px0 + 8, my0, px1 - 8, my1, "cycle_mic"))

            if game_info:
                gy0 = my1 + 4
                gy1 = panel_y1 - 6
                cv2.line(preview, (px0 + 10, gy0 - 2), (px1 - 10, gy0 - 2), (65, 70, 82), 1)
                g_state = f"QR [{game_info.get('room', '----')}] ({game_info.get('players', 0)}p)"
                cv2.putText(
                    preview,
                    f"[q] Games: {g_state}",
                    (px0 + 14, gy0 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.43,
                    (110, 240, 255) if self.qr_open else (225, 210, 255),
                    1,
                    cv2.LINE_AA,
                )
                self._hitboxes.append((px0 + 8, gy0, px1 - 8, gy1, "toggle_qr"))

        # Side-by-side 2-Phone QR Invite card (preview only, never on virtual cam)
        if game_info and self.qr_open and game_info.get("qr_bgr") is not None:
            qr_g = game_info["qr_bgr"]
            qr_h = game_info.get("qr_host_bgr")
            qh, qw = qr_g.shape[:2]
            pad_x = 18
            gap_qr = 22 if qr_h is not None else 0
            card_w = max(250, pad_x * 2 + qw + (qw + gap_qr if qr_h is not None else 0))
            cx0, cy0 = 16, 62
            cx1, cy1 = min(w - 290, cx0 + card_w), cy0 + qh + 96
            _blend_panel(preview, cx0, cy0, cx1, cy1, (14, 22, 36), 0.92)
            cv2.rectangle(preview, (cx0, cy0), (cx1, cy1), (110, 230, 255), 1, cv2.LINE_AA)
            cv2.putText(
                preview,
                f"ROOM {game_info.get('room', '')} | 2-PHONE 1V1 QR",
                (cx0 + 14, cy0 + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (110, 235, 255),
                1,
                cv2.LINE_AA,
            )
            qy = cy0 + 48
            qx_g = cx0 + pad_x
            cv2.putText(preview, "HER PHONE (P1)", (qx_g, qy - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (205, 165, 255), 1, cv2.LINE_AA)
            if qy + qh < cy1 and qx_g + qw <= cx1:
                preview[qy:qy + qh, qx_g:qx_g + qw] = qr_g
            if qr_h is not None:
                qh2, qw2 = qr_h.shape[:2]
                qx_h = qx_g + qw + gap_qr
                cv2.putText(preview, "YOUR PHONE (P2)", (qx_h, qy - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (110, 240, 255), 1, cv2.LINE_AA)
                if qy + qh2 < cy1 and qx_h + qw2 <= cx1:
                    preview[qy:qy + qh2, qx_h:qx_h + qw2] = qr_h
            url_short = _ascii(str(game_info.get("url", "")))[:46]
            cv2.putText(
                preview,
                f"{url_short}   ([q] hide)",
                (cx0 + 14, cy1 - 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (210, 225, 240),
                1,
                cv2.LINE_AA,
            )

        # 3. Bottom HUD bar with live MIC + BlackHole meters & telemetry
        bar_y0 = h - 54
        _blend_panel(preview, 0, bar_y0, w, h, (16, 18, 22), 0.78)
        self._draw_meter(preview, 14, bar_y0 + 10, 150, 14, "MIC", _level_norm(audio.mic_peak), audio.mode == "blackhole")
        self._draw_meter(preview, 14, bar_y0 + 30, 150, 14, "BH ", _level_norm(audio.bh_peak), audio.mode == "blackhole")

        mon_mode = getattr(audio, "monitor_mode", "off")
        mon_tag = " | Hear: SFX" if mon_mode == "sfx" else (" | Hear: SELF+SFX" if mon_mode == "mic_sfx" else "")
        mic_info = _ascii(f"{audio.in_device_name} ({audio.in_sr // 1000}k) -> {audio.out_device_name}{mon_tag}")
        if len(mic_info) > 64:
            mic_info = mic_info[:61] + "..."
        cv2.putText(preview, mic_info, (226, bar_y0 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190, 210, 230), 1, cv2.LINE_AA)

        typing_game = bool(game_info and game_info.get("game") in ("word_duel", "rare_answer"))
        hud_right = (
            f"saber {int(saber_ext * 100)}% ({blade_color}) | {frame_ms:.1f}ms | "
            + ("1v1 on Phones | q QR | Q quit" if typing_game else "1-3 fx | c color | v hear | a mic | q QR | Q quit")
        )
        cv2.putText(preview, hud_right, (226, bar_y0 + 43), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 225, 235), 1, cv2.LINE_AA)

    @staticmethod
    def _draw_meter(img: np.ndarray, x: int, y: int, bar_w: int, bar_h: int, label: str, norm: float, active: bool) -> None:
        cv2.putText(img, label, (x, y + bar_h - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (225, 230, 240), 1, cv2.LINE_AA)
        bx0 = x + 38
        cv2.rectangle(img, (bx0, y), (bx0 + bar_w, y + bar_h), (48, 52, 60), -1)
        fill_w = int(bar_w * norm)
        if fill_w > 0:
            if not active:
                col = (90, 90, 220)
            elif norm > 0.85:
                col = (70, 90, 255)
            elif norm > 0.55:
                col = (60, 220, 245)
            else:
                col = (80, 220, 120)
            cv2.rectangle(img, (bx0, y), (bx0 + fill_w, y + bar_h), col, -1)
        cv2.rectangle(img, (bx0, y), (bx0 + bar_w, y + bar_h), (105, 112, 126), 1)
