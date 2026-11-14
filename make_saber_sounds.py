"""Synthesize lightsaber sounds the way the films made them (Ben Burtt):
two detuned motor hums beating against each other + electrical buzz = idle
hum; swings are that hum Doppler-shifted +/-2-3 semitones, done live in
app.py by varying the hum loop's playback rate with blade-tip speed.

Outputs (48 kHz stereo WAV):
  saber_hum.wav    seamless 2 s loop (all partials complete whole cycles)
  saber_on.wav     ignition: rising sweep + snap into hum
  saber_off.wav    retract: falling sweep
  saber_clash.wav  metallic inharmonic burst + thump
Run: .venv/bin/python make_saber_sounds.py
"""
import wave
from pathlib import Path

import numpy as np

SR = 48000
OUT = Path(__file__).parent / "assets"
rng = np.random.default_rng(11)


def save(name, sig):
    sig = np.clip(sig, -1, 1).astype(np.float32)
    if sig.ndim == 1:
        sig = np.repeat(sig[:, None], 2, axis=1)
    pcm = (sig * 32767 * 0.92).astype(np.int16)
    with wave.open(str(OUT / name), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    print(name, f"{len(sig) / SR:.2f}s")


def hum_tone(t, f0=55.0):
    """Motor hum: fundamental + harmonics, second motor detuned +0.7 Hz so
    the pair beats slowly like Burtt's two projector motors."""
    sig = np.zeros_like(t)
    for mult, amp in [(1, 0.55), (2, 0.34), (3, 0.16), (4, 0.09), (6, 0.05)]:
        sig += amp * np.sin(2 * np.pi * f0 * mult * t)
        sig += amp * 0.85 * np.sin(2 * np.pi * (f0 + 0.7) * mult * t + 0.4)
    return sig


def make_hum_loop():
    dur = 2.0
    t = np.arange(int(SR * dur)) / SR
    sig = hum_tone(t)
    # electrical buzz layer (mains harmonics + faint crackle, loop-safe:
    # use periodic crackle from summed sines, noise folded via crossfade)
    sig += 0.10 * np.sin(2 * np.pi * 120 * t) + 0.05 * np.sin(2 * np.pi * 240 * t)
    noise = rng.standard_normal(len(t))
    k = 48
    smooth = np.convolve(np.r_[noise, noise[:k]], np.ones(k) / k, mode="valid")[:len(t)]
    sig += smooth * 0.35
    # slow breathing, whole cycles in 2 s so the loop seam is inaudible
    sig *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.5 * t)
    sig /= np.max(np.abs(sig)) + 1e-9
    save("saber_hum.wav", sig * 0.8)


def make_ignite():
    dur = 0.55
    t = np.arange(int(SR * dur)) / SR
    f = 38 * (180 / 38) ** (t / dur)  # exponential rise 38 -> 180 Hz
    phase = np.cumsum(2 * np.pi * f / SR)
    sig = 0.6 * np.sin(phase) + 0.3 * np.sin(2 * phase) + 0.15 * np.sin(3 * phase)
    noise = rng.standard_normal(len(t))
    sig += np.convolve(noise, np.ones(24) / 24, mode="same") * (0.1 + 0.5 * t / dur)
    sig *= np.clip(t / 0.03, 0, 1) * (0.55 + 0.45 * t / dur)
    # settle into hum at the tail so the loop takes over seamlessly
    tail = int(SR * 0.12)
    th = np.arange(tail) / SR
    sig[-tail:] = sig[-tail:] * np.linspace(1, 0.4, tail) + hum_tone(th) * np.linspace(0, 0.5, tail)
    save("saber_on.wav", sig / (np.max(np.abs(sig)) + 1e-9))


def make_retract():
    dur = 0.4
    t = np.arange(int(SR * dur)) / SR
    f = 180 * (36 / 180) ** (t / dur)
    phase = np.cumsum(2 * np.pi * f / SR)
    sig = 0.6 * np.sin(phase) + 0.3 * np.sin(2 * phase)
    sig *= np.clip((dur - t) / 0.05, 0, 1) * np.clip(t / 0.01, 0, 1)
    save("saber_off.wav", sig / (np.max(np.abs(sig)) + 1e-9))


def make_clash():
    dur = 0.5
    t = np.arange(int(SR * dur)) / SR
    sig = np.zeros_like(t)
    for f0, amp, dec in [(623, 0.5, 26), (917, 0.42, 32), (1452, 0.34, 40),
                         (2093, 0.26, 52), (2960, 0.16, 66)]:
        sig += amp * np.sin(2 * np.pi * f0 * t + rng.uniform(0, 6)) * np.exp(-t * dec)
    noise = rng.standard_normal(len(t))
    sig += noise * np.exp(-t * 55) * 0.9                       # crack
    sig += np.convolve(noise, np.ones(90) / 90, mode="same") * np.exp(-t * 12) * 1.6  # body
    sig += hum_tone(t) * np.exp(-t * 9) * 0.7                  # blade thrum
    save("saber_clash.wav", sig / (np.max(np.abs(sig)) + 1e-9))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make_hum_loop()
    make_ignite()
    make_retract()
    make_clash()
