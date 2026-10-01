# Data Inventory

_Generated 2026-10-01T17:16:40Z by `python -m scripts.inventory_data` from file metadata._

Raw files remain in `datasets/` exactly as downloaded (nothing moved or copied). Processed products live in `data/processed/`.

## NASA FIRMS VIIRS NOAA-20 (J1V-C2)

| field | value |
|---|---|
| type | Active fire (point detections) |
| status | Available |
| date range | 2019 – 2026-09-30 |
| spatial resolution | 375 m pixel |
| crs | EPSG:4326 (WGS84 points) |
| format | CSV (9 files, 12.70 GB) |
| local path | datasets/DL_FIRE_J1V-C2_* |
| purpose | Active-fire monitoring, inference fire-state initialisation, historical replay comparison (not a training input) |
| preprocessing | Normalised + de-duplicated to Parquet (region subset and 10-day global NRT) |
| data class | observed |
| notes | Region subset: 602,529 detections (2010-01-22 – 2026-09-30); global recent: 1,617,350 (2026-09-21 – 2026-09-30) |

## NASA FIRMS VIIRS NOAA-21 (J2V-C2)

| field | value |
|---|---|
| type | Active fire (point detections) |
| status | Available |
| date range | 2024 – 2026-09-30 |
| spatial resolution | 375 m pixel |
| crs | EPSG:4326 (WGS84 points) |
| format | CSV (3 files, 4.39 GB) |
| local path | datasets/DL_FIRE_J2V-C2_* |
| purpose | Active-fire monitoring, inference fire-state initialisation, historical replay comparison (not a training input) |
| preprocessing | Normalised + de-duplicated to Parquet (region subset and 10-day global NRT) |
| data class | observed |

## NASA FIRMS MODIS Terra/Aqua (M-C61)

| field | value |
|---|---|
| type | Active fire (point detections) |
| status | Available |
| date range | 2010 – 2026-09-30 |
| spatial resolution | 1000 m pixel |
| crs | EPSG:4326 (WGS84 points) |
| format | CSV (10 files, 3.03 GB) |
| local path | datasets/DL_FIRE_M-C61_* |
| purpose | Active-fire monitoring, inference fire-state initialisation, historical replay comparison (not a training input) |
| preprocessing | Normalised + de-duplicated to Parquet (region subset and 10-day global NRT) |
| data class | observed |

## NASA FIRMS VIIRS Suomi NPP (SV-C2)

| field | value |
|---|---|
| type | Active fire (point detections) |
| status | Available |
| date range | 2012 – 2026-09-30 |
| spatial resolution | 375 m pixel |
| crs | EPSG:4326 (WGS84 points) |
| format | CSV (14 files, 20.81 GB) |
| local path | datasets/DL_FIRE_SV-C2_* |
| purpose | Active-fire monitoring, inference fire-state initialisation, historical replay comparison (not a training input) |
| preprocessing | Normalised + de-duplicated to Parquet (region subset and 10-day global NRT) |
| data class | observed |

## ECMWF ERA5 hourly single levels

| field | value |
|---|---|
| type | Weather reanalysis (gridded) |
| status | Available |
| date range | 2024-01-01 – 2025-12-31 |
| spatial resolution | 0.25° (~25 km), hourly |
| crs | EPSG:4326 regular lat/lon |
| format | GRIB (2 files, 710.5 MB) |
| local path | datasets/<cds-request-id>/data.grib |
| purpose | Historical weather for reference simulations, training and replay |
| preprocessing | Subset to [39.75, 42.0]N [-124.5, -121.75]E; K→°C, Td→RH, m→mm; NetCDF data/processed/weather/era5_ncal_hourly.nc |
| data class | observed |
| notes | Variables: 10u, 10v, 2t, 2d, tp, swvl1, lai_hv, lai_lv, cvh, cvl, avg_tprate (California extent 32.5–42N, 124.5–114.25W). |

## NASA SRTM v3 1 arc-second

| field | value |
|---|---|
| type | Digital elevation model |
| status | Available |
| date range | 2000 (mission) |
| spatial resolution | 1″ (~30 m) |
| crs | EPSG:4326 |
| format | GeoTIFF int16 (6 tiles, 155.8 MB) |
| local path | datasets/n4*_w12*_1arc_v3.tif |
| purpose | Elevation; derived slope and aspect; 3D terrain tiles |
| preprocessing | Mosaic → per-window warp to EPSG:5070 (bilinear/average); Horn slope/aspect |
| data class | observed |
| notes | Tiles cover 40–42°N, 125–122°W; nodata -32767.0 |

