"""Settings for the Eternal2x pipeline."""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Eternal2xConfig:
    """Everything the pipeline needs, in one place.

    Defaults are tuned for hand-drawn animation, which is typically drawn on
    2s (each drawing held for two frames) with occasional 1s and 3s.
    """

    # --- duplicate detection ---------------------------------------------
    # A frame counts as a new drawing when its difference from the previous
    # frame exceeds this. It has to sit above codec noise but below the
    # smallest real change (a blink, a mouth flap), hence the small value and
    # the tile-based scorer, which is sensitive to localised change.
    duplicate_threshold: float = 0.004

    # Width the analysis runs at. Detection does not need full resolution and
    # this keeps long clips fast.
    analysis_width: int = 640

    # Force a hold pattern instead of detecting it. 0 means auto-detect.
    # 2 = "on 2s", 3 = "on 3s".
    force_base_hold: int = 0

    # --- output -----------------------------------------------------------
    # Interpolation quality. "fast" uses a coarser optical flow preset.
    quality: str = "better"          # "fast" | "better" | "best"

    # Blend weight for occluded regions, where forward and backward flow
    # disagree. Higher values favour a plain cross-dissolve, which is softer
    # but never tears.
    occlusion_softness: float = 0.5

    interpolate_enabled: bool = True
    upscale_enabled: bool = True
    upscale_factor: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Eternal2xConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# Kept so older saved settings and the previous CLI flags still load.
UpscaleConfig = Eternal2xConfig
