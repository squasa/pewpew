"""MediaPipe FaceLandmarker plumbing (landmarks + blendshapes + head pose) for Stage 2B+ games."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FaceState:
    landmarks: list[tuple[float, float, float]]  # 478 normalized (x, y, z)
    blendshapes: dict[str, float]                # 52 ARKit-style blendshape scores
    matrix: np.ndarray | None                    # 4x4 facial transform matrix
    nose_px: tuple[float, float]                 # landmark 1 (nose tip) in px
    mouth_px: tuple[float, float]                # midpoint of upper/lower inner lip (13, 14) in px
    face_scale_px: float                         # inter-temple / eye span proxy in px

    @property
    def jaw_open(self) -> float:
        return self.blendshapes.get("jawOpen", 0.0)


class FaceTracker:
    """Lazy-running FaceLandmarker wrapper controlled by the Face Tracking toggle."""

    def __init__(self, model_path: Path):
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions

        self._mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.45,
            min_face_presence_confidence=0.45,
            min_tracking_confidence=0.45,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(opts)
        self.last_state: FaceState | None = None

    def detect(self, rgb_frame: np.ndarray, ts_ms: int, width: int, height: int) -> FaceState | None:
        mp_img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        res = self._landmarker.detect_for_video(mp_img, ts_ms)
        if not res.face_landmarks:
            self.last_state = None
            return None

        raw_lms = res.face_landmarks[0]
        lms = [(float(p.x), float(p.y), float(p.z)) for p in raw_lms]
        bs: dict[str, float] = {}
        if res.face_blendshapes:
            for cat in res.face_blendshapes[0]:
                bs[cat.category_name] = float(cat.score)

        mat = None
        if res.facial_transformation_matrixes:
            mat = np.array(res.facial_transformation_matrixes[0], dtype=np.float32)

        nose_px = (lms[1][0] * width, lms[1][1] * height)
        mouth_px = (
            (lms[13][0] + lms[14][0]) * 0.5 * width,
            (lms[13][1] + lms[14][1]) * 0.5 * height,
        )
        # Cheekbone-to-cheekbone span (landmarks 234 and 454)
        dx = (lms[454][0] - lms[234][0]) * width
        dy = (lms[454][1] - lms[234][1]) * height
        face_scale_px = max(float(np.hypot(dx, dy)), 20.0)

        self.last_state = FaceState(
            landmarks=lms,
            blendshapes=bs,
            matrix=mat,
            nose_px=nose_px,
            mouth_px=mouth_px,
            face_scale_px=face_scale_px,
        )
        return self.last_state

    def draw_preview_debug(self, preview: np.ndarray, state: FaceState | None) -> None:
        """Preview-only subtle landmark & blendshape readout (never drawn to virtual cam)."""
        if state is None:
            return
        h, w = preview.shape[:2]
        # Draw key face contour + eye/mouth points cleanly
        for idx, (lx, ly, _) in enumerate(state.landmarks):
            if idx % 3 == 0 or idx in (1, 13, 14, 33, 263, 61, 291):
                cv2.circle(preview, (int(lx * w), int(ly * h)), 1, (180, 230, 140), -1)
        nx, ny = int(state.nose_px[0]), int(state.nose_px[1])
        mx, my = int(state.mouth_px[0]), int(state.mouth_px[1])
        cv2.circle(preview, (nx, ny), 5, (80, 220, 255), 1, cv2.LINE_AA)
        jaw = state.jaw_open
        cv2.circle(preview, (mx, my), max(4, int(5 + jaw * 18)), (110, 255, 160), 1, cv2.LINE_AA)
        cv2.putText(
            preview,
            f"face ok | jawOpen {jaw:.2f} | smile {state.blendshapes.get('mouthSmileLeft', 0):.2f}",
            (mx + 14, my + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (160, 245, 180),
            1,
            cv2.LINE_AA,
        )

    def close(self) -> None:
        self._landmarker.close()