## LANDFIRE 2025 FBFM40

| field | value |
|---|---|
| type | Surface fuel model (Scott & Burgan 40) |
| status | Available |
| date range | LF 2025 (version LF2025) |
| spatial resolution | 30 m |
| crs | EPSG:5070 |
| format | GeoTIFF int16 + VAT (160.4 MB) |
| local path | datasets/landfire_1971d627-499d-41ea-8e91-bc3f3256ac1a/LF2025_FBFM40_CONUS/LF2025_FBFM40_CONUS.tif |
| purpose | Fire-behaviour fuel model input (Rothermel) and model features |
| preprocessing | Native grid; nearest (30 m) or mode (60/120 m) aggregation |
| data class | observed |
| notes | Extent 40–42°N, 124.5–122°W (download box). Defines the model domain. |

## ESA WorldCover 2021 v200

| field | value |
|---|---|
| type | Land cover (11 classes) |
| status | Available |
| date range | 2021 |
| spatial resolution | 10 m nominal (8.33e-05°) |
| crs | EPSG:4326 |
| format | GeoTIFF uint8 (2 tiles, 86.7 MB) |
| local path | datasets/terrascope_download_*/WORLDCOVER/... |
| purpose | Descriptive land-cover input (not a fuel-model substitute) |
| preprocessing | Mode resampling to grid; ~100 m mosaic for coarse windows |
| data class | observed |
| notes | Tiles N39W123, N39W126 (39–42°N, 126–120°W) |

## MTBS / burned-area perimeters (MTBS, BAER, RAVG, CBI)

| field | value |
|---|---|
| type | Burned-area perimeters (vector) |
| status | Available |
| date range | 1984-07-02 – 2026-08-05 |
| spatial resolution | vector (Landsat-derived, 30 m) |
| crs | EPSG:4269 (NAD83 geographic) |
| format | Zipped shapefile (660.9 MB) |
| local path | datasets/bsp_zmysxvwg6simrvuefqrx/burn_severity_perimeter_data.zip |
| purpose | Historical-fire catalogue and final-perimeter context (not used for metrics or training) |
| preprocessing | BBox-filtered 918 perimeters → GeoJSON (pure-Python shapefile reader) |
| data class | observed |

## MTBS thematic burn-severity mosaics (California)

| field | value |
|---|---|
| type | Burn severity raster |
| status | Available (not yet used) |
| date range | 2020 – 2025 |
| spatial resolution | 30 m |
| crs | see embedded metadata |
| format | Zipped GeoTIFF (6 files, 31.5 MB) |
| local path | datasets/bsp_*/mtbs_CA_<year>.zip |
| purpose | Potential severity validation |
| preprocessing | none |
| data class | observed |

## Open-Meteo Forecast API

| field | value |
|---|---|
| type | Current + forecast weather (NWP) |
| status | Online (no key) |
| date range | past 3 days + 4-day forecast |
| spatial resolution | model-dependent (best match, ~1–11 km) |
| crs | EPSG:4326 |
| format | JSON API |
| local path | — |
| purpose | Live weather for predictions, monitoring and alerts |
| preprocessing | Cached 15 min; snapshots in MongoDB weather_conditions |
| data class | observed |

## WTRS reference simulations (wtrs-ncal-v1)

| field | value |
|---|---|
| type | Simulated fire-spread dataset |
| status | Generated |
| date range | ERA5 2024–2025 fire seasons (Jun–Oct) |
| spatial resolution | 30 / 60 / 120 m, 128×128 |
| crs | EPSG:5070 |
| format | NPZ per scenario + Parquet index |
| local path | data/processed/training/wtrs-ncal-v1 |
| purpose | Training / validation / test of U-Net, FNO, PI-FNO |
| preprocessing | 2400 scenarios, 22505 valid samples; spatial-block split |
| data class | simulated |
| notes | Internal Rothermel + MTT reference simulator (not FARSITE/FlamMap); FFWI-weighted start-time sampling. |

## FARSITE / FlamMap outputs

| field | value |
|---|---|
| type | External reference simulations |
| status | Not present |
| date range | — |
| spatial resolution | — |
| crs | — |
| format | arrival-time raster or timed perimeters |
| local path | simulation/outputs/ (import via CLI, UI or API) |
| purpose | Optional reference / benchmark data |
| preprocessing | simulation/converters/importers.py |
| data class | simulated |
