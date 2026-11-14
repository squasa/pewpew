"""Krillion (Rare Answer / Couples Dive) + Word Duel authoritative game logic and streak persistence."""
from __future__ import annotations

import datetime as _dt
import json
import math
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from live_lookup import LiveKnowledgeVerifier


def _load_english_words() -> set[str]:
    """Load /usr/share/dict/words once for sanity checking free-form everyday phrase answers."""
    for path in (Path("/usr/share/dict/words"), Path("/usr/share/dict/web2")):
        if path.exists():
            try:
                return {w.strip().lower() for w in path.read_text(encoding="utf-8", errors="ignore").splitlines() if w.strip()}
            except Exception:
                pass
    return set()


def normalize_answer(text: str) -> str:
    """Normalize free-text answers forgivingly (case, accents, punctuation, abbreviations, articles)."""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = s.replace("c++", "cpp").replace("c#", "csharp")
    s = s.replace("&", " and ")
    s = s.replace("'", "").replace(".", "")
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Expand common English title / place abbreviations
    abbr = {"dr": "doctor", "st": "saint", "mt": "mount", "mr": "mister", "mrs": "missus", "vs": "versus"}
    if s:
        s = " ".join(abbr.get(tok, tok) for tok in s.split())
    for art in ("the ", "a ", "an ", "my "):
        if s.startswith(art) and len(s) >= len(art) + 2:
            s = s[len(art):].strip()
            break
    return s


def _collapse_phonetic(text: str) -> str:
    """Collapse double letters and simple digraphs to forgive everyday spelling slips."""
    s = text.replace(" ", "")
    s = s.replace("ph", "f").replace("ck", "k").replace("qu", "kw")
    return re.sub(r"(.)\1+", r"\1", s)


def _stem_forms(word: str) -> set[str]:
    """Generate simple inflected root/plural/gerund forms for >=4 char tokens or phrases."""
    out = {word}
    if len(word) < 4:
        return out
    if word.endswith("ies") and len(word) > 4:
        out.add(word[:-3] + "y")
    elif word.endswith("ves") and len(word) > 4:
        out.add(word[:-3] + "f")
        out.add(word[:-3] + "fe")
    elif word.endswith("es") and len(word) > 4:
        out.add(word[:-2])
        out.add(word[:-1])
    elif word.endswith("s") and not word.endswith("ss"):
        out.add(word[:-1])
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        out.add(base)
        out.add(base + "e")
        if len(base) >= 3 and base[-1] == base[-2]:
            out.add(base[:-1])
    if word.endswith("ed") and len(word) > 4:
        base = word[:-2]
        out.add(base)
        out.add(base + "e")
        if len(base) >= 3 and base[-1] == base[-2]:
            out.add(base[:-1])
    return out


