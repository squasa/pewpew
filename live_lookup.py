"""Live Wikidata/Wikipedia answer verifier & rarity scorer for Krillion.

Prevents hard-coded prompt banks from rejecting genuine obscure answers
(e.g. "Lagotto Romagnolo", "Azawakh", "Cascatelli", "Praseodymium").
Caches all lookups in memory and optionally to disk so repeat queries are 0ms,
and degrades gracefully to None when offline or rate-limited.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

UA = "PewPewArcade/1.0 (https://localhost; dev@localhost)"
_DEFAULT_ANTI_KEYWORDS = (
    "wikimedia disambiguation",
    "disambiguation page",
    "family name",
    "given name",
    "surname",
    "studio album",
    "ep album",
    "single by",
    "song by",
    "track by",
    "film directed",
    "television series",
    "tv series",
    "video game",
    "fictional character",
    "footballer",
    "baseball player",
    "basketball player",
    "politician",
)


def _norm_simple(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\([^)]*\)", "", s).lower().strip()
    s = s.replace("&", " and ").replace("'", "").replace(".", "")
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    for art in ("the ", "a ", "an ", "my "):
        if s.startswith(art) and len(s) >= len(art) + 2:
            s = s[len(art):].strip()
            break
    return s


def _damerau(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > 2:
        return 99
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            best = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                best = min(best, d[i - 2][j - 2] + 1)
            d[i][j] = best
    return d[la][lb]


class LiveKnowledgeVerifier:
    """Thread-safe / single-process cached Wikidata + Wikipedia fallback verifier."""

    def __init__(self, cache_path: Path | None = None, enabled: bool | None = None) -> None:
        self.cache_path = cache_path
        if enabled is None:
            env_off = os.environ.get("PEWPEW_OFFLINE", "").strip().lower() in ("1", "true", "yes")
            self.enabled = not env_off
        else:
            self.enabled = enabled
        self._mem: dict[str, dict[str, Any] | None] = {}
        self._fail_until: float = 0.0
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._mem.update(data)
        except Exception:
            pass

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            # Cap persisted entries reasonably
            items = list(self._mem.items())[-1500:]
            self.cache_path.write_text(json.dumps(dict(items), indent=1) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _fetch_json(self, url: str, timeout: float = 1.6) -> dict[str, Any] | list[Any] | None:
        if not self.enabled or time.monotonic() < self._fail_until:
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            # Brief backoff on transient failure / offline sandbox
            self._fail_until = time.monotonic() + 8.0
            return None

    @staticmethod
    def _matches_label(norm_user: str, label: str, desc_hint_words: list[str]) -> bool:
        nl = _norm_simple(label)
        if not nl:
            return False
        if nl == norm_user:
            return True
        if nl.replace(" ", "") == norm_user.replace(" ", ""):
            return True
        # e.g. "Bolognese" matching "Bolognese dog" or "Corgi" matching "Welsh Corgi"
        u_toks = norm_user.split()
        l_toks = nl.split()
        if len(u_toks) == 1 and len(l_toks) == 2 and u_toks[0] in l_toks:
            other = l_toks[1] if l_toks[0] == u_toks[0] else l_toks[0]
            if any(h in other or other in h for h in desc_hint_words):
                return True
        # Minor 1-letter typo on >=5 char query against exact entity label
        if len(norm_user) >= 5 and len(nl) >= 5 and norm_user[0] == nl[0]:
            if _damerau(norm_user, nl) <= 1:
                return True
        return False

    @staticmethod
    def _matches_keywords(
        text_blob: str,
        keywords: list[str],
        anti_keywords: list[str],
        must_include: list[str] | None = None,
        hard_anti: list[str] | None = None,
    ) -> bool:
        low = " " + re.sub(r"[^a-z0-9\s]", " ", text_blob.lower()) + " "
        if must_include:
            if not any(m.lower() in low for m in must_include):
                return False
        always_block = (
            "disambiguation page",
            "wikimedia disambiguation",
            "studio album",
            "single by",
            "song by",
            "track by",
            "family name",
            "given name",
            "surname",
        )
        for bad in list(always_block) + list(hard_anti or []):
            b = bad.lower().strip()
            if b and (f" {b} " in low or b in low):
                return False
        for anti in anti_keywords:
            if f" {anti.lower()} " in low or anti.lower() in low:
                if not any(kw.lower() in low for kw in keywords):
                    return False
        for kw in keywords:
            k = kw.lower().strip()
            if not k:
                continue
            if " " in k:
                if k in low:
                    return True
            else:
                if f" {k} " in low or f" {k}s " in low or re.search(rf"\b{re.escape(k)}\w*", low):
                    return True
        return False

    @staticmethod
    def _check_constraints(norm_user: str, canon_label: str, verify: dict[str, Any]) -> bool:
        nl = _norm_simple(canon_label)
        sw = str(verify.get("startsWith", "")).lower().strip()
        if sw:
            if not (norm_user.startswith(sw) and (nl.startswith(sw) or norm_user.startswith(sw))):
                return False
        exact_len = verify.get("exactLen")
        if exact_len:
            n_ns = norm_user.replace(" ", "")
            l_ns = nl.replace(" ", "")
            if len(n_ns) != int(exact_len) and len(l_ns) != int(exact_len):
                return False
        return True

    def _wikidata_lookup(self, norm_user: str, verify: dict[str, Any]) -> dict[str, Any] | None:
        keywords = [str(k) for k in verify.get("keywords", []) if str(k).strip()]
        if not keywords:
            return None
        must_include = [str(k) for k in verify.get("mustInclude", []) if str(k).strip()]
        hard_anti = [str(k) for k in verify.get("antiKeywords", []) if str(k).strip()]
        anti = list(_DEFAULT_ANTI_KEYWORDS)
        hint_words = [k.split()[0].lower() for k in keywords if k]

        q = urllib.parse.quote(norm_user)
        url = (
            "https://www.wikidata.org/w/api.php?action=wbsearchentities"
            f"&search={q}&language=en&limit=8&format=json"
        )
        data = self._fetch_json(url, timeout=1.6)
        if not isinstance(data, dict):
            return None

        best_hit: dict[str, Any] | None = None
        for item in data.get("search", []):
            label = str(item.get("label", "")).strip()
            desc = str(item.get("description", "")).strip()
            match_txt = str(item.get("match", {}).get("text", "")).strip()
            if not desc:
                continue
            label_ok = self._matches_label(norm_user, label, hint_words) or (
                match_txt and self._matches_label(norm_user, match_txt, hint_words)
            )
            if not label_ok:
                continue
            if self._matches_keywords(f"{label} {desc}", keywords, anti, must_include, hard_anti):
                best_hit = {"id": str(item.get("id", "")), "label": label, "desc": desc}
                break

        # Fallback: Wikipedia opensearch with primary category hint (e.g. "boxer" -> "Boxer (dog breed)")
        if best_hit is None and keywords:
            topic = str(verify.get("searchHint") or keywords[0])
            wq = urllib.parse.quote(f"{norm_user} {topic}")
            wurl = (
                "https://en.wikipedia.org/w/api.php?action=opensearch"
                f"&search={wq}&limit=3&namespace=0&redirects=resolve&format=json"
            )
            wdata = self._fetch_json(wurl, timeout=1.5)
            titles = wdata[1] if isinstance(wdata, list) and len(wdata) > 1 and isinstance(wdata[1], list) else []
            for title in titles[:2]:
                clean_title = re.sub(r"\s*\([^)]*\)\s*", "", str(title)).strip()
                if not self._matches_label(norm_user, clean_title, hint_words):
                    continue
                t_enc = urllib.parse.quote(str(title).replace(" ", "_"))
                sdata = self._fetch_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{t_enc}", timeout=1.5)
                if not isinstance(sdata, dict):
                    continue
                blob = f"{sdata.get('title', '')} {sdata.get('description', '')} {sdata.get('extract', '')[:220]}"
                if self._matches_keywords(blob, keywords, anti, must_include, hard_anti):
                    best_hit = {
                        "id": str(sdata.get("wikibase_item", "")),
                        "label": clean_title,
                        "desc": str(sdata.get("description", "")).strip(),
                    }
                    break

        if best_hit is None:
            return None
        if not self._check_constraints(norm_user, best_hit["label"], verify):
            return None

        # Determine genuine rarity via Wikidata sitelinks count
        sitelinks = 20
        qid = best_hit.get("id", "")
        if qid.startswith("Q"):
            ent_url = f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}&props=sitelinks&format=json"
            edata = self._fetch_json(ent_url, timeout=1.3)
            if isinstance(edata, dict):
                ent = (edata.get("entities") or {}).get(qid, {})
                if isinstance(ent, dict) and "sitelinks" in ent:
                    sitelinks = len(ent.get("sitelinks") or {})

        tier_key = self._tier_for_sitelinks(sitelinks, str(verify.get("scale", "default")))
        canon = best_hit["label"]
        if canon.islower():
            canon = canon.title()
        return {
            "canonical": canon,
            "tierKey": tier_key,
            "desc": best_hit["desc"],
            "sitelinks": sitelinks,
        }

    @staticmethod
    def _tier_for_sitelinks(sitelinks: int, scale: str) -> str:
        # Sovereign countries / chemical elements naturally have 100-300+ Wikipedia editions
        if scale == "global":
            if sitelinks <= 175:
                return "krillion"
            if sitelinks <= 245:
                return "deep_cut"
            if sitelinks <= 305:
                return "rare"
            return "schooler"
        if sitelinks <= 12:
            return "krillion"
        if sitelinks <= 32:
            return "deep_cut"
        if sitelinks <= 95:
            return "rare"
        return "schooler"

    def verify(self, raw: str, prompt_entry: dict[str, Any]) -> dict[str, Any] | None:
        """Return {'canonical', 'tierKey', 'desc', 'sitelinks'} if verified, else None."""
        verify = prompt_entry.get("verify")
        if not isinstance(verify, dict) or not self.enabled:
            return None
        kind = verify.get("kind", "wiki")
        norm = _norm_simple(raw)
        if len(norm.replace(" ", "")) < int(verify.get("minChars", 3)):
            return None
        if len(norm.split()) > 6:
            return None
        if not re.search(r"[aeiouy]", norm) and not verify.get("allowNoVowel"):
            return None
        if not self._check_constraints(norm, raw.strip(), verify):
            return None
        if kind != "wiki":
            return None

        cache_key = f"{prompt_entry.get('id', 'p')}:{norm}"
        if cache_key in self._mem:
            return self._mem[cache_key]

        res = self._wikidata_lookup(norm, verify)
        self._mem[cache_key] = res
        self._save_cache()
        return res
