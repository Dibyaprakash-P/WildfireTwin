import math

import numpy as np
import pandas as pd
import pytest

from geo import registry
from geo.firms import confidence_class, make_detection_id, normalize_dataframe
from geo.rasters import LANDFIRE_ORIGIN, AnalysisGrid
from geo.terrain import slope_aspect
from geo.weather import emc_simard, rh_from_dewpoint, wind_speed_dir, wind_uv


def test_slope_aspect_plane():
    # Plane rising toward the east by 1 m per 10 m: slope = atan(0.1), faces WEST (270 deg).
    yy, xx = np.mgrid[0:20, 0:20]
    dem = xx * 1.0
    s, a = slope_aspect(dem.astype(float), 10.0)
    assert np.allclose(s[2:-2, 2:-2], math.degrees(math.atan(0.1)), atol=1e-4)
    assert np.allclose(a[2:-2, 2:-2], 270.0, atol=1e-4)
    # Rising toward the north (row index decreasing) -> faces SOUTH (180 deg).
    s, a = slope_aspect((-yy * 1.0).astype(float), 10.0)
    assert np.allclose(a[2:-2, 2:-2], 180.0, atol=1e-4)


def test_flat_aspect_flag():
    _, a = slope_aspect(np.zeros((5, 5)), 30.0)
    assert (a == -1).all()


def test_grid_snapped_to_landfire_lattice():
    g = AnalysisGrid.centered(-123.1, 41.2, 60.0, 128)
    ox, oy = LANDFIRE_ORIGIN
    assert ((g.x0 - ox) / 30.0).is_integer()
    assert ((g.y0 - oy) / 30.0).is_integer()
    w, s, e, n = g.bounds_wgs84()
    assert w < -123.1 < e and s < 41.2 < n


def test_weather_conversions():
    assert rh_from_dewpoint(20.0, 20.0) == pytest.approx(100.0)
    assert 40 < float(rh_from_dewpoint(30.0, 15.0)) < 45
    spd, d = wind_speed_dir(0.0, -5.0)   # air moving south = wind FROM north
    assert spd == pytest.approx(5.0) and d == pytest.approx(0.0)
    u, v = wind_uv(5.0, 270.0)           # from west -> blowing east
    assert u == pytest.approx(5.0) and abs(v) < 1e-9
    assert emc_simard(30, 10) < emc_simard(30, 60)


def test_firms_normalization():
    df = pd.DataFrame({
        "latitude": [40.5, 40.5, 95.0, 41.0], "longitude": [-123.0, -123.0, -123.0, -122.5],
        "brightness": [330, 330, 300, 310], "scan": [0.4] * 4, "track": [0.4] * 4,
        "acq_date": ["2026-09-30"] * 4, "acq_time": ["104", "104", "1200", "2359"],
        "satellite": ["N20"] * 4, "instrument": ["VIIRS"] * 4, "confidence": ["h", "h", "n", "l"],
        "version": ["2.0NRT"] * 4, "bright_t31": [290] * 4, "frp": [5.0, 5.0, 1.0, 2.0], "daynight": ["D"] * 4,
    })
    out, rep = normalize_dataframe(df, "test")
    assert rep["dropped_malformed"] == 1 and rep["dropped_duplicates"] == 1 and len(out) == 2
    assert out.iloc[0]["acq_datetime"].hour == 1 and out.iloc[0]["acq_datetime"].minute == 4
    assert out.iloc[0]["confidence_class"] == "high"
    assert out["detection_id"].iloc[0] == make_detection_id("N20", "2026-09-30T01:04Z", 40.5, -123.0)


def test_modis_confidence_classes():
    assert confidence_class("15") == "low" and confidence_class("50") == "nominal" and confidence_class(85) == "high"


landfire = registry.path(registry.sources()["landfire_fbfm40"]["path"])


@pytest.mark.skipif(not landfire.exists(), reason="local rasters not present")
def test_landscape_coregistered():
    from geo.landscape import build_landscape
    g = AnalysisGrid.centered(-123.2, 41.0, 60.0, 64)
    L = build_landscape(g)
    for arr in L.stack().values():
        assert arr.shape == (64, 64)
    assert np.isfinite(L.elevation_m).all()
    assert all(e["dst_crs"] == "EPSG:5070" for e in L.transforms.entries)
    assert any(e["reprojected"] for e in L.transforms.entries)   # SRTM 4326 -> 5070 is logged


@pytest.mark.skipif(not landfire.exists(), reason="local rasters not present")
def test_landscape_outside_coverage_raises():
    from geo.landscape import LandscapeUnavailable, build_landscape
    with pytest.raises(LandscapeUnavailable):
        build_landscape(AnalysisGrid.centered(-100.0, 35.0, 60.0, 32))
