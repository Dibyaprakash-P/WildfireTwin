import math

import numpy as np
import pytest
import torch

from geo.weather import FuelMoisture
from ml.datasets.dataset import _hflip, _rot90, _vflip
from ml.evaluation.metrics import hausdorff, mask_metrics
from ml.features import CHANNELS, N_CHANNELS, WeatherState, build_input
from ml.models.factory import build_model
from ml.models.fno.model import FNO2d, SpectralConv2d
from ml.models.physics_fno.physics import PhysicsWeights, eikonal_residual, physics_losses
from simulation.rothermel import spread_field

CFG = {
    "unet": {"model": {"type": "unet", "base": 8, "depth": 3}},
    "fno": {"model": {"type": "fno", "width": 8, "modes": 6, "layers": 2, "padding": 4}},
    "physics_fno": {"model": {"type": "physics_fno", "width": 8, "modes": 6, "layers": 2, "padding": 4}},
}


@pytest.mark.parametrize("mtype", list(CFG))
def test_forward_shape_and_backward(mtype):
    model = build_model(CFG[mtype])
    x = torch.randn(2, N_CHANNELS, 64, 64)
    y = model(x)
    assert y.shape == (2, 1, 64, 64)
    y.mean().backward()
    assert all(p.grad is not None for p in model.parameters() if p.requires_grad)


def test_fno_is_resolution_flexible():
    m = FNO2d(N_CHANNELS, 1, width=8, modes=6, layers=2, padding=4)
    assert m(torch.randn(1, N_CHANNELS, 48, 48)).shape == (1, 1, 48, 48)
    assert m(torch.randn(1, N_CHANNELS, 96, 96)).shape == (1, 1, 96, 96)


def test_spectral_conv_is_global():
    """A single spectral layer couples distant pixels (unlike a 3x3 convolution)."""
    torch.manual_seed(0)
    sc = SpectralConv2d(1, 1, 8, 8)
    x = torch.zeros(1, 1, 64, 64)
    x2 = x.clone(); x2[0, 0, 0, 0] = 1.0
    d = (sc(x2) - sc(x)).abs()[0, 0]
    assert d[40:, 40:].max() > 1e-6


def test_physics_losses_finite_and_differentiable():
    torch.manual_seed(0)
    b, h = 2, 32
    tau = torch.rand(b, 1, h, h, requires_grad=True)
    x = torch.zeros(b, N_CHANNELS, h, h)
    x[:, CHANNELS.index("burnable")] = 1.0
    x[:, CHANNELS.index("fire_t0"), 14:18, 14:18] = 1.0
    phys = torch.stack([torch.full((b, h, h), 2.0), torch.full((b, h, h), 0.5),
                        torch.zeros(b, h, h), torch.ones(b, h, h)], dim=1)
    out = physics_losses(tau, x, phys, torch.tensor([60.0, 60.0]), torch.tensor([30.0, 30.0]),
                         CHANNELS.index("burnable"), CHANNELS.index("fire_t0"), PhysicsWeights())
    assert all(torch.isfinite(v) for v in out.values())
    out["physics"].backward()
    assert tau.grad is not None and torch.isfinite(tau.grad).all()


def test_eikonal_residual_zero_for_exact_isotropic_solution():
    """T = |x - x0| / R satisfies R |grad T| = 1 exactly for isotropic spread (ecc = 0)."""
    h, cell, R, hz = 64, 30.0, 2.0, 60.0
    yy, xx = np.mgrid[0:h, 0:h]
    T = np.hypot(xx - 31.5, yy - 31.5) * cell / R
    tau = torch.tensor(T / hz, dtype=torch.float32)[None, None]
    phys = torch.stack([torch.full((h, h), R), torch.zeros(h, h), torch.zeros(h, h), torch.ones(h, h)])[None]
    r, valid = eikonal_residual(tau, torch.tensor([hz]), torch.tensor([cell]), phys)
    interior = r[0, 0, 5:-5, 5:-5].abs()
    assert float(interior.median()) < 0.01


