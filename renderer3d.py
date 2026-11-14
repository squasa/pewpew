"""Real-time moderngl 3D renderer for hilt.glb + depth-occluded lightsaber blade."""
from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

import cv2
import moderngl
import numpy as np

GRIP_LOCAL_Y = 0.095        # center of fist grip along hilt +Y axis (meters in hilt.glb)
HILT_TOTAL_LEN = 0.257      # pommel (0) to emitter mouth (0.257)
EMITTER_LOCAL_Y = 0.255     # slightly inside emitter lip so blade emerges cleanly
BLADE_MAX_LEN = 0.88        # full blade length in hilt model meters (~3.4x hilt)


def _quat_to_mat4(q_xyzw: list[float]) -> np.ndarray:
    x, y, z, w = q_xyzw
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = 1 - 2 * (y * y + z * z)
    m[0, 1] = 2 * (x * y - w * z)
    m[0, 2] = 2 * (x * z + w * y)
    m[1, 0] = 2 * (x * y + w * z)
    m[1, 1] = 1 - 2 * (x * x + z * z)
    m[1, 2] = 2 * (y * z - w * x)
    m[2, 0] = 2 * (x * z - w * y)
    m[2, 1] = 2 * (y * z + w * x)
    m[2, 2] = 1 - 2 * (x * x + y * y)
    return m


def _perspective(fov_y_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def _read_accessor(gltf: dict, bin_blob: bytes, idx: int) -> np.ndarray:
    acc = gltf["accessors"][idx]
    bv = gltf["bufferViews"][acc["bufferView"]]
    offset = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    count = acc["count"]
    ctype_map = {
        5120: np.int8,
        5121: np.uint8,
        5122: np.int16,
        5123: np.uint16,
        5125: np.uint32,
        5126: np.float32,
    }
    ncomp_map = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
    dt = np.dtype(ctype_map[acc["componentType"]])
    nc = ncomp_map[acc["type"]]
    stride = bv.get("byteStride", dt.itemsize * nc)
    if stride == dt.itemsize * nc:
        arr = np.frombuffer(bin_blob, dtype=dt, count=count * nc, offset=offset)
        arr = arr.reshape(count, nc) if nc > 1 else arr
    else:
        arr = np.empty((count, nc) if nc > 1 else count, dtype=dt)
        for i in range(count):
            pos = offset + i * stride
            elem = np.frombuffer(bin_blob, dtype=dt, count=nc, offset=pos)
            arr[i] = elem if nc > 1 else elem[0]
    return np.ascontiguousarray(arr)


BLADE_COLOR_ORDER: tuple[str, ...] = ("blue", "emerald", "purple", "red", "gold", "white")

BLADE_COLORS: dict[str, dict[str, tuple[float, float, float]]] = {
    "blue": {
        "label": "Kyber Blue",
        "glow_bgr": (1.0, 0.68, 0.28),
        "trail_bgr": (1.0, 0.72, 0.34),
        "light_rgb": (0.45, 0.80, 1.0),
    },
    "emerald": {
        "label": "Consular Green",
        "glow_bgr": (0.18, 1.0, 0.22),
        "trail_bgr": (0.16, 0.96, 0.18),
        "light_rgb": (0.20, 1.0, 0.24),
    },
    "purple": {
        "label": "Amethyst",
        "glow_bgr": (1.0, 0.22, 0.70),
        "trail_bgr": (0.98, 0.20, 0.66),
        "light_rgb": (0.70, 0.22, 1.0),
    },
    "red": {
        "label": "Crimson",
        "glow_bgr": (0.14, 0.14, 1.0),
        "trail_bgr": (0.12, 0.14, 0.96),
        "light_rgb": (1.0, 0.16, 0.14),
    },
    "gold": {
        "label": "Temple Gold",
        "glow_bgr": (0.14, 0.78, 1.0),
        "trail_bgr": (0.14, 0.74, 0.98),
        "light_rgb": (1.0, 0.78, 0.14),
    },
    "white": {
        "label": "Ahsoka White",
        "glow_bgr": (1.0, 0.96, 0.92),
        "trail_bgr": (0.96, 0.92, 0.88),
        "light_rgb": (0.92, 0.96, 1.0),
    },
}


@dataclass
class _SubMesh:
    vao: moderngl.VertexArray
    node_mat: np.ndarray
    base_color: tuple[float, float, float]
    metallic: float
    roughness: float
    name: str = ""


def _load_glb_meshes(glb_path: Path) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, tuple[float, float, float], float, float]]:
    """Parse GLB file into (positions, normals, indices, node_mat4, base_color, metallic, roughness)."""
    raw = glb_path.read_bytes()
    magic, _, _ = struct.unpack("<3I", raw[:12])
    if magic != 0x46546C67:
        raise ValueError(f"Invalid GLB header in {glb_path}")
    pos = 12
    json_bytes = b""
    bin_bytes = b""
    while pos < len(raw):
        clen, ctype = struct.unpack("<2I", raw[pos:pos + 8])
        cdata = raw[pos + 8:pos + 8 + clen]
        if ctype == 0x4E4F534A:
            json_bytes = cdata
        elif ctype == 0x004E4942:
            bin_bytes = cdata
        pos += 8 + clen
    gltf = json.loads(json_bytes.decode("utf-8"))

    # Compute world transform for each node (supports parent-child hierarchies)
    nodes = gltf.get("nodes", [])
    local_mats = []
    children_map: dict[int, int] = {}
    for idx, n in enumerate(nodes):
        if "matrix" in n:
            m = np.array(n["matrix"], dtype=np.float32).reshape(4, 4).T
        else:
            m = np.eye(4, dtype=np.float32)
            if "scale" in n:
                sx, sy, sz = n["scale"]
                s = np.diag([sx, sy, sz, 1.0]).astype(np.float32)
                m = m @ s
            if "rotation" in n:
                m = _quat_to_mat4(n["rotation"]) @ m
            if "translation" in n:
                tx, ty, tz = n["translation"]
                t = np.eye(4, dtype=np.float32)
                t[:3, 3] = [tx, ty, tz]
                m = t @ m
        local_mats.append(m)
        for ch in n.get("children", []):
            children_map[ch] = idx

    world_mats: dict[int, np.ndarray] = {}

    def get_world(i: int) -> np.ndarray:
        if i in world_mats:
            return world_mats[i]
        m = local_mats[i]
        if i in children_map:
            m = get_world(children_map[i]) @ m
        world_mats[i] = m
        return m

    mats_def = gltf.get("materials", [])
    out = []
    for n_idx, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        node_name = str(node.get("name", ""))
        wmat = get_world(n_idx)
        mesh = gltf["meshes"][node["mesh"]]
        for prim in mesh.get("primitives", []):
            attrs = prim["attributes"]
            positions = _read_accessor(gltf, bin_bytes, attrs["POSITION"]).astype(np.float32)
            if "NORMAL" in attrs:
                normals = _read_accessor(gltf, bin_bytes, attrs["NORMAL"]).astype(np.float32)
            else:
                normals = np.tile([0.0, 1.0, 0.0], (len(positions), 1)).astype(np.float32)
            if "indices" in prim:
                indices = _read_accessor(gltf, bin_bytes, prim["indices"]).astype(np.uint32)
            else:
                indices = np.arange(len(positions), dtype=np.uint32)
            mat_idx = prim.get("material")
            base = (0.5, 0.5, 0.5)
            metallic = 0.8
            roughness = 0.35
            if mat_idx is not None and mat_idx < len(mats_def):
                pbr = mats_def[mat_idx].get("pbrMetallicRoughness", {})
                bc = pbr.get("baseColorFactor", [0.5, 0.5, 0.5, 1.0])
                base = (float(bc[0]), float(bc[1]), float(bc[2]))
                metallic = float(pbr.get("metallicFactor", 0.9 if "metal" in mats_def[mat_idx].get("name", "").lower() or "steel" in mats_def[mat_idx].get("name", "").lower() or "brass" in mats_def[mat_idx].get("name", "").lower() else 0.0))
                roughness = float(pbr.get("roughnessFactor", 0.35))
            out.append((positions, normals, indices, wmat, base, metallic, roughness, node_name))
    return out


