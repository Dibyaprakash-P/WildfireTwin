"""Rothermel (1972) surface fire spread model, vectorised over a fuel grid.

References
----------
Rothermel, R.C. (1972) A mathematical model for predicting fire spread in
    wildland fuels. USDA FS Res. Pap. INT-115.
Albini, F.A. (1976) Estimating wildfire behavior and effects. INT-GTR-30.
Albini & Baughman (1979) Estimating windspeeds for predicting wildland fire
    behavior. INT-RP-221  (wind adjustment factor, unsheltered).
Anderson, H.E. (1983) Predicting wind-driven wild land fire size and shape.
    INT-RP-305  (length-to-breadth ratio).
Scott & Burgan (2005) RMRS-GTR-153  (fuel models, dynamic herb transfer).

Implementation notes
--------------------
* US customary units internally (ft, lb, BTU, min); outputs in metres/minute.
* Category weighting uses the original Rothermel (1972) surface-area weights
  f_ij (no size-class sub-weighting).
* Wind and slope effects are combined by vector addition of phi_w and phi_s
  (as in BEHAVE/FARSITE); the original wind limit U <= 0.9 I_R is applied.
* Wind adjustment factor: Albini & Baughman (1979) unsheltered formula for
  grass, grass-shrub, shrub and slash groups; a fixed sheltered value
  (default 0.15) for timber-understory and timber-litter groups because no
  canopy-cover layer is available locally. This is an explicit assumption.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from geo.fuels import FUEL_MODELS, HEAT_CONTENT_BTU_LB, SAV_10H, SAV_100H, TONS_PER_ACRE_TO_LB_PER_FT2, FuelModel
from geo.weather import FuelMoisture

RHO_P = 32.0            # particle density lb/ft3
S_T = 0.0555            # total mineral content
S_E = 0.010             # effective mineral content
ETA_S = min(0.174 * S_E ** -0.19, 1.0)
FT_TO_M = 0.3048
MS_TO_FTMIN = 196.850394
SHELTERED_WAF = 0.15
MAX_LB = 8.0


@dataclass
class FuelTerms:
    """Moisture-dependent, wind/slope-independent Rothermel terms for one fuel model."""
    r0_ftmin: float
    ir: float                 # reaction intensity BTU/ft2/min
    beta: float
    beta_ratio: float
    c: float
    b: float
    e: float
    slope_k: float            # 5.275 beta^-0.3
    waf: float
    heat_per_area: float      # BTU/ft2 (Byram: I_R * residence time), for intensity estimates


def _eta_m(m: float, mx: float) -> float:
    if mx <= 0:
        return 0.0
    r = min(m / mx, 1.0)
    return max(0.0, 1.0 - 2.59 * r + 5.11 * r ** 2 - 3.52 * r ** 3)


def fuel_terms(fm: FuelModel, moist: FuelMoisture) -> FuelTerms:
    l1, l10, l100, lh, lw = (x * TONS_PER_ACRE_TO_LB_PER_FT2 for x in fm.loads)
    sh = fm.sav_herb or 1500.0
    sw = fm.sav_woody or 1500.0
    w_dead_herb = 0.0
    if fm.dynamic and lh > 0:
        cured = min(max((1.20 - moist.m_herb) / 0.90, 0.0), 1.0)
        w_dead_herb, lh = lh * cured, lh * (1.0 - cured)
    dead = [(l1, fm.sav_1h, moist.m1), (l10, SAV_10H, moist.m10), (l100, SAV_100H, moist.m100),
            (w_dead_herb, sh, moist.m1)]
    live = [(lh, sh, moist.m_herb), (lw, sw, moist.m_woody)]
    dead = [c for c in dead if c[0] > 0]
    live = [c for c in live if c[0] > 0]

    def cat(classes):
        a = [w * s / RHO_P for w, s, _ in classes]
        at = sum(a)
        f = [x / at for x in a] if at > 0 else []
        return at, f

    a_d, f_d = cat(dead)
    a_l, f_l = cat(live)
    a_t = a_d + a_l
    fi_d, fi_l = a_d / a_t, a_l / a_t
    sig_d = sum(f * s for f, (_, s, _) in zip(f_d, dead))
    sig_l = sum(f * s for f, (_, s, _) in zip(f_l, live))
    sigma = fi_d * sig_d + fi_l * sig_l

    w_total = sum(w for w, _, _ in dead + live)
    rho_b = w_total / fm.depth_ft
    beta = rho_b / RHO_P
    beta_op = 3.348 * sigma ** -0.8189
    ratio = beta / beta_op
    gmax = sigma ** 1.5 / (495.0 + 0.0594 * sigma ** 1.5)
    a_exp = 133.0 * sigma ** -0.7913
    gamma = gmax * ratio ** a_exp * math.exp(a_exp * (1.0 - ratio))

    wn_d = sum(f * w * (1 - S_T) for f, (w, _, _) in zip(f_d, dead))
    wn_l = sum(f * w * (1 - S_T) for f, (w, _, _) in zip(f_l, live))
    mf_d = sum(f * m for f, (_, _, m) in zip(f_d, dead))
    mf_l = sum(f * m for f, (_, _, m) in zip(f_l, live))
    mx_d = fm.mx_dead_pct / 100.0
    mx_l = mx_d
    if live:
        wd_fine = sum(w * math.exp(-138.0 / s) for w, s, _ in dead)
        wl_fine = sum(w * math.exp(-500.0 / s) for w, s, _ in live)
        md_fine = sum(w * math.exp(-138.0 / s) * m for w, s, m in dead) / wd_fine if wd_fine > 0 else 0.0
        if wl_fine > 0 and wd_fine > 0:
            mx_l = max(2.9 * (wd_fine / wl_fine) * (1.0 - md_fine / mx_d) - 0.226, mx_d)
    ir = gamma * HEAT_CONTENT_BTU_LB * ETA_S * (wn_d * _eta_m(mf_d, mx_d) + wn_l * _eta_m(mf_l, mx_l))
    xi = math.exp((0.792 + 0.681 * sigma ** 0.5) * (beta + 0.1)) / (192.0 + 0.2595 * sigma)

    def sink(classes, f, fi):
        return fi * sum(fj * math.exp(-138.0 / s) * (250.0 + 1116.0 * m) for fj, (_, s, m) in zip(f, classes))

    heat_sink = rho_b * (sink(dead, f_d, fi_d) + sink(live, f_l, fi_l))
    r0 = ir * xi / heat_sink if heat_sink > 0 else 0.0

    c = 7.47 * math.exp(-0.133 * sigma ** 0.55)
    b = 0.02526 * sigma ** 0.54
    e = 0.715 * math.exp(-3.59e-4 * sigma)
    if fm.group in ("TU", "TL"):
        waf = SHELTERED_WAF
    else:
        d = fm.depth_ft
        waf = 1.83 / math.log((20.0 + 0.36 * d) / (0.13 * d))
    t_res = 384.0 / sigma  # Anderson (1969) residence time, min
    return FuelTerms(r0, ir, beta, ratio, c, b, e, 5.275 * beta ** -0.3, min(waf, 1.0), ir * t_res)


@dataclass
class SpreadField:
    """Per-cell elliptical spread parameters for one weather state."""
    r_head_mmin: np.ndarray   # head-fire rate of spread (m/min), 0 = non-burnable / no spread
    ecc: np.ndarray           # ellipse eccentricity 0..1
    theta_max: np.ndarray     # azimuth of maximum spread (rad, clockwise from north)
    r0_mmin: np.ndarray       # no-wind, no-slope rate (m/min)
    fireline_intensity_kwm: np.ndarray

    def ros(self, azimuth_rad: np.ndarray | float) -> np.ndarray:
        """Rate of spread (m/min) toward `azimuth` from the ignition point of the ellipse."""
        return self.r_head_mmin * (1.0 - self.ecc) / (1.0 - self.ecc * np.cos(azimuth_rad - self.theta_max))


def spread_field(fuel_code: np.ndarray, slope_deg: np.ndarray, aspect_deg: np.ndarray,
                 wind_speed_10m_ms: float, wind_from_deg: float, moist: FuelMoisture) -> SpreadField:
    shape = fuel_code.shape
    lut_r0 = np.zeros(256); lut_ir = np.zeros(256); lut_c = np.zeros(256); lut_b = np.ones(256)
    lut_e = np.zeros(256); lut_ratio = np.ones(256); lut_sk = np.zeros(256); lut_waf = np.zeros(256)
    lut_hpa = np.zeros(256)
    for code in np.unique(fuel_code):
        fm = FUEL_MODELS.get(int(code))
        if fm is None:
            continue
        t = fuel_terms(fm, moist)
        lut_r0[code], lut_ir[code], lut_c[code], lut_b[code] = t.r0_ftmin, t.ir, t.c, t.b
        lut_e[code], lut_ratio[code], lut_sk[code], lut_waf[code] = t.e, t.beta_ratio, t.slope_k, t.waf
        lut_hpa[code] = t.heat_per_area
    idx = np.clip(fuel_code.astype(np.int32), 0, 255)
    r0, ir, c, b = lut_r0[idx], lut_ir[idx], lut_c[idx], lut_b[idx]
    e, ratio, sk, waf = lut_e[idx], lut_ratio[idx], lut_sk[idx], lut_waf[idx]

    u20 = wind_speed_10m_ms / 1.15
    u_mid = np.minimum(u20 * MS_TO_FTMIN * waf, 0.9 * ir)  # ft/min, Rothermel wind limit
    with np.errstate(divide="ignore", invalid="ignore"):
        phi_w = np.where(u_mid > 0, c * np.power(u_mid, b) * np.power(ratio, -e), 0.0)
    tan_s = np.tan(np.radians(np.clip(slope_deg, 0, 80)))
    phi_s = sk * tan_s ** 2

    up = np.where(aspect_deg < 0, 0.0, np.radians((aspect_deg + 180.0) % 360.0))
    wind_to = math.radians((wind_from_deg + 180.0) % 360.0)
    delta = wind_to - up
    x = phi_s + phi_w * np.cos(delta)
    y = phi_w * np.sin(delta)
    phi_e = np.hypot(x, y)
    theta = (up + np.arctan2(y, x)) % (2 * math.pi)

    r_head_ft = r0 * (1.0 + phi_e)
    with np.errstate(divide="ignore", invalid="ignore"):
        u_eff = np.where(phi_e > 0, np.power(phi_e * np.power(ratio, e) / np.where(c > 0, c, 1), 1.0 / b), 0.0)
    u_mph = np.nan_to_num(u_eff / 88.0)
    lb = np.clip(0.936 * np.exp(0.2566 * u_mph) + 0.461 * np.exp(-0.1548 * u_mph) - 0.397, 1.0, MAX_LB)
    ecc = np.sqrt(np.maximum(lb ** 2 - 1.0, 0.0)) / lb

    r_head = (r_head_ft * FT_TO_M).astype(np.float32)
    # Byram intensity I = H_A * R  (BTU/ft/min -> kW/m: x 0.05767)
    intensity = (lut_hpa[idx] * r_head_ft * 0.05767).astype(np.float32)
    return SpreadField(r_head.reshape(shape), ecc.astype(np.float32).reshape(shape), theta.astype(np.float32).reshape(shape),
                       (r0 * FT_TO_M).astype(np.float32).reshape(shape), intensity.reshape(shape))
