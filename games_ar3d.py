"""Real-time ModernGL 3D webcam AR overlay renderer for all PewPew multiplayer games."""
from __future__ import annotations

import math
from typing import Any

import cv2
import moderngl
import numpy as np


_AR_VERT = """
#version 330
uniform mat4 u_mvp;
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_norm;
out vec3 v_norm;
out vec3 v_pos;
void main() {
    vec4 wp = u_model * vec4(in_pos, 1.0);
    v_pos = wp.xyz;
    v_norm = mat3(u_model) * in_norm;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

_AR_FRAG = """
#version 330
uniform vec4 u_bgr_a;
uniform vec3 u_emissive;
uniform float u_roughness;
in vec3 v_norm;
in vec3 v_pos;
out vec4 frag_bgra;
void main() {
    vec3 N = normalize(v_norm);
    vec3 V = normalize(-v_pos);
    vec3 L1 = normalize(vec3(0.35, 0.85, 0.65));
    vec3 L2 = normalize(vec3(-0.6, 0.35, 0.5));
    float d1 = max(dot(N, L1), 0.0);
    float d2 = max(dot(N, L2), 0.0) * 0.45;
    vec3 H = normalize(L1 + V);
    float shininess = mix(96.0, 12.0, clamp(u_roughness, 0.0, 1.0));
    float spec = pow(max(dot(N, H), 0.0), shininess) * mix(0.95, 0.15, u_roughness);
    float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0) * 0.28;
    // u_bgr_a stores RGB in .rgb cleanly converted to BGR output at end
    vec3 base_rgb = u_bgr_a.rgb;
    vec3 lit = base_rgb * (0.34 + 0.72 * d1 + 0.32 * d2) + vec3(1.0, 0.98, 0.94) * spec + u_emissive + base_rgb * fres;
    lit = clamp(lit, 0.0, 1.0);
    frag_bgra = vec4(lit.b, lit.g, lit.r, u_bgr_a.a);
}
"""


def _mat_translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def _mat_scale(sx: float, sy: float, sz: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


def _mat_rot_x(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], dtype=np.float32)


def _mat_rot_y(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], dtype=np.float32)


def _mat_rot_z(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32)


def _compute_normals_indexed(pos: np.ndarray, idx: np.ndarray) -> np.ndarray:
    norm = np.zeros_like(pos, dtype=np.float32)
    tris = idx.reshape(-1, 3)
    v0, v1, v2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    for k in range(3):
        np.add.at(norm, tris[:, k], fn)
    lens = np.linalg.norm(norm, axis=1, keepdims=True)
    lens[lens < 1e-6] = 1.0
    return (norm / lens).astype(np.float32)


def _make_sphere(stacks: int = 14, slices: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    verts, idxs = [], []
    for i in range(stacks + 1):
        phi = math.pi * i / stacks
        sp, cp = math.sin(phi), math.cos(phi)
        for j in range(slices + 1):
            th = math.tau * j / slices
            x, y, z = sp * math.cos(th), cp, sp * math.sin(th)
            verts.append((x, y, z))
    for i in range(stacks):
        for j in range(slices):
            a = i * (slices + 1) + j
            b = a + slices + 1
            idxs.extend([a, b, a + 1, b, b + 1, a + 1])
    p = np.array(verts, dtype=np.float32)
    i = np.array(idxs, dtype=np.uint32)
    return p, p.copy(), i


def _make_frustum(r_bot: float, r_top: float, h: float, slices: int = 24) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    verts, norms, idxs = [], [], []
    slope = (r_bot - r_top) / max(h, 1e-4)
    for k in range(slices + 1):
        th = math.tau * k / slices
        c, s = math.cos(th), math.sin(th)
        verts.append((r_bot * c, 0.0, r_bot * s))
        n = np.array([c, slope, s], dtype=np.float32)
        n /= max(np.linalg.norm(n), 1e-5)
        norms.append(tuple(n))
        verts.append((r_top * c, h, r_top * s))
        norms.append(tuple(n))
    for k in range(slices):
        a = k * 2
        idxs.extend([a, a + 1, a + 2, a + 1, a + 3, a + 2])
    return np.array(verts, dtype=np.float32), np.array(norms, dtype=np.float32), np.array(idxs, dtype=np.uint32)


def _make_box() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Unit box [-0.5, 0.5]^3 with crisp flat normals per face
    faces = [
        ((0, 0, 1), [(-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)]),
        ((0, 0, -1), [(0.5, -0.5, -0.5), (-0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5)]),
        ((0, 1, 0), [(-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5)]),
        ((0, -1, 0), [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5)]),
        ((1, 0, 0), [(0.5, -0.5, 0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5)]),
        ((-1, 0, 0), [(-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5)]),
    ]
    verts, norms, idxs = [], [], []
    for n, quad in faces:
        base = len(verts)
        for v in quad:
            verts.append(v)
            norms.append(n)
        idxs.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return np.array(verts, dtype=np.float32), np.array(norms, dtype=np.float32), np.array(idxs, dtype=np.uint32)


def _make_torus(major_r: float = 1.0, minor_r: float = 0.26, segs: int = 24, tube_segs: int = 12) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    verts, norms, idxs = [], [], []
    for i in range(segs + 1):
        u = math.tau * i / segs
        cu, su = math.cos(u), math.sin(u)
        for j in range(tube_segs + 1):
            v = math.tau * j / tube_segs
            cv, sv = math.cos(v), math.sin(v)
            r = major_r + minor_r * cv
            verts.append((r * cu, minor_r * sv, r * su))
            norms.append((cv * cu, sv, cv * su))
    for i in range(segs):
        for j in range(tube_segs):
            a = i * (tube_segs + 1) + j
            b = a + tube_segs + 1
            idxs.extend([a, b, a + 1, b, b + 1, a + 1])
    return np.array(verts, dtype=np.float32), np.array(norms, dtype=np.float32), np.array(idxs, dtype=np.uint32)


_POOL_COLORS_RGB = {
    0: (0.97, 0.96, 0.92),
    1: (0.96, 0.80, 0.14),
    2: (0.14, 0.42, 0.90),
    3: (0.92, 0.22, 0.20),
    4: (0.56, 0.20, 0.82),
    5: (0.96, 0.46, 0.12),
    6: (0.12, 0.62, 0.30),
    7: (0.58, 0.16, 0.16),
    8: (0.10, 0.11, 0.14),
    9: (0.98, 0.85, 0.35),
    10: (0.34, 0.62, 0.95),
    11: (0.95, 0.40, 0.38),
    12: (0.68, 0.40, 0.90),
    13: (0.98, 0.60, 0.30),
    14: (0.30, 0.76, 0.46),
    15: (0.72, 0.30, 0.30),
}

_TIER_COLORS_RGB = {
    "plankton": (0.52, 0.66, 0.82),
    "too_clever": (1.00, 0.62, 0.26),
    "schooler": (0.18, 0.86, 0.76),
    "rare": (1.00, 0.32, 0.35),
    "deep_cut": (0.66, 0.36, 0.98),
    "krillion": (1.00, 0.84, 0.32),
    "miss": (0.45, 0.50, 0.60),
}


def _power_rgb(power: float) -> tuple[float, float, float]:
    """Smooth Green -> Yellow -> Red RGB [0..1] indicator for live aim/power."""
    p = max(0.0, min(1.0, float(power)))
    if p <= 0.5:
        t = p * 2.0
        return (0.20 + 0.78 * t, 0.90 + 0.02 * t, 0.28 - 0.14 * t)
    t = (p - 0.5) * 2.0
    return (0.98, 0.92 - 0.68 * t, 0.14 + 0.08 * t)


class GamesAR3DRenderer:
    """Renders real lit 3D ModernGL game objects directly onto webcam frames."""

    def __init__(self, renderer3d) -> None:
        self.r3d = renderer3d
        self.ctx: moderngl.Context = renderer3d.ctx
        self.width: int = renderer3d.width
        self.height: int = renderer3d.height
        self.prog = self.ctx.program(vertex_shader=_AR_VERT, fragment_shader=_AR_FRAG)

        samples = min(4, self.ctx.max_samples)
        self.depth_rb = self.ctx.depth_renderbuffer((self.width, self.height), samples=samples)
        self.color_rb = self.ctx.renderbuffer((self.width, self.height), 4, samples=samples)
        self.fbo = self.ctx.framebuffer(color_attachments=[self.color_rb], depth_attachment=self.depth_rb)
        self.fbo_res = self.ctx.framebuffer(color_attachments=[self.ctx.texture((self.width, self.height), 4)])

        self.meshes = {
            "sphere": self._upload(*_make_sphere(14, 20)),
            "cup": self._upload(*_make_frustum(0.72, 1.0, 1.65, 24)),
            "box": self._upload(*_make_box()),
            "torus": self._upload(*_make_torus(1.0, 0.24, 24, 10)),
            "donut_dough": self._upload(*_make_torus(0.78, 0.44, 32, 18)),
            "donut_icing": self._upload(*_make_torus(0.78, 0.41, 32, 16)),
            "disc": self._upload(*_make_frustum(1.0, 1.0, 0.14, 28)),
        }

    def _upload(self, pos: np.ndarray, norm: np.ndarray, idx: np.ndarray) -> tuple[moderngl.VertexArray, int]:
        vbo_p = self.ctx.buffer(pos.tobytes())
        vbo_n = self.ctx.buffer(norm.tobytes())
        ibo = self.ctx.buffer(idx.tobytes())
        vao = self.ctx.vertex_array(self.prog, [(vbo_p, "3f", "in_pos"), (vbo_n, "3f", "in_norm")], index_buffer=ibo)
        return vao, len(idx)

    def _draw_mesh(
        self,
        key: str,
        model: np.ndarray,
        rgb: tuple[float, float, float],
        alpha: float = 1.0,
        roughness: float = 0.28,
        emissive: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        vao, _ = self.meshes[key]
        mvp = self.r3d.proj @ model
        self.prog["u_mvp"].write(mvp.T.tobytes())
        self.prog["u_model"].write(model.T.tobytes())
        self.prog["u_bgr_a"].value = (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha))
        self.prog["u_emissive"].value = emissive
        self.prog["u_roughness"].value = float(roughness)
        vao.render()

    def _composite_fbo(self, frame_bgr: np.ndarray) -> None:
        self.ctx.copy_framebuffer(self.fbo_res, self.fbo)
        raw = np.frombuffer(self.fbo_res.read(components=4), dtype=np.uint8).reshape(self.height, self.width, 4)
        raw = np.flipud(raw)
        a = raw[:, :, 3]
        mask = a > 3
        if not np.any(mask):
            return
        af = a[mask].astype(np.float32)[:, None] / 255.0
        fg = raw[:, :, :3][mask].astype(np.float32)
        bg = frame_bgr[mask].astype(np.float32)
        frame_bgr[mask] = np.clip(fg * af + bg * (1.0 - af), 0, 255).astype(np.uint8)

    def render(self, frame_bgr: np.ndarray, games_engine, face_state, open_palms: list, now: float) -> None:
        if games_engine is None:
            return
        g = games_engine.active_game
        if g in ("lobby", "word_duel"):
            return

        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.fbo.use()
        self.fbo.clear(0.0, 0.0, 0.0, 0.0)
        aim = getattr(games_engine, "webcam_aim", None) or getattr(games_engine, "guest_aim", None)

        if g == "beer_pong":
            self._render_pong(games_engine.beer_pong, now, aim)
        elif g == "pool":
            self._render_pool(games_engine.pool, now, aim)
        elif g == "classic_darts":
            self._render_classic_darts(games_engine.classic_darts, now, aim)
        elif g == "face_darts":
            stuck = games_engine.bus.get_stuck_darts() if hasattr(games_engine, "bus") else []
            self._render_face_darts(games_engine.face_darts, stuck, face_state, open_palms, now)
        elif g == "mouth_catch":
            self._render_mouth_catch(games_engine.mouth_catch, now)
        elif g == "rare_answer":
            self._render_krillion_shrimp(games_engine.krillion, face_state, now)

        self._composite_fbo(frame_bgr)

    def _render_pong(self, bp, now: float, webcam_aim: dict | None = None) -> None:
        # Sleek side-docked 3D Bar Table & Red Solo Cups on bottom-left so user's face stays unobstructed
        base_m = _mat_translate(-0.38, -0.32, -1.32) @ _mat_rot_x(0.28) @ _mat_scale(0.70, 0.70, 0.70)
        # Mahogany table surface slab
        self._draw_mesh("box", base_m @ _mat_translate(0.0, -0.04, 0.0) @ _mat_scale(0.95, 0.04, 0.65), (0.36, 0.21, 0.11), roughness=0.42)
        # Cups on host & guest side visible cleanly
        for side_z, rack in [(-0.18, bp.racks.get("host", [])), (0.14, bp.racks.get("guest", []))]:
            for c in rack:
                if not c.get("alive", True):
                    continue
                wob = float(c.get("wobble", 0.0))
                tilt = math.sin(now * 26.0) * wob * 0.18
                cx = float(c["x"]) * 0.82
                cz = (float(c["z"]) - 0.80) * 0.72 + side_z
                cm = base_m @ _mat_translate(cx, -0.02, cz) @ _mat_rot_z(tilt) @ _mat_scale(0.046, 0.068, 0.046)
                self._draw_mesh("cup", cm, (0.86, 0.14, 0.16), roughness=0.28)
                self._draw_mesh("torus", cm @ _mat_translate(0.0, 1.63, 0.0) @ _mat_scale(0.98, 0.35, 0.98), (0.96, 0.96, 0.98), roughness=0.20)
                self._draw_mesh("disc", cm @ _mat_translate(0.0, 1.38, 0.0) @ _mat_scale(0.88, 0.1, 0.88), (0.92, 0.66, 0.18), roughness=0.12)
        # Live Green -> Yellow -> Red target ring over target rack when either player aims
        if webcam_aim and webcam_aim.get("kind") == "beer_pong":
            tx = float(webcam_aim.get("aimX", 0.0)) * 0.82
            pwr = float(webcam_aim.get("power", 0.55))
            tz = -0.18 + (pwr - 0.5) * 0.24
            pr, pg, pb = _power_rgb(pwr)
            tm = base_m @ _mat_translate(tx, 0.11, tz) @ _mat_scale(0.062, 0.032, 0.062)
            self._draw_mesh("torus", tm, (pr, pg, pb), roughness=0.1, emissive=(pr * 0.6, pg * 0.6, pb * 0.6))
        # Flying ping-pong balls in 3D space
        for b in bp.balls:
            bx = float(b.x) * 0.82
            by = float(b.y) * 0.95 - 0.02
            bz = (float(b.z) - 0.55) * 0.65
            bm = base_m @ _mat_translate(bx, by, bz) @ _mat_scale(0.022, 0.022, 0.022)
            self._draw_mesh("sphere", bm, (0.98, 0.98, 0.95), roughness=0.18)

    def _render_pool(self, pm, now: float, webcam_aim: dict | None = None) -> None:
        # Sleek Top-Down GamePigeon PoolScene table docked on bottom-left companion rail
        base_m = _mat_translate(-0.38, -0.24, -1.32) @ _mat_rot_x(math.pi * 0.49) @ _mat_scale(0.68, 0.68, 0.68)
        self._draw_mesh("box", base_m @ _mat_translate(0.0, -0.03, 0.0) @ _mat_scale(1.12, 0.04, 0.62), (0.28, 0.15, 0.08), roughness=0.38)
        self._draw_mesh("box", base_m @ _mat_translate(0.0, -0.008, 0.0) @ _mat_scale(1.00, 0.015, 0.50), (0.05, 0.42, 0.24), roughness=0.74)
        # 6 Overhead Pocket Wells & Brass Collars
        for px, pz in [(-0.465, -0.232), (0.0, -0.245), (0.465, -0.232), (-0.465, 0.232), (0.0, 0.245), (0.465, 0.232)]:
            self._draw_mesh("disc", base_m @ _mat_translate(px, 0.002, pz) @ _mat_scale(0.030, 0.06, 0.030), (0.03, 0.03, 0.04), roughness=0.95)
            self._draw_mesh("torus", base_m @ _mat_translate(px, 0.006, pz) @ _mat_scale(0.032, 0.018, 0.032), (0.78, 0.60, 0.22), roughness=0.25)

        cue_raw = None
        cue_ball = None
        active_balls = []
        for b in pm.balls:
            if b.potted:
                continue
            bx = (float(b.x) / 1.0) * 0.47
            bz = -(float(b.y) / 0.5) * 0.22
            if b.num == 0:
                cue_raw = b
                cue_ball = (bx, bz)
            else:
                active_balls.append(b)
            rgb = _POOL_COLORS_RGB.get(b.num, (0.9, 0.9, 0.9))
            bm = base_m @ _mat_translate(bx, 0.016, bz) @ _mat_scale(0.017, 0.017, 0.017)
            self._draw_mesh("sphere", bm, rgb, roughness=0.08)

        # GamePigeon Dual Trajectory + Live Cue Stick + Green/Yellow/Red Power Color for Active Shooter
        if cue_ball is not None and cue_raw is not None and pm.phase == "aiming":
            has_aim = bool(webcam_aim and webcam_aim.get("kind") == "pool")
            ang = float(webcam_aim["angle"]) if has_aim else 0.0
            pwr = float(webcam_aim["power"]) if has_aim else 0.0
            pr, pg, pb = _power_rgb(pwr) if pwr > 0.02 else (0.28, 0.92, 0.55)
            dx, dz = math.cos(ang), -math.sin(ang)
            cx, cz = cue_ball

            # Raycast against object balls & cushions for ghost ball + dual post-collision forks
            r_tbl = float(getattr(pm, "BALL_R", 0.028))
            min_d = r_tbl * 2.0
            rx_d, ry_d = math.cos(ang), math.sin(ang)
            t_best = 9.9
            max_tx, max_ty = 1.0 - r_tbl, 0.5 - r_tbl
            if rx_d > 1e-6:
                t_best = min(t_best, (max_tx - cue_raw.x) / rx_d)
            elif rx_d < -1e-6:
                t_best = min(t_best, (-max_tx - cue_raw.x) / rx_d)
            if ry_d > 1e-6:
                t_best = min(t_best, (max_ty - cue_raw.y) / ry_d)
            elif ry_d < -1e-6:
                t_best = min(t_best, (-max_ty - cue_raw.y) / ry_d)
            hit_b = None
            for ob in active_balls:
                ox, oy = ob.x - cue_raw.x, ob.y - cue_raw.y
                proj = ox * rx_d + oy * ry_d
                if proj <= 0.0:
                    continue
                perp2 = ox * ox + oy * oy - proj * proj
                if perp2 > min_d * min_d:
                    continue
                thc = math.sqrt(max(0.0, min_d * min_d - perp2))
                th = proj - thc
                if 0.0 <= th < t_best:
                    t_best = th
                    hit_b = ob

            gx_t = cue_raw.x + rx_d * t_best
            gy_t = cue_raw.y + ry_d * t_best
            gx = (gx_t / 1.0) * 0.47
            gz = -(gy_t / 0.5) * 0.22
            if has_aim:
                steps = max(3, min(14, int(math.hypot(gx - cx, gz - cz) / 0.036)))
                for s_i in range(1, steps + 1):
                    f = s_i / float(steps)
                    px, pz = cx + (gx - cx) * f, cz + (gz - cz) * f
                    dot_m = base_m @ _mat_translate(px, 0.018, pz) @ _mat_scale(0.005, 0.004, 0.005)
                    self._draw_mesh("sphere", dot_m, (pr, pg, pb), roughness=0.1, emissive=(pr * 0.55, pg * 0.55, pb * 0.55))
                self._draw_mesh("torus", base_m @ _mat_translate(gx, 0.014, gz) @ _mat_scale(0.016, 0.008, 0.016), (pr, pg, pb), roughness=0.1, emissive=(pr * 0.45, pg * 0.45, pb * 0.45))
                if hit_b is not None:
                    ux, uy = hit_b.x - gx_t, hit_b.y - gy_t
                    ulen = math.hypot(ux, uy) or 1.0
                    ux, uy = ux / ulen, uy / ulen
                    for s_i in range(1, 5):
                        ox_s = (hit_b.x + ux * (s_i * 0.065)) / 1.0 * 0.47
                        oz_s = -(hit_b.y + uy * (s_i * 0.065)) / 0.5 * 0.22
                        self._draw_mesh("sphere", base_m @ _mat_translate(ox_s, 0.018, oz_s) @ _mat_scale(0.005, 0.004, 0.005), (0.42, 0.92, 1.0), roughness=0.1, emissive=(0.2, 0.6, 0.8))
                    dot_tu = rx_d * ux + ry_d * uy
                    tx_d, ty_d = rx_d - dot_tu * ux, ry_d - dot_tu * uy
                    tlen = math.hypot(tx_d, ty_d)
                    if tlen > 0.06:
                        tx_d, ty_d = tx_d / tlen, ty_d / tlen
                        for s_i in range(1, 4):
                            dx_s = (gx_t + tx_d * (s_i * 0.055)) / 1.0 * 0.47
                            dz_s = -(gy_t + ty_d * (s_i * 0.055)) / 0.5 * 0.22
                            self._draw_mesh("sphere", base_m @ _mat_translate(dx_s, 0.018, dz_s) @ _mat_scale(0.0045, 0.004, 0.0045), (0.98, 0.85, 0.28), roughness=0.1, emissive=(0.6, 0.45, 0.1))

            pull = 0.04 + pwr * 0.14
            stick_len = 0.34
            sx = cx - dx * (pull + stick_len * 0.5)
            sz = cz - dz * (pull + stick_len * 0.5)
            stick_m = (
                base_m
                @ _mat_translate(sx, 0.026, sz)
                @ _mat_rot_y(ang)
                @ _mat_scale(stick_len, 0.012, 0.012)
            )
            self._draw_mesh("box", stick_m, (0.82, 0.62, 0.36), roughness=0.28, emissive=(pr * 0.12, pg * 0.12, pb * 0.12))

    def _render_classic_darts(self, cd, now: float, webcam_aim: dict | None = None) -> None:
        # Floating 3D bristle dartboard docked on right side rail + stuck darts & live aim torus
        bm = _mat_translate(0.44, -0.14, -1.28) @ _mat_rot_y(-0.22) @ _mat_rot_x(math.pi * 0.5) @ _mat_scale(0.82, 0.82, 0.82)
        self._draw_mesh("disc", bm @ _mat_scale(0.21, 0.16, 0.21), (0.22, 0.14, 0.09), roughness=0.45)
        self._draw_mesh("disc", bm @ _mat_translate(0.0, 0.014, 0.0) @ _mat_scale(0.18, 0.12, 0.18), (0.10, 0.11, 0.12), roughness=0.68)
        self._draw_mesh("torus", bm @ _mat_translate(0.0, 0.022, 0.0) @ _mat_scale(0.18, 0.03, 0.18), (0.85, 0.22, 0.22), roughness=0.25)
        self._draw_mesh("torus", bm @ _mat_translate(0.0, 0.022, 0.0) @ _mat_scale(0.11, 0.025, 0.11), (0.16, 0.72, 0.34), roughness=0.25)
        self._draw_mesh("disc", bm @ _mat_translate(0.0, 0.024, 0.0) @ _mat_scale(0.026, 0.05, 0.026), (0.90, 0.18, 0.18), roughness=0.22)
        for h in cd.hits_this_turn:
            hx = float(h.get("x", 0.0)) * 0.17
            hy = -float(h.get("y", 0.0)) * 0.17
            dm = bm @ _mat_translate(hx, 0.05, hy) @ _mat_scale(0.008, 0.05, 0.008)
            self._draw_mesh("cup", dm, (0.95, 0.78, 0.24), roughness=0.22)
        if webcam_aim and webcam_aim.get("kind") == "classic_darts":
            ax = float(webcam_aim.get("nx", 0.0)) * 0.17
            ay = -float(webcam_aim.get("ny", 0.0)) * 0.17
            pwr = float(webcam_aim.get("power", 0.5))
            pr, pg, pb = _power_rgb(pwr)
            rm = bm @ _mat_translate(ax, 0.032, ay) @ _mat_scale(0.024, 0.02, 0.024)
            self._draw_mesh("torus", rm, (pr, pg, pb), roughness=0.1, emissive=(pr * 0.6, pg * 0.6, pb * 0.6))

    def _draw_3d_suction_dart(self, base_m: np.ndarray, shaft_rgb: tuple[float, float, float]) -> None:
        # Local +Y is tip/suction cup forward, -Y is foam body & tail fins.
        emiss = (shaft_rgb[0] * 0.14, shaft_rgb[1] * 0.14, shaft_rgb[2] * 0.14)
        self._draw_mesh("cup", base_m @ _mat_translate(0.0, 0.052, 0.0) @ _mat_scale(0.024, 0.015, 0.024), (0.14, 0.16, 0.22), roughness=0.34)
        self._draw_mesh("torus", base_m @ _mat_translate(0.0, 0.064, 0.0) @ _mat_scale(0.021, 0.026, 0.021), (0.28, 0.31, 0.40), roughness=0.28)
        self._draw_mesh("torus", base_m @ _mat_translate(0.0, 0.032, 0.0) @ _mat_scale(0.014, 0.018, 0.014), (0.86, 0.90, 0.96), roughness=0.10)
        self._draw_mesh("cup", base_m @ _mat_translate(0.0, -0.014, 0.0) @ _mat_scale(0.014, 0.038, 0.014), shaft_rgb, roughness=0.25, emissive=emiss)
        self._draw_mesh("sphere", base_m @ _mat_translate(0.0, -0.048, 0.0) @ _mat_scale(0.011, 0.011, 0.011), shaft_rgb, roughness=0.25, emissive=emiss)
        self._draw_mesh("box", base_m @ _mat_translate(0.0, -0.058, 0.0) @ _mat_scale(0.034, 0.028, 0.004), (0.96, 0.97, 0.99), roughness=0.20, emissive=(0.08, 0.09, 0.11))
        self._draw_mesh("box", base_m @ _mat_translate(0.0, -0.058, 0.0) @ _mat_rot_y(math.pi * 0.5) @ _mat_scale(0.034, 0.028, 0.004), (0.80, 0.95, 1.00), roughness=0.20, emissive=(0.06, 0.12, 0.16))

    def _render_face_darts(self, fd, stuck_darts: list, face_state, open_palms: list, now: float) -> None:
        # 1. Dual counter-rotating 3D hex palm shield
        if open_palms:
            px, py, pr = open_palms[0]
            px_pix = float(px) * self.width if float(px) <= 1.5 else float(px)
            py_pix = float(py) * self.height if float(py) <= 1.5 else float(py)
            pr_pix = float(pr) * self.width if float(pr) <= 1.0 else float(pr)
            wp, _ = self.r3d.grip_world_pos(px_pix, py_pix, max(70.0, pr_pix * 0.9))
            sm = _mat_translate(float(wp[0]), float(wp[1]), float(wp[2]) + 0.08) @ _mat_rot_x(math.pi * 0.5)
            self._draw_mesh("torus", sm @ _mat_rot_y(now * 2.5) @ _mat_scale(0.18, 0.10, 0.18), (0.26, 0.90, 1.00), alpha=0.90, roughness=0.14, emissive=(0.14, 0.48, 0.72))
            self._draw_mesh("torus", sm @ _mat_rot_y(-now * 3.8) @ _mat_scale(0.12, 0.12, 0.12), (0.96, 0.40, 0.86), alpha=0.88, roughness=0.14, emissive=(0.34, 0.10, 0.30))
            self._draw_mesh("disc", sm @ _mat_scale(0.155, 0.05, 0.155), (0.34, 0.92, 1.00), alpha=0.26, roughness=0.10, emissive=(0.10, 0.36, 0.52))
            for k in range(6):
                a = k * (math.tau / 6.0) + now * 1.4
                nm = sm @ _mat_translate(math.cos(a) * 0.175, 0.0, math.sin(a) * 0.175) @ _mat_scale(0.016, 0.016, 0.016)
                self._draw_mesh("sphere", nm, (0.72, 0.96, 1.00), roughness=0.10, emissive=(0.25, 0.55, 0.70))

        # 2. Stuck 3D suction darts anchored onto detected face landmarks
        for sd in stuck_darts:
            age = max(0.0, now - float(sd.created))
            if age > float(sd.ttl):
                continue
            if face_state is not None:
                sc = max(90.0, float(face_state.face_scale_px))
                cx = float(face_state.nose_px[0]) + float(sd.dx_norm) * sc
                cy = float(face_state.nose_px[1]) + float(sd.dy_norm) * sc
            else:
                cx, cy = float(sd.fallback_xy[0]), float(sd.fallback_xy[1])
                sc = 145.0
            cy += float(sd.fall_y)
            if cy > self.height + 80:
                continue
            wp, _ = self.r3d.grip_world_pos(cx, cy, max(85.0, sc * 0.62))
            wobble = math.sin(age * 36.0) * math.exp(-age * 6.0) * 0.24
            ang = math.radians(float(sd.angle_deg) * 0.6)
            bgr = sd.color_bgr
            rgb = (float(bgr[2]) / 255.0, float(bgr[1]) / 255.0, float(bgr[0]) / 255.0)
            dm = _mat_translate(float(wp[0]), float(wp[1]), float(wp[2]) + 0.05) @ _mat_rot_z(ang) @ _mat_rot_x(-math.pi * 0.5 + 0.28 + wobble) @ _mat_scale(1.18, 1.18, 1.18)
            self._draw_3d_suction_dart(dm, rgb)

        # 3. Incoming 3D suction darts in depth flight
        for d in getattr(fd, "active", []):
            u = min(1.0, float(d.elapsed) / max(float(d.duration), 1e-3))
            cx = float(d.start_x) + (float(d.target_x) - float(d.start_x)) * u
            cy = float(d.start_y) + (float(d.target_y) - float(d.start_y)) * u - math.sin(u * math.pi) * 0.08
            dz = 1.0 - u
            z = max(0.08, 1.0 - dz)
            wx = (cx - 0.5) * 0.9 * z
            wy = (0.5 - cy) * 0.5 * z
            wz = -0.35 - dz * 1.1
            dm = _mat_translate(wx, wy, wz) @ _mat_rot_x(-math.pi * 0.5) @ _mat_rot_y(now * 8.5) @ _mat_scale(1.15, 1.15, 1.15)
            self._draw_3d_suction_dart(dm, (0.96, 0.34, 0.56))

    def _draw_3d_donut(self, dm: np.ndarray) -> None:
        self._draw_mesh("donut_dough", dm, (0.92, 0.68, 0.36), roughness=0.45)
        icing_m = dm @ _mat_translate(0.0, 0.16, 0.0) @ _mat_scale(0.98, 0.84, 0.98)
        self._draw_mesh("donut_icing", icing_m, (0.98, 0.38, 0.72), roughness=0.12, emissive=(0.12, 0.03, 0.08))
        for k in range(6):
            a = k * (math.tau / 6.0) + 0.35
            dr = 0.96 + (k % 2) * 0.05
            drop_y = 0.02 - (k % 3) * 0.04
            sm = dm @ _mat_translate(math.cos(a) * dr, drop_y, math.sin(a) * dr) @ _mat_scale(0.14, 0.19, 0.14)
            self._draw_mesh("sphere", sm, (0.98, 0.38, 0.72), roughness=0.12)
        sprinkle_cols = [
            (0.28, 0.92, 0.98),
            (0.98, 0.86, 0.24),
            (0.45, 0.96, 0.58),
            (0.98, 0.98, 0.98),
            (0.98, 0.42, 0.32),
        ]
        for k in range(10):
            a = k * (math.tau / 10.0) + 0.18
            rad = 0.66 + (k % 3) * 0.14
            spm = dm @ _mat_translate(math.cos(a) * rad, 0.50, math.sin(a) * rad) @ _mat_rot_y(a + 0.7) @ _mat_rot_z(0.15) @ _mat_scale(0.11, 0.045, 0.045)
            self._draw_mesh("box", spm, sprinkle_cols[k % len(sprinkle_cols)], roughness=0.22)

    def _render_mouth_catch(self, mc, now: float) -> None:
        for f in getattr(mc, "active", []):
            u = min(1.0, float(f.elapsed) / max(float(f.duration), 1e-3))
            cx = float(f.start_x) + (float(f.target_x) - float(f.start_x)) * u
            cy = float(f.start_y) + (float(f.target_y) - float(f.start_y)) * u - math.sin(u * math.pi) * 0.14
            fz = 1.0 - u
            wx = (cx - 0.5) * 0.9
            wy = (0.5 - cy) * 0.55
            wz = -0.32 - fz * 1.1
            dm = _mat_translate(wx, wy, wz) @ _mat_rot_x(0.85 + now * 4.5) @ _mat_rot_y(now * 3.2) @ _mat_scale(0.056, 0.056, 0.056)
            self._draw_3d_donut(dm)

    def _render_krillion_shrimp(self, krill, face_state, now: float) -> None:
        # 3D multi-segment tier-colored shrimp/krill floating right beside player's webcam head!
        last_tier = "plankton"
        if krill.history:
            last_row = krill.history[-1]
            # Pick best tier pulled this round for mascot color showcase!
            g = last_row.get("guest", {})
            h = last_row.get("host", {})
            best = g if int(g.get("pts", 0)) >= int(h.get("pts", 0)) else h
            if best.get("tierKey"):
                last_tier = str(best["tierKey"])
        elif krill.last_feedback:
            for slot in krill.last_feedback.values():
                if slot.get("tierKey"):
                    last_tier = str(slot["tierKey"])

        rgb = _TIER_COLORS_RGB.get(last_tier, _TIER_COLORS_RGB["plankton"])
        gold_boost = (0.32, 0.25, 0.04) if last_tier == "krillion" else tuple(c * 0.16 for c in rgb)

        if face_state is not None:
            hx_px = float(face_state.nose_px[0]) - float(face_state.face_scale_px) * 1.15
            hy_px = float(face_state.nose_px[1]) - float(face_state.face_scale_px) * 0.15
            wp, _ = self.r3d.grip_world_pos(max(110.0, hx_px), max(110.0, hy_px), float(face_state.face_scale_px) * 0.72)
            base_m = _mat_translate(float(wp[0]), float(wp[1]) + math.sin(now * 2.6) * 0.025, float(wp[2]))
        else:
            base_m = _mat_translate(-0.34, 0.06 + math.sin(now * 2.6) * 0.03, -0.95)

        swim = math.sin(now * 6.5) * 0.18
        root = base_m @ _mat_rot_y(0.45 + math.sin(now * 1.7) * 0.22) @ _mat_rot_z(-0.18)

        # Articulated 3D shrimp/krill body segments (head carapace -> 5 tail segments -> tail fan + eyes)
        seg_specs = [
            (0.00, 0.00, 0.042, 0.032, 0.032),
            (-0.036, 0.004, 0.034, 0.028, 0.028),
            (-0.066, -0.004 + swim * 0.015, 0.028, 0.023, 0.023),
            (-0.092, -0.018 + swim * 0.03, 0.022, 0.018, 0.018),
            (-0.112, -0.036 + swim * 0.05, 0.017, 0.013, 0.013),
        ]
        for idx, (ox, oy, sx, sy, sz) in enumerate(seg_specs):
            sm = root @ _mat_translate(ox, oy, 0.0) @ _mat_scale(sx, sy, sz)
            self._draw_mesh("sphere", sm, rgb, roughness=0.14, emissive=gold_boost)
        # Tail fan
        fan_m = root @ _mat_translate(-0.128, -0.050 + swim * 0.06, 0.0) @ _mat_rot_z(0.55 + swim) @ _mat_scale(0.026, 0.006, 0.034)
        self._draw_mesh("box", fan_m, rgb, roughness=0.22, emissive=gold_boost)
        # Glossy eyes on head segment
        for ez in (-0.018, 0.018):
            self._draw_mesh("sphere", root @ _mat_translate(0.026, 0.014, ez) @ _mat_scale(0.008, 0.008, 0.008), (0.04, 0.04, 0.06), roughness=0.05)
        # Rising ocean bubbles around shrimp
        for b_i in range(4):
            bt = (now * 0.8 + b_i * 0.25) % 1.0
            bx = -0.04 + b_i * 0.032
            by = -0.10 + bt * 0.26
            self._draw_mesh("sphere", root @ _mat_translate(bx, by, 0.03) @ _mat_scale(0.008, 0.008, 0.008), (0.65, 0.92, 1.0), alpha=0.65 * (1.0 - bt), roughness=0.05, emissive=(0.2, 0.4, 0.5))
