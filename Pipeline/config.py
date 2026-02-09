from dataclasses import dataclass

@dataclass
class UpscaleConfig:
    upscale_enabled: bool = False
    interprolate_enabled: bool = False

    upscale_factor: int = 2
    interprolate_factor: int = 2