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
| Historical replay | 2024–2025 fires in the domain replayed from observed FIRMS state + ERA5; compared (single case) with later observed FIRMS footprints; MTBS perimeter shown for context |
| Auth | email + password with 6-digit OTP (hashed, 5-min expiry, cooldown, attempt limits), Argon2id, JWT, Google Sign-In |
| Provenance | every product tagged **observed / simulated / predicted / validated** |

## Architecture
```
OBSERVED: FIRMS · ERA5 · SRTM · LANDFIRE · WorldCover · MTBS · Open-Meteo
REFERENCE (training): WTRS = Rothermel + MTT (internal)   |   optional: FARSITE/FlamMap import (external, separate)
MODELS: U-Net · FNO · Physics-informed FNO (trained on WTRS)

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

### Downloaded datasets
**~41 GB of raw data in `datasets/`:** 10 datasets in 57 data files. There are 36 FIRMS CSVs, 5 ERA5 GRIBs,
6 SRTM tiles, 1 LANDFIRE raster, 2 WorldCover tiles and 7 MTBS zips. Raw files are not committed to Git. All dates
and times are in UTC.

| # | Dataset | Type | Files / size | Spatial coverage | Time coverage | Time resolution |
|---|---|---|---|---|---|---|
| 1 | NASA FIRMS VIIRS **Suomi NPP** (SV-C2) | Active-fire point detections (CSV) | 14 CSVs (13 yearly downloads), 20.8 GB | Global, 375 m pixels | 2012-01-20 → 2026-09-30 (**2013 and 2018 not downloaded**) | Per satellite overpass (date + HHMM UTC), ~2 passes/day |
| 2 | NASA FIRMS VIIRS **NOAA-20** (J1V-C2) | Active-fire point detections (CSV) | 9 CSVs (8 yearly downloads), 12.7 GB | Global, 375 m | 2019-01-01 → 2026-09-30 | Per overpass |
| 3 | NASA FIRMS VIIRS **NOAA-21** (J2V-C2) | Active-fire point detections (CSV, NRT) | 3 CSVs, 4.4 GB | Global, 375 m | 2024-01-17 → 2026-09-30 | Per overpass |
| 4 | NASA FIRMS **MODIS** Terra/Aqua (M-C61) | Active-fire point detections (CSV) | 10 CSVs (9 yearly downloads), 3.0 GB | Global, 1 km | 2010–2011 and 2020-01-01 → 2026-09-30 (**2012–2019 not downloaded**) | Per overpass, ~4 passes/day |
| 5 | ECMWF **ERA5** hourly single levels | Weather reanalysis (GRIB) | 5 GRIBs (one per year), ~1.7 GB | California: 32.5–42°N, 124.5–114.25°W at 0.25° (~25 km) | 2021-01-01 → 2025-12-31 on disk. **Only 2024 and 2025 are used** (`config/data_sources.yaml`) | Hourly |
| 6 | NASA **SRTM** v3 1 arc-second | Elevation model (GeoTIFF) | 6 tiles, 156 MB | 40–42°N, 125–122°W, ~30 m | Acquired Feb 2000 (static) | — |
| 7 | **LANDFIRE** 2025 FBFM40 | Surface fuel model (GeoTIFF + VAT) | 1 raster, 160 MB | 40–42°N, 124.5–122°W, 30 m (defines the model domain) | LF2025 version (static) | — |
| 8 | **ESA WorldCover** 2021 v200 | Land cover, 11 classes (GeoTIFF) | 2 tiles, 87 MB | 39–42°N, 126–120°W, 10 m | 2021 (static) | — |
| 9 | **MTBS / BAER / RAVG** burned-area perimeters | Fire perimeters (zipped shapefile) | 1 zip, 661 MB | All US, incl. Alaska, Hawaii, Puerto Rico; 918 perimeters fall inside the study box | 1984-07-02 → 2026-08-05 | Per fire event |
| 10 | **MTBS** burn-severity mosaics (California) | Burn-severity classes (zipped GeoTIFF) | 6 zips (one per year), 32 MB | California, 30 m | Fire years 2020–2025 (2025 does not overlap the model domain) | Per fire year |

### Regions and locations covered
The datasets cover areas of four different sizes, from the whole world down to the study area:

| Coverage level | Datasets | Region and places included |
|---|---|---|
| **Worldwide** | FIRMS Suomi NPP, NOAA-20, NOAA-21, MODIS (1–4) | Every continent. The yearly archives span about 54°S–66°N and 175°W–178°E. These detections drive the 3D globe. |
| **Whole United States** | MTBS / BAER / RAVG perimeters (9) | Lower 48 states, Alaska, Hawaii and Puerto Rico (18–70°N, 166–65°W). Only the 918 fires inside the study box are processed. |
| **California and Nevada** | ERA5 weather (5), MTBS severity mosaics (10) | ERA5: 32.5–42°N, 124.5–114.25°W. This is nearly all of California and most of Nevada, with thin edges of western Arizona and northern Baja California (Mexico). MTBS severity covers California only. |
| **Northern California (wider)** | ESA WorldCover (8) | 39–42°N, 126–120°W. This runs from the Pacific coast to the Nevada border and from the Oregon border south to about Ukiah and Chico. It includes Lassen Volcanic National Park and Susanville. |
| **Northern California study area (model domain)** | LANDFIRE fuels (7), SRTM elevation (6, slightly wider: 125–122°W), and the processed FIRMS, ERA5 and MTBS subsets | 40–42°N, 124.5–122°W: the Klamath Mountains and North Coast Ranges, from the Pacific coast to the Mount Shasta area. Counties: **Del Norte, Humboldt, Trinity, western Siskiyou, western Shasta** and **northwest Tehama**. Towns: **Crescent City, Eureka, Arcata, Weaverville, Redding, Yreka, Mount Shasta**. It also includes the Trinity Alps and the Six Rivers, Klamath and Shasta-Trinity National Forests. |

What this means in practice:
* **Fire monitoring works worldwide.** Fire spread **prediction** works only inside the study area above.
* The processed FIRMS subset uses the study box plus a 0.5° buffer (39.5–42.5°N, 125–121.5°W), so it reaches into
  far southern Oregon.
* The processed ERA5 subset is 39.75–42°N, 124.5–121.75°W.
* Processed MTBS severity rasters exist for 2020–2024. The 2025 mosaic has no fires inside the study area.

Datasets used online, not downloaded:
* **Open-Meteo forecast API (worldwide, queried at the selected fire):** current and forecast weather for live predictions. It covers the past 3 days plus a
  4-day forecast at hourly steps (~1–11 km).
* **NOAA GFS 1° (worldwide):** 10 m wind field for the globe wind-flow layer, fetched from NOMADS on demand.
* **FIRMS API (worldwide):** global near-real-time detections (with `FIRMS_MAP_KEY`).

**Processed from these (`data/processed/`, ~630 MB):**
* FIRMS region subset: 602,529 detections in the domain (2010-01-22 → 2026-09-30).
* Global recent NRT snapshot: 1,617,350 detections (2026-09-21 → 2026-09-30).
* ERA5 subset for northern California (2024–2025, hourly NetCDF).
* MTBS perimeters as GeoJSON and severity rasters for 2020–2024.
* **WTRS training set** `wtrs-ncal-v1`: 2,400 simulated scenarios and 22,505 valid samples. These come from ERA5
  2024–2025 fire seasons (June–October) at 30/60/120 m on a 128×128 grid. This is *simulated*, not observed, data.

FIRMS data is used for monitoring, initialising each forecast and comparing historical replays. It is **not** a
training input. The full table for each file is in [`data/DATA_INVENTORY.md`](data/DATA_INVENTORY.md).

## Database setup
MongoDB collections: `users`, `email_verifications`, `fire_events`, `weather_conditions`, `predictions`, `alerts`,
`model_runs`, `system_logs`, `simulations` — indexes (incl. 2dsphere, TTL) are created at start-up.

## Models, training & evaluation
| Model | Role | Output | Loss |
|---|---|---|---|
| U-Net | baseline | burned-mask logit | BCE + Dice |
| FNO | main | burned-mask logit | BCE + Dice |
| PI-FNO | advanced | arrival-time field → probability | BCE + Dice + arrival-time + λ·(eikonal + irreversibility + non-burnable) |

Training data: 2,400 WTRS reference simulations (Rothermel + MTT, not FARSITE) on the real landscape, driven by ERA5
2024–2025 weather; 22,505 valid samples; spatial-block split by ignition location (plus a strict no-overlap test subset). Configs (seed, channels, resolution, modes, width, lr, epochs, batch,
horizons, λ): `ml/configs/*.yaml`. Methodology: [`docs/model_methodology.md`](docs/model_methodology.md).
Results (only measured values): [`docs/evaluation.md`](docs/evaluation.md) and the **Models** page; before
evaluation the UI shows *Not evaluated*.

## Reference Simulation Methodology
The current WildfireTwin training/reference dataset (**WTRS**, `wtrs-ncal-v1`: 2,400 scenarios, 22,505 valid samples)
is generated by an internal **Rothermel + MTT** pipeline (Rothermel surface spread with LANDFIRE FBFM40 fuels,
Anderson elliptical shape, minimum-travel-time growth, ERA5 weather) — see [`docs/wtrs_dataset.md`](docs/wtrs_dataset.md).
FARSITE/FlamMap is supported as an **external reference/benchmark workflow** (import pipeline, separate dataset
versions) but is **not** the source of the WTRS training samples; no FARSITE/FlamMap output has been imported yet.
WTRS and FARSITE data are labelled per sample (`simulation_source`) and never mixed. Reference simulations are
*simulated* data, not ground truth. FlamMap/FARSITE is not required by end users.
Workflow: [`docs/farsite_flame_map_workflow.md`](docs/farsite_flame_map_workflow.md) · audit:
[`docs/scientific_audit.md`](docs/scientific_audit.md).

## Running simulations
*Simulation* page or `POST /api/simulations`: ignition from the observed FIRMS footprint or a point; Open-Meteo
forecast, ERA5 historical or constant weather; 1–72 h; 30/60/120 m. External FARSITE/FlamMap results:
**[ IMPORT SIMULATION RESULT ]** (`simulation/farsite/README.md`, `simulation/flammap/README.md`).

## Running the application
* **Dashboard:** globe (rotate/zoom/pan), layer panel, click a marker → *FIRE EVENT* panel → **[ ANALYZE FIRE ]**
  (sign-in required) → prediction summary, preview chart, NOW→72 h timeline, live logs and alerts.
* **Globe layers:** observed FIRMS detections (global), AI predicted spread (N. California model domain only),
  terrain relief, and **Atmosphere → Wind flow**: GPU particles following the real NOAA GFS 1° 10 m wind field
  (`/api/wind/field`, fetched from NOMADS, no key). Turn it off in the layer panel to stop the animation; opacity,
  density, speed and a performance tier (Auto/High/Medium/Low) are adjustable. If no field can be downloaded the
  panel shows *Wind data unavailable* and nothing is drawn. Details: [`docs/globe_visualization.md`](docs/globe_visualization.md).
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
