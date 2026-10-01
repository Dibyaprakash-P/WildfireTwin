# FARSITE (offline, optional)

FARSITE is **not** a runtime dependency of WildfireTwin. It is an optional offline source of reference simulations.

## Producing a compatible output
1. Build a landscape (`.lcp`) for the area of interest from LANDFIRE (elevation, slope, aspect, FBFM40, canopy).
2. Run FARSITE with the desired weather/wind streams and ignition.
3. Export the **Time of Arrival** grid (GeoTIFF, or ESRI ASCII `.asc` with its `.prj`) and/or the timed
   **perimeters** shapefile.

## Importing
* Web UI: *Simulation → Import Simulation Result* (simulator = FARSITE).
* API: `POST /api/simulations/import` (multipart: `file`, `kind=arrival_raster|perimeters`, `simulator=FARSITE`,
  `units=minutes|hours`, `time_field` for perimeters).
* Python: `simulation.converters.importers.import_arrival_raster(...)` / `import_perimeters(...)`.

Imported results are stored under `data/simulations/<id>/` and labelled `data_class = "simulated"`,
`simulator = "FARSITE"`. They are reference simulations — not observed ground truth.

## Using FARSITE outputs for training
Convert each run into the scenario format of `ml/datasets/generate.py` (landscape arrays + `arrival_min` +
hourly weather) and add it to a new dataset version; the dataset/trainer code is simulator-agnostic.

Full workflow (export → `python -m simulation.converters.import_cli` → `python -m simulation.converters.build_dataset`
→ separate engine-named dataset version): [`docs/farsite_flame_map_workflow.md`](../../docs/farsite_flame_map_workflow.md).
WTRS (the current training data) is produced by the internal Rothermel + MTT engine, not by this tool.
