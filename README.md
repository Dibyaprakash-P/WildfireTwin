# WILDFIRETWIN
**Physics-Informed Neural Operator for Dynamic Wildfire Spread Prediction** — MCA capstone research prototype.

WildfireTwin monitors active fires worldwide on a 3D globe (NASA FIRMS) and, for a selected fire inside its local
data domain, forecasts fire spread for 10 min → 72 h with a trained neural operator. It refreshes observations and
weather periodically, re-runs the forecast when conditions change materially, and raises explainable alerts.

> **Decision-support research prototype.** Not an autonomous emergency warning system. Predictions are model
> outputs trained on physics-based *reference simulations*; they are not guaranteed real-world forecasts.
> Uncertainty is not quantified and generally increases with horizon.

---

## Contents
1. [Overview](#overview) · 2. [Architecture](#architecture) · 3. [Technology](#technology-stack) · 4. [Quick start](#quick-start)
5. [Data](#data-setup) · 6. [Models](#models-training--evaluation) · 7. [Simulations](#running-simulations)
8. [Configuration](#environment-variables) · 9. [Why no FARSITE/FlamMap for users](#why-farsiteflammap-is-not-required-by-end-users)
10. [Limitations](#limitations) · 11. [Troubleshooting](#troubleshooting) · [Docs](#documentation)

## Overview
| Capability | Implementation |
|---|---|
| Global active-fire monitoring | FIRMS API (with `FIRMS_MAP_KEY`) or local NRT archive → normalised, de-duplicated, clustered into fire events (observed footprints) → CesiumJS globe with zoom-dependent clustering |
| Local environment | SRTM elevation → Horn slope/aspect, LANDFIRE FBFM40 fuel model, ESA WorldCover, Open-Meteo weather; every value with source, units and timestamp |
| Spread prediction | U-Net (baseline), **FNO** (main), **Physics-Informed FNO** (advanced); 8 horizons; probability overlays draped on 3D terrain; timeline slider |
| Reference simulation | in-repo Rothermel + elliptical + minimum-travel-time simulator (WTRS), and FARSITE/FlamMap result import |
| Dynamic updating | polling monitor → change detection → re-inference → forecast comparison → alerts → live SSE push |
| Alerts | WEATHER_CHANGE, FIRE_ACTIVITY_CHANGE, PREDICTION_CHANGE, SPREAD_RISK_CHANGE, DATA_UPDATE; INFO/WARNING/HIGH/CRITICAL from explicit thresholds (`config/alert_rules.yaml`) |
| Historical validation | 2024–2025 fires in the domain replayed from observed FIRMS state + ERA5; compared with later observed FIRMS footprints |
| Auth | email + password with 6-digit OTP (hashed, 5-min expiry, cooldown, attempt limits), Argon2id, JWT, Google Sign-In |
| Provenance | every product tagged **observed / simulated / predicted / validated** |

## Architecture
```
FIRMS (global) ──► fire events ──► 3D globe ──► user selects fire
                                                   │
             local 128×128 window (EPSG:5070; 30/60/120 m by horizon)
   SRTM · LANDFIRE · WorldCover · FIRMS footprint · Open-Meteo
                                                   │
                       PI-FNO / FNO / U-Net (PyTorch)
                                                   │
          GeoTIFF + PNG overlay ─► Cesium · MongoDB metadata · alerts · SSE
```
The FNO is never run globally. Details: [`docs/architecture.md`](docs/architecture.md).

## Technology stack
* **Frontend:** React 18, TypeScript, Vite 5, Tailwind CSS 3, CesiumJS, Recharts, Zustand, Lucide; JetBrains Mono.
* **Backend:** Python, FastAPI, Pydantic, PyMongo (async), Argon2, PyJWT, google-auth, httpx.
* **Geospatial:** rasterio/GDAL, pyproj, shapely, geopandas, xarray, eccodes, DuckDB, pyshp.
* **ML:** PyTorch (CUDA when available, CPU fallback), MLflow (SQLite, optional).
* **Database:** MongoDB (metadata + operational records only; rasters on disk).

## Quick start
```bash
# Python
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cu128   # or /whl/cpu
python -m scripts.init_env                       # local .env with a generated dev JWT secret
# MongoDB running on 127.0.0.1:27017 (see docs/setup.md for a portable server)

# data → dataset → models (one-off)
python -m scripts.preprocess_firms && python -m scripts.preprocess_era5 && python -m scripts.preprocess_mtbs
python -m ml.datasets.generate --workers 7
python -m ml.training.train_unet && python -m ml.training.train_fno && python -m ml.training.train_physics_fno
python -m ml.evaluation.evaluate_models && python -m scripts.inventory_data

# run
.venv/Scripts/python -m uvicorn backend.app.main:app --port 8000
cd frontend && npm install && npm run dev        # → http://127.0.0.1:5173
```
Full instructions, Docker and troubleshooting: [`docs/setup.md`](docs/setup.md).

## Data setup
Raw downloads stay untouched in `datasets/`; paths are registered in `config/data_sources.yaml`. Inventory with
metadata extracted from the files: [`data/DATA_INVENTORY.md`](data/DATA_INVENTORY.md); pipeline and every unit
conversion / reprojection: [`docs/data_pipeline.md`](docs/data_pipeline.md).

**Model domain:** 40–42°N, 124.5–122°W (where LANDFIRE, SRTM and WorldCover all exist locally). Fires elsewhere are
displayed and described, but prediction reports "Model not trained for this region".

## Database setup
MongoDB collections: `users`, `email_verifications`, `fire_events`, `weather_conditions`, `predictions`, `alerts`,
`model_runs`, `system_logs`, `simulations` — indexes (incl. 2dsphere, TTL) are created at start-up.

## Models, training & evaluation
| Model | Role | Output | Loss |
|---|---|---|---|
| U-Net | baseline | burned-mask logit | BCE + Dice |
| FNO | main | burned-mask logit | BCE + Dice |
| PI-FNO | advanced | arrival-time field → probability | BCE + Dice + arrival-time + λ·(eikonal + irreversibility + non-burnable) |

Training data: 2,400 WTRS reference simulations on the real landscape, driven by ERA5 2024–2025 weather; ~22.5 k
valid samples; **spatial-block hold-out** split. Configs (seed, channels, resolution, modes, width, lr, epochs, batch,
horizons, λ): `ml/configs/*.yaml`. Methodology: [`docs/model_methodology.md`](docs/model_methodology.md).
Results (only measured values): [`docs/evaluation.md`](docs/evaluation.md) and the **Models** page; before
evaluation the UI shows *Not evaluated*.

## Running simulations
*Simulation* page or `POST /api/simulations`: ignition from the observed FIRMS footprint or a point; Open-Meteo
forecast, ERA5 historical or constant weather; 1–72 h; 30/60/120 m. External FARSITE/FlamMap results:
**[ IMPORT SIMULATION RESULT ]** (`simulation/farsite/README.md`, `simulation/flammap/README.md`).

## Running the application
* **Dashboard:** globe (rotate/zoom/pan), layer panel, click a marker → *FIRE EVENT* panel → **[ ANALYZE FIRE ]**
  (sign-in required) → prediction summary, preview chart, NOW→72 h timeline, live logs and alerts.
* **Simulation**, **Data**, **Models**, **Logs**, **Historical Data**, **Risk Assessment**, **Alerts**, **Settings**.
* Sign up with email → 6-digit code (printed in the backend console in development) → *Signup successful.*

## Environment variables
See [`.env.example`](.env.example). Secrets are read only from the environment; `.env` is git-ignored.

## Why FARSITE/FlamMap is not required by end users
FARSITE/FlamMap are desktop research simulators. WildfireTwin uses physics-based simulation **offline** to create
reference data and benchmarks; the deployed product runs only the trained neural operator (milliseconds per horizon
on CPU/GPU) plus optional in-repo Python reference runs. Users need nothing but a browser; FARSITE/FlamMap exports
can still be imported by researchers.

## Limitations
* Training targets are simulations (surface fire, no spotting/crown fire/suppression), not observed progression.
* Initial state = satellite active-fire pixels (375 m / 1 km), not mapped perimeters.
* Weather is spatially uniform in each window; ERA5 (training) and Open-Meteo (inference) differ in resolution.
* Domain limited to the local data coverage in N. California; no uncertainty quantification.

## Testing
`python -m pytest` (geo, simulation, ML, backend auth/OTP/fires/weather/alerts) and `cd frontend && npx vitest run`.

## Troubleshooting
See [`docs/setup.md#troubleshooting`](docs/setup.md#troubleshooting).

## Documentation
[`docs/architecture.md`](docs/architecture.md) · [`docs/data_pipeline.md`](docs/data_pipeline.md) ·
[`docs/model_methodology.md`](docs/model_methodology.md) · [`docs/api.md`](docs/api.md) · [`docs/setup.md`](docs/setup.md) ·
[`docs/evaluation.md`](docs/evaluation.md) · [`docs/globe_visualization.md`](docs/globe_visualization.md) · [`research/literature_review.md`](research/literature_review.md) ·
[`PROJECT_INVENTORY.md`](PROJECT_INVENTORY.md)

Data credits: NASA FIRMS (LANCE), ECMWF ERA5 (Copernicus C3S), NASA SRTM, LANDFIRE (USGS/USFS), ESA WorldCover,
MTBS/USFS/USGS burned-area programmes, Open-Meteo, Esri basemaps.
