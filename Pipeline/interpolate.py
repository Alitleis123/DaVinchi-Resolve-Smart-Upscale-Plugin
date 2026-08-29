"""Generate in-between frames from a pair of drawings using optical flow.

The approach is the classic one: estimate motion in both directions, pull each
drawing towards the in-between time, and blend. What matters for hand-drawn
animation is the failure mode. Where the two flows disagree -- occlusions, a
limb appearing from behind a body, a cut -- warping produces the tearing and
melting that optical-flow retimers are notorious for. Those regions are
detected and softened into a plain cross dissolve instead, which reads as
motion blur rather than as a glitch.

Two drawings that are identical produce zero flow and therefore an identical
in-between, so deliberate held frames stay perfectly still.
"""

from __future__ import annotations

from typing import List

import cv2
import numpy as np


_PRESETS = {
    "fast": cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST,
    "better": cv2.DISOPTICAL_FLOW_PRESET_MEDIUM,
    "best": cv2.DISOPTICAL_FLOW_PRESET_MEDIUM,
}

# Above this mean absolute difference, two drawings are treated as unrelated
# (a hard cut). Flow between them is meaningless, so we cut rather than blend.
CUT_THRESHOLD = 0.38


def _flow_engine(quality: str):
    preset = _PRESETS.get(str(quality).lower(), _PRESETS["better"])
    engine = cv2.DISOpticalFlow_create(preset)
    if str(quality).lower() == "best":
        # Finest scale 0 tracks small features -- eyes, fingers, line detail --
        # at the cost of speed.
        engine.setFinestScale(0)
        engine.setGradientDescentIterations(25)
        engine.setVariationalRefinementIterations(10)
    return engine


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _warp(image: np.ndarray, flow: np.ndarray) -> np.ndarray:
    """Resample `image` along `flow`."""
    h, w = flow.shape[:2]
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32),
                                 np.arange(h, dtype=np.float32))
    map_x = grid_x + flow[..., 0]
    map_y = grid_y + flow[..., 1]
    return cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def frames_are_a_cut(a: np.ndarray, b: np.ndarray) -> bool:
    """True when two drawings are too different to interpolate between."""
    ga, gb = _to_gray(a), _to_gray(b)
    if ga.shape != gb.shape:
        return True
    return float(cv2.absdiff(ga, gb).mean()) / 255.0 > CUT_THRESHOLD


def interpolate_pair(
    a: np.ndarray,
    b: np.ndarray,
    times: List[float],
    *,
    quality: str = "better",
    occlusion_softness: float = 0.5,
) -> List[np.ndarray]:
    """Produce in-between frames for `times` (each in 0..1) between a and b.

    t == 0 returns `a` untouched and t == 1 returns `b` untouched, so real
    drawings are never resampled and stay perfectly sharp.
    """
    if not times:
        return []

    # Identical drawings: nothing to interpolate, and computing flow would only
    # invent motion out of compression noise.
    if np.array_equal(a, b):
        return [a.copy() for _ in times]

    # A hard cut: blending across it would produce a ghosted double image.
    if frames_are_a_cut(a, b):
        return [(a.copy() if t < 0.5 else b.copy()) for t in times]

    engine = _flow_engine(quality)
    ga, gb = _to_gray(a), _to_gray(b)
    flow_ab = engine.calc(ga, gb, None)
    flow_ba = engine.calc(gb, ga, None)

    af = a.astype(np.float32)
    bf = b.astype(np.float32)

    out: List[np.ndarray] = []
    for t in times:
        t = float(min(1.0, max(0.0, t)))
        if t <= 0.0:
            out.append(a.copy())
            continue
        if t >= 1.0:
            out.append(b.copy())
            continue

        warped_a = _warp(af, flow_ba * t)
        warped_b = _warp(bf, flow_ab * (1.0 - t))
        warped = warped_a * (1.0 - t) + warped_b * t

        # Where the two warps disagree, the flow could not explain the change,
        # so trust it less and fade towards a straight dissolve.
        disagreement = np.abs(warped_a - warped_b).mean(axis=2) / 255.0
        confidence = np.clip(1.0 - disagreement * (1.0 + 3.0 * occlusion_softness), 0.0, 1.0)
        confidence = cv2.GaussianBlur(confidence, (0, 0), 3.0)[..., None]

        dissolve = af * (1.0 - t) + bf * t
        blended = warped * confidence + dissolve * (1.0 - confidence)
        out.append(np.clip(blended, 0, 255).astype(np.uint8))

    return out


def upscale(frame: np.ndarray, factor: int) -> np.ndarray:
    """Resize by an integer factor.

    Lanczos keeps hand-drawn line art crisp. This is the fallback used when
    Resolve's Super Scale is not available to do the job better.
    """
    if factor <= 1:
        return frame
    h, w = frame.shape[:2]
    return cv2.resize(frame, (w * factor, h * factor), interpolation=cv2.INTER_LANCZOS4)
