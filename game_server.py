"""Single-port asyncio HTTP + RFC6455 WebSocket game server, room manager, and QR code generator."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import random
import re
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# ---------------------------------------------------------------------------
# Minimal ISO 18004 QR Code Generator (Byte mode, ECC Level L, Versions 1..6)
# ---------------------------------------------------------------------------
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_gen_poly(deg: int) -> list[int]:
    poly = [1]
    for i in range(deg):
        nxt = [0] * (len(poly) + 1)
        root = _GF_EXP[i]
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gf_mul(c, root)
        poly = nxt
    return poly


def _rs_remainder(data: list[int], ec_count: int) -> list[int]:
    gen = _rs_gen_poly(ec_count)
    res = list(data) + [0] * ec_count
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# (version, total_data_bytes, ec_per_block, blocks_tuple, align_coords)
_QR_SPECS = [
    (1, 19, 7, (19,), ()),
    (2, 34, 10, (34,), (6, 18)),
    (3, 55, 15, (55,), (6, 22)),
    (4, 80, 20, (80,), (6, 26)),
    (5, 108, 26, (108,), (6, 30)),
    (6, 136, 18, (68, 68), (6, 34)),
]


def _encode_qr_codewords(payload: bytes) -> tuple[int, list[int]]:
    n = len(payload)
    spec = None
    for s in _QR_SPECS:
        # 4 bits mode + 8 bits len = 12 bits + 4 bits terminator = 2 bytes overhead
        if n <= s[1] - 2:
            spec = s
            break
    if spec is None:
        raise ValueError(f"URL too long ({n} bytes) for compact QR (max 134 bytes)")

    ver, total_data, ec_per_block, block_sizes, _ = spec
    bits: list[int] = []

    def push(val: int, width: int) -> None:
        for k in range(width - 1, -1, -1):
            bits.append((val >> k) & 1)

    push(0b0100, 4)  # Byte mode
    push(n, 8)
    for b in payload:
        push(b, 8)
    max_bits = total_data * 8
    term = min(4, max_bits - len(bits))
    push(0, term)
    while len(bits) % 8 != 0:
        bits.append(0)
    pad_bytes = (0xEC, 0x11)
    p_idx = 0
    while len(bits) < max_bits:
        push(pad_bytes[p_idx & 1], 8)
        p_idx += 1

    data_bytes = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | b
        data_bytes.append(byte)

    blocks_data: list[list[int]] = []
    blocks_ec: list[list[int]] = []
    pos = 0
    for bsz in block_sizes:
        blk = data_bytes[pos:pos + bsz]
        pos += bsz
        blocks_data.append(blk)
        blocks_ec.append(_rs_remainder(blk, ec_per_block))

    interleaved: list[int] = []
    max_d = max(len(b) for b in blocks_data)
    for i in range(max_d):
        for b in blocks_data:
            if i < len(b):
                interleaved.append(b[i])
    for i in range(ec_per_block):
        for ec in blocks_ec:
            interleaved.append(ec[i])
    return ver, interleaved


def _format_bits(mask_id: int) -> int:
    # ECC Level L = 01 (2 bits) + 3-bit mask_id
    data = (0b01 << 3) | (mask_id & 0b111)
    rem = data << 10
    gen = 0b10100110111
    for bit in range(14, 9, -1):
        if (rem >> bit) & 1:
            rem ^= gen << (bit - 10)
    fmt = ((data << 10) | rem) ^ 0b101010000010010
    return fmt


def make_qr_matrix(text: str) -> np.ndarray:
    """Return a uint8 boolean QR matrix (1=dark, 0=light) including 4-module quiet zone."""
    ver, codewords = _encode_qr_codewords(text.encode("utf-8"))
    size = 17 + 4 * ver
    grid = [[-1] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def set_mod(r: int, c: int, val: int, is_func: bool = True) -> None:
        if 0 <= r < size and 0 <= c < size:
            grid[r][c] = val
            if is_func:
                func[r][c] = True

    def place_finder(r0: int, c0: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_mod(r, c, 0)
                elif dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4):
                    set_mod(r, c, 1)
                else:
                    set_mod(r, c, 0)

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    # Alignment patterns
    align_coords = _QR_SPECS[ver - 1][4]
    for ar in align_coords:
        for ac in align_coords:
            if func[ar][ac]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                    set_mod(ar + dr, ac + dc, val)

    # Timing strips
    for i in range(8, size - 8):
        val = 1 - (i % 2)
        if not func[6][i]:
            set_mod(6, i, val)
        if not func[i][6]:
            set_mod(i, 6, val)

    # Dark module & reserve format slots
    set_mod(4 * ver + 9, 8, 1)
    for i in range(9):
        if not func[8][i]:
            set_mod(8, i, 0)
        if not func[i][8]:
            set_mod(i, 8, 0)
    for i in range(size - 8, size):
        set_mod(8, i, 0)
    for i in range(size - 7, size):
        set_mod(i, 8, 0)

    # Place codeword bits in standard zigzag
    bit_stream = []
    for cw in codewords:
        for b in range(7, -1, -1):
            bit_stream.append((cw >> b) & 1)
    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if not func[r][c]:
                    val = bit_stream[bit_idx] if bit_idx < len(bit_stream) else 0
                    bit_idx += 1
                    grid[r][c] = val
        upward = not upward
        col -= 2

    def apply_mask_and_score(mask_id: int) -> tuple[int, list[list[int]]]:
        m = [row[:] for row in grid]
        for r in range(size):
            for c in range(size):
                if func[r][c]:
                    continue
                if mask_id == 0:
                    flip = (r + c) % 2 == 0
                elif mask_id == 1:
                    flip = r % 2 == 0
                elif mask_id == 2:
                    flip = c % 3 == 0
                elif mask_id == 3:
                    flip = (r + c) % 3 == 0
                elif mask_id == 4:
                    flip = (r // 2 + c // 3) % 2 == 0
                elif mask_id == 5:
                    flip = (r * c) % 2 + (r * c) % 3 == 0
                elif mask_id == 6:
                    flip = ((r * c) % 2 + (r * c) % 3) % 2 == 0
                else:
                    flip = ((r + c) % 2 + (r * c) % 3) % 2 == 0
                if flip:
                    m[r][c] ^= 1

        fmt = _format_bits(mask_id)
        for i in range(6):
            bit = (fmt >> (14 - i)) & 1
            m[8][i] = bit
            m[size - 1 - i][8] = bit
        m[8][7] = (fmt >> 8) & 1
        m[8][8] = (fmt >> 7) & 1
        m[7][8] = (fmt >> 6) & 1
        for i in range(6):
            m[5 - i][8] = (fmt >> (5 - i)) & 1
        m[size - 7][8] = (fmt >> 8) & 1
        for i in range(8):
            m[8][size - 8 + i] = (fmt >> (7 - i)) & 1

        # Penalty heuristic: run-length + 2x2 blocks + balance
        penalty = 0
        for r in range(size):
            run = 1
            for c in range(1, size):
                if m[r][c] == m[r][c - 1]:
                    run += 1
                    if run == 5:
                        penalty += 3
                    elif run > 5:
                        penalty += 1
                else:
                    run = 1
        for c in range(size):
            run = 1
            for r in range(1, size):
                if m[r][c] == m[r - 1][c]:
                    run += 1
                    if run == 5:
                        penalty += 3
                    elif run > 5:
                        penalty += 1
                else:
                    run = 1
        for r in range(size - 1):
            for c in range(size - 1):
                s = m[r][c] + m[r][c + 1] + m[r + 1][c] + m[r + 1][c + 1]
                if s in (0, 4):
                    penalty += 3
        return penalty, m

    best_score = 10**9
    best_mat = None
    for mid in range(8):
        sc, mat = apply_mask_and_score(mid)
        if sc < best_score:
            best_score = sc
            best_mat = mat

    q = 4
    out = np.zeros((size + 2 * q, size + 2 * q), dtype=np.uint8)
    out[q:q + size, q:q + size] = np.array(best_mat, dtype=np.uint8)
    return out


def render_qr_bgr(url: str, box_px: int = 210) -> np.ndarray:
    """Render a crisp high-contrast white-backed QR code image of shape (box_px, box_px, 3)."""
    mat = make_qr_matrix(url)
    img = ((1 - mat) * 255).astype(np.uint8)
    resized = cv2.resize(img, (box_px, box_px), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)


def detect_lan_ip() -> str:
    """Return local LAN IPv4 address for phones on the same Wi-Fi, falling back to 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        s.close()
    return "127.0.0.1"


