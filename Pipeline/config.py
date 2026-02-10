from dataclasses import dataclass

@dataclass
class UpscaleConfig:
    upscale_enabled: bool = False
    interprolate_enabled: bool = False

    upscale_factor: int = 2
    interprolate_factor: int = 2

    #Motion detection (preview stage)
    motion_mode: str = "detail" # "detail" or "global"
    sensitivity: float = 0.20 # lower = more sensitive
    tile_grid: int = 8 # 8 = 8x8 tiles
    min_segment_frames: int = 4 # ignore tiny bursts
    merge_gap_frames: int = 2 # merge close segments
    sample_every_n: int = 1 # analyze every Nth frame