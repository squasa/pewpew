"""Live Blender GUI bridge: watches the open .blend on disk AND runs a real-time
localhost TCP command server inside Blender's main UI thread so external agents/tools
can model, shade, frame, screenshot, and export in front of you in real time.

Launch:
  open -a Blender --args /abs/hilt.blend --python /abs/live_reload.py
  # or headless test:
  blender -b /abs/hilt.blend --python /abs/live_reload.py
"""
from __future__ import annotations

import io
import json
import math
import os
import queue
import socketserver
import threading
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import bpy
import bmesh
import mathutils

PORT = int(os.environ.get("BLENDER_LIVE_PORT", "9876"))
HOST = "127.0.0.1"

_WATCH = bpy.data.filepath or os.path.join(os.path.dirname(os.path.abspath(__file__)), "hilt.blend")
_mtime = [os.path.getmtime(_WATCH) if _WATCH and os.path.exists(_WATCH) else 0.0]
_cmd_q: queue.Queue[tuple[dict, list, threading.Event]] = queue.Queue()
_server: list = [None]
_exec_ns: dict = {
    "bpy": bpy,
    "bmesh": bmesh,
    "math": math,
    "mathutils": mathutils,
}


def _redraw_viewports() -> None:
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    try:
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except Exception:
        pass


def _scene_summary() -> dict:
    objs = []
    for obj in bpy.data.objects:
        objs.append({
            "name": obj.name,
            "type": obj.type,
            "location": [round(float(v), 4) for v in obj.location],
            "dimensions": [round(float(v), 4) for v in obj.dimensions],
            "visible": not obj.hide_viewport,
            "materials": [m.name for m in obj.data.materials if m] if hasattr(obj.data, "materials") else [],
        })
    return {
        "blender_version": bpy.app.version_string,
        "filepath": bpy.data.filepath,
        "object_count": len(objs),
        "objects": objs,
        "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    }


def _take_screenshot(out_path: str) -> str:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wm = getattr(bpy.context, "window_manager", None)
    if wm is not None:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    for region in area.regions:
                        if region.type == "WINDOW":
                            try:
                                with bpy.context.temp_override(window=win, area=area, region=region):
                                    bpy.ops.screen.screenshot_area(filepath=str(out))
                                if out.exists():
                                    return str(out)
                            except Exception:
                                pass
    bpy.context.scene.render.filepath = str(out)
    bpy.ops.render.opengl(write_still=True)
    return str(out)


def _handle_command(req: dict) -> dict:
    cmd = req.get("cmd", "ping")
    if cmd == "ping":
        return {"ok": True, "blender_version": bpy.app.version_string, "filepath": bpy.data.filepath, "objects": len(bpy.data.objects)}
    if cmd == "scene_info":
        return {"ok": True, **_scene_summary()}
    if cmd == "exec":
        code = str(req.get("code", ""))
        buf = io.StringIO()
        ns = dict(_exec_ns)
        ns["result"] = None
        with redirect_stdout(buf):
            exec(compile(code, "<blender_live>", "exec"), ns)
        _exec_ns.update({k: v for k, v in ns.items() if k != "result"})
        bpy.context.view_layer.update()
        if req.get("redraw", True):
            _redraw_viewports()
        return {"ok": True, "stdout": buf.getvalue(), "result": ns.get("result")}
    if cmd == "frame_all":
        wm = getattr(bpy.context, "window_manager", None)
        if wm is not None:
            for win in wm.windows:
                for area in win.screen.areas:
                    if area.type == "VIEW_3D":
                        for region in area.regions:
                            if region.type == "WINDOW":
                                with bpy.context.temp_override(window=win, area=area, region=region):
                                    bpy.ops.view3d.view_all()
                                break
                        break
        _redraw_viewports()
        return {"ok": True}
    if cmd == "screenshot":
        path = str(req.get("path") or "/tmp/blender_viewport.png")
        saved = _take_screenshot(path)
        return {"ok": True, "path": saved}
    if cmd == "export_glb":
        out = Path(str(req.get("path") or "/tmp/model.glb"))
        out.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.export_scene.gltf(
            filepath=str(out),
            export_format="GLB",
            use_selection=bool(req.get("selected_only", False)),
        )
        return {"ok": True, "path": str(out), "bytes": out.stat().st_size}
    return {"ok": False, "error": f"unknown cmd: {cmd}"}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(2_000_000)
        if not line:
            return
        try:
            req = json.loads(line.decode("utf-8"))
        except Exception as exc:
            self.wfile.write((json.dumps({"ok": False, "error": f"bad json: {exc}"}) + "\n").encode())
            return
        holder: list[dict] = []
        done = threading.Event()
        _cmd_q.put((req, holder, done))
        if not done.wait(timeout=30.0):
            self.wfile.write((json.dumps({"ok": False, "error": "blender main-thread timeout"}) + "\n").encode())
            return
        self.wfile.write((json.dumps(holder[0]) + "\n").encode())


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _start_server() -> None:
    if _server[0] is not None:
        return
    try:
        srv = _Server((HOST, PORT), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True, name="blender_live_bridge").start()
        _server[0] = srv
        print(f"[live] socket bridge listening on {HOST}:{PORT}")
    except OSError as exc:
        print(f"[live] socket bridge not bound on {HOST}:{PORT}: {exc}")


_last_watch_check = [0.0]


def _tick() -> float:
    # 1. Drain live modeling commands immediately in main UI thread (20 Hz)
    while not _cmd_q.empty():
        req, holder, done = _cmd_q.get_nowait()
        try:
            holder.append(_handle_command(req))
        except Exception as exc:
            holder.append({"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        finally:
            done.set()

    # 2. Check .blend mtime on disk once per second for build_hilt.py file reloads
    import time
    now = time.monotonic()
    if now - _last_watch_check[0] >= 1.0:
        _last_watch_check[0] = now
        watch = bpy.data.filepath or _WATCH
        if watch:
            try:
                m = os.path.getmtime(watch)
            except OSError:
                m = _mtime[0]
            if m > _mtime[0] + 0.01:
                _mtime[0] = m
                print(f"[live] {watch} changed - reloading viewport")
                try:
                    bpy.ops.wm.open_mainfile(filepath=watch)
                except Exception as exc:
                    print("[live] reload failed:", exc)
    return 0.05


_start_server()
bpy.app.timers.register(_tick, first_interval=0.1, persistent=True)
print(f"[live] watching {_WATCH} + live TCP bridge :{PORT}")
