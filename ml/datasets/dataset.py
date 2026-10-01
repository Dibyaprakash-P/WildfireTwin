"""PyTorch dataset over generated reference-simulation samples."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from geo import registry
from geo.fuels import is_burnable
from geo.weather import dead_fuel_moisture, wind_speed_dir
from ml.features import CHANNELS, WeatherState, build_input
from simulation.rothermel import spread_field
from simulation.weather_sources import HISTORY_HOURS

TAU_MIN, TAU_MAX = -0.25, 1.5
_IDX = {c: i for i, c in enumerate(CHANNELS)}


def dataset_dir(version: str) -> Path:
    return registry.path(f"data/processed/training/{version}")


@dataclass
class SampleTensors:
    x: torch.Tensor        # C,H,W inputs
    y: torch.Tensor        # 1,H,W target burned mask at t0+h
    tau: torch.Tensor      # 1,H,W normalised arrival time (arrival - t0)/h, clipped
    phys: torch.Tensor     # 4,H,W [R_head m/min, ecc, sin(theta_max), cos(theta_max)]
    meta: dict


def weather_state(z: dict, t0_min: float, horizon_min: float) -> WeatherState:
    H = HISTORY_HOURS
    k0 = int(t0_min // 60)
    kh = max(1, int(math.ceil(horizon_min / 60.0)))
    sl = slice(k0, min(k0 + kh, len(z["w_u"])))
    return WeatherState(
        temp_now_c=float(z["w_temp"][H + k0]), rh_now_pct=float(z["w_rh"][H + k0]),
        u_now_ms=float(z["w_u"][k0]), v_now_ms=float(z["w_v"][k0]),
        temp_mean_c=float(np.mean(z["w_temp"][H + sl.start:H + sl.stop])),
        rh_mean_pct=float(np.mean(z["w_rh"][H + sl.start:H + sl.stop])),
        u_mean_ms=float(np.mean(z["w_u"][sl])), v_mean_ms=float(np.mean(z["w_v"][sl])),
        precip_sum_mm=float(np.sum(z["w_precip"][H + sl.start:H + sl.stop])),
        soil_moisture_m3m3=float(z["w_soil"][k0]),
    )


def physics_fields(fuel, slope, aspect, w: WeatherState, temp_hist, rh_hist, precip_hist,
                   live_herb: float, live_woody: float) -> np.ndarray:
    spd, wdir = wind_speed_dir(w.u_mean_ms, w.v_mean_ms)
    moist = dead_fuel_moisture(temp_hist, rh_hist, precip_hist, live_herb, live_woody)
    sf = spread_field(fuel, slope.astype(np.float32), aspect.astype(np.float32), float(spd), float(wdir), moist)
    return np.stack([sf.r_head_mmin, sf.ecc, np.sin(sf.theta_max), np.cos(sf.theta_max)]).astype(np.float32)


class WildfireDataset(Dataset):
    def __init__(self, version: str, split: str, bands: list[str] | None = None, augment: bool = False,
                 max_samples: int | None = None, seed: int = 0):
        self.root = dataset_dir(version)
        sa = pd.read_parquet(self.root / "samples.parquet")
        sc = pd.read_parquet(self.root / "scenarios.parquet").set_index("scenario_id")
        if "simulation_source" in sa.columns and sa["simulation_source"].nunique() > 1:
            raise ValueError(f"dataset {version} mixes reference engines {sorted(sa['simulation_source'].unique())}; "
                             "keep WTRS and FARSITE/FlamMap samples in separate dataset versions")
        self.simulation_source = str(sa["simulation_source"].iloc[0]) if "simulation_source" in sa.columns else "unknown"
        sa = sa[(sa["split"] == split) & sa["valid"]]
        if bands:
            sa = sa[sa["band"].isin(bands)]
        if max_samples and len(sa) > max_samples:
            sa = sa.sample(max_samples, random_state=seed)
        self.samples = sa.reset_index(drop=True)
        self.scen = sc
        self.augment = augment
        self.rng = np.random.default_rng(seed)
        self._cache: dict[str, dict] = {}

    def __len__(self) -> int:
        return len(self.samples)

    def _scenario(self, sid: str) -> dict:
        if sid not in self._cache:
            with np.load(self.root / "scenarios" / f"{sid}.npz") as z:
                self._cache[sid] = {k: z[k] for k in z.files}
        return self._cache[sid]

    def load(self, i: int) -> SampleTensors:
        row = self.samples.iloc[i]
        z = self._scenario(row["scenario_id"])
        sc = self.scen.loc[row["scenario_id"]]
        t0, hz = float(row["t0_min"]), float(row["horizon_min"])
        arr = z["arrival_min"]
        m0 = (arr <= t0).astype(np.float32)
        y = (arr <= t0 + hz).astype(np.float32)
        tau = np.clip(np.where(np.isfinite(arr), (arr - t0) / hz, TAU_MAX), TAU_MIN, TAU_MAX).astype(np.float32)
        w = weather_state(z, t0, hz)
        lc = z["landcover"] if bool(z["has_landcover"]) else None
        x = build_input(m0, z["elevation_m"], z["slope_deg"].astype(np.float32), z["aspect_deg"].astype(np.float32),
                        z["fuel_code"], lc, w, hz, float(row["cell_m"]))
        k0 = HISTORY_HOURS + int(t0 // 60)
        phys = physics_fields(z["fuel_code"], z["slope_deg"], z["aspect_deg"], w,
                              z["w_temp"][:k0 + 1], z["w_rh"][:k0 + 1], z["w_precip"][:k0 + 1],
                              float(sc["live_herb"]), float(sc["live_woody"]))
        meta = {"scenario_id": row["scenario_id"], "band": row["band"], "t0_min": t0, "horizon_min": hz,
                "cell_m": float(row["cell_m"]), "weather": w.to_dict()}
        return SampleTensors(torch.from_numpy(x), torch.from_numpy(y)[None], torch.from_numpy(tau)[None],
                             torch.from_numpy(phys), meta)

    def __getitem__(self, i: int):
        s = self.load(i)
        x, y, tau, phys = s.x, s.y, s.tau, s.phys
        if self.augment:
            x, y, tau, phys = random_dihedral(x, y, tau, phys, self.rng)
        return {"x": x, "y": y, "tau": tau, "phys": phys,
                "horizon_min": torch.tensor(s.meta["horizon_min"], dtype=torch.float32),
                "cell_m": torch.tensor(s.meta["cell_m"], dtype=torch.float32), "index": i}


# ---------------------------------------------------------------- augmentation
_VEC_PAIRS = [("aspect_sin", "aspect_cos"), ("u_now", "v_now"), ("u_mean", "v_mean")]


def _hflip(x, y, tau, phys):
    """Mirror west<->east: east components and azimuths change sign."""
    x, y, tau, phys = x.flip(-1), y.flip(-1), tau.flip(-1), phys.flip(-1)
    x = x.clone(); phys = phys.clone()
    for e, _ in _VEC_PAIRS:
        x[_IDX[e]] = -x[_IDX[e]]
    phys[2] = -phys[2]          # sin(theta) -> sin(-theta)
    return x, y, tau, phys


def _vflip(x, y, tau, phys):
    """Mirror north<->south: north components change sign; theta -> pi - theta."""
    x, y, tau, phys = x.flip(-2), y.flip(-2), tau.flip(-2), phys.flip(-2)
    x = x.clone(); phys = phys.clone()
    for _, n in _VEC_PAIRS:
        x[_IDX[n]] = -x[_IDX[n]]
    phys[3] = -phys[3]          # cos(pi - theta) = -cos(theta); sin unchanged
    return x, y, tau, phys


def _rot90(x, y, tau, phys):
    """Rotate the image 90 deg counter-clockwise: vector (e, n) -> (-n, e); theta -> theta - pi/2."""
    x, y, tau, phys = (t.rot90(1, dims=(-2, -1)) for t in (x, y, tau, phys))
    x = x.clone(); phys = phys.clone()
    for e, n in _VEC_PAIRS:
        ev, nv = x[_IDX[e]].clone(), x[_IDX[n]].clone()
        x[_IDX[e]], x[_IDX[n]] = -nv, ev
    s, c = phys[2].clone(), phys[3].clone()
    phys[2], phys[3] = -c, s    # sin(t - pi/2) = -cos t ; cos(t - pi/2) = sin t
    return x, y, tau, phys


def random_dihedral(x, y, tau, phys, rng: np.random.Generator):
    if rng.random() < 0.5:
        x, y, tau, phys = _hflip(x, y, tau, phys)
    if rng.random() < 0.5:
        x, y, tau, phys = _vflip(x, y, tau, phys)
    if rng.random() < 0.5:
        x, y, tau, phys = _rot90(x, y, tau, phys)
    return x, y, tau, phys


def load_manifest(version: str) -> dict:
    return json.loads((dataset_dir(version) / "manifest.json").read_text())


__all__ = ["WildfireDataset", "SampleTensors", "weather_state", "physics_fields", "is_burnable", "load_manifest"]
