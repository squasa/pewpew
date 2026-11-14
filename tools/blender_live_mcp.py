"""Zero-dependency MCP stdio server + CLI client for real-time Blender GUI control.

Talks JSON-lines over 127.0.0.1:9876 to models3d/live_reload.py inside a live Blender window.
Run as MCP server (default) or CLI:
  python tools/blender_live_mcp.py --cli status
  python tools/blender_live_mcp.py --cli exec "bpy.ops.mesh.primitive_cube_add()"
  python tools/blender_live_mcp.py --cli screenshot /tmp/vp.png
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
PORT = int(os.environ.get("BLENDER_LIVE_PORT", "9876"))
ROOT = Path(__file__).resolve().parent.parent
LIVE_SCRIPT = ROOT / "models3d" / "live_reload.py"
DEFAULT_SCREENSHOT = ROOT / "tests" / "blender_viewport.png"


def _send_blender(payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            b = sock.recv(65536)
            if not b:
                break
            chunks.append(b)
            if b.endswith(b"\n"):
                break
    return json.loads(b"".join(chunks).decode("utf-8"))


def tool_blender_status() -> dict[str, Any]:
    try:
        return _send_blender({"cmd": "scene_info"}, timeout=3.0)
    except OSError as exc:
        return {
            "ok": False,
            "connected": False,
            "error": f"Blender live bridge not reachable on {HOST}:{PORT} ({exc}). "
                     f"Start it with blender_launch or: open -a Blender --args --python {LIVE_SCRIPT}",
        }


def tool_blender_exec(code: str, redraw: bool = True) -> dict[str, Any]:
    return _send_blender({"cmd": "exec", "code": code, "redraw": redraw}, timeout=30.0)


def tool_blender_screenshot(path: str | None = None) -> dict[str, Any]:
    return _send_blender({"cmd": "screenshot", "path": path or str(DEFAULT_SCREENSHOT)}, timeout=15.0)


def tool_blender_frame_all() -> dict[str, Any]:
    return _send_blender({"cmd": "frame_all"}, timeout=10.0)


def tool_blender_export_glb(path: str, selected_only: bool = False) -> dict[str, Any]:
    return _send_blender({"cmd": "export_glb", "path": path, "selected_only": selected_only}, timeout=30.0)


def tool_blender_launch(blend_file: str | None = None) -> dict[str, Any]:
    try:
        info = _send_blender({"cmd": "ping"}, timeout=1.0)
        if info.get("ok"):
            return {"ok": True, "already_running": True, **info}
    except OSError:
        pass
    args = ["open", "-a", "Blender", "--args"]
    if blend_file:
        args.append(blend_file)
    args.extend(["--python", str(LIVE_SCRIPT)])
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.25)
        try:
            info = _send_blender({"cmd": "ping"}, timeout=1.0)
            if info.get("ok"):
                return {"ok": True, "launched": True, **info}
        except OSError:
            continue
    return {"ok": False, "error": "Launched Blender, waiting for bridge socket timed out."}


TOOLS = [
    {
        "name": "blender_status",
        "description": "Check live Blender GUI viewport connection and inspect objects/materials/cameras.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "blender_launch",
        "description": "Open Blender GUI with the live modeling bridge so the user watches 3D edits in real time.",
        "inputSchema": {
            "type": "object",
            "properties": {"blend_file": {"type": "string", "description": "Optional .blend file path to open."}},
        },
    },
    {
        "name": "blender_exec",
        "description": "Execute Blender Python (bpy/bmesh/mathutils) live inside the open Blender GUI and redraw viewport.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute inside Blender's main UI thread."},
                "redraw": {"type": "boolean", "default": True},
            },
            "required": ["code"],
        },
    },
    {
        "name": "blender_frame_all",
        "description": "Frame all objects cleanly in Blender's 3D viewport.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "blender_screenshot",
        "description": "Capture the current live Blender 3D viewport to a PNG file.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Output PNG path."}},
        },
    },
    {
        "name": "blender_export_glb",
        "description": "Export the current Blender scene or selection to a binary GLTF (.glb) file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Destination .glb path."},
                "selected_only": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    },
]


def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "blender_status":
        return tool_blender_status()
    if name == "blender_launch":
        return tool_blender_launch(args.get("blend_file"))
    if name == "blender_exec":
        return tool_blender_exec(args["code"], bool(args.get("redraw", True)))
    if name == "blender_frame_all":
        return tool_blender_frame_all()
    if name == "blender_screenshot":
        return tool_blender_screenshot(args.get("path"))
    if name == "blender_export_glb":
        return tool_blender_export_glb(args["path"], bool(args.get("selected_only", False)))
    raise KeyError(f"Unknown tool: {name}")


def _write_msg(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def serve_mcp() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if req_id is None:
            # Notification (e.g. notifications/initialized) -> no response
            continue
        try:
            if method == "initialize":
                res = {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "blender-live", "version": "0.1.0"},
                }
            elif method == "ping":
                res = {}
            elif method == "tools/list":
                res = {"tools": TOOLS}
            elif method == "tools/call":
                tname = params.get("name", "")
                targs = params.get("arguments") or {}
                out = _dispatch_tool(tname, targs)
                res = {
                    "content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                    "isError": not bool(out.get("ok", True)),
                }
            else:
                _write_msg({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
                continue
            _write_msg({"jsonrpc": "2.0", "id": req_id, "result": res})
        except Exception as exc:
            _write_msg({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}})
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Blender Live MCP Server + CLI")
    ap.add_argument("--cli", choices=["status", "exec", "screenshot", "frame", "export", "launch"], default=None)
    ap.add_argument("arg", nargs="?", default=None)
    args = ap.parse_args()
    if args.cli is None:
        return serve_mcp()
    if args.cli == "status":
        print(json.dumps(tool_blender_status(), indent=2))
    elif args.cli == "launch":
        print(json.dumps(tool_blender_launch(args.arg), indent=2))
    elif args.cli == "exec":
        print(json.dumps(tool_blender_exec(args.arg or "print('hello from live blender')"), indent=2))
    elif args.cli == "screenshot":
        print(json.dumps(tool_blender_screenshot(args.arg), indent=2))
    elif args.cli == "frame":
        print(json.dumps(tool_blender_frame_all(), indent=2))
    elif args.cli == "export":
        print(json.dumps(tool_blender_export_glb(args.arg or str(ROOT / "models3d" / "hilt.glb")), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
