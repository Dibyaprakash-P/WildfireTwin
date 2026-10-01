import json

import numpy as np
import pytest

from geo.rasters import AnalysisGrid
from geo.overlay import write_geotiff
from simulation.converters.importers import ImportErrorInvalid, import_arrival_raster, import_perimeters


def test_arrival_raster_roundtrip_hours(tmp_path):
    g = AnalysisGrid("EPSG:5070", -2300000.0, 2400000.0, 60.0, 16)
    arr = np.full((16, 16), -9999.0, np.float32)
    arr[4:8, 4:8] = 1.5           # hours
    p = tmp_path / "toa.tif"
    write_geotiff(p, arr, g, nodata=-9999.0)
    sim = import_arrival_raster(p, "hours", "FARSITE")
    assert sim.meta["data_class"] == "simulated" and sim.meta["simulator"] == "FARSITE"
    assert sim.meta["burned_cells"] == 16
    assert np.allclose(sim.arrival_min[4:8, 4:8], 90.0) and (sim.arrival_min[0] == -1).all()


def test_arrival_raster_requires_crs(tmp_path):
    import rasterio
    p = tmp_path / "nocrs.tif"
    with rasterio.open(p, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32") as d:
        d.write(np.zeros((4, 4), np.float32), 1)
    with pytest.raises(ImportErrorInvalid):
        import_arrival_raster(p, "minutes", "FlamMap")


def test_perimeters_earliest_time_wins(tmp_path):
    def sq(x0, y0, d):
        return {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + d, y0], [x0 + d, y0 + d], [x0, y0 + d], [x0, y0]]]}
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"ElapsedT": 2}, "geometry": sq(-123.02, 41.0, 0.04)},
        {"type": "Feature", "properties": {"ElapsedT": 1}, "geometry": sq(-123.01, 41.01, 0.02)},
    ]}
    p = tmp_path / "perims.geojson"
    p.write_text(json.dumps(fc))
    sim = import_perimeters(p, "ElapsedT", "hours", "FARSITE", cell_m=100.0)
    vals = set(np.unique(sim.arrival_min).tolist())
    assert vals == {-1.0, 60.0, 120.0}
    with pytest.raises(ImportErrorInvalid):
        import_perimeters(p, "missing", "hours", "FARSITE")
