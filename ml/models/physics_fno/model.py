"""Physics-informed FNO: predicts a normalised fire ARRIVAL-TIME field.

Output tau(x) = (T(x) - t0) / h  where T is fire arrival time and h the horizon.
The burned-mask probability at t0 + h is derived from it:
        p(x) = sigmoid( (1 - tau(x)) / s )       (s = `sharpness`)
Predicting T (a continuous level-set-like field) rather than a mask is what
makes an eikonal physics residual available (see physics.py).
The backbone is identical to ml.models.fno.FNO2d for a fair comparison.
"""

from __future__ import annotations

import torch
from torch import nn

from ml.models.fno.model import FNO2d


class PhysicsInformedFNO(nn.Module):
    def __init__(self, in_channels: int, width: int = 48, modes: int = 20, layers: int = 4,
                 padding: int = 16, sharpness: float = 0.1):
        super().__init__()
        self.backbone = FNO2d(in_channels, 1, width, modes, layers, padding)
        self.sharpness = sharpness

    def forward_tau(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)

    def logits_from_tau(self, tau: torch.Tensor) -> torch.Tensor:
        return (1.0 - tau) / self.sharpness

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Returns mask logits (same interface as U-Net / FNO)."""
        return self.logits_from_tau(self.forward_tau(x))
