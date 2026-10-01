# FARSITE / FlamMap Workflow (offline, optional)

FARSITE and FlamMap are **external** fire-behaviour simulators. In WildfireTwin they are an optional, offline source of
reference simulations for benchmarking or for a separate training experiment. They are **not** the source of the
current training data (WTRS — see `docs/wtrs_dataset.md`) and are **never** needed by end users.

Current status (audit 2026-10-01): FlamMap 6 is installed on the development machine at `C:\Workspace\FlamMap6`
(it contains `farsite.dll` and `flammap.dll`). **No FARSITE/FlamMap outputs for the study area exist yet** — the only
FlamMap-format files on disk are FlamMap's bundled *Miller* tutorial inputs (Montana), which are not used. The Data
page therefore reports FARSITE/FlamMap outputs as **Not present** and the software separately as **Installed**.
(FlamMap 6 is a GUI application; this installation has no command-line runner, so runs are made by hand.)

## 1. Running FlamMap / FARSITE offline

1. **Landscape (.lcp):** build it for the study region from LANDFIRE (elevation, slope, aspect, FBFM40 fuel model,
   canopy cover/height/base height/bulk density) — e.g. with LANDFIRE's tools or FlamMap's *GetLandscape* utility
   shipped in the install folder. Using the same LANDFIRE edition (LF 2025) as WildfireTwin keeps fuels consistent.
2. **Weather / wind / fuel moisture:** use FlamMap's inputs (or *GetWeather*). To compare with WildfireTwin later,
   record the **UTC start time** of the run; the converter attaches local ERA5 weather for that time.
3. **Ignition:** a point/line/polygon ignition inside 40–42°N, 124.5–122°W (the model domain).
4. Run **FARSITE** (time-stepped growth) or **FlamMap MTT** (minimum travel time).

## 2. What to export

| Export | Format | Import kind | Notes |
|---|---|---|---|
| Arrival time (preferred) | GeoTIFF, or ESRI ASCII `.asc` **with its `.prj`** | `arrival_raster` | time since ignition; note the units shown in your run settings (minutes or hours) |
| Timed perimeters | zipped shapefile or GeoJSON | `perimeters` | needs an attribute holding **elapsed time since ignition**; give its name as `time_field` |

WildfireTwin does not assume FlamMap/FARSITE attribute names or units — you state them at import time. A raster
without CRS is rejected unless you pass the landscape CRS explicitly (`--crs`, e.g. `EPSG:5070` for LANDFIRE).
Time-stamped frames are derived exactly from the arrival field (`burned(t) = arrival ≤ t`); no other frame format
is assumed.

## 3. Where to put the files

`simulation/outputs/<your-run-name>/…` (git-ignored data stays local). Files that sit there but were not imported are
shown on the Data page as *Files present · not imported*.

## 4. How to import

* **Command line** (recommended for research runs):
  ```
  python -m simulation.converters.import_cli --file simulation/outputs/run01/arrival.tif \
      --kind arrival_raster --simulator FlamMap --units minutes --name run01 --ignition-time 2024-08-10T18:00
  ```
  → `data/simulations/IMPORT-run01/` (`arrival_min.tif`, `meta.json` with engine, SHA-256 of the source file, units,
  CRS origin) + `data/simulations/imported_index.json`.
* **Web UI:** *Simulation → Reference engine → [ Import FARSITE / FlamMap ]* (units are a required choice).
* **API:** `POST /api/simulations/import` (multipart `file`, `kind`, `simulator`, `units`, `time_field`).

Imported runs appear in the Results Viewer as `SIMULATED · FlamMap (imported)` / `FARSITE (imported)`.

## 5. Turning imports into training / evaluation data

```
python -m simulation.converters.build_dataset --runs run01 run02 --tag ncal-v1 --cell 60 \
    --t0-hours 2 6 12 --horizons 360 720 --split test
```
* Creates a **separate** dataset version `flammap-ncal-v1` / `farsite-ncal-v1` with the same sample format as WTRS.
* The arrival field is resampled onto a 128×128 grid around the earliest-burning cells (MIN resampling = earliest
  arrival per cell); the landscape comes from the same SRTM/LANDFIRE/WorldCover layers; weather channels come from
  ERA5 at the recorded start time — **an explicit assumption that the run used comparable weather**, stored in the
  manifest.
* Default split is `test`: imported runs act as an **independent benchmark** for models trained on WTRS. Use
  `--split train` only for a deliberate, separately named FARSITE experiment.
* Evaluate with the existing pipeline by pointing a config's `dataset_version` at the new dataset.

## 6. Keeping FARSITE/FlamMap and WTRS apart

* Every scenario and sample carries `simulation_source` (`WTRS` / `FARSITE` / `FlamMap`) and `reference_engine`.
* Dataset versions are named after their engine; the converter refuses to write a `wtrs-*` name.
* `WildfireDataset` raises an error if a dataset mixes engines.
* Models record their training dataset card (`training_data` in `summary.json` / the checkpoint); the Models page shows
  *Training data* and *Reference method* per model.
* A future "FNO surrogate of FARSITE" is therefore a distinct experiment with its own dataset version, runs and
  results — not a relabelling of WTRS.

## 7. End users stay independent of FlamMap

The web application, Docker images and inference path never call FlamMap/FARSITE. On-demand reference runs in the
app use the in-repo WTRS engine (pure Python); imported FARSITE/FlamMap results are just stored rasters. Users need
only a browser.
