"""Model construction from config + checkpoint loading."""

from __future__ import annotations

from pathlib import Path

import torch
from torch import nn

from ml.features import N_CHANNELS
from ml.models.fno.model import FNO2d
from ml.models.physics_fno.model import PhysicsInformedFNO
from ml.models.unet.model import UNet

MODEL_TYPES = ("unet", "fno", "physics_fno")
DISPLAY_NAMES = {"unet": "U-Net", "fno": "FNO", "physics_fno": "Physics-Informed FNO"}


def build_model(cfg: dict) -> nn.Module:
    m = cfg["model"]
    t = m["type"]
    if t == "unet":
        return UNet(N_CHANNELS, 1, base=m.get("base", 32), depth=m.get("depth", 4))
    if t == "fno":
        return FNO2d(N_CHANNELS, 1, width=m["width"], modes=m["modes"], layers=m["layers"], padding=m.get("padding", 16))
    if t == "physics_fno":
        return PhysicsInformedFNO(N_CHANNELS, width=m["width"], modes=m["modes"], layers=m["layers"],
                                  padding=m.get("padding", 16), sharpness=m.get("sharpness", 0.1))
    raise ValueError(f"unknown model type {t}")


def select_device(prefer: str = "auto") -> torch.device:
    if prefer == "cpu":
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_checkpoint(path: Path, device: torch.device | None = None) -> tuple[nn.Module, dict]:
    device = device or select_device()
    ck = torch.load(path, map_location=device, weights_only=False)
    model = build_model(ck["config"])
    model.load_state_dict(ck["state_dict"])
    model.to(device).eval()
    return model, ck
