"""Import -> separate dataset pipeline for external (FARSITE/FlamMap) runs.

The arrival raster here is a TEST FIXTURE written to a temp dir (never to data/); it is not presented as FARSITE output.
"""
import json

import numpy as np
import pandas as pd
import pytest

from geo import registry
from geo.overlay import write_geotiff
from geo.rasters import AnalysisGrid
from simulation.converters.importers import ImportErrorInvalid, arrival_to_frames

landfire = registry.path(registry.sources()["landfire_fbfm40"]["path"])
era5 = registry.path(registry.sources()["era5"]["processed"])


def _fixture_raster(tmp_path):
    g = AnalysisGrid.centered(-123.2, 41.0, 60.0, 64)
    yy, xx = np.mgrid[0:64, 0:64]
    arr = (np.hypot(yy - 32, xx - 32) * 20.0).astype(np.float32)   # minutes, radial growth
    arr[arr > 900] = -9999
    p = tmp_path / "fixture_arrival.tif"
    write_geotiff(p, arr, g, nodata=-9999.0)
    return p


def test_frames_are_exact_derivations():
    a = np.array([[0, 10, 30, -1]], np.float32)
    f = arrival_to_frames(a, [10, 30])
    assert f[10].tolist() == [[True, True, False, False]] and f[30].tolist() == [[True, True, True, False]]


@pytest.mark.skipif(not (landfire.exists() and era5.exists()), reason="local rasters/ERA5 not present")
def test_import_and_separate_dataset(tmp_path):
    from simulation.converters.build_dataset import build
    from simulation.converters.import_cli import load_index, run
    sim_root, out_root = tmp_path / "sims", tmp_path / "training"
    meta = run(_fixture_raster(tmp_path), "arrival_raster", "FlamMap", "minutes", "fixture01",
               ignition_time="2024-08-10T18:00", root=sim_root)
    assert meta["simulation_source"] == "FlamMap" and len(meta["source_sha256"]) == 64
    assert load_index(sim_root)[0]["name"] == "fixture01"
    res = build(["fixture01"], "test-v1", 60.0, [2.0], [360], "test", sim_root=sim_root, out_root=out_root)
    assert res["dataset_version"] == "flammap-test-v1" and res["samples"] == 1
    d = out_root / "flammap-test-v1"
    sa = pd.read_parquet(d / "samples.parquet")
    assert set(sa["simulation_source"]) == {"FlamMap"} and not sa["simulation_source"].str.contains("WTRS").any()
    man = json.loads((d / "manifest.json").read_text())
    assert man["provenance"]["is_farsite"] is False and man["simulator"] == "FlamMap"


def test_bad_name_rejected(tmp_path):
    from simulation.converters.import_cli import run
    with pytest.raises(ImportErrorInvalid):
        run(tmp_path / "x.tif", "arrival_raster", "FARSITE", "minutes", "bad name!", root=tmp_path)
