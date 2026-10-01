# Data Pipeline

Raw files stay exactly where they were downloaded (`datasets/`). Paths are registered in
`config/data_sources.yaml`; processed outputs go to `data/processed/`. Metadata reports are written to
`data/metadata/` and summarised in `data/DATA_INVENTORY.md` (`python -m scripts.inventory_data`).

| Step | Command | Output |
|---|---|---|
| FIRMS normalisation | `python -m scripts.preprocess_firms` | `firms_region.parquet` (study bbox +0.5°, 2010–2026), `firms_recent_global.parquet` (last 10 days of NRT) |
| ERA5 subset | `python -m scripts.preprocess_era5` | `weather/era5_ncal_hourly.nc` (2024–2025, hourly, 0.25°) |
| Burned-area perimeters | `python -m scripts.preprocess_mtbs` | `vectors/mtbs_perimeters_region.geojson` |
| Raster mosaics | automatic on first use | `rasters/srtm_mosaic_4326.tif`, `rasters/worldcover_100m_4326.tif` |
| Training dataset | `python -m ml.datasets.generate` | `training/wtrs-ncal-v1/…` |
| Catalogue | `python -m scripts.inventory_data` | `metadata/catalog.json`, `DATA_INVENTORY.md` |

## Study region

Intersection of the LANDFIRE download, SRTM tiles and WorldCover tiles: **40–42°N, 124.5–122°W** (Klamath / North
Coast Ranges, N. California). This is the **model domain**: prediction requires LANDFIRE fuel, so fires outside it
show "Model not trained for this region". FIRMS discovery remains global.

## FIRMS

* Both sources (local CSVs, FIRMS area API) map to one schema (`geo/firms.py`): detection_id, lat/lon,
  acq_datetime (UTC, from `acq_date` + zero-padded `acq_time`), satellite, instrument, product, raw confidence and
  class (VIIRS l/n/h; MODIS <30 low, 30–79 nominal, ≥80 high), brightness, bright_t31, FRP, scan, track, day/night,
  version, `type` (archive only), source.
* Malformed rows (unparseable time, out-of-range coordinates) are dropped and counted; duplicates are removed by a
  deterministic `detection_id` (md5 of satellite|time|lat|lon, identical in DuckDB and Python).
* Events: connected components of detection centres within 1.5 km over the last 48 h (KD-tree on unit-sphere xyz).
* Initial fire state: each detection is drawn as its pixel footprint (scan × track km, axis-aligned approximation)
  on the analysis grid. Labelled *observed active-fire footprint*, not a perimeter.
* Historical analysis excludes `type` 1–3 (volcano, static sources, offshore); `type` 0 or missing is kept.

## Weather

* **ERA5** (historical, local GRIB): read message-by-message with eccodes, subset to the region, converted:
  K→°C; RH from T and dew point (Magnus, Alduchov & Eskridge 1996); `tp` m→mm (hourly accumulation); winds kept as
  u/v (m/s). Point series are bilinearly interpolated at the window centre.
* **Open-Meteo** (live): current + 3 past days + 4 forecast days, `wind_speed_unit=ms`, GMT; units are stored with
  values; responses cached 15 min; snapshots stored in `weather_conditions`.
* Wind direction convention: meteorological "from" degrees; `u = −s·sin(d)`, `v = −s·cos(d)`.
* 10 m → 20 ft wind: `U20ft = U10m / 1.15`; mid-flame wind via the wind adjustment factor (see methodology).
* Dead fuel moisture: Simard (1968) EMC; 1-h = current EMC, 10-h = 24-h mean EMC, 100-h = 72-h mean EMC; heuristic
  wetting floor (25 %) after ≥1 mm rain in 24 h. Live fuel moisture is a scenario parameter (not observed).
* Soil moisture: ERA5 `swvl1` (0–7 cm) in training; Open-Meteo `soil_moisture_3_to_9cm` at inference (closest
  available layer — documented mismatch; if missing, the default 0.25 m³/m³ is used and flagged in metadata).

