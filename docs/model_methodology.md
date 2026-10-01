# Model Methodology

## 1. Problem formulation

For a fire at time t0 and horizon h ∈ {10 min, 30 min, 1 h, 6 h, 12 h, 24 h, 48 h, 72 h}, learn the operator

    G : ( fire state m₀(x), terrain(x), fuel(x), land cover(x), weather(t0 … t0+h), h ) ↦ p(x, t0 + h)

where p is the **model fire-spread probability** that cell x is burned at t0 + h (thresholded at 0.5 for areas and
metrics). One model serves all horizons; the horizon and cell size are input channels and the window resolution
depends on the horizon band (30 / 60 / 120 m, 128 × 128 cells).

### Input channels (`ml/features.py`, 34 channels)

fire_t0 · elevation (window-relative, /500 m) · slope/45° · aspect sin/cos (0 on flats) · burnable · fuel-group one-hot
(GR, GS, SH, TU, TL, SB) · 1-h dead load · fuel depth · land-cover one-hot (tree, shrub, grass, crop, built, bare,
water/wetland) · temperature, RH, wind u/v **at t0** · mean temperature, RH, wind u/v **over the horizon** ·
precipitation sum over the horizon · soil moisture · EMC-based 1-h dead fuel moisture · horizon · cell size.

The 40 fuel models are encoded through their group and physically meaningful continuous properties rather than a
sparse 40-way one-hot.

## 2. Reference simulator (training targets) — WTRS

FARSITE/FlamMap outputs were not present in the project, and the brief forbids fabricating simulation outputs.
Training targets therefore come from an **in-repo physics-based simulator** (`simulation/`), clearly labelled
`simulated` / `WTRS-Rothermel-MTT`, never "FARSITE" and never "ground truth":

* **Rate of spread:** Rothermel (1972) surface model with Scott & Burgan (2005) FBFM40 parameters, dynamic
  herbaceous curing, live moisture of extinction (Albini 1976), wind limit, and vector combination of wind and
  slope factors. Verified: the head-fire rates at 5 mi/h mid-flame wind fall inside Scott & Burgan's published
  spread-rate classes (test `tests/geo/test_simulation.py`).
* **Wind adjustment:** Albini & Baughman (1979) unsheltered WAF for GR/GS/SH/SB; fixed 0.15 for TU/TL (no canopy
  layer available — assumption).
* **Fire shape:** Anderson (1983) length-to-breadth ratio → ellipse eccentricity e;
  R(ψ) = R_head (1 − e) / (1 − e·cos(ψ − θ_max)).
* **Growth:** time-dependent Dijkstra (minimum travel time) on a 16-neighbour stencil; hourly weather.
* **Limitations:** surface fire only; no crown fire, spotting, suppression, or fuel-moisture conditioning; uniform
  weather inside the window.

The import pipeline (`simulation/converters/importers.py`) accepts real FARSITE/FlamMap exports so those can replace
or benchmark WTRS without code changes.

## 3. Models

### U-Net baseline (`ml/models/unet`)
4-level encoder–decoder (base 32 channels, GroupNorm, GELU), 1 output logit. Loss: BCE + soft Dice.

### Fourier Neural Operator (`ml/models/fno`)
Lifting MLP (34 + 2 grid channels → width 48) → 4 Fourier layers → projection MLP → 1 logit.
Each Fourier layer: `v ← GELU(GroupNorm(F⁻¹[R·F(v)] + W v))`, with R complex weights on the lowest 20 × 20 modes
(both signs of k_y), W a 1 × 1 convolution. The field is zero-padded by 16 cells before the FFT (fire fields are not
periodic) and cropped afterwards. This is a genuine spectral convolution — a unit test checks that one layer couples
distant pixels, which a local CNN kernel cannot.

