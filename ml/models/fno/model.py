"""Fourier Neural Operator (Li et al., ICLR 2021) for 2-D fire-spread operators.

Why an operator: the forecast maps *functions* on the landscape (fuel, terrain,
weather, current fire state) to a *function* (future burned state). An FNO
parameterises the integral kernel of that map in Fourier space, so each layer
mixes information globally (a fire front 3 km away can influence a cell in one
layer) and the learned weights are tied to physical frequencies rather than to
a pixel lattice, giving (approximate) discretization invariance across the
30/60/120 m horizon bands.

Layer:  v_{l+1}(x) = sigma( W v_l(x) + F^{-1}[ R_phi . F[v_l] ](x) )
  F           2-D real FFT
  R_phi       learnable complex weights on the lowest `modes` frequencies
              (positive and negative k_y), higher modes truncated
  W           pointwise (1x1) linear map — carries non-periodic/local info
Boundary: the domain is zero-padded by `padding` cells before the FFT and
cropped afterwards, because fire fields are not periodic.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class SpectralConv2d(nn.Module):
    def __init__(self, cin: int, cout: int, modes1: int, modes2: int):
        super().__init__()
        self.cin, self.cout, self.m1, self.m2 = cin, cout, modes1, modes2
        scale = 1.0 / (cin * cout)
        self.w1 = nn.Parameter(scale * torch.randn(cin, cout, modes1, modes2, dtype=torch.cfloat))
        self.w2 = nn.Parameter(scale * torch.randn(cin, cout, modes1, modes2, dtype=torch.cfloat))

    @staticmethod
    def _mul(a: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        return torch.einsum("bixy,ioxy->boxy", a, w)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, _, h, w = x.shape
        xf = torch.fft.rfft2(x.float(), norm="ortho")
        m1, m2 = min(self.m1, h // 2), min(self.m2, w // 2 + 1)
        out = torch.zeros(b, self.cout, h, w // 2 + 1, dtype=torch.cfloat, device=x.device)
        out[:, :, :m1, :m2] = self._mul(xf[:, :, :m1, :m2], self.w1[:, :, :m1, :m2])
        out[:, :, -m1:, :m2] = self._mul(xf[:, :, -m1:, :m2], self.w2[:, :, :m1, :m2])
        return torch.fft.irfft2(out, s=(h, w), norm="ortho")


class FNOBlock(nn.Module):
    def __init__(self, width: int, modes: int):
        super().__init__()
        self.spectral = SpectralConv2d(width, width, modes, modes)
        self.pointwise = nn.Conv2d(width, width, 1)
        self.norm = nn.GroupNorm(1, width)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.gelu(self.norm(self.spectral(x) + self.pointwise(x)))


class FNO2d(nn.Module):
    def __init__(self, in_channels: int, out_channels: int = 1, width: int = 48, modes: int = 20,
                 layers: int = 4, padding: int = 16, add_grid: bool = True):
        super().__init__()
        self.padding = padding
        self.add_grid = add_grid
        cin = in_channels + (2 if add_grid else 0)
        self.lift = nn.Sequential(nn.Conv2d(cin, width * 2, 1), nn.GELU(), nn.Conv2d(width * 2, width, 1))
        self.blocks = nn.ModuleList(FNOBlock(width, modes) for _ in range(layers))
        self.project = nn.Sequential(nn.Conv2d(width, width * 2, 1), nn.GELU(), nn.Conv2d(width * 2, out_channels, 1))

    @staticmethod
    def grid(x: torch.Tensor) -> torch.Tensor:
        b, _, h, w = x.shape
        gy = torch.linspace(0, 1, h, device=x.device).view(1, 1, h, 1).expand(b, 1, h, w)
        gx = torch.linspace(0, 1, w, device=x.device).view(1, 1, 1, w).expand(b, 1, h, w)
        return torch.cat([gx, gy], dim=1)

    def features(self, x: torch.Tensor) -> torch.Tensor:
        if self.add_grid:
            x = torch.cat([x, self.grid(x)], dim=1)
        x = self.lift(x)
        p = self.padding
        if p:
            x = F.pad(x, (0, p, 0, p))
        for blk in self.blocks:
            x = blk(x)
        if p:
            x = x[..., :-p, :-p]
        return x

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.project(self.features(x))
