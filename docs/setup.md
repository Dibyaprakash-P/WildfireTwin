# Setup & Operations

Verified environment: Windows 11, Python 3.14.7, Node 24.20 / npm 12, MongoDB 8.0.15 (portable),
NVIDIA RTX 5050 Laptop GPU (CUDA 12.8 PyTorch build). A CPU-only path works for everything except fast training.

## 1. Python environment
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt            # Linux/macOS: .venv/bin/pip
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cu128   # or .../whl/cpu
```
> Vector files are read with pure-Python `pyshp` because the `pyogrio`/`fiona` GDAL runtime could not be loaded on
> Python 3.14/Windows; rasters use `rasterio` (bundled GDAL).

## 2. Environment variables
```bash
python -m scripts.init_env      # creates .env from .env.example with a random development JWT secret
```
Edit `.env` for SMTP/Resend/SendGrid, `GOOGLE_CLIENT_ID`, `FIRMS_MAP_KEY` (all optional). In
`APP_ENV=production` the server refuses to start without `JWT_SECRET` and rejects the console email provider.

## 3. MongoDB
Any MongoDB ≥ 6. Without an installation, use the portable server (no admin rights needed):
```bash
curl -L -o tools/mongodb.zip https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.15.zip
# unzip to tools/mongodb, then:
tools/mongodb/bin/mongod --dbpath data/mongo --bind_ip 127.0.0.1 --port 27017
```
Collections and indexes are created automatically at backend start-up.

## 4. Data preparation (one-off; raw files stay in `datasets/`)
```bash
python -m scripts.preprocess_firms     # ~1 min (DuckDB over ~38 GB of CSV)
python -m scripts.preprocess_era5      # ~1 min
python -m scripts.preprocess_mtbs      # ~30 s
python -m scripts.inventory_data       # catalogue + data/DATA_INVENTORY.md
```

## 5. Training data, training, evaluation
```bash
python -m ml.datasets.generate --workers 7            # ~10 min: 2,400 reference simulations
python -m ml.training.train_unet                       # add --dev for a 2-epoch smoke run
python -m ml.training.train_fno
python -m ml.training.train_physics_fno
python -m ml.evaluation.evaluate_models                # writes data/models/evaluation/results.json
# or all of the above trainings + evaluation, detached (Windows):
powershell -File scripts/train_all.ps1
```
Artifacts: `data/models/<type>/<run_id>/` (+ `latest.json`). MLflow runs: `mlflow.db` (`mlflow ui --backend-store-uri sqlite:///mlflow.db`).

## 6. Run the application
```bash
# backend (repo root)
.venv/Scripts/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# frontend
cd frontend && npm install && npm run dev      # http://127.0.0.1:5173 (proxies /api and /files)
```
Development sign-up: with `EMAIL_PROVIDER=console` the 6-digit code is printed to the **backend console**.

Optional: `frontend/.env` with `VITE_CESIUM_ION_TOKEN=...` switches to Cesium World Terrain; without it, terrain is
served from the local SRTM tiles (N. California) and the ellipsoid elsewhere.

## 7. Docker
```bash
cp .env.example .env    # set JWT_SECRET
docker compose up --build      # frontend :8090, backend :8001, mongodb
```
`datasets/` (read-only) and `data/` are mounted; train models locally first (training is not containerised).
FlamMap/FARSITE are not containerised. *Docker was not available on the development machine, so the compose setup
has not been executed there.*

## 8. Tests
```bash
.venv/Scripts/python -m pytest              # geo, simulation, ML, backend (backend tests need MongoDB running)
cd frontend && npx vitest run
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| `No FIRMS data available.` | run `scripts.preprocess_firms` or set `FIRMS_MAP_KEY` |
| `Model not trained.` | run the training commands; check `data/models/<type>/latest.json` |
| `Terrain data not available for this region` / `Model not trained for this region` | fire is outside 40–42°N, 124.5–122°W (local LANDFIRE/SRTM coverage) |
| `Weather service unavailable.` | no internet / Open-Meteo down; retry |
| Globe blank | browser needs WebGL; check the console |
| `email_not_configured` | set SMTP/Resend/SendGrid variables or use `EMAIL_PROVIDER=console` in development |
| Google button disabled | set `GOOGLE_CLIENT_ID` and authorise the frontend origin in Google Cloud Console |
| `pyogrio` GDAL DLL error | not needed — vectors use `geo/vectors.py` |