# ---------------------------------------------------------------------------
# RFC6455 WebSocket Frame Helpers
# ---------------------------------------------------------------------------
def ws_encode_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    header = bytearray([0x80 | (opcode & 0x0F)])
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", n))
    return bytes(header) + payload


async def ws_read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    """Read one possibly-fragmented RFC6455 frame (up to 512 KB). Returns None on EOF."""
    chunks: list[bytes] = []
    first_op: int | None = None
    total = 0
    while True:
        try:
            hdr = await reader.readexactly(2)
        except asyncio.IncompleteReadError:
            return None
        b0, b1 = hdr[0], hdr[1]
        fin = bool(b0 & 0x80)
        op = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await reader.readexactly(8))[0]
        if length > 524288:
            raise ValueError("WebSocket frame too large")
        mask_key = await reader.readexactly(4) if masked else b""
        data = await reader.readexactly(length) if length else b""
        if masked and data:
            data = bytes(b ^ mask_key[i & 3] for i, b in enumerate(data))
        if op in (0x8, 0x9, 0xA):
            return op, data
        if first_op is None:
            first_op = op
        chunks.append(data)
        total += len(data)
        if total > 524288:
            raise ValueError("Reassembled WebSocket message too large")
        if fin:
            return first_op if first_op is not None else 0x1, b"".join(chunks)