**Why an operator:** the target is a mapping between *fields* (landscape, weather, current fire) and a *field*
(future burned state) — the solution operator of a front-propagation problem. Fourier layers mix information
globally per layer (a front kilometres away matters), and their weights live on physical frequencies, giving
approximate discretisation invariance across the 30/60/120 m bands (the same model runs on any grid size; tested).

### Physics-Informed FNO (`ml/models/physics_fno`)
Same backbone; the output is a **normalised arrival-time field** τ(x) = (T(x) − t0)/h. The mask probability is
derived as p = σ((1 − τ)/s), s = 0.1, so the data losses are identical to the other models.

**Loss**

    L_total = L_BCE(p, y) + L_Dice(p, y) + L_τ  +  λ_eik·L_eik + λ_mono·L_mono + λ_nb·L_nb

| Term | Definition | Physical meaning |
|---|---|---|
| L_τ | Huber(τ, τ_ref) with τ_ref the reference arrival time (clipped to [−0.25, 1.5]) | arrival-time supervision available from the reference simulator (data term) |
| L_eik | Huber of r = log(R(x, n̂)·‖∇T‖) where n̂ = ∇T/‖∇T‖, R from Rothermel/Anderson fields computed from inputs (fuel, slope, aspect, horizon-mean wind, t0 moisture); evaluated where the model predicts 0 < τ < 1 on burnable, not-initially-burning cells | anisotropic eikonal equation R(x,n)·‖∇T‖ = 1 of fire-front propagation (Huygens/MTT principle) |
| L_mono | mean over initially burning cells of ReLU(τ) | burned area cannot shrink (irreversibility) |
| L_nb | mean over non-burnable, not-initially-burning cells of p | fire cannot enter non-burnable fuel (NB91–99) |

Defaults: λ_eik = 0.1, λ_mono = λ_nb = 1, linearly ramped over 2 warm-up epochs (`ml/configs/physics_fno.yaml`).
Gradients use central differences in metres on the grid. The physics fields are computed from **inputs only**,
never from targets.

**Honest caveat:** the reference data satisfy the eikonal relation only approximately (hourly weather changes inside
the horizon, discrete 16-neighbour solver). The mean |log residual| of the *reference* arrival fields is logged in
the training history (`reference_eikonal_abs_log_residual`, ≈ 0.7 on the validation set), which is why the term is a
low-weight soft prior. It is a modular, replaceable component — a natural next step is to use the hourly physics
fields instead of horizon means. Training record (audit): the PI-FNO's eikonal term fell from 1.11 to 0.30, i.e. the
trained model satisfies the horizon-mean eikonal relation *more* closely than the reference data does (≈ 0.60) — so the
term acts as a consistency/smoothness prior, not as evidence of greater physical fidelity.

Using FARSITE-like data does **not** by itself make a model physics-informed; only the PI-FNO adds physics terms.

## 4. Training (`ml/training/trainer.py`)

AdamW (lr 1e-3, wd 1e-4), One-Cycle schedule, batch 16, ≤ 40 epochs, early stopping on validation growth-IoU
(patience 8), gradient clipping 1.0, seed 42, dihedral augmentation (flips / 90° rotations) that also transforms the
vector fields (aspect, wind, spread direction) — tested for physical consistency. Device: CUDA if available, else
CPU (`--dev` gives a tiny CPU-friendly run). Artifacts per run: checkpoint, config, history CSV, loss curves,
summary; tracked in MLflow (`mlflow.db`, SQLite) when available.

## 5. Inference

`backend/app/services/inference.py` — localized window per horizon band, observed FIRMS footprint as m₀,
Open-Meteo hourly forecast for the weather channels. A horizon is reported as **"Forecast unavailable"** (never
extrapolated) if the forecast does not cover it, inputs are missing, or the window is outside the data domain.
Each prediction records model name/version/checkpoint, dataset version, weather timestamp and fingerprint, input
transforms, per-horizon inference time and area statistics. Uncertainty is **not** quantified.
