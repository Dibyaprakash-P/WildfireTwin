# Architecture

WildfireTwin is **global for fire discovery** and **local for prediction**.

```
            ┌───────────────────────── GLOBAL ─────────────────────────┐
 NASA FIRMS │ API (MAP_KEY) or local NRT CSVs → normalise → cluster →  │
            │ fire events (observed) → 3D Cesium globe                 │
            └──────────────────────────────┬───────────────────────────┘
                                           │ user selects a fire
            ┌───────────────────────── LOCAL ──────────────────────────┐
            │ 128×128 analysis window in EPSG:5070, snapped to the     │
            │ LANDFIRE 30 m lattice; cell = 30 / 60 / 120 m by horizon │
            │  ├─ SRTM DEM → slope / aspect (Horn)                     │
            │  ├─ LANDFIRE FBFM40 fuel model                           │
            │  ├─ ESA WorldCover land cover                            │
            │  ├─ FIRMS pixel footprints → initial fire mask (observed)│
            │  └─ Open-Meteo forecast → weather state per horizon      │
            │        ↓                                                  │
            │  trained model (PI-FNO / FNO / U-Net) → probability field│
            │        ↓                                                  │
            │  GeoTIFF (native CRS) + PNG overlay (EPSG:4326) → globe   │
            └──────────────────────────────────────────────────────────┘
```

The FNO is **never run over the whole Earth**. Global data (FIRMS) only drive discovery; every model input is
prepared on demand for the selected fire's window.

## Components

| Layer | Location | Responsibility |
|---|---|---|
| Frontend | `frontend/` | React + TypeScript + Vite + Tailwind; CesiumJS globe; pages Dashboard, Simulation, Data, Models, Logs, Historical, Risk, Alerts, Settings; auth screens |
| API | `backend/app/api/` | FastAPI routers (auth, fires, weather/environment, predictions, simulations, historical, terrain tiles, system/SSE) |
| Services | `backend/app/services/` | FIRMS ingestion + clustering, Open-Meteo client, environment, inference, prediction orchestration, simulations, monitor loop, email |
| Alerts | `backend/app/alerts/` | pure rule engine (`engine.py`, thresholds in `config/alert_rules.yaml`) + persistence/push (`store.py`) |
| Auth | `backend/app/auth/` + `api/auth.py` | Argon2id passwords, HMAC-hashed OTPs, JWT (HS256), Google ID-token verification |
| Geospatial core | `geo/` | grid definition, logged warping, terrain derivatives, fuels table, land cover, FIRMS normalisation, footprints, overlays, vector I/O, ERA5 |
| Reference simulator | `simulation/` | Rothermel + elliptical spread + minimum-travel-time solver (WTRS), FARSITE/FlamMap importers |
| ML | `ml/` | features, dataset generation, PyTorch dataset/augmentation, U-Net / FNO / PI-FNO, training, evaluation |
| Data | `datasets/` (raw, untouched), `data/` (processed, models, predictions, metadata) | |
| Database | MongoDB | metadata & operational records only (no rasters/tensors) |

## Runtime flows

**Startup** — connect MongoDB, create indexes, load FIRMS (API if `FIRMS_MAP_KEY`, else local NRT Parquet),
cluster detections into events, upsert `fire_events`, start the monitor loop.

**Prediction** (`POST /api/predictions`) — build fire context → fetch Open-Meteo (cached) and store a weather
snapshot → compute an input hash (fire detections, weather fingerprint, model version, horizons) → return a cached
prediction if identical → otherwise run inference per horizon in a worker thread → write GeoTIFF/PNG → store the
prediction document → compare with the previous prediction of the same fire/model → emit alerts → push SSE events.

**Dynamic update** (`services/monitor.py`, every `MONITOR_INTERVAL_SECONDS`) — refresh FIRMS → for fires predicted
in the last 24 h compare fire activity and weather with stored state → if a change is material (rule thresholds) or
the forecast/observations changed, re-run the model → the prediction service compares old vs new forecast and raises
`PREDICTION_CHANGE` / `SPREAD_RISK_CHANGE` alerts → the frontend updates via SSE (`/api/events/stream`).

**Reference simulation** (`POST /api/simulations`) — WTRS runs in a background thread on the same local landscape;
results are labelled `simulated`. External FARSITE/FlamMap results are imported via `POST /api/simulations/import`.

## Data classes (provenance)

| Class | Examples | UI tag |
|---|---|---|
| observed | FIRMS detections, Open-Meteo/ERA5 weather, SRTM, LANDFIRE, WorldCover, burned-area perimeters | `OBSERVED` (cyan) |
| simulated | WTRS reference runs, imported FARSITE/FlamMap, the training dataset | `SIMULATED` (amber) |
| predicted | WildfireTwin model output ("model fire-spread probability") | `PREDICTED` (orange) |
| validated | comparison of predictions with observed footprints (historical replay) | `VALIDATED` (green) |

Tags always include text — colour is never the only signal.

## MongoDB collections

`users`, `email_verifications` (TTL purge), `fire_events` (2dsphere centroid), `weather_conditions` (2dsphere),
`predictions`, `alerts`, `model_runs`, `system_logs` (TTL 30 days), `simulations`. Index definitions: `backend/app/db.py`.

## Why FARSITE/FlamMap is not required by end users

FARSITE/FlamMap are Windows desktop research tools. In WildfireTwin they are an *optional offline* source of reference
simulations: their exported arrival-time rasters or perimeters can be imported for benchmarking. The production path
needs only the trained neural model (and, for on-demand reference runs, the in-repo WTRS simulator, which is plain
Python). Users need only a web browser.