def damerau_levenshtein(a: str, b: str) -> int:
    """Optimal String Alignment / restricted Damerau-Levenshtein distance."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            best = min(
                d[i - 1][j] + 1,      # deletion
                d[i][j - 1] + 1,      # insertion
                d[i - 1][j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                best = min(best, d[i - 2][j - 2] + 1)  # transposition
            d[i][j] = best
    return d[la][lb]


class StreaksStore:
    """Lightweight JSON store for Rare Answer / Word Duel streaks and personal bests."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "krillion": {
                "dives": 0,
                "bestScore": 0,
                "bestDepth": 0,
                "totalScore": 0,
                "currentStreak": 0,
                "bestStreak": 0,
                "lastDailyDate": "",
                "couplesPlayed": 0,
                "jinxCount": 0,
                "rarePulls": 0,
            },
            "wordDuel": {
                "played": 0,
                "wins": 0,
                "currentStreak": 0,
                "bestStreak": 0,
                "lastDailyDate": "",
            },
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for section in ("krillion", "wordDuel"):
                    if isinstance(loaded.get(section), dict):
                        self.data[section].update(loaded[section])
        except Exception:
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    def record_krillion(
        self,
        total_pts: int,
        total_depth: int,
        mode: str,
        jinx_hits: int,
        rare_pulls: int,
    ) -> dict[str, Any]:
        k = self.data["krillion"]
        k["dives"] += 1
        k["totalScore"] += int(total_pts)
        k["bestScore"] = max(int(k["bestScore"]), int(total_pts))
        k["bestDepth"] = max(int(k["bestDepth"]), int(total_depth))
        k["rarePulls"] += int(rare_pulls)
        if mode == "couples":
            k["couplesPlayed"] += 1
            k["jinxCount"] += int(jinx_hits)
        today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        if mode == "daily":
            last = k.get("lastDailyDate", "")
            if last != today:
                yesterday = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
                k["currentStreak"] = (int(k["currentStreak"]) + 1) if last == yesterday else 1
                k["lastDailyDate"] = today
                k["bestStreak"] = max(int(k["bestStreak"]), int(k["currentStreak"]))
        self.save()
        return self.krillion_summary()

    def krillion_summary(self) -> dict[str, Any]:
        k = self.data["krillion"]
        dives = max(1, int(k["dives"]))
        return {
            **k,
            "avgScore": round(k["totalScore"] / dives, 1) if k["dives"] else 0.0,
        }

    def record_word_duel(self, won: bool, mode: str) -> dict[str, Any]:
        w = self.data["wordDuel"]
        w["played"] += 1
        if won:
            w["wins"] += 1
            w["currentStreak"] += 1
            w["bestStreak"] = max(int(w["bestStreak"]), int(w["currentStreak"]))
        else:
            w["currentStreak"] = 0
        if mode == "daily":
            w["lastDailyDate"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        self.save()
        return dict(w)


class KrillionMatch:
    """Authoritative Krillion game state supporting Couples Dive, Daily Dive, Free Dive & Customizer."""

    def __init__(self, data_dir: Path, web_data_dir: Path, store: StreaksStore) -> None:
        self.data_dir = data_dir
        self.web_data_dir = web_data_dir
        self.store = store
        self.tiers: dict[str, dict[str, Any]] = {}
        self.prompts: list[dict[str, Any]] = []
        self.theme: dict[str, Any] = {}
        self.mode: str = "couples"   # Strict 1v1 Jinx (Her on Phone vs Him in Webcam)
        self.phase: str = "idle"     # "idle" | "preview" | "answering" | "reveal" | "surface"
        self.round_idx: int = 0
        self.selected_prompts: list[dict[str, Any]] = []
        self._recent_ids: set[str] = set()
        self.phase_timer: float = 0.0
        self.pending_round_answers: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.last_forfeit: str = ""
        self.loser_role: str = ""
        self.puffer_players: list[dict[str, Any]] = []
        self.puffer_turn: int = 0
        self.puffer_used: list[dict[str, str]] = []
        self.puffer_fuse: float = 10.0
        self.puffer_last_event: dict[str, Any] = {}
        self.puffer_winner: str = ""
        self.settings_by_role: dict[str, dict[str, bool]] = {
            "guest": self._default_settings(),
            "host": self._default_settings(),
        }
        self.last_feedback: dict[str, dict[str, Any]] = {"guest": {}, "host": {}}
        self._events: list[dict[str, Any]] = []
        self.live_verifier = LiveKnowledgeVerifier(cache_path=self.data_dir / "wiki_cache.json")
        self._dict_words: set[str] = _load_english_words()
        self.reload_assets()

    @staticmethod
    def _default_settings() -> dict[str, bool]:
        return {
            "answerCorrections": True,
            "clearRejected": False,
            "lowPower": False,
            "colorblind": False,
            "shareLink": False,
            "couplesJinx": True,
        }

    def reload_assets(self) -> None:
        base = json.loads((self.data_dir / "rare_answer_prompts.json").read_text(encoding="utf-8"))
        self.tiers = dict(base.get("tiers", {}))
        prompts = list(base.get("prompts", []))
        custom_path = self.web_data_dir / "rare_answer_custom_prompts.json"
        if custom_path.exists():
            try:
                custom = json.loads(custom_path.read_text(encoding="utf-8"))
                extra = custom.get("prompts", [])
                if isinstance(extra, list):
                    prompts.extend(p for p in extra if isinstance(p, dict) and p.get("prompt") and p.get("answers"))
            except Exception:
                pass
        self.prompts = prompts

        theme_path = self.web_data_dir / "rare_answer_theme.json"
        if theme_path.exists():
            try:
                self.theme = json.loads(theme_path.read_text(encoding="utf-8"))
            except Exception:
                self.theme = {}

    def _preview_seconds(self) -> float:
        if self.mode == "puffer":
            return 2.0
        return float(self.theme.get("previewSeconds", 3.0))

    def _answer_seconds(self) -> float:
        if self.mode == "puffer":
            return float(self.puffer_fuse)
        return float(self.theme.get("answerSeconds", 25.0))

    def _round_count(self, mode: str) -> int:
        if mode == "puffer":
            return min(len(self.prompts), 18)
        if mode in ("daily", "unlimited"):
            return min(len(self.prompts), int(self.theme.get("dailyRounds", 7)))
        return min(len(self.prompts), int(self.theme.get("couplesRounds", 5)))

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    @staticmethod
    def _build_puffer_players(players: Any) -> list[dict[str, Any]]:
        names: list[str] = []
        if isinstance(players, list):
            names = [str(n).strip()[:16] for n in players if str(n).strip()][:6]
        elif players is not None:
            try:
                count = max(2, min(6, int(players)))
                names = [f"Player {i + 1}" for i in range(count)]
            except Exception:
                names = []
        if len(names) < 2:
            names = ["Player 1", "Player 2", "Player 3"]
        return [
            {"idx": i, "name": nm, "hearts": 3, "alive": True, "passes": 0, "rares": 0}
            for i, nm in enumerate(names)
        ]

    def start(self, mode: str = "couples", players: Any = None) -> None:
        # Strict 1v1 only (Her on Phone vs Him in Webcam)
        self.mode = "couples"
        count = self._round_count(self.mode)
        self._dive_seq = getattr(self, "_dive_seq", 0) + 1
        today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        seed = f"krillion-{self.mode}-{today}" if self.mode == "daily" else f"krillion-{self.mode}-{today}-{self._dive_seq}"
        rng = random.Random(seed)
        fresh = [p for p in self.prompts if p.get("id") not in self._recent_ids]
        if self.mode != "daily" and len(fresh) >= count:
            pool = list(fresh)
        else:
            prev_ids = {str(p.get("id", "")) for p in self.selected_prompts}
            if self.mode != "daily":
                self._recent_ids.clear()
            pool = [p for p in self.prompts if str(p.get("id", "")) not in prev_ids]
            if len(pool) < count:
                pool = list(self.prompts)
        rng.shuffle(pool)
        self.selected_prompts = pool[:count]
        if self.mode != "daily":
            self._recent_ids.update(str(p.get("id", "")) for p in self.selected_prompts)
        self.round_idx = 0
        self.history = []
        self.pending_round_answers = {}
        self.last_feedback = {"guest": {}, "host": {}}
        self.last_forfeit = ""
        self.loser_role = ""
        self.puffer_players = self._build_puffer_players(players) if self.mode == "puffer" else []
        self.puffer_turn = 0
        self.puffer_used = []
        self.puffer_fuse = 10.5
        self.puffer_last_event = {}
        self.puffer_winner = ""
        self._enter_preview()

    def _enter_preview(self) -> None:
        self.phase = "preview"
        self.phase_timer = self._preview_seconds()
        self.pending_round_answers = {}
        self.puffer_used = []
        self.puffer_fuse = 10.5
        self.last_feedback = {"guest": {}, "host": {}}
        self._events.append({"kind": "krill_preview", "round": self.round_idx + 1})

    def _enter_answering(self) -> None:
        self.phase = "answering"
        self.phase_timer = self._answer_seconds()
        self._events.append({"kind": "krill_ping", "round": self.round_idx + 1})

    def update_setting(self, role: str, key: str, value: bool) -> None:
        r = role if role in self.settings_by_role else "guest"
        if key == "couplesJinx":
            for rk in self.settings_by_role:
                self.settings_by_role[rk][key] = bool(value)
        elif key in self.settings_by_role[r]:
            self.settings_by_role[r][key] = bool(value)

    def _score_payload(
        self,
        canon: str,
        tier_key: str,
        raw: str,
        corrected: bool = False,
        extra_note: str = "",
    ) -> dict[str, Any]:
        tier = self.tiers.get(tier_key, {"label": tier_key.upper(), "pts": 30, "depth": 300, "note": ""})
        base_note = str(tier.get("note", ""))
        note = extra_note if extra_note else (f"matched {canon} · {base_note}" if corrected else base_note)
        return {
            "status": "scored",
            "canonical": canon,
            "tierKey": tier_key,
            "tierLabel": tier["label"],
            "pts": int(tier["pts"]),
            "depth": int(tier["depth"]),
            "note": note,
            "corrected": corrected,
            "inputRaw": raw.strip(),
        }

    @staticmethod
    def _is_clean_variant(norm: str, cand: str) -> bool:
        """Accept exact, space-collapsed, and clean English plural/gerund/past inflections."""
        if not cand:
            return False
        if norm == cand:
            return True
        norm_ns = norm.replace(" ", "")
        cand_ns = cand.replace(" ", "")
        if len(norm_ns) >= 2 and norm_ns == cand_ns:
            return True
        if max(len(norm_ns), len(cand_ns)) < 4:
            return False
        if _stem_forms(norm_ns) & _stem_forms(cand_ns):
            return True
        n_toks = norm.split()
        c_toks = cand.split()
        if len(n_toks) == len(c_toks) and len(n_toks) > 1:
            if n_toks[:-1] == c_toks[:-1] and (_stem_forms(n_toks[-1]) & _stem_forms(c_toks[-1])):
                return True
        return False

    def _word_subset_match(
        self,
        norm: str,
        entries: list[tuple[str, list[str], str]],
    ) -> tuple[str, str] | None:
        """Match core noun subsets ("corgi" -> "Welsh Corgi") or longer natural phrases ("iced caramel latte")."""
        u_toks = norm.split()
        norm_ns = norm.replace(" ", "")
        if len(norm_ns) >= 4 or len(u_toks) >= 2:
            # 1) User words all present inside canonical phrase
            sub_hits: list[tuple[str, str, int, int]] = []
            for canon, aliases, tier_key in entries:
                for cand_str in [canon] + aliases:
                    cn = normalize_answer(cand_str)
                    c_toks = cn.split()
                    if len(u_toks) < len(c_toks) and all(tok in c_toks for tok in u_toks):
                        sub_hits.append((canon, tier_key, len(c_toks), len(cn)))
                        break
            if len(sub_hits) == 1:
                return sub_hits[0][0], sub_hits[0][1]
            if len(sub_hits) > 1:
                sub_hits.sort(key=lambda x: (x[2], x[3]))
                shortest = normalize_answer(sub_hits[0][0])
                if all(shortest in normalize_answer(h[0]) for h in sub_hits):
                    return sub_hits[0][0], sub_hits[0][1]

        # 2) User typed extra modifiers around canonical (e.g. "hot caramel macchiato") -> longest canonical wins
        if len(u_toks) >= 2:
            sup_hits: list[tuple[str, str, int, int]] = []
            for canon, aliases, tier_key in entries:
                for cand_str in [canon] + aliases:
                    cn = normalize_answer(cand_str)
                    c_toks = cn.split()
                    cn_ns = cn.replace(" ", "")
                    if len(c_toks) < len(u_toks) and (len(c_toks) >= 2 or len(cn_ns) >= 5):
                        for i in range(len(u_toks) - len(c_toks) + 1):
                            if u_toks[i : i + len(c_toks)] == c_toks:
                                sup_hits.append((canon, tier_key, len(c_toks), len(cn_ns)))
                                break
            if sup_hits:
                sup_hits.sort(key=lambda x: (x[2], x[3]), reverse=True)
                top = sup_hits[0]
                if not any(h[0] != top[0] and h[2] == top[2] and h[3] == top[3] for h in sup_hits):
                    return top[0], top[1]
        return None

    def _verify_everyday_phrase(self, raw: str, norm: str, prompt_entry: dict[str, Any]) -> dict[str, Any] | None:
        """Accept creative natural phrases on everyday scenario prompts when topic + dictionary words hold."""
        verify = prompt_entry.get("verify")
        if not isinstance(verify, dict) or verify.get("kind") != "phrase":
            return None
        toks = norm.split()
        norm_ns = norm.replace(" ", "")
        if len(norm_ns) < 4 or len(toks) > 7:
            return None
        sw = str(verify.get("startsWith", "")).lower().strip()
        if sw and not norm.startswith(sw):
            return None
        topics = [str(t).lower().strip() for t in verify.get("topics", []) if str(t).strip()]
        if not topics:
            return None
        topic_hit = any(
            (t in norm if " " in t else any(tok.startswith(t) or t in _stem_forms(tok) for tok in toks))
            for t in topics
        )
        if not topic_hit:
            return None
        # Ensure all non-trivial words (>=3 chars) look like real English words if system dictionary loaded
        if self._dict_words:
            for tok in toks:
                if len(tok) < 3 or tok.isdigit():
                    continue
                if tok in self._dict_words:
                    continue
                if any(stem in self._dict_words for stem in _stem_forms(tok)):
                    continue
                if tok in topics:
                    continue
                return None
        tier_key = "deep_cut" if len(toks) >= 3 else "rare"
        canon = " ".join(w.capitalize() if len(w) > 2 else w for w in raw.strip().split())[:42]
        return self._score_payload(canon, tier_key, raw, corrected=False)

    def evaluate_guess(self, raw: str, prompt_entry: dict[str, Any], answer_corrections: bool, clear_rejected: bool) -> dict[str, Any]:
        norm = normalize_answer(raw)
        if not norm:
            return {"status": "empty", "message": ""}

        # Build canonical index
        entries: list[tuple[str, list[str], str]] = []
        for row in prompt_entry.get("answers", []):
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            canon, aliases, tier_key = str(row[0]), [str(a) for a in (row[1] or [])], str(row[2])
            entries.append((canon, aliases, tier_key))

        # 1A. Exact, space-collapsed, or clean plural/stem match -> immediate score
        for canon, aliases, tier_key in entries:
            cands = [normalize_answer(canon)] + [normalize_answer(a) for a in aliases]
            if any(self._is_clean_variant(norm, c) for c in cands):
                return self._score_payload(canon, tier_key, raw, corrected=False)

        norm_ns = norm.replace(" ", "")
        # 1B. Double-letter/phonetic collapse on >=5 char guesses (e.g. "cappucino", "machiato", "brocoli")
        if len(norm_ns) >= 5:
            norm_ph = _collapse_phonetic(norm_ns)
            for canon, aliases, tier_key in entries:
                cands = [normalize_answer(canon)] + [normalize_answer(a) for a in aliases]
                for c in cands:
                    c_ns = c.replace(" ", "")
                    if len(c_ns) >= 5 and norm_ns[0] == c_ns[0] and abs(len(norm_ns) - len(c_ns)) <= 2:
                        if _collapse_phonetic(c_ns) == norm_ph:
                            return self._score_payload(canon, tier_key, raw, corrected=True)

        # 1C. Clean word-subset / modified-phrase match (e.g. "corgi" or "iced caramel macchiato")
        sub_hit = self._word_subset_match(norm, entries)
        if sub_hit is not None:
            return self._score_payload(sub_hit[0], sub_hit[1], raw, corrected=False)

        # 2. Close-typo + half-answer prefix matching (only >= 4 chars so never too hinty)
        best_score = 999
        best_ratio = 0.0
        best_entry: tuple[str, str] | None = None
        tied = False

        if len(norm_ns) >= 4:
            # 2a. Conservative Damerau-Levenshtein typo corrections (1-edit on >=5 chars auto-accepts!)
            for canon, aliases, tier_key in entries:
                raw_cands = [normalize_answer(canon)] + [normalize_answer(a) for a in aliases]
                seen_cands: set[str] = set()
                cands: list[tuple[str, str]] = []
                for c in raw_cands:
                    if len(c) < 4 or c in seen_cands:
                        continue
                    seen_cands.add(c)
                    cands.append((norm, c))
                    c_ns = c.replace(" ", "")
                    if len(c_ns) >= 4 and (c_ns != c or norm_ns != norm):
                        cands.append((norm_ns, c_ns))

                canon_best: tuple[int, float] | None = None
                for probe, cand in cands:
                    if abs(len(probe) - len(cand)) > 3:
                        continue
                    if not (probe[0] == cand[0] or (len(probe) >= 2 and len(cand) >= 2 and probe[:2] == cand[1] + cand[0])):
                        continue
                    max_dist = 1 if len(cand) <= 5 else (2 if len(cand) <= 8 else 3)
                    dist = damerau_levenshtein(probe, cand)
                    if dist <= 0 or dist > max_dist:
                        continue
                    ratio = 1.0 - (dist / max(len(probe), len(cand)))
                    if ratio < 0.66:
                        continue
                    if canon_best is None or dist < canon_best[0] or (dist == canon_best[0] and ratio > canon_best[1]):
                        canon_best = (dist, ratio)

                if canon_best is None:
                    continue
                dist, ratio = canon_best
                if best_entry is None or (dist < best_score) or (dist == best_score and ratio > best_ratio):
                    best_score = dist
                    best_ratio = ratio
                    best_entry = (canon, tier_key)
                    tied = False
                elif dist == best_score and abs(ratio - best_ratio) < 1e-6 and best_entry[0] != canon:
                    tied = True

            if best_entry is not None and not tied:
                canon, tier_key = best_entry
                if answer_corrections:
                    return {
                        "status": "confirm",
                        "inputRaw": raw.strip(),
                        "suggested": canon,
                        "message": f'"{raw.strip()}" -> "{canon}" · tap or hit enter to use',
                    }
                return self._score_payload(canon, tier_key, raw, corrected=True)

            # 2b. Unambiguous half-answer prefix matches (e.g. "schnauz" -> "Schnauzer")
            prefix_hits: list[tuple[str, str, int]] = []
            for canon, aliases, tier_key in entries:
                cands = [normalize_answer(canon)] + [normalize_answer(a) for a in aliases]
                hit_len = 0
                for c in cands:
                    c_ns = c.replace(" ", "")
                    if len(c_ns) >= 5 and c_ns.startswith(norm_ns) and (len(norm_ns) / len(c_ns)) >= 0.48:
                        hit_len = len(normalize_answer(canon)) if not hit_len else min(hit_len, len(c_ns))
                if hit_len:
                    prefix_hits.append((canon, tier_key, len(normalize_answer(canon))))
            p_hit: tuple[str, str] | None = None
            if len(prefix_hits) == 1:
                p_hit = (prefix_hits[0][0], prefix_hits[0][1])
            elif len(prefix_hits) > 1:
                prefix_hits.sort(key=lambda x: x[2])
                shortest_norm = normalize_answer(prefix_hits[0][0])
                if all(shortest_norm in normalize_answer(h[0]) for h in prefix_hits):
                    p_hit = (prefix_hits[0][0], prefix_hits[0][1])
            if p_hit is not None:
                if answer_corrections:
                    return {
                        "status": "confirm",
                        "inputRaw": raw.strip(),
                        "suggested": p_hit[0],
                        "message": f'"{raw.strip()}" -> "{p_hit[0]}" · hit enter again to confirm',
                    }
                return self._score_payload(p_hit[0], p_hit[1], raw, corrected=True)

        # 3. Dynamic knowledge check (Wikidata / Wikipedia) + everyday phrase fallback for rare unlisted answers
        live_hit = self.live_verifier.verify(raw, prompt_entry)
        if live_hit is not None:
            desc = str(live_hit.get("desc", "")).strip()
            tier = self.tiers.get(live_hit["tierKey"], {})
            note = str(tier.get("note", ""))
            if desc:
                note = f"{desc} · live check"
            return self._score_payload(live_hit["canonical"], live_hit["tierKey"], raw, corrected=False, extra_note=note)

        phrase_hit = self._verify_everyday_phrase(raw, norm, prompt_entry)
        if phrase_hit is not None:
            return phrase_hit

        # 4. No match -> non-fatal no echo
        return {
            "status": "no_echo",
            "inputRaw": raw.strip(),
            "clearInput": bool(clear_rejected),
            "message": f'"{raw.strip()}": not quite — try another',
        }

    def _next_alive_puffer_idx(self, after_idx: int) -> int:
        n = len(self.puffer_players)
        if n <= 0:
            return 0
        for step_i in range(1, n + 1):
            cand = (after_idx + step_i) % n
            if self.puffer_players[cand].get("alive", False):
                return cand
        return after_idx % n

    def _submit_puffer_answer(self, r: str, raw: str, prompt_entry: dict[str, Any]) -> dict[str, Any]:
        if not self.puffer_players:
            return {"status": "ignored"}
        seat = self.puffer_players[self.puffer_turn % len(self.puffer_players)]
        res = self.evaluate_guess(raw, prompt_entry, answer_corrections=False, clear_rejected=False)
        self.last_feedback[r] = res
        if res["status"] != "scored":
            self._events.append({"kind": "krill_miss", "role": r})
            return res

        norm_c = normalize_answer(res["canonical"])
        if any(normalize_answer(u["canon"]) == norm_c for u in self.puffer_used):
            msg = f'"{res["canonical"]}" was already said — pick another'
            out = {"status": "no_echo", "inputRaw": raw.strip(), "clearInput": True, "message": msg}
            self.last_feedback[r] = out
            self._events.append({"kind": "krill_miss", "role": r})
            return out

        self.puffer_used.append({
            "canon": res["canonical"],
            "by": seat["name"],
            "tierKey": res["tierKey"],
            "tierLabel": res["tierLabel"],
        })
        seat["passes"] = int(seat.get("passes", 0)) + 1
        healed = False
        if res["tierKey"] in ("deep_cut", "krillion"):
            seat["rares"] = int(seat.get("rares", 0)) + 1
            if int(seat.get("hearts", 0)) < 3:
                seat["hearts"] = min(3, int(seat["hearts"]) + 1)
                healed = True

        next_idx = self._next_alive_puffer_idx(self.puffer_turn)
        next_seat = self.puffer_players[next_idx]
        self.puffer_turn = next_idx
        self.puffer_fuse = round(max(6.0, 10.5 - 0.35 * len(self.puffer_used)), 1)
        self.phase_timer = self.puffer_fuse
        self.puffer_last_event = {
            "type": "pass",
            "by": seat["name"],
            "to": next_seat["name"],
            "canon": res["canonical"],
            "tierKey": res["tierKey"],
            "tierLabel": res["tierLabel"],
            "healed": healed,
        }
        kind = "krill_deep" if res["pts"] >= 85 else "krill_ping"
        self._events.append({"kind": kind, "role": r, "res": res})

        # Keep circle fresh if players rattle off 16+ valid answers on a single category
        if len(self.puffer_used) >= 16:
            self.round_idx += 1
            if self.round_idx >= len(self.selected_prompts):
                random.shuffle(self.selected_prompts)
                self.round_idx = 0
            self.puffer_used = []
            self.puffer_last_event["rotated"] = True
            self.puffer_fuse = 10.0
            self.phase_timer = self.puffer_fuse

        return {**res, "passedTo": next_seat["name"], "healed": healed}

    def submit_answer(self, role: str, raw: str, active_roles: set[str]) -> dict[str, Any]:
        r = role if role in ("guest", "host") else "guest"
        if self.phase != "answering" or self.round_idx >= len(self.selected_prompts):
            return {"status": "ignored"}
        prompt_entry = self.selected_prompts[self.round_idx]
        if self.mode == "puffer":
            return self._submit_puffer_answer(r, raw, prompt_entry)

        if r in self.pending_round_answers:
            return {"status": "already_locked"}

        st = self.settings_by_role.get(r, self._default_settings())
        res = self.evaluate_guess(
            raw,
            prompt_entry,
            answer_corrections=st["answerCorrections"],
            clear_rejected=st["clearRejected"],
        )
        self.last_feedback[r] = res
        if res["status"] == "scored":
            self.pending_round_answers[r] = res
            if res["pts"] >= 85:
                self._events.append({"kind": "krill_deep", "role": r, "res": res})
            else:
                self._events.append({"kind": "krill_ping", "role": r, "res": res})
            # Always wait for both Her (guest phone) and Him (host webcam) unless timer expires
            needed = {"guest", "host"} if self.mode == "couples" else {r}
            if needed.issubset(self.pending_round_answers.keys()):
                self._finalize_round(active_roles)
        elif res["status"] == "no_echo":
            self._events.append({"kind": "krill_miss", "role": r})
        return res

    def next_round(self) -> None:
        if self.phase != "reveal":
            return
        if self.mode == "puffer":
            self.round_idx += 1
            if self.round_idx >= len(self.selected_prompts):
                random.shuffle(self.selected_prompts)
                self.round_idx = 0
            self.puffer_last_event = {}
            self._enter_preview()
            return
        if self.round_idx + 1 < len(self.selected_prompts):
            self.round_idx += 1
            self._enter_preview()
        else:
            self._enter_surface()

    def _finalize_puffer_pop(self) -> None:
        if self.phase != "answering" or not self.puffer_players:
            return
        prompt_entry = self.selected_prompts[self.round_idx]
        entries = prompt_entry.get("answers", [])
        top_rare = entries[-1][0] if entries else ""
        seat = self.puffer_players[self.puffer_turn % len(self.puffer_players)]
        seat["hearts"] = max(0, int(seat.get("hearts", 0)) - 1)
        seat["alive"] = seat["hearts"] > 0

        self.puffer_last_event = {
            "type": "pop",
            "player": seat["name"],
            "heartsLeft": seat["hearts"],
            "eliminated": not seat["alive"],
            "passes": len(self.puffer_used),
            "sampleDeep": top_rare,
            "prompt": prompt_entry["prompt"],
        }
        empty_slot = {
            "locked": False,
            "canonical": None,
            "tierKey": "timeout",
            "tierLabel": "PUFFER POP",
            "pts": len(self.puffer_used) * 10,
            "depth": len(self.puffer_used) * 100,
            "note": f"{seat['name']} got spiked (-1 ♥)",
        }
        self.history.append({
            "round": len(self.history) + 1,
            "prompt": prompt_entry["prompt"],
            "sampleDeep": top_rare,
            "jinx": False,
            "poppedBy": seat["name"],
            "passes": len(self.puffer_used),
            "guest": empty_slot,
            "host": dict(empty_slot),
        })
        self._events.append({"kind": "krill_miss", "role": "guest"})

        alive = [p for p in self.puffer_players if p.get("alive")]
        if len(alive) <= 1:
            self.puffer_winner = alive[0]["name"] if alive else seat["name"]
            self._enter_surface()
            return

        self.puffer_turn = self._next_alive_puffer_idx(self.puffer_turn)
        self.phase = "reveal"
        self.phase_timer = 0.0
        self._events.append({"kind": "krill_reveal", "row": self.history[-1]})

    def _finalize_round(self, active_roles: set[str]) -> None:
        if self.phase != "answering":
            return
        if self.mode == "puffer":
            self._finalize_puffer_pop()
            return
        prompt_entry = self.selected_prompts[self.round_idx]
        entries = prompt_entry.get("answers", [])
        top_rare = entries[-1][0] if entries else ""
        guest_ans = self.pending_round_answers.get("guest")
        host_ans = self.pending_round_answers.get("host")

        jinx = False
        jinx_pts = int(self.theme.get("jinxPoints", 5))
        jinx_depth = jinx_pts * 10

        def make_slot(ans: dict[str, Any] | None, role_jinxed: bool) -> dict[str, Any]:
            if ans is None:
                return {
                    "locked": False,
                    "canonical": None,
                    "tierKey": "timeout",
                    "tierLabel": "NOTHING LANDED",
                    "pts": 0,
                    "depth": 0,
                    "note": "ran out of time",
                }
            if role_jinxed:
                return {
                    "locked": True,
                    "canonical": ans["canonical"],
                    "tierKey": "jinx",
                    "tierLabel": self.theme.get("jinxLabel", "JINX!"),
                    "pts": jinx_pts,
                    "depth": jinx_depth,
                    "note": f"you both said {ans['canonical']} — 5 pt jinx",
                }
            return {"locked": True, **ans}

        jinx_enabled = (
            self.mode == "couples"
            and bool(self.settings_by_role.get("guest", {}).get("couplesJinx", True))
            and bool(self.settings_by_role.get("host", {}).get("couplesJinx", True))
        )
        if jinx_enabled and guest_ans and host_ans:
            if normalize_answer(guest_ans["canonical"]) == normalize_answer(host_ans["canonical"]):
                jinx = True

        row = {
            "round": self.round_idx + 1,
            "prompt": prompt_entry["prompt"],
            "sampleDeep": top_rare,
            "jinx": jinx,
            "guest": make_slot(guest_ans, jinx),
            "host": make_slot(host_ans, jinx),
        }
        self.history.append(row)
        self.phase = "reveal"
        self.phase_timer = 0.0
        self._events.append({"kind": "krill_reveal", "row": row})

    def _enter_surface(self) -> None:
        self.phase = "surface"
        self.phase_timer = 0.0
        guest_total = sum(r["guest"]["pts"] for r in self.history)
        host_total = sum(r["host"]["pts"] for r in self.history)
        guest_depth = sum(r["guest"]["depth"] for r in self.history)
        total_ref = max(guest_total, host_total) if self.mode != "couples" else guest_total
        depth_ref = total_ref * 10
        jinx_hits = sum(1 for r in self.history if r.get("jinx"))
        rare_pulls = sum(1 for r in self.history if r["guest"]["pts"] >= 60 or r["host"]["pts"] >= 60)

        forfeit_map = ["seaweed", "bubble_helmet", "shrimp_partner", "neon_glow"]
        if self.mode == "couples":
            if guest_total != host_total:
                self.loser_role = "host" if guest_total > host_total else "guest"
                self.last_forfeit = forfeit_map[(guest_total + host_total) % len(forfeit_map)]
            else:
                self.loser_role = ""
                self.last_forfeit = ""

        self.store.record_krillion(total_ref, depth_ref, self.mode, jinx_hits, rare_pulls)
        self._events.append({
            "kind": "krill_surface",
            "guestTotal": guest_total,
            "hostTotal": host_total,
            "loserRole": self.loser_role,
            "forfeit": self.last_forfeit,
        })

    def step(self, dt: float, active_roles: set[str]) -> bool:
        changed = False
        if self.phase == "preview":
            self.phase_timer = max(0.0, self.phase_timer - dt)
            if self.phase_timer <= 0.0:
                self._enter_answering()
                changed = True
        elif self.phase == "answering":
            self.phase_timer = max(0.0, self.phase_timer - dt)
            if self.phase_timer <= 0.0:
                self._finalize_round(active_roles)
                changed = True
        return changed

    def bearing_for(self, total_pts: int) -> dict[str, Any]:
        # Scale bracket cleanly for 5 vs 7 rounds relative to default 7-round brackets
        scale = max(1, len(self.selected_prompts)) / 7.0
        for b in self.theme.get("bearing", []):
            if total_pts <= int(round(b["max"] * scale)):
                return b
        return {"name": "One in a krillion", "desc": "no way anyone else had that."}

    def percentile_for(self, total_pts: int) -> int:
        # Smooth bell-curve cumulative estimate for 7-prompt ~266 avg / ~95 std
        n = max(1, len(self.selected_prompts))
        mean = 38.0 * n
        std = 13.5 * n
        z = (total_pts - mean) / max(std, 1.0)
        cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        return max(1, min(99, int(round(cdf * 100))))

    def share_text(self, role: str = "guest") -> str:
        if self.mode == "puffer":
            passes = sum(int(p.get("passes", 0)) for p in self.puffer_players)
            return f"KRILLION — Circle Party\nWinner: {self.puffer_winner or 'Circle'}\n{passes} total passes across {len(self.history)} prompts"
        r_key = role if role in ("guest", "host") else "guest"
        title = self.theme.get("title", "KRILLION")
        sub = (
            "1v1 Dive" if self.mode == "couples"
            else ("Daily Dive" if self.mode == "daily" else "Free Dive ∞")
        )
        pts = sum(r[r_key]["pts"] for r in self.history)
        depth = sum(r[r_key]["depth"] for r in self.history)
        blocks = []
        for r in self.history:
            tk = r[r_key]["tierKey"]
            blocks.append({
                "krillion": "🫧",
                "deep_cut": "🟣",
                "rare": "🔵",
                "schooler": "🟢",
                "too_clever": "🟡",
                "plankton": "⚪",
                "jinx": "🕸️",
                "timeout": "⬛",
            }.get(tk, "🟦"))
        b = self.bearing_for(pts)
        lines = [
            f"{title} — {sub}",
            f"{pts} pts · -{depth:,}m · {b['name']}",
            "".join(blocks),
        ]
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        cur = self.selected_prompts[self.round_idx] if self.round_idx < len(self.selected_prompts) else None
        guest_total = sum(r["guest"]["pts"] for r in self.history)
        host_total = sum(r["host"]["pts"] for r in self.history)
        guest_depth = sum(r["guest"]["depth"] for r in self.history)
        host_depth = sum(r["host"]["depth"] for r in self.history)
        return {
            "mode": self.mode,
            "phase": self.phase,
            "roundIdx": self.round_idx,
            "totalRounds": len(self.selected_prompts) or self._round_count(self.mode),
            "timer": round(self.phase_timer, 2),
            "previewTotal": self._preview_seconds(),
            "answerTotal": self._answer_seconds(),
            "prompt": cur["prompt"] if cur else "",
            "locked": {
                "guest": "guest" in self.pending_round_answers,
                "host": "host" in self.pending_round_answers,
            },
            "feedback": self.last_feedback,
            "settings": self.settings_by_role,
            "history": self.history,
            "puffer": {
                "players": self.puffer_players,
                "turnIdx": self.puffer_turn,
                "used": self.puffer_used,
                "fuse": self.puffer_fuse,
                "lastEvent": self.puffer_last_event,
                "winner": self.puffer_winner,
            },
            "totals": {
                "guestPts": guest_total,
                "hostPts": host_total,
                "guestDepth": guest_depth,
                "hostDepth": host_depth,
                "guestBearing": self.bearing_for(guest_total),
                "hostBearing": self.bearing_for(host_total),
                "guestPercentile": self.percentile_for(guest_total),
                "hostPercentile": self.percentile_for(host_total),
            },
            "loserRole": self.loser_role,
            "forfeit": self.last_forfeit,
            "shareText": {
                "guest": self.share_text("guest"),
                "host": self.share_text("host"),
            },
            "stats": self.store.krillion_summary(),
            "theme": self.theme,
        }


class WordDuelMatch:
    """5-letter Word Duel (daily & head-to-head race)."""

    def __init__(self, data_dir: Path, store: StreaksStore) -> None:
        self.store = store
        words = json.loads((data_dir / "word_duel_words.json").read_text(encoding="utf-8"))
        self.targets: list[str] = [str(w).upper() for w in words.get("targets", []) if len(str(w)) == 5]
        extra = [str(w).upper() for w in words.get("extra_valid", []) if len(str(w)) == 5]
        self.valid_set: set[str] = set(self.targets) | set(extra)
        self.mode: str = "duel"  # "duel" | "daily"
        self.phase: str = "playing"
        self.target: str = "CRANE"
        self.started_at: float = time.monotonic()
        self.boards: dict[str, dict[str, Any]] = {}
        self.winner: str | None = None
        self.error_by_role: dict[str, str] = {"guest": "", "host": ""}
        self._events: list[dict[str, Any]] = []
        self.start("duel")

    def pop_events(self) -> list[dict[str, Any]]:
        ev = self._events
        self._events = []
        return ev

    @staticmethod
    def score_word(guess: str, target: str) -> list[str]:
        g = guess.upper()
        t = target.upper()
        res = ["absent"] * 5
        rem: dict[str, int] = {}
        for i in range(5):
            if g[i] == t[i]:
                res[i] = "correct"
            else:
                rem[t[i]] = rem.get(t[i], 0) + 1
        for i in range(5):
            if res[i] == "correct":
                continue
            ch = g[i]
            if rem.get(ch, 0) > 0:
                res[i] = "present"
                rem[ch] -= 1
        return res

    def start(self, mode: str = "duel") -> None:
        # Strict 1v1 race only
        self.mode = "duel"
        if self.mode == "daily":
            today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
            rng = random.Random(f"word-duel-{today}")
            self.target = rng.choice(self.targets)
        else:
            self.target = random.choice(self.targets)
        self.phase = "playing"
        self.started_at = time.monotonic()
        self.winner = None
        self.error_by_role = {"guest": "", "host": ""}
        self.boards = {
            "guest": {"rows": [], "done": False, "solved": False, "finishTime": None},
            "host": {"rows": [], "done": False, "solved": False, "finishTime": None},
        }

    def submit_guess(self, role: str, word_raw: str, active_roles: set[str] | None = None) -> dict[str, Any]:
        r = role if role in ("guest", "host") else "guest"
        b = self.boards[r]
        if self.phase != "playing" or b["done"]:
            return {"ok": False, "error": "Round finished"}
        w = re.sub(r"[^A-Za-z]", "", str(word_raw)).upper()
        if len(w) != 5:
            msg = "Need 5 letters"
            self.error_by_role[r] = msg
            return {"ok": False, "error": msg}
        if w not in self.valid_set:
            msg = f"{w} not in word list"
            self.error_by_role[r] = msg
            return {"ok": False, "error": msg}

        self.error_by_role[r] = ""
        states = self.score_word(w, self.target)
        b["rows"].append({"word": w, "states": states})
        solved = (w == self.target)
        if solved or len(b["rows"]) >= 6:
            b["done"] = True
            b["solved"] = solved
            b["finishTime"] = round(time.monotonic() - self.started_at, 2)
            self._events.append({"kind": "word_row", "role": r, "word": w, "states": states, "solved": solved})
        else:
            self._events.append({"kind": "word_row", "role": r, "word": w, "states": states, "solved": False})

        self._check_finish(active_roles or {"guest", "host"})
        return {"ok": True, "states": states, "solved": solved}

    def _check_finish(self, active_roles: set[str]) -> None:
        g, h = self.boards["guest"], self.boards["host"]
        # Always race both Her (phone guest) and Him (webcam host)
        done_now = g["done"] and h["done"]
        if not done_now:
            return
        self.phase = "finished"
        if g["solved"] and h["solved"]:
            if len(g["rows"]) != len(h["rows"]):
                self.winner = "guest" if len(g["rows"]) < len(h["rows"]) else "host"
            else:
                self.winner = "guest" if (g["finishTime"] or 999) <= (h["finishTime"] or 999) else "host"
        elif g["solved"]:
            self.winner = "guest"
        elif h["solved"]:
            self.winner = "host"
        else:
            self.winner = "draw"
        self.store.record_word_duel(g["solved"], self.mode)
        if self.winner in ("guest", "host"):
            self._events.append({"kind": "word_win", "winner": self.winner, "target": self.target})

    def emoji_grid(self, role: str) -> str:
        r = role if role in ("guest", "host") else "guest"
        rows = self.boards[r]["rows"]
        m = {"correct": "🟩", "present": "🟨", "absent": "⬛"}
        grid = "\n".join("".join(m.get(s, "⬛") for s in row["states"]) for row in rows)
        score = f"{len(rows)}/6" if self.boards[r]["solved"] else "X/6"
        return f"Word Duel ({score})\n{grid}"

    def snapshot_for(self, role: str) -> dict[str, Any]:
        # Never leak opponent's actual guessed letters; expose colored tile silhouette + letter count
        out_boards: dict[str, Any] = {}
        for r_key, b in self.boards.items():
            reveal_letters = (r_key == role) or (self.phase == "finished")
            out_boards[r_key] = {
                "done": b["done"],
                "solved": b["solved"],
                "finishTime": b["finishTime"],
                "rows": [
                    {
                        "word": row["word"] if reveal_letters else "?????",
                        "states": row["states"],
                    }
                    for row in b["rows"]
                ],
            }
        return {
            "mode": self.mode,
            "phase": self.phase,
            "target": self.target if self.phase == "finished" else None,
            "winner": self.winner,
            "boards": out_boards,
            "error": self.error_by_role.get(role, ""),
            "shareText": self.emoji_grid(role),
            "stats": dict(self.store.data["wordDuel"]),
        }