def _sample_tensors(theta_deg=30.0):
    rng = np.random.default_rng(0)
    h = 16
    fuel = rng.choice([102, 122, 145, 165], size=(h, h)).astype(np.int16)
    yy, xx = np.mgrid[0:h, 0:h]
    elev = (xx * 12.0 + yy * 5.0 + rng.normal(0, 2, (h, h))).astype(np.float32)
    from geo.terrain import slope_aspect
    slope, aspect = slope_aspect(elev, 30.0)
    w = WeatherState(25, 20, 3.0, -2.0, 25, 20, 3.0, -2.0, 0, 0.2)
    x = torch.from_numpy(build_input(np.zeros((h, h), np.float32), elev, slope, aspect, fuel, None, w, 60, 30))
    return fuel, elev, slope, aspect, x


def _phys(fuel, slope, aspect, u, v):
    from geo.weather import wind_speed_dir
    spd, d = wind_speed_dir(u, v)
    sf = spread_field(fuel, slope, aspect, float(spd), float(d), FuelMoisture(0.06, 0.07, 0.08, 0.6, 0.9))
    return torch.from_numpy(np.stack([sf.r_head_mmin, sf.ecc, np.sin(sf.theta_max), np.cos(sf.theta_max)]).astype(np.float32))


@pytest.mark.parametrize("op", ["h", "v", "r"])
def test_augmentation_is_physically_consistent(op):
    """Transforming inputs then recomputing physics == transforming the physics fields."""
    from geo.terrain import slope_aspect
    fuel, elev, slope, aspect, x = _sample_tensors()
    u, v = 3.0, -2.0
    phys = _phys(fuel, slope, aspect, u, v)
    y = torch.zeros(1, *fuel.shape); tau = torch.zeros(1, *fuel.shape)
    f = {"h": _hflip, "v": _vflip, "r": _rot90}[op]
    x2, _, _, phys2 = f(x, y, tau, phys)
    t = {"h": lambda a: np.flip(a, 1), "v": lambda a: np.flip(a, 0), "r": lambda a: np.rot90(a, 1)}[op]
    fuel_t, elev_t = np.ascontiguousarray(t(fuel)), np.ascontiguousarray(t(elev))
    s_t, a_t = slope_aspect(elev_t, 30.0)
    u_t, v_t = {"h": (-u, v), "v": (u, -v), "r": (-v, u)}[op]
    expect = _phys(fuel_t, s_t, a_t, u_t, v_t)
    inner = (slice(None), slice(2, -2), slice(2, -2))
    assert torch.allclose(phys2[inner][0], expect[inner][0], rtol=1e-3, atol=1e-4)
    ang2 = torch.atan2(phys2[2], phys2[3])[inner[1:]]
    ang_e = torch.atan2(expect[2], expect[3])[inner[1:]]
    diff = torch.remainder(ang2 - ang_e + math.pi, 2 * math.pi) - math.pi
    assert diff.abs().max() < 1e-2
    ci, cv = CHANNELS.index("u_now"), CHANNELS.index("v_now")
    assert math.isclose(float(x2[ci, 0, 0]) * 10, u_t, abs_tol=1e-5)
    assert math.isclose(float(x2[cv, 0, 0]) * 10, v_t, abs_tol=1e-5)


def test_metrics_perfect_and_disjoint():
    t = np.zeros((20, 20), bool); t[5:10, 5:10] = True
    m0 = np.zeros_like(t); m0[6:8, 6:8] = True
    perfect = mask_metrics(t.astype(np.float32), t, m0, 30.0)
    assert perfect["iou"] == 1.0 and perfect["dice"] == 1.0 and perfect["growth_iou"] == 1.0
    assert perfect["hausdorff_m"] == 0.0
    p = np.zeros((20, 20), np.float32); p[12:17, 12:17] = 1
    bad = mask_metrics(p, t, m0, 30.0)
    assert bad["iou"] == 0.0 and bad["hausdorff_m"] > 0


def test_hausdorff_known_shift():
    a = np.zeros((30, 30), bool); a[10:20, 10:20] = True
    b = np.zeros_like(a); b[10:20, 13:23] = True
    hd, _ = hausdorff(a, b, 10.0)
    assert hd == pytest.approx(30.0)
