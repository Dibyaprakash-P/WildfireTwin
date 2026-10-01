"""U-Net baseline (Ronneberger et al., 2015) for burned-mask prediction."""

from __future__ import annotations

import torch
from torch import nn


def _block(cin: int, cout: int, groups: int = 8) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.GroupNorm(min(groups, cout), cout), nn.GELU(),
        nn.Conv2d(cout, cout, 3, padding=1, bias=False), nn.GroupNorm(min(groups, cout), cout), nn.GELU(),
    )


class UNet(nn.Module):
    def __init__(self, in_channels: int, out_channels: int = 1, base: int = 32, depth: int = 4):
        super().__init__()
        chs = [base * 2 ** i for i in range(depth + 1)]
        self.downs = nn.ModuleList()
        c = in_channels
        for ch in chs[:-1]:
            self.downs.append(_block(c, ch))
            c = ch
        self.bottleneck = _block(chs[-2], chs[-1])
        self.ups = nn.ModuleList()
        self.up_convs = nn.ModuleList()
        for ch in reversed(chs[:-1]):
            self.ups.append(nn.ConvTranspose2d(ch * 2, ch, 2, stride=2))
            self.up_convs.append(_block(ch * 2, ch))
        self.head = nn.Conv2d(chs[0], out_channels, 1)
        self.pool = nn.MaxPool2d(2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips = []
        for d in self.downs:
            x = d(x)
            skips.append(x)
            x = self.pool(x)
        x = self.bottleneck(x)
        for up, conv, s in zip(self.ups, self.up_convs, reversed(skips)):
            x = up(x)
            x = conv(torch.cat([x, s], dim=1))
        return self.head(x)
