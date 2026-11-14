"""Deterministic game engines & physics for Face Darts, Mouth Catch, 8-Ball Pool, Beer Pong, and Classic Darts 301."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 1. Face Darts (Stage 2B)
# ---------------------------------------------------------------------------
@dataclass
class ActiveDart:
    shooter: str
    start_x: float
    start_y: float
    target_x: float
    target_y: float
    elapsed: float = 0.0
    duration: float = 0.36
    color_bgr: tuple[int, int, int] = (95, 110, 255)


class FaceDartsMatch:
    """Best-of-3 rounds, 6 suction darts/round vs live open-palm block & head-dodge."""

    def __init__(self) -> None:
        self.best_of: int = 3
        self.darts_per_round: int = 6
        self.round_num: int = 1
        self.phase: str = "playing"  # "playing" | "round_over" | "match_over"
        self.darts_left: int = self.darts_per_round
        self.scores: dict[str, int] = {"guest": 0, "host": 0}
        self.round_wins: dict[str, int] = {"guest": 0, "host": 0}
        self.last_result: dict[str, Any] = {}
        self.loser_role: str = ""
        self.active: list[ActiveDart] = []
        self._events: list[dict[str, Any]] = []
        self._prev_nose: tuple[float, float] | None = None
        self._head_speed: float = 0.0

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    def reset_match(self) -> None:
        self.round_num = 1
        self.phase = "playing"
        self.darts_left = self.darts_per_round
        self.scores = {"guest": 0, "host": 0}
        self.round_wins = {"guest": 0, "host": 0}
        self.last_result = {}
        self.loser_role = ""
        self.active.clear()
        self._events.append({"kind": "clear_forfeit"})

    def next_round(self) -> None:
        if self.phase == "match_over":
            self.reset_match()
            return
        self.round_num += 1
        self.phase = "playing"
        self.darts_left = self.darts_per_round
        self.scores = {"guest": 0, "host": 0}
        self.active.clear()

    def throw_dart(self, role: str, aim_x: float, aim_y: float, power: float = 0.85) -> dict[str, Any]:
        if self.phase != "playing" or self.darts_left <= 0:
            return {"ok": False}
        tx = max(0.06, min(0.94, float(aim_x)))
        ty = max(0.06, min(0.94, float(aim_y)))
        dur = max(0.24, min(0.52, 0.46 - 0.16 * max(0.0, min(1.0, float(power)))))
        self.darts_left -= 1
        palette = [(80, 95, 255), (255, 195, 70), (140, 235, 95), (240, 105, 210)]
        col = palette[(self.darts_per_round - self.darts_left) % len(palette)]
        self.active.append(ActiveDart(shooter=role, start_x=0.5, start_y=0.92, target_x=tx, target_y=ty, duration=dur, color_bgr=col))
        self._events.append({"kind": "dart_throw"})
        return {"ok": True}

    def step(
        self,
        dt: float,
        face_state,
        open_palms: list[tuple[float, float, float]],
        w: int = 1280,
        h: int = 720,
    ) -> tuple[bool, list[dict[str, Any]]]:
        changed = False
        if face_state is not None:
            if self._prev_nose is not None and dt > 1e-4:
                dx = face_state.nose_px[0] - self._prev_nose[0]
                dy = face_state.nose_px[1] - self._prev_nose[1]
                inst_speed = math.hypot(dx, dy) / max(face_state.face_scale_px, 20.0) / dt
                self._head_speed = self._head_speed * 0.65 + inst_speed * 0.35
            self._prev_nose = face_state.nose_px
        else:
            self._prev_nose = None
            self._head_speed *= 0.8

        flying_out: list[dict[str, Any]] = []
        still_active: list[ActiveDart] = []
        for d in self.active:
            d.elapsed += dt
            u = min(1.0, d.elapsed / max(d.duration, 1e-3))
            cx = d.start_x + (d.target_x - d.start_x) * u
            arc = math.sin(u * math.pi) * 0.08
            cy = d.start_y + (d.target_y - d.start_y) * u - arc
            if u < 1.0:
                still_active.append(d)
                flying_out.append({"kind": "dart", "x": cx, "y": cy, "z": 1.0 - u, "color_bgr": d.color_bgr})
            else:
                self._resolve_impact(d, face_state, open_palms, w, h)
                changed = True
        self.active = still_active

        if self.phase == "playing" and self.darts_left == 0 and not self.active:
            self._finish_round()
            changed = True
        return changed, flying_out

    def _resolve_impact(self, d: ActiveDart, face_state, open_palms: list[tuple[float, float, float]], w: int, h: int) -> None:
        ix, iy = d.target_x, d.target_y
        # 1. Check open-palm block
        for px, py, pr in open_palms:
            if math.hypot(ix - px, iy - py) <= pr + 0.045:
                self.scores["host"] += 20
                self.last_result = {"outcome": "blocked", "pts": 20, "label": "PALM BLOCK! +20 DEF"}
                self._events.append({"kind": "dart_block", "x": ix, "y": iy})
                return

        # 2. Check live face rings
        if face_state is not None:
            sc = max(face_state.face_scale_px, 20.0)
            px_x, px_y = ix * w, iy * h
            dx_n = (px_x - face_state.nose_px[0]) / sc
            dy_n = (px_y - face_state.nose_px[1]) / sc
            r_n = math.hypot(dx_n, dy_n)
            if r_n <= 0.24:
                pts, label = 50, "BULLSEYE! +50"
            elif r_n <= 0.56:
                pts, label = 25, "INNER RING! +25"
            elif r_n <= 0.96:
                pts, label = 10, "OUTER RING +10"
            else:
                pts, label = 0, ""

            if pts > 0:
                self.scores["guest"] += pts
                self.last_result = {"outcome": "hit", "pts": pts, "label": label}
                self._events.append({
                    "kind": "dart_hit",
                    "pts": pts,
                    "label": label,
                    "dx_norm": dx_n,
                    "dy_norm": dy_n,
                    "fallback_xy": (px_x, px_y),
                    "color_bgr": d.color_bgr,
                })
                return

            if self._head_speed > 0.36:
                self.scores["host"] += 10
                self.last_result = {"outcome": "dodge", "pts": 10, "label": "HEAD DODGE! +10 DEF"}
                self._events.append({"kind": "dart_dodge"})
                return

        self.last_result = {"outcome": "miss", "pts": 0, "label": "MISS"}
        self._events.append({"kind": "dart_miss"})

    def _finish_round(self) -> None:
        if self.scores["guest"] >= self.scores["host"]:
            self.round_wins["guest"] += 1
        else:
            self.round_wins["host"] += 1
        needed = (self.best_of // 2) + 1
        if self.round_wins["guest"] >= needed or self.round_wins["host"] >= needed or self.round_num >= self.best_of:
            self.phase = "match_over"
            if self.round_wins["guest"] >= self.round_wins["host"]:
                self.loser_role = "host"
                self._events.append({"kind": "face_darts_crown", "loser": "host"})
            else:
                self.loser_role = "guest"
        else:
            self.phase = "round_over"

    def snapshot(self) -> dict[str, Any]:
        return {
            "roundNum": self.round_num,
            "bestOf": self.best_of,
            "phase": self.phase,
            "dartsLeft": self.darts_left,
            "scores": dict(self.scores),
            "roundWins": dict(self.round_wins),
            "lastResult": dict(self.last_result),
            "loserRole": self.loser_role,
        }


# ---------------------------------------------------------------------------
# 2. Mouth Catch (Stage 2B, Co-op)
# ---------------------------------------------------------------------------
@dataclass
class FlyingFood:
    kind: str
    start_x: float
    start_y: float
    target_x: float
    target_y: float
    elapsed: float = 0.0
    duration: float = 0.56
    color_bgr: tuple[int, int, int] = (170, 95, 255)


class MouthCatchMatch:
    """Co-op arcade food toss caught via FaceState.jaw_open > 0.28 at mouth_px."""

    FOODS = [
        ("donut", (185, 110, 255)),
        ("taco", (80, 210, 245)),
        ("berry", (165, 65, 225)),
        ("burger", (85, 165, 235)),
        ("sushi", (105, 130, 255)),
    ]

    def __init__(self) -> None:
        self.total_throws: int = 12
        self.throws_left: int = self.total_throws
        self.score: int = 0
        self.combo: int = 0
        self.best_combo: int = 0
        self.catches: int = 0
        self.splats: int = 0
        self.phase: str = "playing"
        self.last_result: dict[str, Any] = {}
        self.active: list[FlyingFood] = []
        self._food_idx: int = 0
        self._events: list[dict[str, Any]] = []

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    def reset_match(self) -> None:
        self.throws_left = self.total_throws
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.catches = 0
        self.splats = 0
        self.phase = "playing"
        self.last_result = {}
        self.active.clear()

    def throw_food(self, aim_x: float, aim_y: float, power: float = 0.75) -> dict[str, Any]:
        if self.phase != "playing" or self.throws_left <= 0:
            return {"ok": False}
        self.throws_left -= 1
        kind, col = self.FOODS[self._food_idx % len(self.FOODS)]
        self._food_idx += 1
        tx = max(0.08, min(0.92, float(aim_x)))
        ty = max(0.08, min(0.92, float(aim_y)))
        dur = max(0.42, min(0.75, 0.68 - 0.22 * max(0.0, min(1.0, float(power)))))
        self.active.append(FlyingFood(kind=kind, start_x=0.5, start_y=0.92, target_x=tx, target_y=ty, duration=dur, color_bgr=col))
        self._events.append({"kind": "dart_throw"})
        return {"ok": True, "food": kind}

    def step(self, dt: float, face_state, w: int = 1280, h: int = 720) -> tuple[bool, list[dict[str, Any]]]:
        changed = False
        flying_out: list[dict[str, Any]] = []
        still: list[FlyingFood] = []
        for f in self.active:
            f.elapsed += dt
            u = min(1.0, f.elapsed / max(f.duration, 1e-3))
            cx = f.start_x + (f.target_x - f.start_x) * u
            cy = f.start_y + (f.target_y - f.start_y) * u - math.sin(u * math.pi) * 0.14
            if u < 1.0:
                still.append(f)
                flying_out.append({"kind": f.kind, "x": cx, "y": cy, "z": 1.0 - u, "color_bgr": f.color_bgr})
            else:
                self._resolve(f, face_state, w, h)
                changed = True
        self.active = still

        if self.phase == "playing" and self.throws_left == 0 and not self.active:
            self.phase = "finished"
            changed = True
        return changed, flying_out

    def _resolve(self, f: FlyingFood, face_state, w: int, h: int) -> None:
        px_x, px_y = f.target_x * w, f.target_y * h
        caught = False
        if face_state is not None:
            sc = max(face_state.face_scale_px, 20.0)
            dist = math.hypot(px_x - face_state.mouth_px[0], px_y - face_state.mouth_px[1])
            if dist <= sc * 0.50 and face_state.jaw_open > 0.28:
                caught = True

        if caught:
            self.combo += 1
            self.best_combo = max(self.best_combo, self.combo)
            self.catches += 1
            pts = 10 * min(5, self.combo)
            self.score += pts
            self.last_result = {"outcome": "catch", "food": f.kind, "pts": pts, "combo": self.combo}
            self._events.append({"kind": "mouth_catch", "food": f.kind, "pts": pts, "combo": self.combo})
        else:
            self.combo = 0
            self.splats += 1
            dx_n = ((px_x - face_state.nose_px[0]) / max(face_state.face_scale_px, 20.0)) if face_state else 0.0
            dy_n = ((px_y - face_state.nose_px[1]) / max(face_state.face_scale_px, 20.0)) if face_state else 0.0
            self.last_result = {"outcome": "splat", "food": f.kind, "pts": 0, "combo": 0}
            self._events.append({
                "kind": "mouth_splat",
                "food": f.kind,
                "dx_norm": dx_n,
                "dy_norm": dy_n,
                "fallback_xy": (px_x, px_y),
                "color_bgr": f.color_bgr,
            })

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "throwsLeft": self.throws_left,
            "totalThrows": self.total_throws,
            "score": self.score,
            "combo": self.combo,
            "bestCombo": self.best_combo,
            "catches": self.catches,
            "splats": self.splats,
            "lastResult": dict(self.last_result),
        }


# ---------------------------------------------------------------------------
# 3. 8-Ball Pool (Stage 2C)
# ---------------------------------------------------------------------------
@dataclass
class PoolBall:
    num: int  # 0=cue, 1-7=solid, 8=eight, 9-15=stripe
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    potted: bool = False


class PoolMatch:
    """Deterministic GamePigeon-faithful 8-Ball Pool on [-1.0, 1.0] x [-0.5, 0.5] table."""

    BALL_R = 0.028
    POCKETS = [
        (-0.965, -0.465, 0.072),
        (0.0, -0.495, 0.066),
        (0.965, -0.465, 0.072),
        (-0.965, 0.465, 0.072),
        (0.0, 0.495, 0.066),
        (0.965, 0.465, 0.072),
    ]

    def __init__(self) -> None:
        self.balls: list[PoolBall] = []
        self.turn: str = "guest"
        self.phase: str = "aiming"  # "aiming" | "moving" | "ball_in_hand" | "finished"
        self.groups: dict[str, str | None] = {"guest": None, "host": None}
        self.winner: str | None = None
        self.status_msg: str = "Her's turn — Break shot!"
        self.practice_mode: bool = False
        self._first_contact: int | None = None
        self._potted_this_turn: list[int] = []
        self._rail_hit: bool = False
        self._events: list[dict[str, Any]] = []
        self.reset_rack()

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    def reset_rack(self) -> None:
        r = self.BALL_R
        row_dx = r * 1.76
        col_dy = r * 2.04
        rack_x0 = 0.46
        solids = [1, 2, 3, 4, 5, 6, 7]
        stripes = [9, 10, 11, 12, 13, 14, 15]
        # Traditional corner contrast + 8-ball in center of row 3
        layout = [
            solids[0],
            stripes[0], solids[1],
            stripes[1], 8, solids[2],
            solids[3], stripes[2], solids[4], stripes[3],
            stripes[4], solids[5], stripes[5], solids[6], stripes[6],
        ]
        balls = [PoolBall(num=0, x=-0.52, y=0.0)]
        idx = 0
        for row in range(5):
            rx = rack_x0 + row * row_dx
            y_start = -row * col_dy * 0.5
            for col in range(row + 1):
                balls.append(PoolBall(num=layout[idx], x=rx, y=y_start + col * col_dy))
                idx += 1
        self.balls = balls
        self.turn = "guest"
        self.phase = "aiming"
        self.groups = {"guest": None, "host": None}
        self.winner = None
        self.status_msg = "Her's turn — Break shot!"
        self._first_contact = None
        self._potted_this_turn = []
        self._rail_hit = False

    def shoot(self, role: str, angle: float, power: float, spin_x: float = 0.0, spin_y: float = 0.0) -> dict[str, Any]:
        if self.phase not in ("aiming", "ball_in_hand"):
            return {"ok": False}
        if not self.practice_mode and role != self.turn:
            return {"ok": False}
        cue = self.balls[0]
        if cue.potted:
            cue.potted = False
            cue.x, cue.y = -0.52, 0.0
        spd = max(0.28, min(5.4, float(power) * 5.4))
        cue.vx = math.cos(angle) * spd
        cue.vy = math.sin(angle) * spd
        self._spin_y = max(-1.0, min(1.0, float(spin_y)))
        self._spin_applied = False
        self._first_contact = None
        self._potted_this_turn = []
        self._rail_hit = False
        self.phase = "moving"
        self._events.append({"kind": "pool_hit", "gain": min(1.0, 0.35 + power * 0.65)})
        return {"ok": True}

    def place_cue(self, role: str, x: float, y: float) -> dict[str, Any]:
        if self.phase != "ball_in_hand":
            return {"ok": False}
        if not self.practice_mode and role != self.turn:
            return {"ok": False}
        cx = max(-0.96, min(0.96, float(x)))
        cy = max(-0.46, min(0.46, float(y)))
        for b in self.balls[1:]:
            if not b.potted and math.hypot(cx - b.x, cy - b.y) < self.BALL_R * 2.08:
                return {"ok": False, "error": "Overlap"}
        cue = self.balls[0]
        cue.potted = False
        cue.x, cue.y = cx, cy
        cue.vx = cue.vy = 0.0
        self.phase = "aiming"
        return {"ok": True}

    def step(self, dt: float) -> bool:
        if self.phase != "moving":
            return False
        # 240 Hz substeps prevent tunneling on full-power break shots
        substeps = max(6, int(math.ceil(dt / 0.004)))
        sdt = dt / substeps
        r = self.BALL_R
        min_d = r * 2.0
        max_x, max_y = 1.0 - r, 0.5 - r

        for _ in range(substeps):
            for b in self.balls:
                if b.potted:
                    continue
                b.x += b.vx * sdt
                b.y += b.vy * sdt

                # Two-stage GamePigeon cloth friction: fast sliding phase -> smooth rolling phase
                spd = math.hypot(b.vx, b.vy)
                if spd > 0.007:
                    if spd > 0.85:
                        drag = 0.992 ** (sdt * 60.0)
                        new_spd = max(0.0, spd * drag - 0.62 * sdt)
                    else:
                        drag = 0.995 ** (sdt * 60.0)
                        new_spd = max(0.0, spd * drag - 0.34 * sdt)
                    if new_spd < 0.007:
                        new_spd = 0.0
                    scale = new_spd / spd
                    b.vx *= scale
                    b.vy *= scale
                else:
                    b.vx = b.vy = 0.0

                # Pocket-jaw gravity funneling & pocket capture
                potted_now = False
                for px, py, pr in self.POCKETS:
                    dxp = px - b.x
                    dyp = py - b.y
                    dp = math.hypot(dxp, dyp)
                    if dp <= pr:
                        b.potted = True
                        b.vx = b.vy = 0.0
                        self._potted_this_turn.append(b.num)
                        if b.num != 0:
                            self._events.append({"kind": "pool_pot", "ball": b.num})
                        potted_now = True
                        break
                    if dp < pr * 1.45 and dp > 1e-6:
                        pull = 1.65 * sdt / dp
                        b.vx += dxp * pull
                        b.vy += dyp * pull
                if potted_now:
                    continue

                # Cushions (GamePigeon rail restitution 0.84)
                if b.x < -max_x:
                    b.x = -max_x
                    b.vx = abs(b.vx) * 0.84
                    self._rail_hit = True
                elif b.x > max_x:
                    b.x = max_x
                    b.vx = -abs(b.vx) * 0.84
                    self._rail_hit = True
                if b.y < -max_y:
                    b.y = -max_y
                    b.vy = abs(b.vy) * 0.84
                    self._rail_hit = True
                elif b.y > max_y:
                    b.y = max_y
                    b.vy = -abs(b.vy) * 0.84
                    self._rail_hit = True

            # Pairwise elastic ball collisions (e = 0.985 + 0.003 throw friction)
            n = len(self.balls)
            step_hit_gain = 0.0
            for i in range(n):
                bi = self.balls[i]
                if bi.potted:
                    continue
                for j in range(i + 1, n):
                    bj = self.balls[j]
                    if bj.potted:
                        continue
                    dx = bj.x - bi.x
                    dy = bj.y - bi.y
                    dist = math.hypot(dx, dy)
                    if dist < min_d and dist > 1e-9:
                        nx, ny = dx / dist, dy / dist
                        overlap = 0.5 * (min_d - dist)
                        bi.x -= nx * overlap
                        bi.y -= ny * overlap
                        bj.x += nx * overlap
                        bj.y += ny * overlap
                        dvx = bi.vx - bj.vx
                        dvy = bi.vy - bj.vy
                        rel = dvx * nx + dvy * ny
                        if rel > 0.0:
                            imp = rel * 0.9925  # (1 + 0.985) / 2
                            bi.vx -= imp * nx
                            bi.vy -= imp * ny
                            bj.vx += imp * nx
                            bj.vy += imp * ny
                            tx, ty = -ny, nx
                            trel = dvx * tx + dvy * ty
                            timp = trel * 0.003
                            bi.vx -= timp * tx
                            bi.vy -= timp * ty
                            bj.vx += timp * tx
                            bj.vy += timp * ty
                            if rel > 0.06:
                                step_hit_gain = max(step_hit_gain, min(1.0, rel / 2.2))
                            if bi.num == 0 and self._first_contact is None:
                                self._first_contact = bj.num
                            elif bj.num == 0 and self._first_contact is None:
                                self._first_contact = bi.num
                            if (bi.num == 0 or bj.num == 0) and not getattr(self, "_spin_applied", True):
                                self._spin_applied = True
                                cue = bi if bi.num == 0 else bj
                                spin_y = getattr(self, "_spin_y", 0.0)
                                cue.vx += nx * spin_y * 0.35
                                cue.vy += ny * spin_y * 0.35
            if step_hit_gain > 0.12 and len(self._events) < 8:
                self._events.append({"kind": "pool_hit", "gain": round(step_hit_gain, 2)})

        if all(b.potted or (abs(b.vx) < 0.007 and abs(b.vy) < 0.007) for b in self.balls):
            for b in self.balls:
                b.vx = b.vy = 0.0
            self._finish_turn()
        return True

    @staticmethod
    def _group_of(num: int) -> str | None:
        if 1 <= num <= 7:
            return "solids"
        if 9 <= num <= 15:
            return "stripes"
        return None

    def _group_remaining(self, group: str) -> int:
        if group == "solids":
            return sum(1 for b in self.balls if 1 <= b.num <= 7 and not b.potted)
        return sum(1 for b in self.balls if 9 <= b.num <= 15 and not b.potted)

    def _finish_turn(self) -> None:
        shooter = self.turn
        other = "host" if shooter == "guest" else "guest"
        scratched = 0 in self._potted_this_turn
        potted_8 = 8 in self._potted_this_turn
        my_group = self.groups[shooter]

        if potted_8:
            cleared = my_group is not None and self._group_remaining(my_group) == 0
            if cleared and not scratched:
                self.winner = shooter
                self.phase = "finished"
                self.status_msg = f"{'Her' if shooter == 'guest' else 'Him'} sinks the 8-ball cleanly!"
                self._events.append({"kind": "pool_win", "winner": shooter})
            else:
                self.winner = other
                self.phase = "finished"
                self.status_msg = "Early 8-ball / scratch foul — frame lost!"
            return

        foul = scratched or (self._first_contact is None) or (not self._rail_hit and not self._potted_this_turn)
        if my_group is not None and self._first_contact is not None:
            if self._group_remaining(my_group) > 0 and self._group_of(self._first_contact) != my_group:
                foul = True
            elif self._group_remaining(my_group) == 0 and self._first_contact != 8:
                foul = True

        # Assign group on first non-foul pot when open
        keep_turn = False
        if not foul and self._potted_this_turn:
            if my_group is None:
                first_grp = next((self._group_of(n) for n in self._potted_this_turn if self._group_of(n)), None)
                if first_grp:
                    self.groups[shooter] = first_grp
                    self.groups[other] = "stripes" if first_grp == "solids" else "solids"
                    my_group = first_grp
                    keep_turn = True
            else:
                if any(self._group_of(n) == my_group for n in self._potted_this_turn):
                    keep_turn = True

        if foul:
            self.balls[0].potted = False
            self.turn = other
            self.phase = "ball_in_hand"
            self.status_msg = "FOUL! Ball in hand" + (" (+Clown Nose)" if scratched else "")
            if scratched:
                self._events.append({"kind": "pool_scratch"})
        else:
            if not keep_turn:
                self.turn = other
            self.phase = "aiming"
            self.status_msg = f"{'Her' if self.turn == 'guest' else 'Him'}'s turn"

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "turn": self.turn,
            "groups": dict(self.groups),
            "winner": self.winner,
            "status": self.status_msg,
            "practiceMode": self.practice_mode,
            "balls": [
                {
                    "n": b.num,
                    "x": round(b.x, 4),
                    "y": round(b.y, 4),
                    "vx": round(b.vx, 4),
                    "vy": round(b.vy, 4),
                    "potted": b.potted,
                }
                for b in self.balls
            ],
        }


# ---------------------------------------------------------------------------
# 4. Beer Pong (Stage 2C)
# ---------------------------------------------------------------------------
@dataclass
class PongBall:
    shooter: str
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    bounced: bool = False
    table_bounces: int = 0
    rim_bounces: int = 0
    deflected: bool = False


class BeerPongMatch:
    """3D parabolic Beer Pong with equilateral cups, lively bounce physics, 3-shot +1-on-make turns."""

    def __init__(self) -> None:
        self.cup_count: int = 6
        self.rules: dict[str, bool] = {
            "bounceDouble": True,
            "redemption": True,
            "heatingUp": True,
            "rerack": True,
        }
        self.turn: str = "guest"
        self.shots_left: int = 3
        self.practice_mode: bool = False
        self.phase: str = "playing"  # "playing" | "redemption" | "finished"
        self.winner: str | None = None
        self.status_msg: str = "Her's turn (3 shots — swipe fast!)"
        self.streaks: dict[str, int] = {"guest": 0, "host": 0}
        self.reracked: dict[str, bool] = {"guest": False, "host": False}
        self.racks: dict[str, list[dict[str, Any]]] = {"guest": [], "host": []}
        self.balls: list[PongBall] = []
        self._events: list[dict[str, Any]] = []
        self.reset_game(6)

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    @staticmethod
    def _pyramid_coords(count: int) -> list[tuple[float, float]]:
        # Cup topR=0.056 (diameter 0.112). Equilateral spacing 0.120 eliminates cup clipping.
        rows = 3 if count <= 6 else 4
        dx = 0.120
        dz = dx * math.sqrt(3.0) * 0.5  # ~0.1039
        z_base = 0.65 if count <= 6 else 0.58
        pts: list[tuple[float, float]] = []
        for r in range(rows):
            z = z_base + r * dz
            x0 = -r * dx * 0.5
            for c in range(r + 1):
                pts.append((x0 + c * dx, z))
        return pts[:count]

    def reset_game(self, cup_count: int = 6) -> None:
        self.cup_count = 10 if int(cup_count) >= 10 else 6
        self.turn = "guest"
        self.shots_left = 3
        self.phase = "playing"
        self.winner = None
        self.status_msg = "Her's turn (3 shots — swipe fast!)"
        self.streaks = {"guest": 0, "host": 0}
        self.reracked = {"guest": False, "host": False}
        self.balls.clear()
        for side in ("guest", "host"):
            self.racks[side] = [
                {"id": i, "x": x, "z": z, "alive": True, "wobble": 0.0}
                for i, (x, z) in enumerate(self._pyramid_coords(self.cup_count))
            ]

    def set_rule(self, key: str, val: bool) -> None:
        if key in self.rules:
            self.rules[key] = bool(val)

    def set_practice_mode(self, enabled: bool) -> None:
        # Strict 1v1 only: always alternate between Her (guest) and Him (host)
        self.practice_mode = False
        if not self.balls:
            self.status_msg = f"{'Her' if self.turn == 'guest' else 'Him'}'s turn ({self.shots_left} shots)"

    def rerack(self, role: str) -> bool:
        shooter = self.turn if self.practice_mode else role
        target_side = "host" if shooter == "guest" else "guest"
        if not self.rules["rerack"] or self.reracked[shooter]:
            return False
        alive = [c for c in self.racks[target_side] if c["alive"]]
        if len(alive) not in (1, 2, 3, 4):
            return False
        if len(alive) == 3:
            pts = [(-0.060, 0.72), (0.060, 0.72), (0.0, 0.824)]
        elif len(alive) == 2:
            pts = [(0.0, 0.71), (0.0, 0.835)]
        elif len(alive) == 4:
            pts = [(-0.060, 0.70), (0.060, 0.70), (-0.060, 0.825), (0.060, 0.825)]
        else:
            pts = [(0.0, 0.78)]
        for cup, (x, z) in zip(alive, pts):
            cup["x"], cup["z"] = x, z
        self.reracked[shooter] = True
        self.status_msg = "Rerack!"
        return True

    def throw(self, role: str, aim_x: float, power: float, loft: float = 0.55) -> dict[str, Any]:
        if self.phase == "finished" or self.balls:
            return {"ok": False}
        if not self.practice_mode and role != self.turn:
            return {"ok": False}
        if not self.practice_mode and self.shots_left <= 0:
            return {"ok": False}
        shooter = self.turn if self.practice_mode else role
        self.shots_left = max(0, self.shots_left - 1)
        # GamePigeon BeerView crisp 0.64s parabolic arc tuned to z=[0.58..0.90] racks
        ax = max(-0.55, min(0.55, float(aim_x)))
        p = max(0.12, min(1.0, float(power)))
        arc = max(0.0, min(1.0, float(loft)))
        g = 6.2
        t_flight = 0.56 + 0.14 * arc  # ~0.637s at default arc=0.55
        x0, y0, z0 = 0.0, 0.24, 0.04
        target_z = 0.34 + p * 0.70  # p=0.45..0.75 hits cup rack; p<0.33 bounces before rack
        vx = (ax * 0.62) / t_flight
        vz = (target_z - z0) / t_flight
        vy = (0.145 - y0 + 0.5 * g * (t_flight ** 2)) / t_flight
        self.balls.append(PongBall(shooter=shooter, x=x0, y=y0, z=z0, vx=vx, vy=vy, vz=vz))
        self._events.append({"kind": "dart_throw"})
        return {"ok": True}

    def swat_bounce(self) -> bool:
        swatted = False
        for b in self.balls:
            if b.bounced and not b.deflected:
                b.deflected = True
                b.vx += 0.9
                b.vy = 0.65
                swatted = True
        if swatted:
            self.status_msg = "SWATTED!"
            self._events.append({"kind": "dart_block"})
        return swatted

    def step(self, dt: float) -> bool:
        any_wobble = False
        for side in ("guest", "host"):
            for c in self.racks[side]:
                wob = float(c.get("wobble", 0.0))
                if wob > 0.0:
                    c["wobble"] = max(0.0, round(wob - dt * 3.8, 3))
                    any_wobble = True

        if not self.balls:
            return any_wobble

        g = -6.2
        ball_r = 0.017
        cup_top_r = 0.056
        cup_bot_r = 0.039
        rim_y = 0.145
        open_r = cup_top_r * 0.84  # ~0.047 clean drop opening inside plastic lip
        substeps = max(4, int(math.ceil(dt / 0.006)))
        sub_dt = dt / substeps
        air_drag = 0.997 ** (sub_dt * 60.0)
        remaining: list[PongBall] = []

        for b in self.balls:
            target_side = "host" if b.shooter == "guest" else "guest"
            sunk = False
            missed = False

            for _ in range(substeps):
                prev_y = b.y
                b.x += b.vx * sub_dt
                b.y += b.vy * sub_dt
                b.z += b.vz * sub_dt
                b.vx *= air_drag
                b.vz *= air_drag
                b.vy += g * sub_dt

                # Table surface bounce: allow 1 pre-cup table bounce (bounceDouble); resolve 2nd bounce or back-court hit immediately
                if b.y <= ball_r and b.vy < 0.0:
                    if b.table_bounces == 0 and b.z <= 0.78 and abs(b.vy) >= 0.35:
                        b.y = ball_r
                        b.vy = abs(b.vy) * 0.78
                        b.vx *= 0.94
                        b.vz *= 0.94
                        b.bounced = True
                        b.table_bounces = 1
                        self._events.append({"kind": "pong_table_bounce", "x": round(b.x, 3), "z": round(b.z, 3)})
                    else:
                        self._on_miss(b)
                        missed = True
                        break

                if b.deflected:
                    continue

                # Standing 3D cup collisions (inner sink, inner rim funnel, lip bounce, tapered outer wall)
                for cup in self.racks[target_side]:
                    if not cup["alive"]:
                        continue
                    dx = b.x - cup["x"]
                    dz = b.z - cup["z"]
                    d = math.hypot(dx, dz)

                    # 1. Clean interior drop-in through cup opening
                    if d <= open_r and ((prev_y >= rim_y - 0.010 >= b.y) or (0.04 <= b.y <= rim_y and d <= open_r * 0.92)):
                        self._on_sink(b, target_side, cup)
                        sunk = True
                        break

                    # 2. Inner rim funneling (gentle lip grabs slightly off-center descending shots like GamePigeon)
                    if b.vy < 0.0 and 0.06 <= b.y <= (rim_y + ball_r + 0.02) and open_r < d <= cup_top_r * 1.15:
                        if b.rim_bounces == 0 and (abs(b.vx) + abs(b.vz)) < 1.85 and d > 1e-5:
                            pull = 0.85 * sub_dt / d
                            b.vx -= dx * pull
                            b.vz -= dz * pull
                            b.vx *= 0.92
                            b.vz *= 0.92

                    # 3. Top plastic rim torus bounce
                    if (rim_y - 0.018) <= b.y <= (rim_y + ball_r + 0.008) and (open_r - 0.002) <= d <= (cup_top_r + ball_r):
                        rim_center_r = 0.5 * (open_r + cup_top_r)
                        inv_d = 1.0 / max(d, 1e-5)
                        rx, rz = dx * inv_d * rim_center_r, dz * inv_d * rim_center_r
                        nx, ny, nz = b.x - (cup["x"] + rx), b.y - rim_y, b.z - (cup["z"] + rz)
                        nlen = math.hypot(math.hypot(nx, nz), ny)
                        if nlen > 1e-5:
                            nx, ny, nz = nx / nlen, ny / nlen, nz / nlen
                            vn = b.vx * nx + b.vy * ny + b.vz * nz
                            if vn < 0.0:
                                rest = 0.45 if b.rim_bounces >= 1 else 0.58
                                b.vx -= (1.0 + rest) * vn * nx
                                b.vy -= (1.0 + rest) * vn * ny
                                b.vz -= (1.0 + rest) * vn * nz
                                b.rim_bounces += 1
                                push = (0.008 + ball_r) - nlen + 0.002
                                if push > 0.0:
                                    b.x += nx * push
                                    b.y += ny * push
                                    b.z += nz * push
                                cup["wobble"] = 1.0
                                self.status_msg = "RIM CLINK!"
                                self._events.append({"kind": "pong_rim", "cupId": cup["id"], "x": round(b.x, 3), "z": round(b.z, 3)})
                                break

                    # 4. Tapered outer plastic wall deflection (0 < y < rim_y)
                    if 0.0 <= b.y < (rim_y - 0.014):
                        frac = max(0.0, min(1.0, b.y / rim_y))
                        r_wall = cup_bot_r + (cup_top_r - cup_bot_r) * frac
                        if d < (r_wall + ball_r) and d > 1e-5:
                            inv_d = 1.0 / d
                            nx, ny, nz = dx * inv_d * 0.96, -0.22, dz * inv_d * 0.96
                            vn = b.vx * nx + b.vy * ny + b.vz * nz
                            if vn < 0.0:
                                rest = 0.72
                                b.vx -= (1.0 + rest) * vn * nx
                                b.vy -= (1.0 + rest) * vn * ny
                                b.vz -= (1.0 + rest) * vn * nz
                                b.table_bounces = max(1, b.table_bounces)
                                push = (r_wall + ball_r) - d + 0.003
                                b.x += dx * inv_d * push
                                b.z += dz * inv_d * push
                                cup["wobble"] = 0.85
                                self.status_msg = "CUP DEFLECT!"
                                self._events.append({"kind": "pong_rim", "cupId": cup["id"], "x": round(b.x, 3), "z": round(b.z, 3)})
                                break

                if sunk or missed:
                    break

                if b.z > 1.12 or b.z < -0.45 or abs(b.x) > 0.72 or b.y < -0.55:
                    self._on_miss(b)
                    missed = True
                    break

            if not sunk and not missed:
                remaining.append(b)

        self.balls = remaining
        return True

    def _on_sink(self, b: PongBall, target_side: str, cup: dict[str, Any]) -> None:
        cup["alive"] = False
        cups_removed = 1
        if b.bounced and self.rules["bounceDouble"]:
            extra = next((c for c in self.racks[target_side] if c["alive"]), None)
            if extra:
                extra["alive"] = False
                cups_removed = 2
        self.streaks[b.shooter] += 1
        # Reward every made shot with +1 shot back (so making all in a row stays infinite)
        self.shots_left += 1
        self._events.append({"kind": "pong_cup", "cups": cups_removed})
        alive_left = sum(1 for c in self.racks[target_side] if c["alive"])
        if alive_left == 0:
            if self.rules["redemption"] and not self.practice_mode and self.phase == "playing":
                self.phase = "redemption"
                self.turn = target_side
                self.shots_left = 1
                self.status_msg = "REDEMPTION SHOT!"
            else:
                self.winner = b.shooter
                self.phase = "finished"
                self.shots_left = 0
                self.status_msg = f"RACK CLEARED! Streak {self.streaks[b.shooter]} — hit Reset!" if self.practice_mode else "CUPS CLEARED! WIN!"
                self._events.append({"kind": "pool_win", "winner": b.shooter})
        else:
            fire = " · HEATING UP!" if (self.rules["heatingUp"] and self.streaks[b.shooter] >= 2) else ""
            self.status_msg = f"SPLASH! {'2 CUPS!' if cups_removed == 2 else 'CUP!'} +1 shot ({self.shots_left} left){fire}"

    def _on_miss(self, b: PongBall) -> None:
        self.streaks[b.shooter] = 0
        other = "host" if b.shooter == "guest" else "guest"
        if self.phase == "redemption":
            self.winner = other
            self.phase = "finished"
            self.shots_left = 0
            self.status_msg = "Redemption missed — Game Over!"
            self._events.append({"kind": "pool_win", "winner": other})
        elif self.shots_left <= 0:
            self.shots_left = 3
            if self.practice_mode:
                self.turn = b.shooter
                self.status_msg = "New round — 3 shots!"
            else:
                self.turn = other
                self.status_msg = f"{'Her' if self.turn == 'guest' else 'Him'}'s turn (3 shots)"
        else:
            s = "shot" if self.shots_left == 1 else "shots"
            self.status_msg = f"Miss — {self.shots_left} {s} left"

    def snapshot(self) -> dict[str, Any]:
        return {
            "cupCount": self.cup_count,
            "rules": dict(self.rules),
            "practiceMode": self.practice_mode,
            "phase": self.phase,
            "turn": self.turn,
            "shotsLeft": self.shots_left,
            "winner": self.winner,
            "status": self.status_msg,
            "streaks": dict(self.streaks),
            "racks": self.racks,
            "balls": [
                {
                    "x": round(b.x, 4),
                    "y": round(b.y, 4),
                    "z": round(b.z, 4),
                    "vx": round(b.vx, 4),
                    "vy": round(b.vy, 4),
                    "vz": round(b.vz, 4),
                    "bounced": b.bounced,
                }
                for b in self.balls
            ],
        }


# ---------------------------------------------------------------------------
# 5. Classic Darts 301-lite (Stage 2C)
# ---------------------------------------------------------------------------
class ClassicDartsMatch:
    """Standard 20-sector 301-lite with 3 darts/turn and straight or double-out checkout."""

    SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]

    def __init__(self) -> None:
        self.start_score: int = 301
        self.double_out: bool = False
        self.scores: dict[str, int] = {"guest": 301, "host": 301}
        self.turn: str = "guest"
        self.darts_left: int = 3
        self.turn_start_score: int = 301
        self.phase: str = "playing"
        self.winner: str | None = None
        self.hits_this_turn: list[dict[str, Any]] = []
        self.last_throw: dict[str, Any] = {}
        self.status_msg: str = "Her's turn — Throw dart 1"
        self._events: list[dict[str, Any]] = []

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    def reset_game(self, double_out: bool | None = None) -> None:
        if double_out is not None:
            self.double_out = bool(double_out)
        self.scores = {"guest": self.start_score, "host": self.start_score}
        self.turn = "guest"
        self.darts_left = 3
        self.turn_start_score = self.start_score
        self.phase = "playing"
        self.winner = None
        self.hits_this_turn = []
        self.last_throw = {}
        self.status_msg = "Her's turn — Throw dart 1"

    @classmethod
    def score_coord(cls, nx: float, ny: float) -> tuple[int, str, bool]:
        """Score board coordinate normalized around center (0, 0), radius 1.0 = outer double edge."""
        r = math.hypot(nx, ny)
        if r <= 0.055:
            return 50, "BULL 50", True
        if r <= 0.12:
            return 25, "OUTER BULL 25", False
        if r > 1.0:
            return 0, "MISS", False
        # Top is 0 deg -> clockwise sector 20 centered at +/-9 deg
        deg = (math.degrees(math.atan2(nx, -ny)) + 360.0 + 9.0) % 360.0
        sector = cls.SECTORS[int(deg // 18.0) % 20]
        if 0.56 <= r <= 0.64:
            return sector * 3, f"T{sector}", False
        if 0.91 <= r <= 1.0:
            return sector * 2, f"D{sector}", True
        return sector, f"{sector}", False

    def throw(self, role: str, nx: float, ny: float, wobble: float = 0.02) -> dict[str, Any]:
        if self.phase != "playing" or role != self.turn:
            return {"ok": False}
        jitter_x = random.gauss(0.0, max(0.0, min(0.12, wobble)))
        jitter_y = random.gauss(0.0, max(0.0, min(0.12, wobble)))
        x = max(-1.15, min(1.15, float(nx) + jitter_x))
        y = max(-1.15, min(1.15, float(ny) + jitter_y))
        pts, label, is_double = self.score_coord(x, y)
        cur_p = self.turn
        new_score = self.scores[cur_p] - pts
        bust = new_score < 0 or (self.double_out and new_score == 1) or (self.double_out and new_score == 0 and not is_double)

        self.last_throw = {"x": round(x, 3), "y": round(y, 3), "pts": pts, "label": label, "bust": bust}
        self.hits_this_turn.append(self.last_throw)
        self.darts_left -= 1

        if bust:
            self.scores[cur_p] = self.turn_start_score
            self.status_msg = f"BUST! ({label}) Back to {self.turn_start_score}"
            self._events.append({"kind": "krill_miss"})
            self._advance_turn()
        elif new_score == 0:
            self.scores[cur_p] = 0
            self.phase = "finished"
            self.winner = cur_p
            self.status_msg = f"CHECKOUT! {label}"
            self._events.append({"kind": "pool_win", "winner": cur_p})
        else:
            self.scores[cur_p] = new_score
            self.status_msg = f"{label} (-{pts}) -> {new_score}"
            if pts >= 50 or label.startswith("T"):
                self._events.append({"kind": "dart_bullseye", "label": label, "pts": pts})
            else:
                self._events.append({"kind": "dart_hit_simple"})
            if self.darts_left <= 0:
                self._advance_turn()
        return {"ok": True, **self.last_throw}

    def _advance_turn(self) -> None:
        self.turn = "host" if self.turn == "guest" else "guest"
        self.darts_left = 3
        self.turn_start_score = self.scores[self.turn]
        self.hits_this_turn = []
        self.status_msg = f"{'Her' if self.turn == 'guest' else 'Him'}'s turn — 3 darts ({self.turn_start_score} left)"

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "turn": self.turn,
            "dartsLeft": self.darts_left,
            "doubleOut": self.double_out,
            "scores": dict(self.scores),
            "winner": self.winner,
            "status": self.status_msg,
            "hitsThisTurn": list(self.hits_this_turn),
            "lastThrow": dict(self.last_throw),
        }
