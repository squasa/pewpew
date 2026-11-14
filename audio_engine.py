"""Audio engine: separate real-mic -> BlackHole 2ch ring-buffer mixer + live safeguards."""
from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import numpy as np


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        sr, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
        raw = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return raw.reshape(-1, ch), sr


def _resample_buf(src: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or len(src) == 0:
        return src.astype(np.float32)
    n_out = max(1, int(round(len(src) * dst_sr / src_sr)))
    idx = np.linspace(0.0, len(src) - 1, n_out, endpoint=False)
    cols = [np.interp(idx, np.arange(len(src)), src[:, c]) for c in range(src.shape[1])]
    return np.stack(cols, axis=1).astype(np.float32)


class ResamplingRingBuffer:
    """Thread-safe stereo ring buffer bridging independent input & output clocks/rates."""

    def __init__(self, in_sr: int, out_sr: int, capacity_s: float = 0.35, target_latency_s: float = 0.032):
        self.in_sr = float(in_sr)
        self.out_sr = float(out_sr)
        self.cap = max(2048, int(round(self.in_sr * capacity_s)))
        self.target_fill = max(256.0, self.in_sr * target_latency_s)
        self.buf = np.zeros((self.cap, 2), dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0.0
        self.fill = 0.0
        self._lock = threading.Lock()
        self.underruns = 0
        self.overruns = 0

    def configure_rates(self, in_sr: int, out_sr: int) -> None:
        with self._lock:
            self.in_sr = float(in_sr)
            self.out_sr = float(out_sr)
            self.target_fill = max(256.0, self.in_sr * 0.032)
            self.write_pos = 0
            self.read_pos = 0.0
            self.fill = 0.0

    def clear(self) -> None:
        with self._lock:
            self.buf.fill(0.0)
            self.write_pos = 0
            self.read_pos = 0.0
            self.fill = 0.0

    def push(self, indata: np.ndarray) -> None:
        if len(indata) == 0:
            return
        if indata.ndim == 1:
            stereo = np.column_stack([indata, indata])
        elif indata.shape[1] == 1:
            stereo = np.repeat(indata, 2, axis=1)
        else:
            stereo = indata[:, :2]
        n = len(stereo)
        with self._lock:
            if n >= self.cap:
                stereo = stereo[-self.cap:]
                n = len(stereo)
            if self.fill + n > self.cap:
                # Drop oldest samples smoothly rather than wrapping over unread audio
                drop = (self.fill + n) - self.cap
                self.read_pos = (self.read_pos + drop) % self.cap
                self.fill -= drop
                self.overruns += 1
            end = self.write_pos + n
            if end <= self.cap:
                self.buf[self.write_pos:end] = stereo
            else:
                first = self.cap - self.write_pos
                self.buf[self.write_pos:] = stereo[:first]
                self.buf[:n - first] = stereo[first:]
            self.write_pos = end % self.cap
            self.fill += n

    def pop(self, frames: int, out_ch: int = 2) -> np.ndarray:
        if frames <= 0:
            return np.zeros((0, out_ch), dtype=np.float32)
        with self._lock:
            base_ratio = self.in_sr / max(self.out_sr, 1.0)
            # Gentle ±0.3% clock-drift lock around target_fill (~32ms)
            drift_err = (self.fill - self.target_fill) / max(self.target_fill, 1.0)
            adj = float(np.clip(drift_err * 0.002, -0.003, 0.003))
            step = base_ratio * (1.0 + adj)
            needed = frames * step + 1.0
            if self.fill < needed:
                avail_frames = max(0, int((self.fill - 1.0) / max(step, 1e-6)))
                self.underruns += 1
            else:
                avail_frames = frames
            out = np.zeros((frames, out_ch), dtype=np.float32)
            if avail_frames > 0:
                pos = self.read_pos + np.arange(avail_frames, dtype=np.float64) * step
                i0 = np.floor(pos).astype(np.int64) % self.cap
                i1 = (i0 + 1) % self.cap
                frac = (pos - np.floor(pos)).astype(np.float32)[:, None]
                seg = self.buf[i0] * (1.0 - frac) + self.buf[i1] * frac
                if out_ch == 1:
                    out[:avail_frames, 0] = seg.mean(axis=1)
                else:
                    out[:avail_frames, :2] = seg[:, :2]
                if avail_frames < frames:
                    fade = np.linspace(1.0, 0.0, min(16, avail_frames), dtype=np.float32)[:, None]
                    out[avail_frames - len(fade):avail_frames] *= fade
                consumed = avail_frames * step
                self.read_pos = (self.read_pos + consumed) % self.cap
                self.fill = max(0.0, self.fill - consumed)
            return out


MONITOR_MODES = ("off", "sfx", "mic_sfx")


def is_virtual_audio_name(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in ("blackhole", "bgm", "background music", "soundflower", "loopback"))


def _is_multi_output(name: str) -> bool:
    return "multi-output" in name.lower()


class AudioEngine:
    """Real-mic passthrough + SFX/saber mixer -> BlackHole 2ch with local monitor & safeguards."""

    def __init__(
        self,
        assets_dir: Path,
        enabled: bool = True,
        mic_selector: str | None = None,
        monitor_mode: str = "off",
    ):
        self.assets_dir = assets_dir
        self.mode = "off"
        self.monitor_mode = monitor_mode if monitor_mode in MONITOR_MODES else "off"
        self.pop_time = 0.0
        self.sr = 48000
        self.in_sr = 48000
        self.in_ch = 1
        self.out_ch = 2
        self.mon_sr = 48000
        self.mon_ch = 2
        self.in_device_name = "none"
        self.out_device_name = "none"
        self.mon_device_name = "none"
        self.available_mics: list[tuple[int, str]] = []
        self._mic_idx: int | None = None
        self._bh_idx: int | None = None
        self._mon_idx: int | None = None
        self._mic_pinned = mic_selector is not None

        self.mic_rms = 0.0
        self.mic_peak = 0.0
        self.bh_rms = 0.0
        self.bh_peak = 0.0
        self._in_callbacks = 0
        self._out_callbacks = 0
        self._last_in_cb = 0.0
        self._last_out_cb = 0.0
        self._zero_since: float | None = None
        self._auto_switched_from_zero = False
        self._last_recover_try = 0.0
        self._last_status_err = ""

        self._sfx: np.ndarray | None = None
        self._sfx_pos = 0
        self._voices: list[list] = []
        self._voice_lock = threading.Lock()
        self._prev_peak = 0.0
        self._bufs: dict[str, np.ndarray] = {}
        self._raw_bufs: dict[str, tuple[np.ndarray, int]] = {}
        self._in_stream = None
        self._out_stream = None
        self._mon_stream = None
        self._ring = ResamplingRingBuffer(48000, 48000)
        self._mon_mic_ring = ResamplingRingBuffer(48000, 48000, target_latency_s=0.020)
        self._sfx_mon_ring = ResamplingRingBuffer(48000, 48000, target_latency_s=0.018)

        # Continuous saber hum & whoosh (dual-hand capable)
        self._hum_pos = 0.0
        self._hum_gain = 0.0
        self._hum_target = 0.0
        self._hum2_pos = 1400.0
        self._hum2_gain = 0.0
        self._hum2_target = 0.0
        self._hum_rate = 1.0
        self._hum_rate_target = 1.0
        self._swing_gain = 0.0
        self._swing_target = 0.0
        self._noise_lp = 0.0
        self._rng = np.random.default_rng(3)

        if not enabled:
            return
        try:
            import sounddevice as sd
            self._sd = sd
            self._load_all_sfx()
            self._start_audio(mic_selector)
        except Exception as exc:
            self._last_status_err = f"{type(exc).__name__}: {exc}"
            print(f"[audio] ERROR disabled: {self._last_status_err}")
            self.mode = "off"

    def _load_all_sfx(self) -> None:
        files = {
            "gunshot": self.assets_dir / "gunshot.wav",
            "hum": self.assets_dir / "saber_hum.wav",
            "on": self.assets_dir / "saber_on.wav",
            "off": self.assets_dir / "saber_off.wav",
            "clash": self.assets_dir / "saber_clash.wav",
        }
        for p in sorted(self.assets_dir.glob("sfx_*.wav")):
            files[p.stem[4:]] = p
        for key, path in files.items():
            try:
                self._raw_bufs[key] = load_wav(path)
            except Exception as exc:
                print(f"[audio] missing {path.name}: {exc}")
        if "gunshot" in self._raw_bufs:
            self.sr = self._raw_bufs["gunshot"][1]

    def _prepare_sfx_for_rate(self, out_sr: int) -> None:
        self._bufs = {
            k: _resample_buf(arr, src_sr, out_sr)
            for k, (arr, src_sr) in self._raw_bufs.items()
        }
        self.sr = out_sr

    def _discover_devices(self, mic_selector: str | None = None) -> tuple[int | None, list[int]]:
        devs = self._sd.query_devices()
        print("[audio] CoreAudio devices:")
        for i, d in enumerate(devs):
            print(f"  [{i}] {d['name']} (in={d['max_input_channels']}, out={d['max_output_channels']}, sr={int(d['default_samplerate'])}Hz)")

        bh_out = next(
            (i for i, d in enumerate(devs) if "blackhole" in d["name"].lower() and d["max_output_channels"] > 0),
            None,
        )
        mics = [
            i for i, d in enumerate(devs)
            if d["max_input_channels"] > 0 and not is_virtual_audio_name(d["name"])
        ]
        self.available_mics = [(i, devs[i]["name"]) for i in mics]

        default_in = self._sd.default.device[0] if self._sd.default.device else None
        if default_in == -1:
            default_in = None
        if default_in is not None and 0 <= default_in < len(devs) and "blackhole" in devs[default_in]["name"].lower():
            print(f"[audio] NOTE: macOS system default input is '{devs[default_in]['name']}' "
                  "(that is normal if FaceTime uses BlackHole, pewpew will still read your real mic)")

        ordered: list[int] = []
        if mic_selector is not None:
            if mic_selector.isdigit() and int(mic_selector) in mics:
                ordered.append(int(mic_selector))
            else:
                low = mic_selector.lower()
                for i in mics:
                    if low in devs[i]["name"].lower():
                        ordered.append(i)
                        break
        if default_in in mics and default_in not in ordered:
            ordered.append(default_in)
        for i in mics:
            if i not in ordered:
                ordered.append(i)
        return bh_out, ordered

    def _open_input_stream(self, mic_idx: int) -> bool:
        devs = self._sd.query_devices()
        d = devs[mic_idx]
        max_ch = int(d["max_input_channels"])
        sr = int(d["default_samplerate"]) or 48000
        # Try 1ch or up to 2ch cleanly (MacBook mic flips between 1ch and 3ch when HFP wakes!)
        ch_tries = [1, 2] if max_ch >= 2 else [1]
        for ch in ch_tries:
            try:
                stream = self._sd.InputStream(
                    samplerate=sr,
                    blocksize=512,
                    dtype="float32",
                    channels=ch,
                    device=mic_idx,
                    callback=self._in_cb,
                )
                self._ring.configure_rates(sr, self.sr)
                self._mon_mic_ring.configure_rates(sr, self.mon_sr)
                stream.start()
                self._in_stream = stream
                self._mic_idx = mic_idx
                self.in_device_name = d["name"]
                self.in_sr = sr
                self.in_ch = ch
                self._in_callbacks = 0
                self._last_in_cb = time.monotonic()
                self._zero_since = None
                return True
            except Exception as exc:
                print(f"[audio] input open failed on '{d['name']}' ({ch}ch @ {sr}Hz): {exc}")
        return False

    def _open_blackhole_output(self, bh_out: int) -> bool:
        devs = self._sd.query_devices()
        d = devs[bh_out]
        out_sr = int(d["default_samplerate"]) or 48000
        out_ch = min(2, int(d["max_output_channels"]))
        self._prepare_sfx_for_rate(out_sr)
        stream = self._sd.OutputStream(
            samplerate=out_sr,
            blocksize=512,
            dtype="float32",
            channels=out_ch,
            device=bh_out,
            callback=self._bh_out_cb,
        )
        stream.start()
        self._out_stream = stream
        self._bh_idx = bh_out
        self.out_device_name = d["name"]
        self.out_ch = out_ch
        self._out_callbacks = 0
        self._last_out_cb = time.monotonic()
        return True

    def _find_monitor_output(self) -> tuple[int | None, int, int, str]:
        devs = self._sd.query_devices()
        def_out = self._sd.default.device[1] if self._sd.default.device else None
        cands = [
            i for i, d in enumerate(devs)
            if d["max_output_channels"] > 0
            and not is_virtual_audio_name(d["name"])
            and not _is_multi_output(d["name"])
        ]
        ordered: list[int] = []
        if def_out in cands:
            ordered.append(def_out)
        for i in cands:
            if i not in ordered:
                ordered.append(i)
        if not ordered:
            return None, 48000, 2, "none"
        idx = ordered[0]
        d = devs[idx]
        return idx, int(d["default_samplerate"]) or 48000, min(2, int(d["max_output_channels"])), d["name"]

    def _close_monitor_stream(self) -> None:
        if self._mon_stream is not None:
            try:
                self._mon_stream.stop()
                self._mon_stream.close()
            except Exception:
                pass
            self._mon_stream = None

    def _open_monitor_stream(self) -> None:
        self._close_monitor_stream()
        if self.mode != "blackhole" or self.monitor_mode == "off":
            return
        idx, out_sr, ch, name = self._find_monitor_output()
        if idx is None:
            return
        try:
            self.mon_sr = out_sr
            self.mon_ch = ch
            self.mon_device_name = name
            self._mon_idx = idx
            self._mon_mic_ring.configure_rates(self.in_sr, out_sr)
            self._sfx_mon_ring.configure_rates(self.sr, out_sr)
            stream = self._sd.OutputStream(
                samplerate=out_sr,
                blocksize=512,
                dtype="float32",
                channels=ch,
                device=idx,
                callback=self._mon_out_cb,
            )
            stream.start()
            self._mon_stream = stream
        except Exception as exc:
            print(f"[audio] monitor output open failed ({name}): {exc}")

    def _start_audio(self, mic_selector: str | None = None) -> None:
        bh_out, mic_cands = self._discover_devices(mic_selector)
        _, _, _, mon_name = self._find_monitor_output()
        self.mon_device_name = mon_name
        if bh_out is not None and mic_cands:
            try:
                self._open_blackhole_output(bh_out)
                for idx in mic_cands:
                    if self._open_input_stream(idx):
                        self.mode = "blackhole"
                        self._open_monitor_stream()
                        print(
                            f"[audio] ACTIVE ROUTE: INPUT '{self.in_device_name}' "
                            f"({self.in_ch}ch @ {self.in_sr}Hz) + SFX -> "
                            f"OUTPUT '{self.out_device_name}' ({self.out_ch}ch @ {self.sr}Hz)"
                        )
                        print(f"[audio] Monitor: {self.monitor_mode} -> '{self.mon_device_name}' (press [v] to toggle)")
                        print("[audio] FaceTime setup: set Microphone = 'BlackHole 2ch', "
                              "Mic Mode = 'Standard' (not Voice Isolation)")
                        return
            except Exception as exc:
                self._last_status_err = f"BlackHole open error: {exc}"
                print(f"[audio] WARNING: {self._last_status_err}")
                self._close_streams()

        # Fallback: speaker output only (loudly reported!)
        self.mode = "speaker"
        devs = self._sd.query_devices()
        def_out = self._sd.default.device[1] if self._sd.default.device else None
        out_sr = int(devs[def_out]["default_samplerate"]) if (def_out is not None and def_out >= 0) else 48000
        self._prepare_sfx_for_rate(out_sr)
        self.out_device_name = devs[def_out]["name"] if (def_out is not None and def_out >= 0) else "Speakers"
        self._out_stream = self._sd.OutputStream(
            samplerate=out_sr,
            blocksize=512,
            dtype="float32",
            channels=2,
            callback=self._speaker_out_cb,
        )
        self._out_stream.start()
        print("[audio] WARNING: BlackHole passthrough inactive — speaker fallback only! "
              "FaceTime callers will NOT hear SFX through BlackHole.")

    def _in_cb(self, indata, frames, t, status) -> None:  # noqa: ARG002
        now = time.monotonic()
        self._in_callbacks += 1
        self._last_in_cb = now
        if not frames:
            return
        peak = float(np.max(np.abs(indata)))
        rms = float(np.sqrt(np.mean(indata * indata)))
        # Fast attack, smooth decay for HUD meter
        self.mic_peak = max(peak, self.mic_peak * 0.85)
        self.mic_rms = max(rms, self.mic_rms * 0.88)
        if peak == 0.0:
            if self._zero_since is None:
                self._zero_since = now
        else:
            self._zero_since = None
        if peak > 0.55 and self._prev_peak < 0.18:
            self.pop_time = now
        self._prev_peak = peak
        self._ring.push(indata)
        if self.monitor_mode == "mic_sfx":
            self._mon_mic_ring.push(indata)

    def _bh_out_cb(self, outdata, frames, t, status) -> None:  # noqa: ARG002
        self._out_callbacks += 1
        self._last_out_cb = time.monotonic()
        outdata[:] = self._ring.pop(frames, outdata.shape[1])
        sfx_blk = np.zeros((frames, outdata.shape[1]), dtype=np.float32)
        self._mix_continuous(sfx_blk)
        self._mix_into(sfx_blk)
        outdata += sfx_blk
        if self.monitor_mode != "off":
            self._sfx_mon_ring.push(sfx_blk)
        np.clip(outdata, -1.0, 1.0, out=outdata)
        peak = float(np.max(np.abs(outdata))) if frames else 0.0
        rms = float(np.sqrt(np.mean(outdata * outdata))) if frames else 0.0
        self.bh_peak = max(peak, self.bh_peak * 0.85)
        self.bh_rms = max(rms, self.bh_rms * 0.88)

    def _mon_out_cb(self, outdata, frames, t, status) -> None:  # noqa: ARG002
        out_ch = outdata.shape[1]
        mode = self.monitor_mode
        if mode == "off" or not frames:
            outdata[:] = 0
            return
        sfx = self._sfx_mon_ring.pop(frames, out_ch)
        if mode == "mic_sfx":
            outdata[:] = self._mon_mic_ring.pop(frames, out_ch) + sfx
        else:
            outdata[:] = sfx
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def _speaker_out_cb(self, outdata, frames, t, status) -> None:  # noqa: ARG002
        self._out_callbacks += 1
        self._last_out_cb = time.monotonic()
        if self.monitor_mode == "mic_sfx" and self._in_stream is not None:
            outdata[:] = self._mon_mic_ring.pop(frames, outdata.shape[1])
        else:
            outdata[:] = 0
        self._mix_continuous(outdata)
        self._mix_into(outdata)
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def _mix_continuous(self, out: np.ndarray) -> None:
        self._hum_gain += (self._hum_target - self._hum_gain) * 0.08
        self._hum2_gain += (self._hum2_target - self._hum2_gain) * 0.08
        self._hum_rate += (self._hum_rate_target - self._hum_rate) * 0.10
        self._swing_gain += (self._swing_target - self._swing_gain) * 0.12
        hum = self._bufs.get("hum")
        if hum is not None and (self._hum_gain > 0.002 or self._hum2_gain > 0.002):
            n = len(out)
            if self._hum_gain > 0.002:
                idx = self._hum_pos + np.arange(n) * self._hum_rate
                i0 = np.floor(idx).astype(np.int64)
                frac = (idx - i0).astype(np.float32)
                a = hum[i0 % len(hum)]
                b = hum[(i0 + 1) % len(hum)]
                seg = (a * (1.0 - frac[:, None]) + b * frac[:, None]) * self._hum_gain
                if seg.shape[1] == out.shape[1]:
                    out += seg
                elif out.shape[1] == 1:
                    out += seg.mean(axis=1, keepdims=True)
                else:
                    out += seg[:, :1]
                self._hum_pos = float(idx[-1] + self._hum_rate) if n else self._hum_pos
            if self._hum2_gain > 0.002:
                rate2 = self._hum_rate * 1.014
                idx2 = self._hum2_pos + np.arange(n) * rate2
                i0_2 = np.floor(idx2).astype(np.int64)
                frac2 = (idx2 - i0_2).astype(np.float32)
                a2 = hum[i0_2 % len(hum)]
                b2 = hum[(i0_2 + 1) % len(hum)]
                seg2 = (a2 * (1.0 - frac2[:, None]) + b2 * frac2[:, None]) * self._hum2_gain
                if seg2.shape[1] == out.shape[1]:
                    out += seg2
                elif out.shape[1] == 1:
                    out += seg2.mean(axis=1, keepdims=True)
                else:
                    out += seg2[:, :1]
                self._hum2_pos = float(idx2[-1] + rate2) if n else self._hum2_pos
        if self._swing_gain > 0.004:
            white = self._rng.standard_normal(len(out)).astype(np.float32)
            lp = np.empty_like(white)
            acc = self._noise_lp
            coef = 0.10 + 0.25 * min(self._hum_rate - 0.9, 0.4)
            for i, x in enumerate(white):
                acc += coef * (x - acc)
                lp[i] = acc
            self._noise_lp = float(acc)
            whoosh = (white - lp) * (self._swing_gain * 0.8)
            out += whoosh[:, None]

    def _mix_into(self, out: np.ndarray) -> None:
        def add_seg(buf: np.ndarray, pos: int, gain: float = 1.0) -> int:
            n = min(len(out), len(buf) - pos)
            if n <= 0:
                return -1
            seg = buf[pos:pos + n] * gain
            if seg.shape[1] == out.shape[1]:
                out[:n] += seg
            elif out.shape[1] == 1:
                out[:n] += seg.mean(axis=1, keepdims=True)
            elif seg.shape[1] == 1:
                out[:n] += seg
            else:
                ch = min(seg.shape[1], out.shape[1])
                out[:n, :ch] += seg[:, :ch]
            new_pos = pos + n
            return -1 if new_pos >= len(buf) else new_pos

        if self._sfx is not None:
            nxt = add_seg(self._sfx, self._sfx_pos)
            if nxt < 0:
                self._sfx = None
            else:
                self._sfx_pos = nxt

        with self._voice_lock:
            alive: list[list] = []
            for v in self._voices:
                nxt = add_seg(v[0], v[1], v[2])
                if nxt >= 0:
                    v[1] = nxt
                    alive.append(v)
            self._voices = alive

    def fire(self) -> None:
        self.play("gunshot")

    def play(self, key: str, gain: float = 1.0) -> None:
        buf = self._bufs.get(key)
        if buf is None or self.mode == "off":
            return
        with self._voice_lock:
            if len(self._voices) >= 8:
                self._voices.pop(0)
            self._voices.append([buf, 0, float(gain)])

    def set_saber(self, active: bool, speed_norm: float = 0.0, active_count: int = 1) -> None:
        s = float(min(max(speed_norm, 0.0), 1.0))
        cnt = active_count if active else 0
        self._hum_target = 0.42 if cnt >= 1 else 0.0
        self._hum2_target = 0.24 if cnt >= 2 else 0.0
        self._hum_rate_target = 1.0 + 0.19 * s
        self._swing_target = (s ** 1.5) * (0.62 if cnt >= 2 else 0.55) if cnt >= 1 else 0.0

    def set_monitor_mode(self, mode: str) -> str:
        """Switch local headphone/speaker monitor between 'off', 'sfx', and 'mic_sfx'."""
        if mode not in MONITOR_MODES:
            mode = "off"
        self.monitor_mode = mode
        self._mon_mic_ring.clear()
        self._sfx_mon_ring.clear()
        if self.mode == "blackhole":
            self._open_monitor_stream()
        print(f"[audio] MONITOR -> {mode} ('{self.mon_device_name}')")
        return mode

    def cycle_monitor(self) -> str:
        idx = MONITOR_MODES.index(self.monitor_mode) if self.monitor_mode in MONITOR_MODES else 0
        return self.set_monitor_mode(MONITOR_MODES[(idx + 1) % len(MONITOR_MODES)])

    def cycle_mic(self) -> str | None:
        """Switch to the next non-virtual input mic live (hotkey 'a')."""
        if self.mode != "blackhole" or not self.available_mics:
            return None
        ids = [i for i, _ in self.available_mics]
        cur_pos = ids.index(self._mic_idx) if self._mic_idx in ids else -1
        for step in range(1, len(ids) + 1):
            cand = ids[(cur_pos + step) % len(ids)]
            if self._in_stream is not None:
                try:
                    self._in_stream.stop()
                    self._in_stream.close()
                except Exception:
                    pass
                self._in_stream = None
            if self._open_input_stream(cand):
                self._mic_pinned = True
                print(f"[audio] switched INPUT -> '{self.in_device_name}' ({self.in_ch}ch @ {self.in_sr}Hz)")
                return self.in_device_name
        return None

    def check_health(self) -> str | None:
        """Periodic health check + auto-recovery; returns loud warning text if unhealthy."""
        if self.mode == "off":
            return "AUDIO OFF (--no-audio or init error)"
        if self.mode == "speaker":
            return "NO BLACKHOLE OUTPUT! FaceTime won't get audio (speaker fallback)"

        now = time.monotonic()
        # If an external/Bluetooth mic (like in-case AirPods) delivers exact 0.0 for >2s,
        # auto-fallback once to MacBook Pro Microphone if available and unpinned.
        if (not self._mic_pinned and not self._auto_switched_from_zero
                and self._zero_since is not None and (now - self._zero_since) > 2.0
                and "macbook" not in self.in_device_name.lower()):
            fallback = next((i for i, nm in self.available_mics if "macbook" in nm.lower()), None)
            if fallback is not None:
                print(f"[audio] '{self.in_device_name}' delivered exact 0.0 (idle/in-case?); "
                      "falling back to MacBook Pro Microphone")
                self._auto_switched_from_zero = True
                if self._in_stream is not None:
                    try:
                        self._in_stream.stop()
                        self._in_stream.close()
                    except Exception:
                        pass
                    self._in_stream = None
                self._open_input_stream(fallback)

        # Check callback stall (e.g. CoreAudio device change / AirPods reconnect)
        in_stalled = self._last_in_cb > 0.0 and (now - self._last_in_cb) > 1.2
        out_stalled = self._last_out_cb > 0.0 and (now - self._last_out_cb) > 1.2
        if (in_stalled or out_stalled) and (now - self._last_recover_try) > 3.0:
            self._last_recover_try = now
            print("[audio] WARNING: CoreAudio stream stalled — refreshing PortAudio devices & reopening...")
            self._close_streams()
            try:
                self._sd._terminate()
                self._sd._initialize()
                self._start_audio()
            except Exception as exc:
                self._last_status_err = str(exc)
            return "AUDIO RECONNECTING (CoreAudio device changed/stalled)"

        if self._zero_since is not None and (now - self._zero_since) > 1.5:
            return f"MIC '{self.in_device_name}' IS ALL ZEROS (0.0)! Check macOS Privacy > Microphone or press [a]"
        if self._last_in_cb > 0.0 and (now - self._last_in_cb) > 0.8:
            return "MIC STREAM STALLED — no input audio frames"
        if (self.monitor_mode == "mic_sfx"
                and "macbook" in self.in_device_name.lower()
                and "macbook" in self.mon_device_name.lower()):
            return "MIC+SFX MONITOR on speakers can echo! Use headphones or press [v]"
        return None

    def _close_streams(self) -> None:
        self._close_monitor_stream()
        for s in (self._in_stream, self._out_stream):
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
        self._in_stream = None
        self._out_stream = None

    def close(self) -> None:
        self._close_streams()
