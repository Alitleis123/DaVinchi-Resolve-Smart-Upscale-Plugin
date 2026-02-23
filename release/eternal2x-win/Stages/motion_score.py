# Stages/motion_score.py
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Union

import numpy as np
import cv2

from Pipeline.config import UpscaleConfig


def _parse_tile_grid(tile_grid: Union[int, tuple, list, str]) -> Tuple[int, int]:
    # Accept 8, (8,8), "8x8", "8,8"
    if isinstance(tile_grid, int):
        return max(1, tile_grid), max(1, tile_grid)
    if isinstance(tile_grid, (tuple, list)) and len(tile_grid) == 2:
        return max(1, int(tile_grid[0])), max(1, int(tile_grid[1]))
    if isinstance(tile_grid, str):
        s = tile_grid.lower().replace(" ", "")
        if "x" in s:
            a, b = s.split("x", 1)
            return max(1, int(a)), max(1, int(b))
        if "," in s:
            a, b = s.split(",", 1)
            return max(1, int(a)), max(1, int(b))
        v = int(s)
        return max(1, v), max(1, v)
    return 8, 8


def _preprocess(frame_bgr: np.ndarray, max_width: int = 640) -> np.ndarray:
    """Grayscale + optional downscale for speed."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    if max_width and gray.shape[1] > max_width:
        h, w = gray.shape[:2]
        scale = max_width / float(w)
        gray = cv2.resize(gray, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    return gray


def score_global(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Whole-frame motion score in [0, ~1]."""
    diff = cv2.absdiff(prev_gray, curr_gray)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)
    return float(diff.mean()) / 255.0


def score_detail(prev_gray: np.ndarray, curr_gray: np.ndarray, tile_grid) -> float:
    """
    Tile-based score: compute mean diff per tile, then average of the top 15% tiles.
    Good for small localized motion (hair/blinks).
    """
    diff = cv2.absdiff(prev_gray, curr_gray)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)

    gx, gy = _parse_tile_grid(tile_grid)
    h, w = diff.shape[:2]
    tw, th = max(1, w // gx), max(1, h // gy)

    vals = []
    for ty in range(gy):
        y0 = ty * th
        y1 = (ty + 1) * th if ty < gy - 1 else h
        for tx in range(gx):
            x0 = tx * tw
            x1 = (tx + 1) * tw if tx < gx - 1 else w
            tile = diff[y0:y1, x0:x1]
            vals.append(float(tile.mean()) / 255.0)

    v = np.array(vals, dtype=np.float32)
    k = max(1, int(np.ceil(len(v) * 0.15)))   # top 15%
    topk = np.partition(v, -k)[-k:]
    return float(topk.mean())


def compute_motion_scores(
    video_path: Path,
    cfg: UpscaleConfig,
    *,
    max_width: int = 640
) -> Tuple[List[float], float]:
    """
    Returns (scores_per_frame, fps).

    Uses cfg.sample_every_n:
      - only *scores* every Nth frame (faster)
      - repeats that score for the skipped frames
      - divides by N so scores stay closer to per-frame scale
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 30.0  # fallback

    n = max(1, int(getattr(cfg, "sample_every_n", 1)))
    mode = str(getattr(cfg, "motion_mode", "detail")).lower()
    tile_grid = getattr(cfg, "tile_grid", (8, 8))

    ret, first = cap.read()
    if not ret:
        raise RuntimeError(f"Could not read first frame: {video_path}")

    prev = _preprocess(first, max_width=max_width)
    scores: List[float] = [0.0]  # frame 0 has no previous frame

    while True:
        grabbed = 0

        # Grab n frames quickly, decode only the last one
        for _ in range(n):
            ok = cap.grab()
            if not ok:
                break
            grabbed += 1

        if grabbed == 0:
            break

        ret2, frame = cap.retrieve()
        if not ret2:
            break

        curr = _preprocess(frame, max_width=max_width)

        raw = score_global(prev, curr) if mode == "global" else score_detail(prev, curr, tile_grid)
        score = raw / grabbed
        scores.extend([score] * grabbed)

        prev = curr

    cap.release()
    return scores, fps