@dataclass
class ConnectedClient:
    client_id: str
    role: str  # "guest" | "host" | "spectator"
    name: str
    writer: asyncio.StreamWriter
    queue: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    last_seen: float = field(default_factory=time.monotonic)


class GameServer:
    """Single-port HTTP static + API + RFC6455 WebSocket game server."""

    def __init__(
        self,
        web_dir: Path,
        data_dir: Path,
        host: str = "0.0.0.0",
        port: int = 8770,
        room_code: str | None = None,
        public_url: str | None = None,
        enable_tunnel: bool = False,
        room_ttl_s: float = 7200.0,
    ) -> None:
        self.web_dir = web_dir.resolve()
        self.data_dir = data_dir.resolve()
        self.host = host
        self.port = port
        self.room_code = (room_code or "".join(secrets.choice(ROOM_ALPHABET) for _ in range(4))).upper()
        self._explicit_public_url = public_url.rstrip("/") if public_url else None
        self._tunnel_url: str | None = None
        self._tunnel_proc: subprocess.Popen | None = None
        self._enable_tunnel = enable_tunnel
        self.tunnel_error: str | None = None
        self.room_ttl_s = room_ttl_s
        self.created_at = time.monotonic()

        self._clients: dict[str, ConnectedClient] = {}
        self._clients_lock = threading.Lock()
        self._on_message: Callable[[str, str, dict[str, Any]], None] | None = None
        self._on_connect: Callable[[str, str, str], None] | None = None
        self._on_disconnect: Callable[[str, str], None] | None = None
        self._on_prompts_changed: Callable[[], None] | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._server: asyncio.AbstractServer | None = None
        self._qr_cache_url: str | None = None
        self._qr_cache_bgr: np.ndarray | None = None

    def set_handlers(
        self,
        on_message: Callable[[str, str, dict[str, Any]], None] | None = None,
        on_connect: Callable[[str, str, str], None] | None = None,
        on_disconnect: Callable[[str, str], None] | None = None,
        on_prompts_changed: Callable[[], None] | None = None,
    ) -> None:
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_prompts_changed = on_prompts_changed

    @property
    def lan_url(self) -> str:
        ip = detect_lan_ip()
        return f"http://{ip}:{self.port}/?room={self.room_code}"

    @property
    def share_url(self) -> str:
        if self._tunnel_url:
            return f"{self._tunnel_url}/?room={self.room_code}"
        if self._explicit_public_url:
            return f"{self._explicit_public_url}/?room={self.room_code}"
        return self.lan_url

    @property
    def host_phone_url(self) -> str:
        base = self.share_url
        return f"{base}&role=host"

    def qr_bgr(self, box_px: int = 190) -> np.ndarray:
        url = self.share_url
        if self._qr_cache_url != url or self._qr_cache_bgr is None or self._qr_cache_bgr.shape[0] != box_px:
            self._qr_cache_url = url
            self._qr_cache_bgr = render_qr_bgr(url, box_px=box_px)
        return self._qr_cache_bgr

    def start(self) -> None:
        if self._thread is not None:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_thread, name="pewpew-game-server", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        if self._enable_tunnel:
            self._start_cloudflared()

    def _run_thread(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        finally:
            loop.close()

    async def _serve(self) -> None:
        self._server = await asyncio.start_server(self._handle_conn, self.host, self.port)
        socks = self._server.sockets
        if socks:
            self.port = int(socks[0].getsockname()[1])
        self._ready.set()
        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass

    def _start_cloudflared(self) -> None:
        cf = shutil.which("cloudflared")
        if not cf:
            self.tunnel_error = "cloudflared not found on PATH (brew install cloudflared)"
            return
        try:
            self._tunnel_proc = subprocess.Popen(
                [cf, "tunnel", "--url", f"http://127.0.0.1:{self.port}", "--no-autoupdate"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            t = threading.Thread(target=self._watch_tunnel_stderr, name="pewpew-tunnel", daemon=True)
            t.start()
        except Exception as e:
            self.tunnel_error = f"cloudflared failed: {e}"

    def _watch_tunnel_stderr(self) -> None:
        proc = self._tunnel_proc
        if proc is None or proc.stderr is None:
            return
        pat = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        for line in proc.stderr:
            m = pat.search(line)
            if m:
                self._tunnel_url = m.group(0).rstrip("/")
                self.tunnel_error = None
                break

    def stop(self) -> None:
        if self._tunnel_proc is not None:
            try:
                self._tunnel_proc.terminate()
                self._tunnel_proc.wait(timeout=1.5)
            except Exception:
                pass
            self._tunnel_proc = None
        if self._loop is not None and self._server is not None:
            def _shutdown() -> None:
                if self._server:
                    self._server.close()
                for task in asyncio.all_tasks(self._loop):
                    task.cancel()
            try:
                self._loop.call_soon_threadsafe(_shutdown)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def active_counts(self) -> dict[str, int]:
        with self._clients_lock:
            roles = [c.role for c in self._clients.values()]
        return {
            "total": len(roles),
            "guest": roles.count("guest"),
            "host": roles.count("host"),
        }

    def broadcast(self, payload: dict[str, Any]) -> None:
        msg = json.dumps(payload, separators=(",", ":"))
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._clients_lock:
            clients = list(self._clients.values())
        for c in clients:
            try:
                loop.call_soon_threadsafe(self._enqueue_nowait, c, msg)
            except RuntimeError:
                pass

    def send_to(self, client_id: str, payload: dict[str, Any]) -> None:
        msg = json.dumps(payload, separators=(",", ":"))
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._clients_lock:
            c = self._clients.get(client_id)
        if c is not None:
            try:
                loop.call_soon_threadsafe(self._enqueue_nowait, c, msg)
            except RuntimeError:
                pass

    @staticmethod
    def _enqueue_nowait(client: ConnectedClient, msg: str) -> None:
        if client.queue.full():
            try:
                client.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            client.queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req_bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10.0)
        except Exception:
            writer.close()
            return

        lines = req_bytes.decode("latin-1", errors="replace").split("\r\n")
        if not lines or " " not in lines[0]:
            writer.close()
            return
        parts = lines[0].split(" ")
        method = parts[0].upper()
        raw_target = parts[1] if len(parts) > 1 else "/"
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        parsed = urlparse(raw_target)
        path = parsed.path or "/"
        qs = parse_qs(parsed.query)

        if path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
            await self._handle_ws(reader, writer, headers, qs)
            return

        content_len = int(headers.get("content-length", "0") or "0")
        body = b""
        if content_len > 0:
            if content_len > 524288:
                await self._send_http(writer, 413, "text/plain", b"Payload Too Large")
                writer.close()
                return
            body = await reader.readexactly(content_len)

        await self._handle_http(writer, method, path, qs, body)
        try:
            await writer.drain()
        except Exception:
            pass
        writer.close()

    async def _handle_http(
        self,
        writer: asyncio.StreamWriter,
        method: str,
        path: str,
        qs: dict[str, list[str]],
        body: bytes,
    ) -> None:
        if method == "OPTIONS":
            await self._send_http(writer, 204, "text/plain", b"")
            return

        if path == "/api/info":
            counts = self.active_counts()
            info = {
                "room": self.room_code,
                "shareUrl": self.share_url,
                "lanUrl": self.lan_url,
                "hostUrl": self.host_phone_url,
                "clients": counts,
                "tunnelError": self.tunnel_error,
                "expired": (time.monotonic() - self.created_at) > self.room_ttl_s,
            }
            await self._send_http(writer, 200, "application/json", json.dumps(info).encode("utf-8"))
            return

        if path == "/api/theme":
            theme_path = self.web_dir / "data" / "rare_answer_theme.json"
            if method == "GET":
                data = theme_path.read_bytes() if theme_path.exists() else b"{}"
                await self._send_http(writer, 200, "application/json", data)
                return
            if method in ("POST", "PUT"):
                try:
                    parsed = json.loads(body.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError("theme must be JSON object")
                    theme_path.parent.mkdir(parents=True, exist_ok=True)
                    theme_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
                    if self._on_prompts_changed:
                        self._on_prompts_changed()
                    await self._send_http(writer, 200, "application/json", b'{"ok":true}')
                except Exception as exc:
                    await self._send_http(writer, 400, "application/json", json.dumps({"error": str(exc)}).encode())
                return

        if path == "/api/custom-prompts":
            custom_path = self.web_dir / "data" / "rare_answer_custom_prompts.json"
            if method == "GET":
                data = custom_path.read_bytes() if custom_path.exists() else b'{"prompts":[]}'
                await self._send_http(writer, 200, "application/json", data)
                return
            if method in ("POST", "PUT"):
                try:
                    parsed = json.loads(body.decode("utf-8"))
                    if not isinstance(parsed, dict) or not isinstance(parsed.get("prompts", []), list):
                        raise ValueError("expected {prompts: [...]}")
                    custom_path.parent.mkdir(parents=True, exist_ok=True)
                    custom_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
                    if self._on_prompts_changed:
                        self._on_prompts_changed()
                    await self._send_http(writer, 200, "application/json", b'{"ok":true}')
                except Exception as exc:
                    await self._send_http(writer, 400, "application/json", json.dumps({"error": str(exc)}).encode())
                return

        if method != "GET":
            await self._send_http(writer, 405, "text/plain", b"Method Not Allowed")
            return

        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        candidate = (self.web_dir / rel).resolve()
        try:
            candidate.relative_to(self.web_dir)
        except ValueError:
            await self._send_http(writer, 403, "text/plain", b"Forbidden")
            return

        if not candidate.is_file():
            await self._send_http(writer, 404, "text/plain", b"Not Found")
            return

        mime, _ = mimetypes.guess_type(str(candidate))
        if candidate.suffix == ".js":
            mime = "application/javascript; charset=utf-8"
        elif candidate.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif candidate.suffix == ".json":
            mime = "application/json; charset=utf-8"
        elif candidate.suffix == ".html":
            mime = "text/html; charset=utf-8"
        elif candidate.suffix == ".wav":
            mime = "audio/wav"
        elif candidate.suffix == ".ogg":
            mime = "audio/ogg"
        else:
            mime = mime or "application/octet-stream"

        await self._send_http(writer, 200, mime, candidate.read_bytes())

    @staticmethod
    async def _send_http(writer: asyncio.StreamWriter, status: int, content_type: str, body: bytes) -> None:
        reasons = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden",
                   404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large"}
        hdr = (
            f"HTTP/1.1 {status} {reasons.get(status, 'OK')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Cache-Control: no-store\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Access-Control-Allow-Methods: GET, POST, PUT, OPTIONS\r\n"
            f"Access-Control-Allow-Headers: Content-Type\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("latin-1")
        writer.write(hdr + body)

    async def _handle_ws(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        qs: dict[str, list[str]],
    ) -> None:
        ws_key = headers.get("sec-websocket-key", "")
        if not ws_key:
            writer.close()
            return
        accept = base64.b64encode(hashlib.sha1((ws_key + WS_GUID).encode("ascii")).digest()).decode("ascii")
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("latin-1")
        writer.write(resp)
        await writer.drain()

        req_room = (qs.get("room", [""])[0] or "").strip().upper()
        if req_room != self.room_code:
            err = json.dumps({"type": "error", "code": "bad_room", "message": f"Invalid or expired room code ({req_room or 'none'})."})
            writer.write(ws_encode_frame(err.encode("utf-8"), 0x1))
            writer.write(ws_encode_frame(b"", 0x8))
            await writer.drain()
            writer.close()
            return

        if (time.monotonic() - self.created_at) > self.room_ttl_s:
            err = json.dumps({"type": "error", "code": "expired", "message": "Session expired."})
            writer.write(ws_encode_frame(err.encode("utf-8"), 0x1))
            writer.write(ws_encode_frame(b"", 0x8))
            await writer.drain()
            writer.close()
            return

        req_role = (qs.get("role", ["guest"])[0] or "guest").strip().lower()
        if req_role not in ("guest", "host"):
            req_role = "guest"
        req_name = (qs.get("name", [""])[0] or "").strip()[:24]

        with self._clients_lock:
            existing_roles = {c.role for c in self._clients.values()}
            if req_role == "guest" and "guest" in existing_roles:
                role = "host" if "host" not in existing_roles else "spectator"
            elif req_role == "host" and "host" in existing_roles:
                role = "guest" if "guest" not in existing_roles else "spectator"
            else:
                role = req_role

            client_id = secrets.token_hex(6)
            display_name = req_name or ("Her" if role == "guest" else ("Him" if role == "host" else "Viewer"))
            client = ConnectedClient(client_id=client_id, role=role, name=display_name, writer=writer)
            self._clients[client_id] = client

        welcome = json.dumps({
            "type": "welcome",
            "clientId": client_id,
            "role": role,
            "name": display_name,
            "room": self.room_code,
        })
        await client.queue.put(welcome)
        if self._on_connect:
            self._on_connect(client_id, role, display_name)

        async def sender_loop() -> None:
            while True:
                msg = await client.queue.get()
                writer.write(ws_encode_frame(msg.encode("utf-8"), 0x1))
                await writer.drain()

        sender_task = asyncio.create_task(sender_loop())
        try:
            while True:
                res = await ws_read_frame(reader)
                if res is None:
                    break
                op, data = res
                client.last_seen = time.monotonic()
                if op == 0x8:
                    break
                elif op == 0x9:
                    writer.write(ws_encode_frame(data, 0xA))
                    await writer.drain()
                elif op == 0x1:
                    try:
                        msg = json.loads(data.decode("utf-8"))
                    except Exception:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("type") == "set_profile":
                        new_name = str(msg.get("name", "")).strip()[:24]
                        req_switch = str(msg.get("role", "")).strip().lower()
                        with self._clients_lock:
                            if new_name:
                                client.name = new_name
                            if req_switch in ("guest", "host") and req_switch != client.role:
                                taken = any(
                                    cid != client_id and c.role == req_switch
                                    for cid, c in self._clients.items()
                                )
                                if not taken:
                                    client.role = req_switch
                                    await client.queue.put(json.dumps({
                                        "type": "welcome",
                                        "clientId": client_id,
                                        "role": client.role,
                                        "name": client.name,
                                        "room": self.room_code,
                                    }))
                        if self._on_connect:
                            self._on_connect(client_id, client.role, client.name)
                        continue
                    if self._on_message:
                        self._on_message(client_id, client.role, msg)
        except Exception:
            pass
        finally:
            sender_task.cancel()
            with self._clients_lock:
                self._clients.pop(client_id, None)
            if self._on_disconnect:
                self._on_disconnect(client_id, client.role)
            try:
                writer.close()
            except Exception:
                pass
