# Project Inventory (Phase 0)

Inspection of `C:\WildFireTwin` before any code was written (2026-10-01). Nothing was deleted, moved or modified.

## Existing contents
| Path | Size | Content |
|---|---|---|
| `Research Papers/` | 11 PDFs | FNO, Neural Operator, PINN, 8 wildfire ML papers — see `research/literature_review.md` |
| `datasets/DL_FIRE_*` (36 CSVs) | ~38 GB | NASA FIRMS archive + NRT downloads: MODIS C6.1 (2010–2026), VIIRS S-NPP (2012–2026), NOAA-20 (2019–2026), NOAA-21 NRT (2024–2026); global; latest acquisition 2026-09-30 12:04 UTC |
| `datasets/9e8e…/data.grib`, `datasets/1663…/data.grib` | 2 × 340 MB | ERA5 hourly single levels 2024 and 2025, California (32.5–42°N, 124.5–114.25°W), 0.25°: 10u, 10v, 2t, 2d, tp, swvl1, cvh, cvl, lai_hv, lai_lv, avg_tprate |
| `datasets/n4{0,1}_w12{3,4,5}_1arc_v3.tif` | 6 × 25 MB | SRTM 1″ DEM, 40–42°N, 125–122°W, EPSG:4326, int16 |
| `datasets/landfire_…/LF2025_FBFM40_CONUS/` | 207 MB | LANDFIRE 2025 FBFM40, 30 m, EPSG:5070, 40–42°N × 124.5–122°W, with VAT and metadata |
| `datasets/lf_download_extent*.geojson` | 2 small files | LANDFIRE download box (EPSG:3857) |
| `datasets/terrascope_download_…/WORLDCOVER/` | 115 MB | ESA WorldCover 2021 v200 tiles N39W123, N39W126 (10 m) + input-quality layers |
| `datasets/bsp_…/burn_severity_perimeter_data.zip` | 1.1 GB unzipped | US burned-area perimeters (MTBS, BAER, RAVG, CBI, FWS…), NAD83 |
| `datasets/bsp_…/mtbs_CA_20{20..25}.zip` | 6 files | MTBS thematic burn-severity mosaics, California |

No existing code, configuration or dependency manifests were present.

## Environment found
Windows 11 Home; Python 3.14.7; Node 24.20.0, npm 12.0.2; git 2.55; NVIDIA GeForce RTX 5050 Laptop GPU (8 GB,
driver 616.64); **no Docker, no MongoDB** (a portable MongoDB 8.0.15 was placed in `tools/`); PyTorch 2.11 + CUDA 12.8
installed into `.venv`.

## Key findings that shaped the design
* All local landscape layers intersect in **N. California (40–42°N, 124.5–122°W)** → this is the model domain.
  FIRMS is global → global discovery, local prediction.
* ERA5 covers 2024–2025 → training scenarios use 2024–2025 fire-season weather; historical replay is offered for
  2024–2025 fires in the domain (e.g. Shelly 2024, Boise 2024, Green 2025).
* **No FARSITE/FlamMap outputs** were present → an in-repo Rothermel/MTT reference simulator generates the training
  targets (labelled `simulated`), and an import pipeline accepts real FARSITE/FlamMap exports.
* Burned-area perimeters are used only as observed context; replay validation compares against observed FIRMS
  footprints whose timing is defensible.

## Created structure
```
backend/app/   api · auth · alerts · services · ml · schemas · utils · db.py · config.py · main.py
frontend/      React + TS + Vite + Tailwind + CesiumJS
geo/           geospatial core (grids, warping, terrain, fuels, land cover, FIRMS, footprints, overlays, vectors, ERA5)
simulation/    Rothermel + MTT reference simulator, converters (FARSITE/FlamMap import), READMEs
ml/            features, datasets (generation + torch dataset), models (unet, fno, physics_fno), training, evaluation, configs
config/        data_sources.yaml, alert_rules.yaml
scripts/       preprocessing, inventory, env init, training driver
data/          processed/, models/, predictions/, simulations/, metadata/, DATA_INVENTORY.md
docs/ research/ tests/
```
