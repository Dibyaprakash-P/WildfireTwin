"""Subset local ERA5 GRIB files to the study region and write one hourly NetCDF.

Usage:  python -m scripts.preprocess_era5
"""

from __future__ import annotations

import json
import logging
import time

import xarray as xr

from geo import registry
from geo.weather import derive_era5_fields, extract_era5_region

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    cfg = registry.sources()["era5"]
    bbox = registry.study_bbox()
    parts = []
    for f in cfg["files"]:
        t0 = time.time()
        ds = extract_era5_region(registry.path(f["path"]), bbox)
        logging.info("ERA5 %s: %s in %.1fs", f["path"], dict(ds.sizes), time.time() - t0)
        parts.append(ds)
    raw = xr.concat(parts, dim="time").sortby("time")
    raw = raw.isel(time=~raw.get_index("time").duplicated())
    out = derive_era5_fields(raw)
    dst = registry.path(cfg["processed"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_netcdf(dst)
    meta = {
        "output": cfg["processed"],
        "time_min": str(out.time.values.min()), "time_max": str(out.time.values.max()),
        "n_times": int(out.sizes["time"]),
        "lat": [float(out.latitude.min()), float(out.latitude.max())],
        "lon": [float(out.longitude.min()), float(out.longitude.max())],
        "grid_deg": 0.25,
        "variables": {k: out[k].attrs.get("units") for k in out.data_vars},
        "nan_fraction": {k: float(out[k].isnull().mean()) for k in out.data_vars},
    }
    registry.path("data/metadata/era5_preprocess_report.json").write_text(json.dumps(meta, indent=2))
    logging.info("wrote %s", dst)


if __name__ == "__main__":
    main()
