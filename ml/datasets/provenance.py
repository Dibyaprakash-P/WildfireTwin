"""Reference-simulation provenance for training datasets.

Every dataset version records which engine produced its targets. WTRS samples are labelled
`simulation_source = "WTRS"` / `reference_engine = "WTRS-Rothermel-MTT"`; samples converted from imported
FARSITE/FlamMap runs live in a SEPARATE dataset version with `simulation_source = "FARSITE"` or `"FlamMap"`.
Datasets from different engines are never mixed by the loader.
"""

from __future__ import annotations

import json
from pathlib import Path

from geo import registry

WTRS_PROVENANCE = {
    "simulation_source": "WTRS",
    "reference_engine": "WTRS-Rothermel-MTT",
    "simulation_method": ("Rothermel (1972) surface rate of spread with Scott & Burgan (2005) FBFM40 fuels, "
                          "Anderson (1983) elliptical shape, minimum-travel-time growth (time-dependent Dijkstra, "
                          "16-neighbour stencil), hourly ERA5 weather"),
    "source_version": "1.0.0",
    "data_class": "simulated",
    "is_farsite": False,
}

PROVENANCE_COLUMNS = ["simulation_source", "reference_engine", "simulation_method", "source_version"]


def dataset_dir(version: str) -> Path:
    return registry.path(f"data/processed/training/{version}")


def dataset_card(version: str) -> dict | None:
    """Training-data description used by model metadata, the Models page and the audit."""
    d = dataset_dir(version)
    mp = d / "manifest.json"
    if not mp.exists():
        return None
    man = json.loads(mp.read_text())
    cfg = man.get("config", {})
    prov = man.get("provenance") or {
        # manifests written before provenance fields existed: derive from the recorded simulator name
        **(WTRS_PROVENANCE if str(man.get("simulator", "")).startswith("WTRS") else {}),
        "simulation_source": man.get("simulator", "unknown"),
    }
    bands = cfg.get("bands", {})
    w = cfg.get("weather", {})
    return {
        "dataset_name": man.get("dataset_version", version).replace("-", "_"),
        "dataset_version": man.get("dataset_version", version),
        **{k: prov.get(k) for k in ("simulation_source", "reference_engine", "simulation_method", "source_version")},
        "data_class": man.get("data_class", "simulated"),
        "region": registry.sources()["study_region"]["name"],
        "region_bbox_wgs84": registry.sources()["study_region"]["bbox_wgs84"],
        "temporal_coverage": (f"ERA5 weather, years {w.get('years')}, months {w.get('months')}"
                              if w else "Not documented in current implementation"),
        "spatial_resolution_m": sorted({b.get("cell_m") for b in bands.values()}) if bands else None,
        "grid_size": cfg.get("grid_size"),
        "forecast_horizons_min": sorted({h for b in bands.values() for h in b.get("horizons_min", [])}),
        "target_variable": "burned mask at t0 + horizon (arrival time <= t0 + h) from the reference simulation",
        "split": "spatial blocks of {}° (ignition location); see docs/wtrs_dataset.md for window-overlap caveat".format(
            cfg.get("split", {}).get("block_deg", "?")),
    }


def add_provenance_columns(version: str) -> dict:
    """Non-destructively add provenance columns to an existing WTRS dataset (rows and values unchanged)."""
    import pandas as pd
    d = dataset_dir(version)
    out = {}
    for name in ("scenarios", "samples"):
        p = d / f"{name}.parquet"
        df = pd.read_parquet(p)
        if "simulator" in df.columns and not df["simulator"].astype(str).str.startswith("WTRS").all():
            raise ValueError(f"{name}: non-WTRS simulator values present; refusing to label as WTRS")
        if all(c in df.columns for c in PROVENANCE_COLUMNS):
            out[name] = "already present"
            continue
        backup = d / f"{name}.pre_provenance.parquet"
        if not backup.exists():
            df.to_parquet(backup, index=False)
        n0 = len(df)
        for c in PROVENANCE_COLUMNS:
            df[c] = WTRS_PROVENANCE[c]
        assert len(df) == n0
        df.to_parquet(p, index=False)
        out[name] = f"added {PROVENANCE_COLUMNS} to {n0} rows (backup {backup.name})"
    mp = d / "manifest.json"
    man = json.loads(mp.read_text())
    if "provenance" not in man:
        man["provenance"] = WTRS_PROVENANCE
        mp.write_text(json.dumps(man, indent=2, default=str))
        out["manifest"] = "provenance block added"
    return out


if __name__ == "__main__":
    import sys
    print(add_provenance_columns(sys.argv[1] if len(sys.argv) > 1 else "wtrs-ncal-v1"))