def _build_capsule_blade_mesh(segs: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """Unit blade cylinder (y in [0, 1], radius 1) + hemispherical tip cap."""
    verts = []
    idxs = []
    # Cylinder rings: y=0 and y=1
    for j, y in enumerate([0.0, 1.0]):
        for i in range(segs):
            a = 2.0 * math.pi * i / segs
            verts.append((math.cos(a), y, math.sin(a)))
    for i in range(segs):
        ni = (i + 1) % segs
        a, b = i, ni
        c, d = segs + i, segs + ni
        idxs.extend([a, c, b, b, c, d])
    # Bottom cap at y=0
    bot_c = len(verts)
    verts.append((0.0, 0.0, 0.0))
    for i in range(segs):
        ni = (i + 1) % segs
        idxs.extend([bot_c, i, ni])
    # Top hemisphere rings above y=1
    rings = 6
    prev_ring = list(range(segs, 2 * segs))
    for r in range(1, rings):
        phi = (math.pi / 2.0) * (r / rings)
        y = 1.0 + math.sin(phi) * 0.02  # mild rounded tip
        rad = math.cos(phi)
        cur_ring = []
        for i in range(segs):
            a = 2.0 * math.pi * i / segs
            cur_ring.append(len(verts))
            verts.append((rad * math.cos(a), y, rad * math.sin(a)))
        for i in range(segs):
            ni = (i + 1) % segs
            idxs.extend([prev_ring[i], cur_ring[i], prev_ring[ni],
                         prev_ring[ni], cur_ring[i], cur_ring[ni]])
        prev_ring = cur_ring
    top_c = len(verts)
    verts.append((0.0, 1.02, 0.0))
    for i in range(segs):
        ni = (i + 1) % segs
        idxs.extend([prev_ring[i], top_c, prev_ring[ni]])
    return np.array(verts, dtype=np.float32), np.array(idxs, dtype=np.uint32)


_HILT_VERT = """
#version 330
uniform mat4 u_mvp;
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_norm;
out vec3 v_world_pos;
out vec3 v_world_norm;
void main() {
    vec4 wp = u_model * vec4(in_pos, 1.0);
    v_world_pos = wp.xyz;
    v_world_norm = normalize(mat3(u_model) * in_norm);
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

_HILT_FRAG = """
#version 330
uniform vec3 u_base_color;
uniform float u_metallic;
uniform float u_roughness;
uniform vec3 u_blade_light_pos;
uniform vec3 u_blade_light_color;
uniform float u_blade_light_power;
in vec3 v_world_pos;
in vec3 v_world_norm;
out vec4 frag_bgra;

vec3 fresnel_schlick(float cos_theta, vec3 f0) {
    return f0 + (1.0 - f0) * pow(clamp(1.0 - cos_theta, 0.0, 1.0), 5.0);
}

void main() {
    vec3 N = normalize(v_world_norm);
    vec3 V = normalize(-v_world_pos);  // camera is at origin in view/world space
    vec3 base = u_base_color;
    vec3 f0 = mix(vec3(0.04), base, u_metallic);
    float shininess = mix(180.0, 14.0, clamp(u_roughness, 0.05, 1.0));

    // Key light (studio upper-left-front)
    vec3 L1 = normalize(vec3(0.45, 0.72, 0.65));
    vec3 H1 = normalize(L1 + V);
    float ndl1 = max(dot(N, L1), 0.0);
    float spec1 = pow(max(dot(N, H1), 0.0), shininess) * mix(1.4, 0.15, u_roughness);
    vec3 F1 = fresnel_schlick(max(dot(H1, V), 0.0), f0);

    // Cool rim light (back-right)
    vec3 L2 = normalize(vec3(-0.75, 0.28, -0.35));
    vec3 H2 = normalize(L2 + V);
    float ndl2 = max(dot(N, L2), 0.0);
    float spec2 = pow(max(dot(N, H2), 0.0), shininess * 0.7) * mix(1.0, 0.1, u_roughness);

    // Ignited blade point light illuminating emitter & metallic body
    vec3 to_blade = u_blade_light_pos - v_world_pos;
    float dist = max(length(to_blade), 0.04);
    vec3 Lb = to_blade / dist;
    vec3 Hb = normalize(Lb + V);
    float atten = u_blade_light_power / (0.03 + 2.2 * dist * dist);
    float ndlb = max(dot(N, Lb), 0.0);
    float specb = pow(max(dot(N, Hb), 0.0), shininess * 0.6) * mix(1.2, 0.2, u_roughness);

    // Hemisphere reflection approximation so metals look rich rather than black
    vec3 R = reflect(-V, N);
    float hemi = 0.5 + 0.5 * R.y;
    vec3 env = mix(vec3(0.10, 0.11, 0.13), vec3(0.72, 0.78, 0.88), pow(hemi, 1.6));
    env += vec3(0.25, 0.28, 0.34) * smoothstep(0.65, 0.95, abs(R.x));
    vec3 Fv = fresnel_schlick(max(dot(N, V), 0.0), f0);

    vec3 diff = base * (1.0 - u_metallic);
    vec3 color = vec3(0.0);
    color += (diff * 0.95 + F1 * spec1) * ndl1 * vec3(1.15, 1.12, 1.06);
    color += (diff * 0.35 + f0 * spec2) * ndl2 * vec3(0.45, 0.58, 0.78);
    color += (diff * 0.8 + f0 * specb) * ndlb * atten * u_blade_light_color;
    color += diff * mix(vec3(0.18), vec3(0.32), 0.5 + 0.5 * N.y);
    color += env * Fv * mix(0.85, 0.18, u_roughness);

    // Tone map + linear->sRGB gamma; output BGRA directly for OpenCV frame
    color = color / (color + vec3(0.85));
    color = pow(clamp(color, 0.0, 1.0), vec3(1.0 / 2.2));
    frag_bgra = vec4(color.b, color.g, color.r, 1.0);
}
"""

_BLADE_VERT = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

_BLADE_FRAG = """
#version 330
uniform vec4 u_bgr_a;
out vec4 frag_bgra;
void main() {
    frag_bgra = u_bgr_a;
}
"""


_TRAIL_VERT = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in float in_fade;
out float v_fade;
void main() {
    v_fade = in_fade;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

_TRAIL_FRAG = """
#version 330
uniform vec4 u_bgr_a;
in float v_fade;
out vec4 frag_bgra;
void main() {
    frag_bgra = vec4(u_bgr_a.rgb, u_bgr_a.a * v_fade);
}
"""


PISTOL_TOTAL_LEN = 0.208
PISTOL_MUZZLE_LOCAL = np.array([0.0, 0.047, 0.164, 1.0], dtype=np.float32)
PISTOL_SLIDE_TRAVEL = 0.028


class Hilt3DRenderer:
    """Headless moderngl renderer for 3D hilt/blade/trails and tactical pistol."""

    def __init__(
        self,
        glb_path: Path,
        width: int = 1280,
        height: int = 720,
        fov_y_deg: float = 52.0,
        pistol_glb_path: Path | None = None,
        load_pistol: bool = False,
    ):
        self.width = width
        self.height = height
        self.fov_y_deg = fov_y_deg
        self.proj = _perspective(fov_y_deg, width / height, 0.04, 20.0)
        self.ctx = moderngl.create_standalone_context()
        self.ctx.enable(moderngl.DEPTH_TEST)

        self.hilt_prog = self.ctx.program(vertex_shader=_HILT_VERT, fragment_shader=_HILT_FRAG)
        self.blade_prog = self.ctx.program(vertex_shader=_BLADE_VERT, fragment_shader=_BLADE_FRAG)
        self.trail_prog = self.ctx.program(vertex_shader=_TRAIL_VERT, fragment_shader=_TRAIL_FRAG)

        self.submeshes: list[_SubMesh] = self._build_submeshes(glb_path)
        self.pistol_submeshes: list[_SubMesh] = []
        if load_pistol:
            cand_pistol = pistol_glb_path if pistol_glb_path is not None else (glb_path.parent / "pistol.glb")
            if cand_pistol.exists():
                self.pistol_submeshes = self._build_submeshes(cand_pistol)

        b_verts, b_idxs = _build_capsule_blade_mesh(24)
        self.blade_vbo = self.ctx.buffer(b_verts.tobytes())
        self.blade_ibo = self.ctx.buffer(b_idxs.tobytes())
        self.blade_vao = self.ctx.vertex_array(
            self.blade_prog, [(self.blade_vbo, "3f", "in_pos")], index_buffer=self.blade_ibo
        )

        # Dynamic VBO for 3D motion-blur trail quads & 3D muzzle flash ribbons: (x, y, z, fade) * 6 verts
        self.trail_vbo = self.ctx.buffer(reserve=64 * 6 * 4 * 4)
        self.trail_vao = self.ctx.vertex_array(
            self.trail_prog, [(self.trail_vbo, "3f 1f", "in_pos", "in_fade")]
        )

        # Offscreen 4x MSAA FBOs sharing depth attachment for real blade/hilt occlusion
        samples = min(4, self.ctx.max_samples)
        self.depth_rb = self.ctx.depth_renderbuffer((width, height), samples=samples)
        self.hilt_rb = self.ctx.renderbuffer((width, height), 4, samples=samples)
        self.blade_rb = self.ctx.renderbuffer((width, height), 4, samples=samples)
        self.fbo_hilt = self.ctx.framebuffer(color_attachments=[self.hilt_rb], depth_attachment=self.depth_rb)
        self.fbo_blade = self.ctx.framebuffer(color_attachments=[self.blade_rb], depth_attachment=self.depth_rb)
        self.fbo_hilt_res = self.ctx.framebuffer(color_attachments=[self.ctx.texture((width, height), 4)])
        self.fbo_blade_res = self.ctx.framebuffer(color_attachments=[self.ctx.texture((width, height), 4)])

    def _build_submeshes(self, glb_path: Path) -> list[_SubMesh]:
        subs: list[_SubMesh] = []
        for pos, norm, idx, node_mat, base, metallic, roughness, name in _load_glb_meshes(glb_path):
            vbo_p = self.ctx.buffer(pos.tobytes())
            vbo_n = self.ctx.buffer(norm.tobytes())
            ibo = self.ctx.buffer(idx.tobytes())
            vao = self.ctx.vertex_array(
                self.hilt_prog,
                [(vbo_p, "3f", "in_pos"), (vbo_n, "3f", "in_norm")],
                index_buffer=ibo,
            )
            subs.append(_SubMesh(vao, node_mat, base, metallic, roughness, name=name))
        return subs

    def load_pistol(self, glb_path: Path) -> bool:
        """Load or hot-reload `models3d/pistol.glb` onto the existing GL context."""
        if not glb_path.exists():
            return False
        self.pistol_submeshes = self._build_submeshes(glb_path)
        return len(self.pistol_submeshes) > 0

    def grip_world_pos(self, px: float, py: float, hand_scale_px: float) -> tuple[np.ndarray, float]:
        """Unproject screen fist center + pixel hand scale into 3D camera-space position."""
        tan_half = math.tan(math.radians(self.fov_y_deg) / 2.0)
        target_hilt_px = max(2.15 * hand_scale_px, 40.0)
        d = (HILT_TOTAL_LEN * self.height) / (2.0 * tan_half * target_hilt_px)
        d = float(min(max(d, 0.28), 3.5))
        half_h = d * tan_half
        half_w = half_h * (self.width / self.height)
        wx = (px / self.width - 0.5) * 2.0 * half_w
        wy = (0.5 - py / self.height) * 2.0 * half_h
        return np.array([wx, wy, -d], dtype=np.float32), d

    def hilt_world_matrix(self, world_pos: np.ndarray, rot3: np.ndarray) -> np.ndarray:
        """Build 4x4 transform mapping hilt.glb local space -> camera world space."""
        t_grip = np.eye(4, dtype=np.float32)
        t_grip[1, 3] = -GRIP_LOCAL_Y
        r4 = np.eye(4, dtype=np.float32)
        r4[:3, :3] = rot3.astype(np.float32)
        t_world = np.eye(4, dtype=np.float32)
        t_world[:3, 3] = world_pos
        return t_world @ r4 @ t_grip

    def project_point(self, world_pt: np.ndarray) -> tuple[float, float] | None:
        """Project 3D camera-space point to pixel (x, y); returns None if degenerate."""
        z = min(float(world_pt[2]), -0.05)
        pt = np.array([world_pt[0], world_pt[1], z, 1.0], dtype=np.float32)
        clip = self.proj @ pt
        if abs(clip[3]) < 1e-5:
            return None
        ndc_x = clip[0] / clip[3]
        ndc_y = clip[1] / clip[3]
        return ((ndc_x * 0.5 + 0.5) * self.width, (0.5 - ndc_y * 0.5) * self.height)

    def pistol_world_pos(self, px: float, py: float, hand_scale_px: float) -> tuple[np.ndarray, float]:
        """Unproject grip-web screen anchor + pixel hand scale into 3D camera space."""
        tan_half = math.tan(math.radians(self.fov_y_deg) / 2.0)
        target_pistol_px = max(2.30 * hand_scale_px, 42.0)
        d = (PISTOL_TOTAL_LEN * self.height) / (2.0 * tan_half * target_pistol_px)
        d = float(min(max(d, 0.28), 3.5))
        half_h = d * tan_half
        half_w = half_h * (self.width / self.height)
        wx = (px / self.width - 0.5) * 2.0 * half_w
        wy = (0.5 - py / self.height) * 2.0 * half_h
        return np.array([wx, wy, -d], dtype=np.float32), d

    @staticmethod
    def pistol_world_matrix(world_pos: np.ndarray, rot3: np.ndarray) -> np.ndarray:
        """Build 4x4 transform mapping pistol.glb local grip origin -> camera world space."""
        r4 = np.eye(4, dtype=np.float32)
        r4[:3, :3] = rot3.astype(np.float32)
        t_world = np.eye(4, dtype=np.float32)
        t_world[:3, 3] = world_pos
        return t_world @ r4

    def render_saber(
        self,
        frame_bgr: np.ndarray,
        world_pos: np.ndarray,
        rot3: np.ndarray,
        ext: float,
        trail_world: list[tuple[np.ndarray, np.ndarray]],
        jitter_rad: float = 1.0,
        clash_flash: float = 0.0,
        clash_px: tuple[float, float] | None = None,
        hand_occ: tuple[int, int, int, int, np.ndarray] | None = None,
        color_key: str = "blue",
    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        """Render 3D hilt + occluded 3D blade onto `frame_bgr`. Returns (base_px, tip_px)."""
        pal = BLADE_COLORS.get(color_key, BLADE_COLORS["blue"])
        hilt_m = self.hilt_world_matrix(world_pos, rot3)
        e = 1.0 - (1.0 - ext) ** 2 if ext > 0.01 else 0.0
        blade_len = BLADE_MAX_LEN * e

        # Blade base & tip in 3D world space (clamp tip cleanly ahead of near plane)
        base_local = np.array([0.0, EMITTER_LOCAL_Y, 0.0, 1.0], dtype=np.float32)
        base_w = (hilt_m @ base_local)[:3]
        axis_w = rot3[:, 1].astype(np.float32)
        if e > 0.01 and axis_w[2] > 0.05 and base_w[2] < -0.11:
            max_before_lens = float((-0.11 - base_w[2]) / axis_w[2])
            blade_len = max(0.02, min(blade_len, max_before_lens))
        tip_w = base_w + axis_w * blade_len
        blade_mid = (base_w + tip_w) * 0.5 if e > 0.01 else base_w

        # Pass 1: 3D metallic hilt into fbo_hilt (sets depth buffer)
        self.fbo_hilt.use()
        self.ctx.viewport = (0, 0, self.width, self.height)
        self.ctx.depth_mask = True
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.fbo_hilt.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)

        self.hilt_prog["u_blade_light_pos"].value = tuple(float(v) for v in blade_mid)
        self.hilt_prog["u_blade_light_color"].value = pal["light_rgb"]
        self.hilt_prog["u_blade_light_power"].value = 1.35 * min(ext * 2.0, 1.0)

        for sm in self.submeshes:
            model = hilt_m @ sm.node_mat
            mvp = self.proj @ model
            self.hilt_prog["u_model"].write(model.T.astype(np.float32).tobytes())
            self.hilt_prog["u_mvp"].write(mvp.T.astype(np.float32).tobytes())
            self.hilt_prog["u_base_color"].value = sm.base_color
            self.hilt_prog["u_metallic"].value = sm.metallic
            self.hilt_prog["u_roughness"].value = sm.roughness
            sm.vao.render()

        # Pass 2: 3D blade core, additive outer glow shell, and trail ribbons
        self.fbo_blade.use()
        self.fbo_blade.clear(0.0, 0.0, 0.0, 0.0)  # preserve hilt depth!
        if e > 0.01:
            # 1) Inner white-hot blade core first (depth-tested against hilt; cull backfaces)
            self.ctx.enable(moderngl.CULL_FACE)
            self.ctx.disable(moderngl.BLEND)
            self.ctx.depth_mask = True
            core_r = 0.0092 * jitter_rad
            m_core = np.eye(4, dtype=np.float32)
            m_core[0, 0] = core_r
            m_core[1, 1] = blade_len
            m_core[2, 2] = core_r
            m_core[1, 3] = EMITTER_LOCAL_Y
            mvp_core = self.proj @ (hilt_m @ m_core)
            self.blade_prog["u_mvp"].write(mvp_core.T.astype(np.float32).tobytes())
            self.blade_prog["u_bgr_a"].value = (1.0, 1.0, 1.0, 1.0)
            self.blade_vao.render()

            # 2) Outer colored glow shell (front-face only additive over core + black, occluded by hilt)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.ONE, moderngl.ONE
            self.ctx.depth_mask = False
            outer_r = 0.0165 * jitter_rad
            m_outer = np.eye(4, dtype=np.float32)
            m_outer[0, 0] = outer_r
            m_outer[1, 1] = blade_len
            m_outer[2, 2] = outer_r
            m_outer[1, 3] = EMITTER_LOCAL_Y
            mvp_outer = self.proj @ (hilt_m @ m_outer)
            self.blade_prog["u_mvp"].write(mvp_outer.T.astype(np.float32).tobytes())
            gb, gg, gr = pal["glow_bgr"]
            self.blade_prog["u_bgr_a"].value = (gb, gg, gr, 1.0)
            self.blade_vao.render()
            self.ctx.disable(moderngl.CULL_FACE)

            # 3) Motion-blur trail ribbons (additive, feathered gradient)
            if len(trail_world) >= 2:
                self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
                self.trail_prog["u_mvp"].write(self.proj.T.astype(np.float32).tobytes())
                tb, tg, tr = pal["trail_bgr"]
                n_seg = len(trail_world) - 1
                for idx in range(n_seg):
                    b0, t0 = trail_world[idx]
                    b1, t1 = trail_world[idx + 1]
                    if float(np.linalg.norm(t1 - t0)) < 0.015:
                        continue
                    f0 = (idx / max(n_seg, 1)) ** 1.4
                    f1 = ((idx + 1) / max(n_seg, 1)) ** 1.4
                    verts = np.array([
                        [b0[0], b0[1], b0[2], f0 * 0.25],
                        [t0[0], t0[1], t0[2], f0],
                        [t1[0], t1[1], t1[2], f1],
                        [b0[0], b0[1], b0[2], f0 * 0.25],
                        [t1[0], t1[1], t1[2], f1],
                        [b1[0], b1[1], b1[2], f1 * 0.25],
                    ], dtype=np.float32)
                    self.trail_vbo.write(verts.tobytes())
                    self.trail_prog["u_bgr_a"].value = (tb, tg, tr, 0.34)
                    self.trail_vao.render(moderngl.TRIANGLES, vertices=6)
            self.ctx.disable(moderngl.BLEND)
            self.ctx.depth_mask = True

        # Resolve MSAA and composite tight hilt bounding-box ROI onto frame_bgr
        self.ctx.copy_framebuffer(self.fbo_hilt_res, self.fbo_hilt)
        hilt_buf = np.frombuffer(self.fbo_hilt_res.read(components=4), dtype=np.uint8)
        hilt_img = hilt_buf.reshape(self.height, self.width, 4)[::-1].copy()
        if hand_occ is not None:
            hx0, hy0, hx1, hy1, h_alpha = hand_occ
            # Hand always sits in front of the gripped hilt (lightsaber held inside/under hand)
            hilt_img[hy0:hy1, hx0:hx1, 3] = np.clip(
                hilt_img[hy0:hy1, hx0:hx1, 3].astype(np.float32) * (1.0 - h_alpha[..., 0]),
                0,
                255,
            ).astype(np.uint8)
        ys, xs = np.where(hilt_img[:, :, 3] > 0)
        if len(xs) > 0:
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            roi_fg = hilt_img[y0:y1, x0:x1, :3].astype(np.float32)
            roi_a = hilt_img[y0:y1, x0:x1, 3:4].astype(np.float32) * (1.0 / 255.0)
            roi_bg = frame_bgr[y0:y1, x0:x1].astype(np.float32)
            frame_bgr[y0:y1, x0:x1] = np.clip(
                roi_fg * roi_a + roi_bg * (1.0 - roi_a), 0, 255
            ).astype(np.uint8)

        # Composite 3D blade + fast downsampled Gaussian bloom
        if e > 0.01:
            self.ctx.copy_framebuffer(self.fbo_blade_res, self.fbo_blade)
            blade_buf = np.frombuffer(self.fbo_blade_res.read(components=3), dtype=np.uint8)
            blade_bgr = blade_buf.reshape(self.height, self.width, 3)[::-1].copy()
            if hand_occ is not None:
                hx0, hy0, hx1, hy1, h_alpha = hand_occ
                # Keep blade occluded behind hand unless angled steeply forward toward camera
                front_blade = float(np.clip((float(axis_w[2]) - 0.38) / 0.25, 0.0, 1.0))
                occ = 1.0 - h_alpha * (1.0 - front_blade)
                blade_bgr[hy0:hy1, hx0:hx1] = np.clip(
                    blade_bgr[hy0:hy1, hx0:hx1].astype(np.float32) * occ,
                    0,
                    255,
                ).astype(np.uint8)
            small = cv2.resize(blade_bgr, (self.width // 4, self.height // 4), interpolation=cv2.INTER_LINEAR)
            if clash_flash > 0.0 and clash_px is not None:
                cx, cy = int(clash_px[0] / 4), int(clash_px[1] / 4)
                cv2.circle(small, (cx, cy), 22, (255, 230, 190), -1, cv2.LINE_AA)
            bloom_small = cv2.GaussianBlur(small, (0, 0), sigmaX=5.0)
            bloom = cv2.resize(bloom_small, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
            cv2.add(frame_bgr, bloom, dst=frame_bgr)
            cv2.add(frame_bgr, blade_bgr, dst=frame_bgr)

        if e > 0.01:
            return self.project_point(base_w), self.project_point(tip_w)
        return self.project_point(base_w), None

    def render_pistol(
        self,
        frame_bgr: np.ndarray,
        world_pos: np.ndarray,
        rot3: np.ndarray,
        recoil: float = 0.0,
        flash_alpha: float = 0.0,
        hand_occ: tuple[int, int, int, int, np.ndarray] | None = None,
    ) -> tuple[float, float] | None:
        """Render 3D tactical pistol with slide blowback, muzzle-flash lighting, and under-hand occlusion."""
        if not self.pistol_submeshes:
            return None

        recoil_c = float(min(max(recoil, 0.0), 1.0))
        flash_c = float(min(max(flash_alpha, 0.0), 1.0))
        pistol_m = self.pistol_world_matrix(world_pos, rot3)
        muzzle_w = (pistol_m @ PISTOL_MUZZLE_LOCAL)[:3]
        fwd_w = rot3[:, 2].astype(np.float32)
        right_w = rot3[:, 0].astype(np.float32)
        up_w = rot3[:, 1].astype(np.float32)
        flash_light_pos = muzzle_w + fwd_w * 0.025

        # Pass 1: 3D pistol mesh (matte polymer grip, satin titanium slide, stainless barrel)
        self.fbo_hilt.use()
        self.ctx.viewport = (0, 0, self.width, self.height)
        self.ctx.depth_mask = True
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.fbo_hilt.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)

        self.hilt_prog["u_blade_light_pos"].value = tuple(float(v) for v in flash_light_pos)
        self.hilt_prog["u_blade_light_color"].value = (1.0, 0.56, 0.16)
        self.hilt_prog["u_blade_light_power"].value = 2.6 * flash_c

        m_recoil = np.eye(4, dtype=np.float32)
        m_recoil[2, 3] = -PISTOL_SLIDE_TRAVEL * recoil_c

        for sm in self.pistol_submeshes:
            base_m = (pistol_m @ m_recoil) if sm.name.startswith("slide_") else pistol_m
            model = base_m @ sm.node_mat
            mvp = self.proj @ model
            self.hilt_prog["u_model"].write(model.T.astype(np.float32).tobytes())
            self.hilt_prog["u_mvp"].write(mvp.T.astype(np.float32).tobytes())
            self.hilt_prog["u_base_color"].value = sm.base_color
            self.hilt_prog["u_metallic"].value = sm.metallic
            self.hilt_prog["u_roughness"].value = sm.roughness
            sm.vao.render()

        # Pass 2: 3D crossed muzzle-flash burst + forward jet (preserves depth buffer!)
        self.fbo_blade.use()
        self.fbo_blade.clear(0.0, 0.0, 0.0, 0.0)
        if flash_c > 0.02 and muzzle_w[2] < -0.06:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
            self.ctx.depth_mask = False
            self.trail_prog["u_mvp"].write(self.proj.T.astype(np.float32).tobytes())

            jet_len = 0.080 + 0.095 * flash_c
            jet_rad = 0.015 + 0.022 * flash_c
            star_rad = 0.034 + 0.042 * flash_c
            m0 = muzzle_w
            m_mid = muzzle_w + fwd_w * (jet_len * 0.28)
            m_tip = muzzle_w + fwd_w * jet_len

            # Pointed supersonic flame petals along barrel axis (no flat quad ends)
            fin_axes = [
                right_w,
                up_w,
                (right_w + up_w) * 0.7071,
                (right_w - up_w) * 0.7071,
            ]
            for ax in fin_axes:
                p_l = m_mid - ax * jet_rad
                p_r = m_mid + ax * jet_rad
                verts = np.array([
                    [m0[0], m0[1], m0[2], flash_c],
                    [p_r[0], p_r[1], p_r[2], 0.55 * flash_c],
                    [m_tip[0], m_tip[1], m_tip[2], 0.0],
                    [m0[0], m0[1], m0[2], flash_c],
                    [m_tip[0], m_tip[1], m_tip[2], 0.0],
                    [p_l[0], p_l[1], p_l[2], 0.55 * flash_c],
                ], dtype=np.float32)
                self.trail_vbo.write(verts.tobytes())
                self.trail_prog["u_bgr_a"].value = (0.28, 0.62, 1.0, 0.90 * flash_c)
                self.trail_vao.render(moderngl.TRIANGLES, vertices=6)

            # Star crown spikes + incandescent white-gold muzzle core
            for radius, bgr in ((star_rad, (0.34, 0.68, 1.0)), (star_rad * 0.48, (0.96, 0.99, 1.0))):
                for ax, bx in ((right_w, up_w), ((right_w + up_w) * 0.7071, (up_w - right_w) * 0.7071)):
                    p0 = m_mid - ax * radius
                    p1 = m_mid + ax * radius
                    s_up = m0 + bx * (radius * 0.22)
                    s_dn = m0 - bx * (radius * 0.22)
                    verts = np.array([
                        [m0[0], m0[1], m0[2], flash_c],
                        [s_up[0], s_up[1], s_up[2], 0.6 * flash_c],
                        [p1[0], p1[1], p1[2], 0.0],
                        [m0[0], m0[1], m0[2], flash_c],
                        [s_dn[0], s_dn[1], s_dn[2], 0.6 * flash_c],
                        [p0[0], p0[1], p0[2], 0.0],
                    ], dtype=np.float32)
                    self.trail_vbo.write(verts.tobytes())
                    self.trail_prog["u_bgr_a"].value = (bgr[0], bgr[1], bgr[2], 0.92 * flash_c)
                    self.trail_vao.render(moderngl.TRIANGLES, vertices=6)

            self.ctx.disable(moderngl.BLEND)
            self.ctx.depth_mask = True

        # Resolve MSAA pistol ROI & composite under hand
        self.ctx.copy_framebuffer(self.fbo_hilt_res, self.fbo_hilt)
        pistol_buf = np.frombuffer(self.fbo_hilt_res.read(components=4), dtype=np.uint8)
        pistol_img = pistol_buf.reshape(self.height, self.width, 4)[::-1].copy()
        if hand_occ is not None:
            hx0, hy0, hx1, hy1, h_alpha = hand_occ
            front_pistol = float(np.clip((float(fwd_w[2]) - 0.35) / 0.30, 0.0, 1.0))
            occ_strength = 1.0 - 0.65 * front_pistol
            pistol_img[hy0:hy1, hx0:hx1, 3] = np.clip(
                pistol_img[hy0:hy1, hx0:hx1, 3].astype(np.float32) * (1.0 - h_alpha[..., 0] * occ_strength),
                0,
                255,
            ).astype(np.uint8)
        ys, xs = np.where(pistol_img[:, :, 3] > 0)
        if len(xs) > 0:
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            roi_fg = pistol_img[y0:y1, x0:x1, :3].astype(np.float32)
            roi_a = pistol_img[y0:y1, x0:x1, 3:4].astype(np.float32) * (1.0 / 255.0)
            roi_bg = frame_bgr[y0:y1, x0:x1].astype(np.float32)
            frame_bgr[y0:y1, x0:x1] = np.clip(
                roi_fg * roi_a + roi_bg * (1.0 - roi_a), 0, 255
            ).astype(np.uint8)

        if flash_c > 0.02 and muzzle_w[2] < -0.06:
            self.ctx.copy_framebuffer(self.fbo_blade_res, self.fbo_blade)
            flash_buf = np.frombuffer(self.fbo_blade_res.read(components=3), dtype=np.uint8)
            flash_bgr = flash_buf.reshape(self.height, self.width, 3)[::-1].copy()
            small = cv2.resize(flash_bgr, (self.width // 4, self.height // 4), interpolation=cv2.INTER_LINEAR)
            bloom_small = cv2.GaussianBlur(small, (0, 0), sigmaX=4.5)
            bloom = cv2.resize(bloom_small, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
            cv2.add(frame_bgr, bloom, dst=frame_bgr)
            cv2.add(frame_bgr, flash_bgr, dst=frame_bgr)

        return self.project_point(muzzle_w)

    def close(self) -> None:
        self.ctx.release()
