"""Synthesize original procedural WAV SFX for pewpew Stage 2 & Stage 3 games."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000
ASSETS = Path(__file__).parent / "assets"


def _save_wav(path: Path, data: np.ndarray) -> None:
    arr = np.clip(data, -1.0, 1.0)
    pcm = (arr * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def _tone(dur: float, f0: float, f1: float | None = None, amp: float = 0.5, wave_type: str = "sine") -> np.ndarray:
    n = int(SR * dur)
    t = np.linspace(0.0, dur, n, endpoint=False)
    if f1 is None or abs(f1 - f0) < 1e-3:
        phase = 2.0 * np.pi * f0 * t
    else:
        freqs = np.linspace(f0, f1, n)
        phase = 2.0 * np.pi * np.cumsum(freqs) / SR
    if wave_type == "tri":
        sig = 2.0 / np.pi * np.arcsin(np.sin(phase))
    elif wave_type == "sq":
        sig = np.tanh(2.5 * np.sin(phase))
    else:
        sig = np.sin(phase)
    env = np.minimum(1.0, t / 0.006) * np.exp(-t / max(dur * 0.35, 0.02))
    return (sig * env * amp).astype(np.float32)


def _mix(*arrs: np.ndarray) -> np.ndarray:
    n = max(len(a) for a in arrs)
    out = np.zeros(n, dtype=np.float32)
    for a in arrs:
        out[: len(a)] += a
    return out


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    rng = np.random.default_rng(42)

    # 1. Dart whoosh + suction pop
    whoosh = rng.standard_normal(int(SR * 0.14)).astype(np.float32)
    t = np.linspace(0, 0.14, len(whoosh))
    whoosh = np.convolve(whoosh, np.ones(14) / 14.0, mode="same") * np.sin(np.pi * t / 0.14) * 0.45
    _save_wav(ASSETS / "sfx_dart_throw.wav", whoosh)

    suction = _mix(_tone(0.11, 210, 520, amp=0.55, wave_type="sine"), _tone(0.06, 950, 380, amp=0.25))
    _save_wav(ASSETS / "sfx_dart_hit.wav", suction)

    block = _mix(_tone(0.16, 480, 1180, amp=0.45, wave_type="tri"), _tone(0.12, 160, 110, amp=0.35))
    _save_wav(ASSETS / "sfx_dart_block.wav", block)

    # 2. Mouth catch crunch & splat
    crunch_n = rng.standard_normal(int(SR * 0.12)).astype(np.float32) * np.exp(-np.linspace(0, 8, int(SR * 0.12)))
    catch = _mix(_tone(0.18, 523.25, 784.0, amp=0.50, wave_type="tri"), crunch_n * 0.28)
    _save_wav(ASSETS / "sfx_catch.wav", catch)

    splat_n = rng.standard_normal(int(SR * 0.20)).astype(np.float32)
    splat_lp = np.convolve(splat_n, np.ones(28) / 28.0, mode="same")
    splat = _mix(splat_lp * np.exp(-np.linspace(0, 7, len(splat_lp))) * 0.8, _tone(0.18, 190, 75, amp=0.35))
    _save_wav(ASSETS / "sfx_splat.wav", splat)

    # 3. Pool ball clack & pocket drop
    clack = _mix(_tone(0.045, 2200, 1100, amp=0.65), _tone(0.035, 3600, 2100, amp=0.35))
    _save_wav(ASSETS / "sfx_pool_hit.wav", clack)

    pot = np.concatenate([_tone(0.08, 330, 260, amp=0.45), _tone(0.16, 523.25, 659.25, amp=0.50, wave_type="tri")])
    _save_wav(ASSETS / "sfx_pool_pot.wav", pot)

    # 4. Beer pong splash
    splash_n = rng.standard_normal(int(SR * 0.28)).astype(np.float32)
    splash_bp = np.convolve(splash_n, np.ones(10) / 10.0, mode="same") - np.convolve(splash_n, np.ones(45) / 45.0, mode="same")
    splash = _mix(splash_bp * np.exp(-np.linspace(0, 6.5, len(splash_bp))) * 1.1, _tone(0.18, 340, 880, amp=0.35))
    _save_wav(ASSETS / "sfx_pong_cup.wav", splash)

    # 5. Word Duel / Celebration chime
    fanfare = np.concatenate([
        _tone(0.10, 523.25, None, amp=0.42, wave_type="tri"),
        _tone(0.10, 659.25, None, amp=0.42, wave_type="tri"),
        _tone(0.24, 783.99, None, amp=0.48, wave_type="tri"),
    ])
    _save_wav(ASSETS / "sfx_word_win.wav", fanfare)

    # 6. Krillion / Rare Answer sonar pings, rare chord, and no-echo sonar buzz
    sonar_ping = _mix(_tone(0.32, 1320.0, 1312.0, amp=0.40), _tone(0.28, 2640.0, 2635.0, amp=0.14))
    _save_wav(ASSETS / "sfx_krill_ping.wav", sonar_ping)

    deep_chime = (
        _tone(0.45, 523.25, 523.25, amp=0.30, wave_type="sine")
        + _tone(0.45, 783.99, 783.99, amp=0.28, wave_type="sine")
        + _tone(0.45, 1046.5, 1046.5, amp=0.25, wave_type="tri")
    )
    _save_wav(ASSETS / "sfx_krill_deep.wav", deep_chime)

    miss_buzz = _tone(0.18, 175.0, 135.0, amp=0.42, wave_type="sq")
    _save_wav(ASSETS / "sfx_krill_miss.wav", miss_buzz)
    print(f"Generated 12 game SFX WAVs in {ASSETS}")


if __name__ == "__main__":
    main()
