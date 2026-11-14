"""Fast real-time anatomical + color-refined hand occlusion matte for 3D weapon compositing."""
from __future__ import annotations

import math

import cv2
import numpy as np

_PALM_IDX = (0, 1, 2, 5, 9, 13, 17)
_BONES = (
    (0, 5), (0, 9), (0, 13), (0, 17),
    (1, 2), (2, 3), (3, 4),
    (5, 6), (6, 7), (7, 8),
    (9, 10), (10, 11), (11, 12),
    (13, 14), (14, 15), (15, 16),
    (17, 18), (18, 19), (19, 20),
)
_K3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
_K5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
_K9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


def extract_hand_occlusion(
    frame_bgr: np.ndarray,
    lm: list[tuple[float, float]] | None,
) -> tuple[int, int, int, int, np.ndarray] | None:
    """Return `(x0, y0, x1, y1, alpha_roi)` in `[0..1]` (`float32`, HxWx1) for the tracked hand."""
    if lm is None or len(lm) < 21:
        return None
    h, w = frame_bgr.shape[:2]
    pts = np.array([(p[0] * w, p[1] * h) for p in lm], dtype=np.float32)
    hs_px = max(
        math.hypot(float(pts[9, 0] - pts[0, 0]), float(pts[9, 1] - pts[0, 1])),
        math.hypot(float(pts[5, 0] - pts[17, 0]), float(pts[5, 1] - pts[17, 1])) * 1.15,
        24.0,
    )
    pad = max(24, int(round(0.32 * hs_px)))
    x0 = max(0, int(math.floor(float(pts[:, 0].min()))) - pad)
    y0 = max(0, int(math.floor(float(pts[:, 1].min()))) - pad)
    x1 = min(w, int(math.ceil(float(pts[:, 0].max()))) + pad)
    y1 = min(h, int(math.ceil(float(pts[:, 1].max()))) + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None

    rw, rh = x1 - x0, y1 - y0
    lpts = np.round(pts - np.array([x0, y0], dtype=np.float32)).astype(np.int32)
    palm = lpts[list(_PALM_IDX)]

    core = np.zeros((rh, rw), dtype=np.uint8)
    med = np.zeros((rh, rw), dtype=np.uint8)
    loose = np.zeros((rh, rw), dtype=np.uint8)

    t_core = max(3, int(round(0.11 * hs_px)))
    t_med = max(5, int(round(0.22 * hs_px)))
    t_loose = max(9, int(round(0.36 * hs_px)))

    cv2.fillPoly(core, [palm], 255)
    cv2.fillPoly(med, [palm], 255)
    cv2.fillPoly(loose, [palm], 255)
    # Include curled-knuckle span in loose envelope (gated by skin color check so open gaps stay clear)
    knuckle_shield = lpts[[5, 6, 10, 14, 18, 17]]
    cv2.fillPoly(loose, [knuckle_shield], 255)
    for a, b in _BONES:
        pa, pb = tuple(int(v) for v in lpts[a]), tuple(int(v) for v in lpts[b])
        cv2.line(core, pa, pb, 255, t_core, cv2.LINE_AA)
        cv2.line(med, pa, pb, 255, t_med, cv2.LINE_AA)
        cv2.line(loose, pa, pb, 255, t_loose, cv2.LINE_AA)

    roi_lab = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2Lab).astype(np.float32)
    feat = np.empty_like(roi_lab)
    feat[..., 0] = roi_lab[..., 0] * 0.45
    feat[..., 1:] = roi_lab[..., 1:]

    fg_pts = feat[core > 0]
    if len(fg_pts) < 16:
        mask_f = cv2.GaussianBlur(med.astype(np.float32) * (1.0 / 255.0), (5, 5), 1.0)
        return (x0, y0, x1, y1, mask_f[..., None])

    fg_mean = fg_pts.mean(axis=0)
    fg_std = np.maximum(fg_pts.std(axis=0), np.array([12.0, 5.5, 5.5], dtype=np.float32))
    d2_fg = np.sum(((feat - fg_mean) / fg_std) ** 2, axis=-1)

    bg_ring = (cv2.dilate(loose, _K9) > 0) & (loose == 0)
    bg_d2 = d2_fg[bg_ring]
    non_skin_bg = feat[bg_ring][bg_d2 > 4.0] if len(bg_d2) > 0 else np.empty((0, 3), dtype=np.float32)

    if len(non_skin_bg) >= 24:
        bg_mean = non_skin_bg.mean(axis=0)
        bg_std = np.maximum(non_skin_bg.std(axis=0), np.array([14.0, 6.5, 6.5], dtype=np.float32))
        d2_bg = np.sum(((feat - bg_mean) / bg_std) ** 2, axis=-1)
        skin_match = (d2_fg < 8.5) & (d2_fg <= d2_bg + 1.4)
    else:
        skin_match = d2_fg < 6.5

    fg = (core > 0) | ((med > 0) & (d2_fg < 11.5)) | ((loose > 0) & skin_match)
    fg_u8 = (fg.astype(np.uint8) * 255)
    fg_u8 = cv2.morphologyEx(fg_u8, cv2.MORPH_CLOSE, _K5)
    fg_u8 = cv2.morphologyEx(fg_u8, cv2.MORPH_OPEN, _K3)

    # Keep only connected component(s) overlapping the hand core so background patches stay excluded
    n_lbl, labels = cv2.connectedComponents(fg_u8, connectivity=8)
    if n_lbl > 2:
        core_lbls = np.unique(labels[core > 0])
        keep = np.isin(labels, core_lbls[core_lbls > 0])
        fg_u8 = np.where(keep, np.uint8(255), np.uint8(0))

    mask_f = cv2.GaussianBlur(fg_u8.astype(np.float32) * (1.0 / 255.0), (5, 5), 1.05)
    return (x0, y0, x1, y1, mask_f[..., None])
