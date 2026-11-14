"""Unified authoritative multiplayer game coordinator (Stage 2B, 2C, Stage 3)."""
from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Any

from effect_bus import EffectBus, FlyingSprite
from game_server import GameServer
from krillion_engine import KrillionMatch, StreaksStore, WordDuelMatch
from table_physics import (
    BeerPongMatch,
    ClassicDartsMatch,
    FaceDartsMatch,
    MouthCatchMatch,
    PoolMatch,
)

ALL_GAMES = (
    "lobby",
    "rare_answer",
    "face_darts",
    "mouth_catch",
    "pool",
    "beer_pong",
    "classic_darts",
    "word_duel",
)


class GamesEngine:
    """Thread-safe host coordinator connecting WebSocket inputs, game state, EffectBus, and Audio."""

    def __init__(
        self,
        data_dir: Path,
        web_data_dir: Path,
        effect_bus: EffectBus,
        server: GameServer | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.web_data_dir = web_data_dir
        self.bus = effect_bus
        self.server = server

        self._lock = threading.Lock()
        self.active_game: str = "lobby"
        self.players: dict[str, dict[str, Any]] = {}
        self.store = StreaksStore(data_dir / "streaks.json")

        self.krillion = KrillionMatch(data_dir, web_data_dir, self.store)
        self.word_duel = WordDuelMatch(data_dir, self.store)
        self.face_darts = FaceDartsMatch()
        self.mouth_catch = MouthCatchMatch()
        self.pool = PoolMatch()
        self.beer_pong = BeerPongMatch()
        self.classic_darts = ClassicDartsMatch()

        self._dirty = False
        self._last_broadcast = 0.0
        self._has_face = False
        self._last_face_state = None
        self._open_palms_count = 0
        self._hand_pinch_active: bool = False
        self._hand_pinch_start: tuple[float, float, float] | None = None
        self._hand_last_xy: tuple[float, float, float] | None = None
        self._mouse_drag_active: bool = False
        self._mouse_drag_start: tuple[float, float, float] | None = None
        self._mouse_last_xy: tuple[float, float, float] | None = None
        self._hover_pool_angle: float | None = None
        self.webcam_aim: dict[str, Any] | None = None
        self.guest_aim: dict[str, Any] | None = None
        self._last_aim_broadcast: float = 0.0
        self.host_text_buf: str = ""
        self.host_text_err: str = ""
        self._last_webcam_action: float = 0.0

        if server is not None:
            server.set_handlers(
                on_message=self.on_ws_message,
                on_connect=self.on_ws_connect,
                on_disconnect=self.on_ws_disconnect,
                on_prompts_changed=self.reload_krillion_assets,
            )

    def active_roles(self) -> set[str]:
        with self._lock:
            return {p["role"] for p in self.players.values() if p.get("role") in ("guest", "host")}

    def needs_face_tracking(self) -> bool:
        with self._lock:
            if self.active_game in ("face_darts", "mouth_catch", "rare_answer"):
                return True
        return self.bus.has_face_fx()

    def reload_krillion_assets(self) -> None:
        with self._lock:
            self.krillion.reload_assets()
            self._dirty = True
        self.broadcast_state(force=True)

    def on_ws_connect(self, client_id: str, role: str, name: str) -> None:
        with self._lock:
            self.players[client_id] = {"role": role, "name": name}
            self._dirty = True
        self.send_state_to(client_id)
        self.broadcast_state(force=True)

    def on_ws_disconnect(self, client_id: str, role: str) -> None:
        with self._lock:
            self.players.pop(client_id, None)
            self._dirty = True
        self.broadcast_state(force=True)

    def on_ws_message(self, client_id: str, role: str, msg: dict[str, Any]) -> None:
        mtype = str(msg.get("type", ""))
        reply: dict[str, Any] | None = None
        with self._lock:
            roles = {p["role"] for p in self.players.values()}
            if mtype == "select_game":
                g = str(msg.get("game", "lobby"))
                if g in ALL_GAMES:
                    self._set_active_game_locked(g)
            elif mtype == "clear_forfeit":
                self.bus.set_forfeit(None)
                self._dirty = True
            elif mtype == "ping":
                reply = {"type": "pong", "t": msg.get("t")}
            elif mtype == "action":
                act_name = str(msg.get("act", ""))
                reply = self._dispatch_action(role, str(msg.get("game", self.active_game)), msg, roles)
                if act_name == "aim":
                    now_m = time.monotonic()
                    if (now_m - self._last_aim_broadcast) >= 0.035:
                        self._dirty = True
                        self._last_aim_broadcast = now_m
                else:
                    self._dirty = True

            self._flush_events_locked(1280, 720)
            dirty = self._dirty

        if reply is not None and self.server is not None:
            self.server.send_to(client_id, reply)
        if dirty:
            self.broadcast_state(force=True)

    def _dispatch_action(self, role: str, game: str, msg: dict[str, Any], active_roles: set[str]) -> dict[str, Any] | None:
        act = str(msg.get("act", ""))
        if game == "rare_answer":
            if act == "start":
                self.krillion.start("couples")
                self.host_text_buf = ""
                self.host_text_err = ""
            elif act == "submit":
                res = self.krillion.submit_answer(role, str(msg.get("text", "")), active_roles)
                return {"type": "krill_ack", "res": res}
            elif act == "next":
                self.krillion.next_round()
                self.host_text_buf = ""
                self.host_text_err = ""
            elif act == "setting":
                self.krillion.update_setting(role, str(msg.get("key", "")), bool(msg.get("value", False)))
            elif act == "trigger_forfeit":
                kind = str(msg.get("kind", "seaweed"))
                self.bus.set_forfeit(kind)
                self.krillion.last_forfeit = kind
            elif act == "clear_forfeit":
                self.bus.set_forfeit(None)
                self.krillion.last_forfeit = ""
            return None

        if game == "word_duel":
            if act == "start":
                self.word_duel.start("duel")
                self.host_text_buf = ""
                self.host_text_err = ""
            elif act == "guess":
                res = self.word_duel.submit_guess(role, str(msg.get("word", "")), active_roles)
                return {"type": "word_ack", "res": res}
            return None

        if game == "face_darts":
            if act == "throw":
                self.face_darts.throw_dart(role, float(msg.get("x", 0.5)), float(msg.get("y", 0.48)), float(msg.get("power", 0.85)))
            elif act == "next":
                self.face_darts.next_round()
            elif act == "reset":
                self.face_darts.reset_match()
            return None

        if game == "mouth_catch":
            if act == "throw":
                self.mouth_catch.throw_food(float(msg.get("x", 0.5)), float(msg.get("y", 0.55)), float(msg.get("power", 0.75)))
            elif act == "reset":
                self.mouth_catch.reset_match()
            return None

        if game == "pool":
            if act == "aim":
                self.guest_aim = {
                    "kind": "pool",
                    "game": "pool",
                    "by": role,
                    "angle": float(msg.get("angle", 0.0)),
                    "power": max(0.0, min(1.0, float(msg.get("power", 0.0)))),
                    "aimX": float(msg.get("aimX", 0.0)),
                    "aimY": float(msg.get("aimY", 0.0)),
                    "ts": time.monotonic(),
                }
            elif act == "shoot":
                self.guest_aim = None
                self.pool.shoot(role, float(msg.get("angle", 0.0)), float(msg.get("power", 0.7)), float(msg.get("spinX", 0.0)), float(msg.get("spinY", 0.0)))
            elif act == "place":
                self.guest_aim = None
                self.pool.place_cue(role, float(msg.get("x", -0.52)), float(msg.get("y", 0.0)))
            elif act == "practice":
                self.pool.practice_mode = False
            elif act == "reset":
                self.guest_aim = None
                self.pool.reset_rack()
            return None

        if game == "beer_pong":
            if act == "aim":
                ax = max(-0.58, min(0.58, float(msg.get("aimX", 0.0))))
                pw = max(0.0, min(1.0, float(msg.get("power", 0.0))))
                self.guest_aim = {
                    "kind": "beer_pong",
                    "game": "beer_pong",
                    "by": role,
                    "aimX": ax,
                    "power": pw,
                    "loft": float(msg.get("loft", msg.get("arc", 0.55))),
                    "ts": time.monotonic(),
                }
            elif act == "throw":
                self.guest_aim = None
                self.beer_pong.throw(role, float(msg.get("aimX", 0.0)), float(msg.get("power", 0.55)), float(msg.get("loft", 0.55)))
            elif act == "swat":
                self.beer_pong.swat_bounce()
            elif act == "rerack":
                self.beer_pong.rerack(role)
            elif act == "practice":
                self.beer_pong.set_practice_mode(False)
            elif act == "rule":
                self.beer_pong.set_rule(str(msg.get("key", "")), bool(msg.get("value", False)))
            elif act == "reset":
                self.guest_aim = None
                self.beer_pong.reset_game(int(msg.get("cups", self.beer_pong.cup_count)))
            return None

        if game == "classic_darts":
            if act == "aim":
                nx = max(-1.0, min(1.0, float(msg.get("x", msg.get("nx", 0.0)))))
                ny = max(-1.0, min(1.0, float(msg.get("y", msg.get("ny", 0.0)))))
                pw = max(0.0, min(1.0, float(msg.get("power", 0.0))))
                self.guest_aim = {
                    "kind": "classic_darts",
                    "game": "classic_darts",
                    "by": role,
                    "nx": nx,
                    "ny": ny,
                    "x": nx,
                    "y": ny,
                    "power": pw,
                    "ts": time.monotonic(),
                }
            elif act == "throw":
                self.guest_aim = None
                self.classic_darts.throw(role, float(msg.get("x", 0.0)), float(msg.get("y", -0.59)), float(msg.get("wobble", 0.015)))
            elif act == "reset":
                self.guest_aim = None
                do = msg.get("doubleOut")
                self.classic_darts.reset_game(None if do is None else bool(do))
            return None
        return None

    def step(self, dt: float, face_state, open_palms: list[tuple[float, float, float]], w: int = 1280, h: int = 720) -> None:
        dt = max(1e-4, min(0.05, float(dt)))
        now = time.monotonic()
        with self._lock:
            self._has_face = face_state is not None
            self._last_face_state = face_state
            self._open_palms_count = len(open_palms)
            roles = {p["role"] for p in self.players.values()}
            flying_sprites: list[FlyingSprite] = []
            moving = False

            if self.active_game == "face_darts":
                c, fs = self.face_darts.step(dt, face_state, open_palms, w, h)
                moving = bool(fs) or c
                for item in fs:
                    flying_sprites.append(FlyingSprite(**item))
            elif self.active_game == "mouth_catch":
                c, fs = self.mouth_catch.step(dt, face_state, w, h)
                moving = bool(fs) or c
                for item in fs:
                    flying_sprites.append(FlyingSprite(**item))
            elif self.active_game == "pool":
                moving = self.pool.step(dt)
            elif self.active_game == "beer_pong":
                if open_palms:
                    self.beer_pong.swat_bounce()
                moving = self.beer_pong.step(dt)
            elif self.active_game == "rare_answer":
                moving = self.krillion.step(dt, roles)

            self.bus.update_flying(flying_sprites)
            self._flush_events_locked(w, h)
            if moving:
                self._dirty = True

        # Broadcast periodic simulation state at ~25 Hz when active or dirty
        if self._dirty and (now - self._last_broadcast >= 0.04):
            self.broadcast_state(force=False)

    def _flush_events_locked(self, w: int, h: int) -> None:
        # 1. Face Darts events
        for ev in self.face_darts.pop_events():
            k = ev["kind"]
            if k == "dart_throw":
                self.bus.play_sfx("dart_throw", 0.85)
            elif k == "dart_block":
                self.bus.play_sfx("dart_block", 0.95)
                self.bus.add_callout("PALM BLOCK!", "+20 DEF", color_bgr=(90, 235, 140))
            elif k == "dart_dodge":
                self.bus.play_sfx("dart_block", 0.75)
                self.bus.add_callout("DODGE!", "+10 DEF", color_bgr=(90, 220, 255))
            elif k == "dart_hit":
                self.bus.play_sfx("dart_hit", 0.95)
                self.bus.add_stuck_dart(ev["dx_norm"], ev["dy_norm"], ev["fallback_xy"], ev["color_bgr"], ttl=5.0)
                self.bus.add_callout(ev["label"], color_bgr=(85, 140, 255))
                if ev["pts"] >= 50:
                    self.bus.spawn_confetti(w, h, count=30)
            elif k == "face_darts_crown":
                self.bus.set_forfeit("crown")
                self.bus.spawn_confetti(w, h, count=50)
            elif k == "clear_forfeit":
                self.bus.set_forfeit(None)

        # 2. Mouth Catch events
        for ev in self.mouth_catch.pop_events():
            k = ev["kind"]
            if k == "dart_throw":
                self.bus.play_sfx("dart_throw", 0.75)
            elif k == "mouth_catch":
                self.bus.play_sfx("catch", 0.95)
                self.bus.spawn_confetti(w, h, count=24)
                self.bus.add_callout(f"CHOMP! +{ev['pts']}", f"COMBO {ev['combo']}x", color_bgr=(115, 255, 165))
            elif k == "mouth_splat":
                self.bus.play_sfx("splat", 0.90)
                self.bus.add_food_splat(ev["dx_norm"], ev["dy_norm"], ev["fallback_xy"], ev["food"], ev["color_bgr"])
                self.bus.add_callout("SPLAT!", color_bgr=(120, 110, 255))

        # 3. Pool events
        for ev in self.pool.pop_events():
            k = ev["kind"]
            if k == "pool_hit":
                self.bus.play_sfx("pool_hit", ev.get("gain", 0.8))
            elif k == "pool_pot":
                self.bus.play_sfx("pool_pot", 0.9)
                self.bus.spawn_confetti(w, h, count=28)
                self.bus.add_callout(f"BALL #{ev['ball']} POTTED!", color_bgr=(110, 245, 255))
            elif k == "pool_scratch":
                self.bus.play_sfx("krill_miss", 0.85)
                self.bus.set_clown_nose(10.0)
                self.bus.add_callout("SCRATCH FOUL!", "Clown nose unlocked", color_bgr=(90, 90, 255))
            elif k == "pool_win":
                self.bus.play_sfx("word_win", 0.95)
                self.bus.spawn_confetti(w, h, count=60)
                self.bus.add_callout("8-BALL VICTORY!", color_bgr=(110, 255, 190))

        # 4. Beer Pong events
        for ev in self.beer_pong.pop_events():
            k = ev["kind"]
            if k == "dart_throw":
                self.bus.play_sfx("dart_throw", 0.7)
            elif k == "pong_table_bounce":
                self.bus.play_sfx("pong_bounce" if hasattr(self.bus, "play_sfx") else "clack", 0.62)
            elif k == "pong_rim":
                self.bus.play_sfx("pool_hit", 0.65)
                self.bus.add_callout("RIM CLINK!", color_bgr=(120, 210, 255), ttl=1.1)
            elif k == "dart_block":
                self.bus.play_sfx("dart_block", 0.85)
                self.bus.add_callout("SWATTED!", color_bgr=(100, 235, 255))
            elif k == "pong_cup":
                self.bus.play_sfx("pong_cup", 0.95)
                self.bus.spawn_confetti(w, h, count=36, kind="splash")
                self.bus.add_callout("CUP SUNK!" if ev["cups"] == 1 else "BOUNCE 2 CUPS!", color_bgr=(255, 225, 110))
            elif k == "pool_win":
                self.bus.play_sfx("word_win", 0.95)
                self.bus.spawn_confetti(w, h, count=56)

        # 5. Classic Darts events
        for ev in self.classic_darts.pop_events():
            k = ev["kind"]
            if k == "dart_bullseye":
                self.bus.play_sfx("dart_hit", 0.95)
                self.bus.spawn_confetti(w, h, count=32)
                self.bus.add_callout(f"{ev['label']}!", f"+{ev['pts']}", color_bgr=(90, 235, 255))
            elif k == "dart_hit_simple":
                self.bus.play_sfx("dart_hit", 0.72)
            elif k == "krill_miss":
                self.bus.play_sfx("krill_miss", 0.85)
            elif k == "pool_win":
                self.bus.play_sfx("word_win", 0.95)
                self.bus.spawn_confetti(w, h, count=56)
                self.bus.add_callout("301 CHECKOUT!", color_bgr=(110, 255, 180))

        # 6. Word Duel events
        for ev in self.word_duel.pop_events():
            k = ev["kind"]
            if k == "word_row":
                self.bus.play_sfx("krill_ping", 0.75)
                if ev.get("solved"):
                    self.bus.add_callout("WORD SOLVED!", ev["word"], color_bgr=(120, 255, 160), tiles=ev["states"])
            elif k == "word_win":
                self.bus.play_sfx("word_win", 0.95)
                self.bus.spawn_confetti(w, h, count=56)
                self.bus.add_callout("WORD DUEL WIN!", ev["target"], color_bgr=(110, 255, 175))

        # 7. Krillion events
        for ev in self.krillion.pop_events():
            k = ev["kind"]
            if k == "krill_preview":
                self.bus.play_sfx("krill_ping", 0.55)
            elif k == "krill_ping":
                self.bus.play_sfx("krill_ping", 0.88)
                self.bus.spawn_confetti(w, h, count=14, kind="bubble")
            elif k == "krill_deep":
                self.bus.play_sfx("krill_deep", 0.95)
                self.bus.spawn_confetti(w, h, count=26, kind="bubble")
            elif k == "krill_miss":
                self.bus.play_sfx("krill_miss", 0.75)
            elif k == "krill_reveal":
                row = ev["row"]
                if row.get("jinx"):
                    self.bus.play_sfx("krill_miss", 0.95)
                    self.bus.add_callout("JINX! SAME NET!", f"+{row['guest']['pts']} pts both", color_bgr=(125, 125, 255))
                else:
                    best = max(row["guest"]["pts"], row["host"]["pts"])
                    best_slot = row["guest"] if row["guest"]["pts"] >= row["host"]["pts"] else row["host"]
                    if best >= 60:
                        self.bus.spawn_confetti(w, h, count=22, kind="bubble")
                        self.bus.add_callout(
                            best_slot["tierLabel"],
                            f"-{best_slot['depth']}m · +{best_slot['pts']} pts",
                            color_bgr=(255, 225, 110),
                        )
            elif k == "krill_surface":
                self.bus.play_sfx("krill_deep", 0.92)
                self.bus.spawn_confetti(w, h, count=36, kind="bubble")
                if ev.get("forfeit") and ev.get("loserRole"):
                    self.bus.set_forfeit(ev["forfeit"])
                    self.bus.add_callout(
                        "SURFACE DIVE!",
                        f"Forfeit unlocked: {ev['forfeit'].replace('_', ' ')}",
                        color_bgr=(255, 215, 115),
                        ttl=3.0,
                    )

    # ------------------------------------------------------------------
    # Webcam-Native Controls for Him (host): hand pinch, mouse, keyboard
    # ------------------------------------------------------------------

    def _set_active_game_locked(self, game: str) -> None:
        self.active_game = game
        self.bus.reset_transient()
        self.webcam_aim = None
        self.guest_aim = None
        self._hover_pool_angle = None
        self.host_text_buf = ""
        self.host_text_err = ""
        if game == "rare_answer" and self.krillion.phase == "idle":
            self.krillion.start("couples")
        self._dirty = True

    def select_game_host(self, game: str) -> None:
        if game not in ALL_GAMES:
            return
        with self._lock:
            self._set_active_game_locked(game)
            self._flush_events_locked(1280, 720)
        self.broadcast_state(force=True)

    def host_reset_or_next(self) -> None:
        with self._lock:
            g = self.active_game
            if g == "pool":
                self.pool.reset_rack()
            elif g == "beer_pong":
                self.beer_pong.reset_game(self.beer_pong.cup_count)
            elif g == "classic_darts":
                self.classic_darts.reset_game(self.classic_darts.double_out)
            elif g == "face_darts":
                if self.face_darts.phase == "round_over":
                    self.face_darts.next_round()
                else:
                    self.face_darts.reset_match()
            elif g == "mouth_catch":
                self.mouth_catch.reset_match()
            elif g == "word_duel":
                self.word_duel.start("duel")
                self.host_text_buf = ""
                self.host_text_err = ""
            elif g == "rare_answer":
                if self.krillion.phase == "reveal":
                    self.krillion.next_round()
                else:
                    self.krillion.start("couples")
                self.host_text_buf = ""
                self.host_text_err = ""
            self._flush_events_locked(1280, 720)
            self._dirty = True
        self.broadcast_state(force=True)

    def wants_keyboard(self) -> bool:
        with self._lock:
            return self.active_game in ("word_duel", "rare_answer")

    def handle_host_key(self, key_code: int) -> bool:
        """Process Mac keyboard input for Word Duel & Krillion 1v1 inside webcam window."""
        handled = False
        with self._lock:
            roles = {p["role"] for p in self.players.values()}
            if self.active_game == "word_duel":
                wd = self.word_duel
                if key_code in (10, 13):  # Enter
                    if wd.phase == "finished":
                        wd.start("duel")
                        self.host_text_buf = ""
                        self.host_text_err = ""
                    elif not wd.boards["host"]["done"]:
                        res = wd.submit_guess("host", self.host_text_buf, roles | {"host"})
                        if res.get("ok"):
                            self.host_text_buf = ""
                            self.host_text_err = ""
                        else:
                            self.host_text_err = str(res.get("error", "Invalid word"))
                    handled = True
                elif key_code in (8, 127):  # Backspace / Delete
                    self.host_text_buf = self.host_text_buf[:-1]
                    self.host_text_err = ""
                    handled = True
                elif key_code == 27:  # ESC clears draft
                    if self.host_text_buf or self.host_text_err:
                        self.host_text_buf = ""
                        self.host_text_err = ""
                        handled = True
                elif (65 <= key_code <= 90) or (97 <= key_code <= 122):
                    if not wd.boards["host"]["done"] and wd.phase == "playing" and len(self.host_text_buf) < 5:
                        self.host_text_buf += chr(key_code).upper()
                        self.host_text_err = ""
                    handled = True

            elif self.active_game == "rare_answer":
                kr = self.krillion
                if key_code in (10, 13):  # Enter
                    if kr.phase in ("idle", "surface"):
                        kr.start("couples")
                        self.host_text_buf = ""
                        self.host_text_err = ""
                    elif kr.phase == "reveal":
                        kr.next_round()
                        self.host_text_buf = ""
                        self.host_text_err = ""
                    elif kr.phase == "answering" and "host" not in kr.pending_round_answers:
                        if self.host_text_buf.strip():
                            res = kr.submit_answer("host", self.host_text_buf, roles | {"host"})
                            st = res.get("status")
                            if st == "confirm" and res.get("suggested"):
                                self.host_text_buf = str(res["suggested"])
                                self.host_text_err = str(res.get("message", "Hit Enter again to use"))
                            elif st == "scored":
                                self.host_text_buf = ""
                                self.host_text_err = ""
                            else:
                                self.host_text_err = str(res.get("message", "Try another"))
                    handled = True
                elif key_code in (8, 127):
                    self.host_text_buf = self.host_text_buf[:-1]
                    self.host_text_err = ""
                    handled = True
                elif key_code == 27:
                    if self.host_text_buf or self.host_text_err:
                        self.host_text_buf = ""
                        self.host_text_err = ""
                        handled = True
                elif 32 <= key_code <= 126:
                    if kr.phase == "answering" and "host" not in kr.pending_round_answers and len(self.host_text_buf) < 42:
                        self.host_text_buf += chr(key_code)
                        self.host_text_err = ""
                    handled = True

            if handled:
                self._flush_events_locked(1280, 720)
                self._dirty = True
        if handled:
            self.broadcast_state(force=True)
        return handled

    def _compute_drag_shot_locked(self, sx: float, sy: float, cx: float, cy: float, dt_g: float) -> dict[str, Any] | None:
        g = self.active_game
        dx, dy = cx - sx, cy - sy
        dist = math.hypot(dx, dy)
        if g == "pool" and self.pool.phase == "aiming" and self.pool.turn == "host":
            if self._hover_pool_angle is not None:
                hx, hy = math.cos(self._hover_pool_angle), -math.sin(self._hover_pool_angle)
                if dist < 0.015 or (dx * hx + dy * hy) <= 0.0:
                    angle = self._hover_pool_angle
                else:
                    angle = math.atan2(-dy, dx)
            else:
                angle = math.atan2(-dy, dx) if dist >= 1e-4 else 0.0
            power = max(0.04, min(1.0, dist * 3.8))
            return {"kind": "pool", "game": "pool", "by": "host", "sx": sx, "sy": sy, "cx": cx, "cy": cy, "angle": angle, "power": power, "ts": time.monotonic()}
        if g == "beer_pong" and self.beer_pong.turn == "host" and self.beer_pong.phase != "finished" and not self.beer_pong.balls:
            pull = max(-dy, dist * 0.85)
            power = max(0.06, min(0.96, pull * 3.1 / max(dt_g * 1.4, 0.36)))
            aim_x = max(-0.55, min(0.55, (sx - 0.5) * 1.55))
            loft = max(0.25, min(0.75, 0.40 + power * 0.28))
            return {"kind": "beer_pong", "game": "beer_pong", "by": "host", "sx": sx, "sy": sy, "cx": cx, "cy": cy, "aimX": aim_x, "power": power, "loft": loft, "ts": time.monotonic()}
        if g == "classic_darts" and self.classic_darts.turn == "host" and self.classic_darts.phase == "playing":
            nx = max(-0.98, min(0.98, (cx - 0.5) * 2.2))
            ny = max(-0.98, min(0.98, (cy - 0.45) * 2.2))
            power = max(0.08, min(1.0, max(-dy, dist * 0.85) * 3.2))
            return {"kind": "classic_darts", "game": "classic_darts", "by": "host", "sx": sx, "sy": sy, "cx": cx, "cy": cy, "nx": nx, "ny": ny, "x": nx, "y": ny, "power": power, "ts": time.monotonic()}
        return None

    def _fire_drag_shot_locked(self, sx: float, sy: float, ex: float, ey: float, dt_g: float, now: float) -> bool:
        if (now - self._last_webcam_action) < 0.35:
            return False
        dx, dy = ex - sx, ey - sy
        if math.hypot(dx, dy) < 0.024:
            return False
        spec = self._compute_drag_shot_locked(sx, sy, ex, ey, dt_g)
        if spec is None or float(spec.get("power", 0.0)) < 0.08:
            return False
        kind = spec["kind"]
        ok = False
        if kind == "pool":
            ok = bool(self.pool.shoot("host", spec["angle"], spec["power"], 0.0, 0.0).get("ok"))
        elif kind == "beer_pong":
            ok = bool(self.beer_pong.throw("host", spec["aimX"], spec["power"], spec["loft"]).get("ok"))
        elif kind == "classic_darts":
            ok = bool(self.classic_darts.throw("host", spec["nx"], spec["ny"], 0.018).get("ok"))
        if ok:
            self._last_webcam_action = now
            self._hover_pool_angle = None
            self.guest_aim = None
            self._dirty = True
            self._flush_events_locked(1280, 720)
        return ok

    def process_webcam_hands(self, hands_lm: list[Any], now: float) -> None:
        """Let the webcam user (host) aim and shoot Pool, Cup Pong, or Darts via hand pinch gestures."""
        fired = False
        with self._lock:
            if not hands_lm or self.active_game not in ("beer_pong", "classic_darts", "pool"):
                self._hand_pinch_active = False
                self._hand_pinch_start = None
                self._hand_last_xy = None
                if not self._mouse_drag_active and self.webcam_aim is None:
                    self.webcam_aim = None
                elif not self._mouse_drag_active and self.webcam_aim and self.webcam_aim.get("hover"):
                    pass
                else:
                    self.webcam_aim = None
                return
            lm = hands_lm[0]
            thumb, index = lm[4], lm[8]
            pinch_dist = ((thumb[0] - index[0]) ** 2 + (thumb[1] - index[1]) ** 2) ** 0.5
            is_pinch = pinch_dist < 0.058
            cx, cy = (thumb[0] + index[0]) * 0.5, (thumb[1] + index[1]) * 0.5

            if is_pinch:
                if not self._hand_pinch_active:
                    self._hand_pinch_active = True
                    self._hand_pinch_start = (cx, cy, now)
                self._hand_last_xy = (cx, cy, now)
                sx, sy, st = self._hand_pinch_start
                self.webcam_aim = self._compute_drag_shot_locked(sx, sy, cx, cy, max(0.04, now - st))
                return

            if not self._hand_pinch_active or self._hand_pinch_start is None:
                if not self._mouse_drag_active and not (self.webcam_aim and self.webcam_aim.get("hover")):
                    self.webcam_aim = None
                return
            sx, sy, st = self._hand_pinch_start
            ex, ey, _ = self._hand_last_xy or (cx, cy, now)
            self._hand_pinch_active = False
            self._hand_pinch_start = None
            self._hand_last_xy = None
            self.webcam_aim = None
            fired = self._fire_drag_shot_locked(sx, sy, ex, ey, max(0.04, now - st), now)
        if fired:
            self.broadcast_state(force=True)

    def handle_host_mouse(self, action: str, nx: float, ny: float, now: float) -> bool:
        """Mouse-first host controls in pewpew window: live hover aim + click-drag Green/Yellow/Red power pullback."""
        fired = False
        aim_dirty = False
        with self._lock:
            g = self.active_game
            if g not in ("pool", "beer_pong", "classic_darts"):
                self._mouse_drag_active = False
                self._hover_pool_angle = None
                return False

            if action == "down":
                # Pool Ball-In-Hand placement directly on projected overhead AR table
                if g == "pool" and self.pool.phase == "ball_in_hand" and self.pool.turn == "host":
                    if 0.24 <= nx <= 0.76 and 0.48 <= ny <= 0.94:
                        px = max(-0.92, min(0.92, (nx - 0.5) / 0.232))
                        py = max(-0.44, min(0.44, (0.71 - ny) / 0.205 * 0.5))
                        if self.pool.place_cue("host", px, py).get("ok"):
                            self._dirty = True
                            self._flush_events_locked(1280, 720)
                            fired = True
                else:
                    if g == "pool" and self.pool.phase == "aiming" and self.pool.turn == "host":
                        cue = self.pool.balls[0]
                        tx = (nx - 0.5) / 0.232
                        ty = (0.71 - ny) / 0.205 * 0.5
                        if math.hypot(tx - cue.x, ty - cue.y) > 0.02:
                            self._hover_pool_angle = math.atan2(ty - cue.y, tx - cue.x)
                    self._mouse_drag_active = True
                    self._mouse_drag_start = (nx, ny, now)
                    self._mouse_last_xy = (nx, ny, now)
            elif action == "move":
                if self._mouse_drag_active and self._mouse_drag_start is not None:
                    self._mouse_last_xy = (nx, ny, now)
                    sx, sy, st = self._mouse_drag_start
                    self.webcam_aim = self._compute_drag_shot_locked(sx, sy, nx, ny, max(0.04, now - st))
                    aim_dirty = (now - self._last_aim_broadcast) >= 0.04
                else:
                    # Live hover aiming on host turn so cue/target tracks cursor smoothly before click
                    if g == "pool" and self.pool.phase == "aiming" and self.pool.turn == "host":
                        cue = self.pool.balls[0]
                        tx = (nx - 0.5) / 0.232
                        ty = (0.71 - ny) / 0.205 * 0.5
                        angle = math.atan2(ty - cue.y, tx - cue.x)
                        self._hover_pool_angle = angle
                        self.webcam_aim = {
                            "kind": "pool",
                            "game": "pool",
                            "by": "host",
                            "hover": True,
                            "angle": angle,
                            "power": 0.0,
                            "aimX": nx,
                            "aimY": ny,
                            "ts": now,
                        }
                        aim_dirty = (now - self._last_aim_broadcast) >= 0.06
                    elif g == "beer_pong" and self.beer_pong.turn == "host" and self.beer_pong.phase != "finished" and not self.beer_pong.balls:
                        ax = max(-0.55, min(0.55, (nx - 0.5) * 1.55))
                        self.webcam_aim = {
                            "kind": "beer_pong",
                            "game": "beer_pong",
                            "by": "host",
                            "hover": True,
                            "aimX": ax,
                            "power": 0.58,
                            "loft": 0.55,
                            "ts": now,
                        }
                        aim_dirty = (now - self._last_aim_broadcast) >= 0.06
                    elif g == "classic_darts" and self.classic_darts.turn == "host" and self.classic_darts.phase == "playing":
                        dx = max(-0.98, min(0.98, (nx - 0.5) * 2.2))
                        dy = max(-0.98, min(0.98, (ny - 0.45) * 2.2))
                        self.webcam_aim = {
                            "kind": "classic_darts",
                            "game": "classic_darts",
                            "by": "host",
                            "hover": True,
                            "nx": dx,
                            "ny": dy,
                            "x": dx,
                            "y": dy,
                            "power": 0.0,
                            "ts": now,
                        }
                        aim_dirty = (now - self._last_aim_broadcast) >= 0.06
            elif action == "up" and self._mouse_drag_active and self._mouse_drag_start is not None:
                sx, sy, st = self._mouse_drag_start
                self._mouse_drag_active = False
                self._mouse_drag_start = None
                self._mouse_last_xy = None
                self.webcam_aim = None
                fired = self._fire_drag_shot_locked(sx, sy, nx, ny, max(0.04, now - st), now)
            if aim_dirty:
                self._last_aim_broadcast = now
        if fired or aim_dirty:
            self.broadcast_state(force=True)
        return fired

    def _active_live_aim_locked(self) -> dict[str, Any] | None:
        now_m = time.monotonic()
        aim = self.webcam_aim
        if aim and (now_m - float(aim.get("ts", now_m))) < 3.0:
            return dict(aim)
        gaim = self.guest_aim
        if gaim and (now_m - float(gaim.get("ts", now_m))) < 3.0:
            return dict(gaim)
        return None

    def hud_state(self) -> dict[str, Any]:
        """Thread-safe lightweight snapshot for EffectBus on-camera 1v1 HUD rendering."""
        snap = self.snapshot_for("host")
        with self._lock:
            live = self._active_live_aim_locked()
            snap["webcamAim"] = dict(self.webcam_aim) if self.webcam_aim else None
            snap["liveAim"] = live
            snap["hostTextBuf"] = self.host_text_buf
            snap["hostTextErr"] = self.host_text_err
        return snap

    def snapshot_for(self, role: str) -> dict[str, Any]:
        with self._lock:
            face_info: dict[str, Any] = {"present": self._has_face, "openPalms": self._open_palms_count}
            if self._last_face_state is not None:
                fs = self._last_face_state
                face_info["jawOpen"] = round(float(fs.jaw_open), 3)
                face_info["faceScale"] = round(float(fs.face_scale_px) / 1280.0, 4)
                face_info["nose"] = [round(fs.nose_px[0] / 1280.0, 3), round(fs.nose_px[1] / 720.0, 3)]
                face_info["mouth"] = [round(fs.mouth_px[0] / 1280.0, 3), round(fs.mouth_px[1] / 720.0, 3)]

            payload = {
                "type": "state",
                "activeGame": self.active_game,
                "players": [
                    {"role": p["role"], "name": p["name"]}
                    for p in self.players.values()
                ],
                "cam": face_info,
                "liveAim": self._active_live_aim_locked(),
                "rare_answer": self.krillion.snapshot(),
                "word_duel": self.word_duel.snapshot_for(role),
                "face_darts": self.face_darts.snapshot(),
                "mouth_catch": self.mouth_catch.snapshot(),
                "pool": self.pool.snapshot(),
                "beer_pong": self.beer_pong.snapshot(),
                "classic_darts": self.classic_darts.snapshot(),
            }
            return payload

    def send_state_to(self, client_id: str) -> None:
        if self.server is None:
            return
        with self.server._clients_lock:
            c = self.server._clients.get(client_id)
            role = c.role if c else "guest"
        self.server.send_to(client_id, self.snapshot_for(role))

    def broadcast_state(self, force: bool = False) -> None:
        if self.server is None:
            return
        self._dirty = False
        self._last_broadcast = time.monotonic()
        with self.server._clients_lock:
            targets = [(cid, c.role) for cid, c in self.server._clients.items()]
        if not targets:
            return
        # Cache snapshots per role so guest & host don't re-serialize twice if multiple spectators
        by_role: dict[str, dict[str, Any]] = {}
        for cid, role in targets:
            if role not in by_role:
                by_role[role] = self.snapshot_for(role)
            self.server.send_to(cid, by_role[role])
