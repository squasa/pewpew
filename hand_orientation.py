"""Hand gesture classifiers, One-Euro filters, and 3D fist orientation with anti-flip guard."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _extended(lm, tip: int, pip: int) -> bool:
    return _d(lm[tip], lm[0]) > _d(lm[pip], lm[0]) * 1.10


def hand_scale(lm) -> float:
    return max(_d(lm[0], lm[9]), 1e-6)


def is_finger_gun(lm) -> bool:
    return (_extended(lm, 8, 6)
            and not _extended(lm, 12, 10)
            and not _extended(lm, 16, 14)
            and not _extended(lm, 20, 18))


def thumb_is_up(lm) -> bool:
    """Thumb cocked = thumb tip held well away from the index knuckle."""
    return _d(lm[4], lm[5]) > 0.52 * hand_scale(lm)


def aim_dir(lm) -> tuple[float, float]:
    """Pointing vector: index knuckle -> index fingertip."""
    return (lm[8][0] - lm[5][0], lm[8][1] - lm[5][1])


def is_fist(lm) -> bool:
    """All four fingers curled = gripping a saber hilt."""
    return (not _extended(lm, 8, 6) and not _extended(lm, 12, 10)
            and not _extended(lm, 16, 14) and not _extended(lm, 20, 18))


def is_finger_heart(lm) -> bool:
    """Thumb & index tips pinched/crossed into a mini heart while other 3 fingers curl."""
    sc = hand_scale(lm)
    pinch = _d(lm[4], lm[8]) < 0.40 * sc
    index_arched = _d(lm[8], lm[0]) > _d(lm[6], lm[0]) * 1.05
    thumb_raised = _d(lm[4], lm[9]) > 0.36 * sc
    curled_others = (
        not _extended(lm, 12, 10)
        and not _extended(lm, 16, 14)
        and not _extended(lm, 20, 18)
    )
    return pinch and index_arched and thumb_raised and curled_others


def is_open_palm(lm) -> bool:
    """All four fingers extended and facing camera enough to swat/block incoming throws."""
    return (_extended(lm, 8, 6) and _extended(lm, 12, 10)
            and _extended(lm, 16, 14) and _extended(lm, 20, 18)
            and palm_projected_area(lm) > 0.16)


def palm_center_radius(lm) -> tuple[float, float, float]:
    """Return normalized (cx, cy, block_radius) for an open-palm blocker."""
    pts = (0, 5, 9, 13, 17)
    cx = sum(float(lm[i][0]) for i in pts) / len(pts)
    cy = sum(float(lm[i][1]) for i in pts) / len(pts)
    r = max(0.08, min(0.24, hand_scale(lm) * 0.95))
    return cx, cy, r


def saber_dir(lm) -> tuple[float, float]:
    """2D grip axis in image space: pinky knuckle -> index knuckle."""
    return (lm[5][0] - lm[17][0], lm[5][1] - lm[17][1])


def foreshorten(world_lm) -> float:
    """Projected XY fraction of the grip axis in MediaPipe world landmarks."""
    if not world_lm:
        return 1.0
    dx = world_lm[5][0] - world_lm[17][0]
    dy = world_lm[5][1] - world_lm[17][1]
    dz = world_lm[5][2] - world_lm[17][2]
    full = math.sqrt(dx * dx + dy * dy + dz * dz)
    if full < 1e-6:
        return 1.0
    return float(min(max(math.sqrt(dx * dx + dy * dy) / full, 0.0), 1.0))


class OneEuro:
    """One-Euro filter: low jitter when still, low lag when moving fast."""

    def __init__(self, min_cutoff: float = 1.4, beta: float = 0.7, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x: float | None = None
        self._dx: float = 0.0
        self._t: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-3))

    def __call__(self, x: float, t: float) -> float:
        if self._x is None:
            self._x, self._t = x, t
            return x
        dt = max(t - self._t, 1e-3)
        self._t = t
        dx = (x - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx += a_d * (dx - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x += a * (x - self._x)
        return self._x

    def reset(self) -> None:
        self._x, self._dx, self._t = None, 0.0, None


class OneEuro2:
    def __init__(self, **kw):
        self.fx = OneEuro(**kw)
        self.fy = OneEuro(**kw)

    def __call__(self, x: float, y: float, t: float) -> tuple[float, float]:
        return (self.fx(x, t), self.fy(y, t))

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()


def _normalize(v: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-7:
        return fallback.copy()
    return v / n


def mp_world_to_gl(pt: tuple[float, float, float]) -> np.ndarray:
    """Convert MediaPipe world coords (+X right, +Y down, +Z away) to GL (+X right, +Y up, +Z toward cam)."""
    return np.array([pt[0], -pt[1], -pt[2]], dtype=np.float64)


def mat3_to_quat(r: np.ndarray) -> np.ndarray:
    """Convert 3x3 proper rotation matrix (columns = basis axes) to unit quaternion (w, x, y, z)."""
    m00, m01, m02 = r[0, 0], r[0, 1], r[0, 2]
    m10, m11, m12 = r[1, 0], r[1, 1], r[1, 2]
    m20, m21, m22 = r[2, 0], r[2, 1], r[2, 2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return _normalize(q, np.array([1.0, 0.0, 0.0, 0.0]))


def quat_to_mat3(q: np.ndarray) -> np.ndarray:
    """Convert unit quaternion (w, x, y, z) to 3x3 rotation matrix."""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


class OneEuroQuat:
    """Continuous hemisphere-aligned One-Euro filter for unit quaternions."""

    def __init__(self, min_cutoff: float = 2.2, beta: float = 1.8, d_cutoff: float = 1.5):
        self.filters = [OneEuro(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff) for _ in range(4)]
        self._last: np.ndarray | None = None

    def __call__(self, q: np.ndarray, t: float) -> np.ndarray:
        q = _normalize(q, np.array([1.0, 0.0, 0.0, 0.0]))
        if self._last is not None and float(np.dot(q, self._last)) < 0.0:
            q = -q
        out = np.array([self.filters[i](float(q[i]), t) for i in range(4)], dtype=np.float64)
        out = _normalize(out, q)
        self._last = out
        return out

    def reset(self) -> None:
        for f in self.filters:
            f.reset()
        self._last = None


def palm_projected_area(lm) -> float:
    """Normalized 2D area of palm triangle (0, 5, 17) relative to hand scale^2."""
    sc = hand_scale(lm)
    ax, ay = lm[5][0] - lm[0][0], lm[5][1] - lm[0][1]
    bx, by = lm[17][0] - lm[0][0], lm[17][1] - lm[0][1]
    return abs(ax * by - ay * bx) / (sc * sc)


@dataclass
class HandOrientationTracker:
    """Tracks 3D fist / pistol orientation with anti-flip continuity guard."""

    hand_sign: float | None = None
    prev_rot: np.ndarray | None = None
    _q_filter: OneEuroQuat | None = None
    _prev_pistol_rot: np.ndarray | None = None
    _pistol_q_filter: OneEuroQuat | None = None

    def __post_init__(self) -> None:
        if self._q_filter is None:
            self._q_filter = OneEuroQuat(min_cutoff=2.2, beta=1.8, d_cutoff=1.5)
        if self._pistol_q_filter is None:
            self._pistol_q_filter = OneEuroQuat(min_cutoff=2.6, beta=2.1, d_cutoff=1.5)

    def reset(self) -> None:
        self.hand_sign = None
        self.prev_rot = None
        self._q_filter.reset()
        self._prev_pistol_rot = None
        self._pistol_q_filter.reset()

    def update_pistol(
        self,
        lm,
        world_lm,
        now: float,
        handedness: str = "Right",
    ) -> np.ndarray:
        """Return smoothed 3x3 rotation matrix (columns = X_right, Y_up, Z_barrel) for pistol.glb."""
        if not world_lm:
            dx, dy = aim_dir(lm)
            z_axis = _normalize(np.array([dx, -dy, 0.25]), np.array([0.0, 0.0, 1.0]))
            v_up = np.array([float(lm[5][0] - lm[17][0]), float(lm[17][1] - lm[5][1]), 0.0])
            y_axis = _normalize(v_up - np.dot(v_up, z_axis) * z_axis, np.array([0.0, 1.0, 0.0]))
            x_axis = _normalize(np.cross(y_axis, z_axis), np.array([1.0, 0.0, 0.0]))
            y_axis = _normalize(np.cross(z_axis, x_axis), y_axis)
            rot = np.column_stack([x_axis, y_axis, z_axis])
            q = self._pistol_q_filter(mat3_to_quat(rot), now)
            self._prev_pistol_rot = quat_to_mat3(q)
            return self._prev_pistol_rot

        p5 = mp_world_to_gl(world_lm[5])
        p8 = mp_world_to_gl(world_lm[8])
        p17 = mp_world_to_gl(world_lm[17])

        # Barrel forward: index MCP (5) -> index fingertip (8)
        z_axis = _normalize(p8 - p5, np.array([0.0, 0.0, 1.0]))
        if self._prev_pistol_rot is not None:
            prev_z = self._prev_pistol_rot[:, 2]
            xy_dot = float(z_axis[0] * prev_z[0] + z_axis[1] * prev_z[1])
            if (float(np.dot(z_axis, prev_z)) < -0.15
                    and xy_dot >= -0.05
                    and abs(float(prev_z[2])) > 0.45):
                z_axis = _normalize(np.array([z_axis[0], z_axis[1], -z_axis[2]]), prev_z)

        # Grip vertical up-axis: pinky MCP (17) -> index MCP (5) stays stable during thumb trigger clicks
        y_fallback = self._prev_pistol_rot[:, 1] if self._prev_pistol_rot is not None else np.array([0.0, 1.0, 0.0])
        v_up = _normalize(p5 - p17, y_fallback)
        y_axis = _normalize(v_up - np.dot(v_up, z_axis) * z_axis, y_fallback)

        area = palm_projected_area(lm) if lm is not None else 1.0
        if self._prev_pistol_rot is not None:
            prev_y = self._prev_pistol_rot[:, 1]
            if float(np.dot(y_axis, prev_y)) < -0.25 and area < 0.16:
                y_axis = -y_axis
                if float(np.dot(y_axis, prev_y)) < 0.15:
                    proj_prev = prev_y - np.dot(prev_y, z_axis) * z_axis
                    if float(np.linalg.norm(proj_prev)) > 1e-4:
                        y_axis = _normalize(proj_prev, y_axis)

        x_axis = _normalize(np.cross(y_axis, z_axis), np.array([1.0, 0.0, 0.0]))
        y_axis = _normalize(np.cross(z_axis, x_axis), y_axis)

        rot = np.column_stack([x_axis, y_axis, z_axis])
        q = self._pistol_q_filter(mat3_to_quat(rot), now)
        self._prev_pistol_rot = quat_to_mat3(q)
        return self._prev_pistol_rot

    def update(
        self,
        lm,
        world_lm,
        now: float,
        handedness: str = "Right",
    ) -> np.ndarray:
        """Return smoothed 3x3 rotation matrix (columns = X_knuckle, Y_blade, Z_palm) in GL space."""
        if not world_lm:
            # Fallback from 2D image landmarks if world landmarks are unavailable
            dx, dy = saber_dir(lm)
            y_axis = _normalize(np.array([dx, -dy, 0.0]), np.array([0.0, 1.0, 0.0]))
            z_axis = np.array([0.0, 0.0, 1.0])
            x_axis = _normalize(np.cross(y_axis, z_axis), np.array([1.0, 0.0, 0.0]))
            z_axis = np.cross(x_axis, y_axis)
            r = np.column_stack([x_axis, y_axis, z_axis])
            q = self._q_filter(mat3_to_quat(r), now)
            self.prev_rot = quat_to_mat3(q)
            return self.prev_rot

        p0 = mp_world_to_gl(world_lm[0])
        p5 = mp_world_to_gl(world_lm[5])
        p17 = mp_world_to_gl(world_lm[17])

        if self.hand_sign is None:
            self.hand_sign = 1.0 if handedness.lower().startswith("r") else -1.0

        # Primary blade axis: pinky MCP (17) -> index MCP (5), matching fist grip.
        y_axis = _normalize(p5 - p17, np.array([0.0, 1.0, 0.0]))

        # Guard against single-frame MediaPipe Z-axis mirror ambiguity when pointing near camera.
        if self.prev_rot is not None:
            prev_y = self.prev_rot[:, 1]
            # If 2D direction barely changed but Z suddenly flipped > 90 deg in one step,
            # clamp out the impossible instantaneous depth flip.
            xy_dot = float(y_axis[0] * prev_y[0] + y_axis[1] * prev_y[1])
            if (float(np.dot(y_axis, prev_y)) < -0.15
                    and xy_dot >= -0.05
                    and abs(float(prev_y[2])) > 0.45):
                y_axis = _normalize(np.array([y_axis[0], y_axis[1], -y_axis[2]]), prev_y)

        # Palm normal: perpendicular to (p5 - p0) and (p17 - p0), hence perpendicular to y_axis.
        palm_raw = np.cross(p5 - p0, p17 - p0)
        z_fallback = self.prev_rot[:, 2] if self.prev_rot is not None else np.array([0.0, 0.0, 1.0])
        z_axis = _normalize(palm_raw * self.hand_sign, z_fallback)
        # Re-orthogonalize z_axis strictly against y_axis in case of degenerate cross product.
        z_axis = _normalize(z_axis - np.dot(z_axis, y_axis) * y_axis, z_fallback)

        # Anti-flip roll guard: when palm is edge-on in 2D image, depth noise can mirror the normal 180 deg.
        area = palm_projected_area(lm) if lm is not None else 1.0
        if self.prev_rot is not None:
            prev_z = self.prev_rot[:, 2]
            if float(np.dot(z_axis, prev_z)) < -0.25 and area < 0.16:
                z_axis = -z_axis
                # If flipping still leaves near-orthogonal ambiguity, blend toward projected prev_z.
                if float(np.dot(z_axis, prev_z)) < 0.15:
                    proj_prev = prev_z - np.dot(prev_z, y_axis) * y_axis
                    if float(np.linalg.norm(proj_prev)) > 1e-4:
                        z_axis = _normalize(proj_prev, z_axis)

        x_axis = _normalize(np.cross(y_axis, z_axis), np.array([1.0, 0.0, 0.0]))
        z_axis = _normalize(np.cross(x_axis, y_axis), z_axis)

        rot = np.column_stack([x_axis, y_axis, z_axis])
        q = self._q_filter(mat3_to_quat(rot), now)
        self.prev_rot = quat_to_mat3(q)
        return self.prev_rot
