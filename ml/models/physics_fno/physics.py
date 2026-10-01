"""Physics loss terms for the PI-FNO.

L_total = L_data + lambda_eik * L_eik + lambda_mono * L_mono + lambda_nb * L_nb

L_eik  (anisotropic eikonal residual)
    Fire arrival time T satisfies  R(x, n) |grad T| = 1  where n = grad T / |grad T|
    is the local spread direction and R(x, n) is the Rothermel head-fire rate
    with Anderson's elliptical shape:
        R(x, psi) = R_head (1 - e) / (1 - e cos(psi - theta_max)).
    R_head, e, theta_max are computed per cell from fuel, slope, aspect and the
    horizon-mean wind (inputs only — never from the target). The residual is
    taken in log space, r = log(R |grad T|), because R spans orders of
    magnitude, and is evaluated only where the model itself predicts the cell
    burns inside the horizon (0 < tau < 1) on burnable cells.
    Approximation: weather is time-varying within the horizon, so the reference
    data do not satisfy the equation exactly; `reference_residual` reports the
    residual of the reference arrival field for transparency.

L_mono (irreversibility)
    Burned area cannot shrink: cells burning at t0 must have tau <= 0.

L_nb   (non-burnable fuel)
    Cells with non-burnable fuel (NB91-99) that are not burning at t0 cannot burn.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F

EPS = 1e-6


@dataclass
class PhysicsWeights:
    eik: float = 0.1
    mono: float = 1.0
    nb: float = 1.0
    gate_sharpness: float = 0.05


def _grad(T: torch.Tensor, cell_m: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Central differences. Returns (dT/dx east, dT/dy north) in time-units per metre (interior only)."""
    dx = (T[..., 1:-1, 2:] - T[..., 1:-1, :-2]) / (2.0 * cell_m)
    dy = -(T[..., 2:, 1:-1] - T[..., :-2, 1:-1]) / (2.0 * cell_m)   # rows increase southward
    return dx, dy


def eikonal_residual(tau: torch.Tensor, horizon_min: torch.Tensor, cell_m: torch.Tensor,
                     phys: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Returns (log-residual r, interior-valid mask of R>0) on the interior grid (H-2, W-2)."""
    hz = horizon_min.view(-1, 1, 1, 1)
    cm = cell_m.view(-1, 1, 1, 1)
    T = tau * hz                                            # minutes since t0
    gx, gy = _grad(T, cm)
    gnorm = torch.sqrt(gx ** 2 + gy ** 2 + 1e-12)           # min / m
    psi = torch.atan2(gx, gy)                                # azimuth of spread, clockwise from north
    r_head, ecc = phys[:, 0:1, 1:-1, 1:-1], phys[:, 1:2, 1:-1, 1:-1]
    sin_t, cos_t = phys[:, 2:3, 1:-1, 1:-1], phys[:, 3:4, 1:-1, 1:-1]
    cos_d = torch.cos(psi) * cos_t + torch.sin(psi) * sin_t  # cos(psi - theta_max)
    R = r_head * (1.0 - ecc) / (1.0 - ecc * cos_d).clamp_min(EPS)   # m / min
    valid = (R > 1e-4).float()
    r = torch.log((R * gnorm).clamp_min(EPS))
    return r, valid


def physics_losses(tau: torch.Tensor, x: torch.Tensor, phys: torch.Tensor, horizon_min: torch.Tensor,
                   cell_m: torch.Tensor, burnable_ch: int, fire_ch: int, w: PhysicsWeights) -> dict[str, torch.Tensor]:
    m0 = x[:, fire_ch:fire_ch + 1]
    burnable = x[:, burnable_ch:burnable_ch + 1]
    r, valid = eikonal_residual(tau, horizon_min, cell_m, phys)
    t_in = tau[..., 1:-1, 1:-1]
    gate = torch.sigmoid(t_in / w.gate_sharpness) * torch.sigmoid((1.0 - t_in) / w.gate_sharpness)
    wgt = gate * valid * burnable[..., 1:-1, 1:-1] * (1.0 - m0[..., 1:-1, 1:-1])
    l_eik = (wgt * F.smooth_l1_loss(r, torch.zeros_like(r), reduction="none", beta=0.5)).sum() / wgt.sum().clamp_min(1.0)
    l_mono = (m0 * F.relu(tau)).sum() / m0.sum().clamp_min(1.0)
    p = torch.sigmoid((1.0 - tau) / 0.1)
    nb = (1.0 - burnable) * (1.0 - m0)
    l_nb = (nb * p).sum() / nb.sum().clamp_min(1.0)
    total = w.eik * l_eik + w.mono * l_mono + w.nb * l_nb
    return {"physics": total, "eikonal": l_eik, "monotonic": l_mono, "nonburnable": l_nb}


@torch.no_grad()
def reference_residual(tau_true: torch.Tensor, x: torch.Tensor, phys: torch.Tensor, horizon_min: torch.Tensor,
                       cell_m: torch.Tensor, burnable_ch: int, fire_ch: int) -> float:
    """Mean |log residual| of the reference arrival field (diagnostic of the eikonal approximation)."""
    r, valid = eikonal_residual(tau_true, horizon_min, cell_m, phys)
    t_in = tau_true[..., 1:-1, 1:-1]
    m0 = x[:, fire_ch:fire_ch + 1, 1:-1, 1:-1]
    b = x[:, burnable_ch:burnable_ch + 1, 1:-1, 1:-1]
    sel = valid * b * (1 - m0) * ((t_in > 0) & (t_in < 1)).float()
    return float((r.abs() * sel).sum() / sel.sum().clamp_min(1.0))