## Rasters and alignment

`geo/rasters.py` defines an `AnalysisGrid` (EPSG:5070, square, north-up, origin snapped to the LANDFIRE 30 m
lattice). Every source is warped onto it with an explicit resampling method and **every warp is logged**
(`TransformLog`, stored in sample/prediction metadata):

| Layer | Source CRS | ≤30 m cells | coarser cells |
|---|---|---|---|
| elevation | EPSG:4326 | bilinear | average |
| fuel code | EPSG:5070 | nearest | mode |
| land cover | EPSG:4326 | mode (10 m tiles) | mode (~100 m mosaic) |

Slope/aspect are derived **after** warping, on the metre grid (Horn 1981), with a one-cell pad so window edges use
real neighbours. Aspect = downslope azimuth from grid north; the grid north of EPSG:5070 differs from true north by
the meridian convergence (< ~4° here) — a documented approximation. A window is rejected (`LandscapeUnavailable`)
if < 98 % of a required layer is valid.

## Variables

| Variable | Status | Source |
|---|---|---|
| elevation, fuel model | required | SRTM, LANDFIRE |
| slope, aspect | derived | from elevation |
| land cover | optional (zeros if unavailable) | WorldCover |
| fire state | required | FIRMS footprint (inference) / simulation (training) |
| temperature, RH, wind u/v, precipitation | required | ERA5 (training) / Open-Meteo (inference) |
| soil moisture | optional | ERA5 swvl1 / Open-Meteo |
| dead fuel moisture | derived | EMC from T, RH |

Land cover is **not** used as a substitute for the fuel model; LANDFIRE FBFM40 remains the fuel input.

## Training dataset (`ml/datasets/generate.py`, config `ml/configs/dataset.yaml`)

1. Random ignition inside the study bbox; build the landscape for the band's cell size.
2. Random ERA5 start hour in Jun–Oct 2024/2025, accepted with probability ∝ Fosberg FFWI (over-samples fire
   weather on purpose — **not climatological**).
3. Run WTRS for `max(t0) + max(horizon)` hours; store landscape, arrival time and hourly weather per scenario.
4. For each `t0` and horizon: input mask = arrival ≤ t0, target = arrival ≤ t0 + h.
5. Validity: initial fire non-empty and target not within 2 cells of the window edge (truncation). Invalid samples
   are kept in the index with flags but never used.

Bands: short (30 m; t0 1/2/4 h; 10/30/60 min), medium (60 m; t0 2/6/12/24 h; 6/12 h), long (120 m;
t0 6/12/24/48 h; 24/48/72 h). 800 scenarios per band.

### Split (leakage control)

The study bbox is cut into 0.5° × 0.5° blocks (20 blocks); whole blocks are assigned to train / val (3) / test (4)
with a fixed seed. Overlapping time slices of one scenario therefore never cross splits, and the test set evaluates
generalisation to **unseen fire scenarios**. Landscapes are only partly unseen: blocks are assigned by *ignition*
location and the 128×128 windows (up to 15.4 km wide) cross block borders — 54 % of test windows overlap some training
window (audit, `docs/wtrs_dataset.md`). The evaluation therefore also reports a strict subset with zero window overlap
(2,308 samples); growth IoU differs by ≤ 0.007. There is no temporal hold-out (all splits use 2024–2025 weather).

Every scenario/sample row carries `simulation_source = WTRS`, `reference_engine = WTRS-Rothermel-MTT`,
`simulation_method`, `source_version`. Imported FARSITE/FlamMap runs become separate dataset versions
(`docs/farsite_flame_map_workflow.md`); the loader refuses mixed engines.

## Burned-area perimeters (MTBS / BAER / RAVG)

Used to list historical fires that can be replayed and to display their final perimeter as **context**. Replay
metrics are computed against the observed cumulative FIRMS footprint at t0 + h, not against these perimeters
(a final perimeter has no timing). Burn-severity mosaics are not used.
