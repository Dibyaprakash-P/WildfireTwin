import numpy as np
from PIL import Image

from geo.overlay import front_png, probability_png
from geo.rasters import AnalysisGrid

G = AnalysisGrid("EPSG:5070", -2300000.0, 2400000.0, 60.0, 64)


def test_front_is_outer_boundary_only(tmp_path):
    prob = np.zeros((64, 64), np.float32)
    prob[16:48, 16:48] = 0.9
    prob[28:36, 28:36] = 0.1          # interior hole (e.g. non-burnable cells)
    front_png(tmp_path / "f.png", prob, G)
    a = np.asarray(Image.open(tmp_path / "f.png"))[..., 3]
    h, w = a.shape
    assert a[h // 2, w // 2] == 0       # no front drawn around the interior hole
    assert a.max() > 200                # outer edge drawn


def test_probability_png_transparent_below_threshold(tmp_path):
    prob = np.zeros((64, 64), np.float32)
    prob[:, 32:] = 1.0
    probability_png(tmp_path / "p.png", prob, G)
    a = np.asarray(Image.open(tmp_path / "p.png"))[..., 3]
    # middle rows only: the EPSG:5070 window is slightly rotated in lon/lat, so the PNG corners lie outside it
    mid = a[a.shape[0] // 2 - 4: a.shape[0] // 2 + 4]
    w = mid.shape[1]
    assert mid[:, w // 8: 3 * w // 8].max() == 0 and mid[:, 5 * w // 8: 7 * w // 8].min() > 0


def test_hillshade_tile_inside_and_outside_coverage():
    from backend.app.api.terrain import _hillshade
    png = _hillshade(11, 638, 557)      # Trinity River area, inside SRTM coverage
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert _hillshade(3, 0, 0) is None  # far outside coverage -> no data, nothing invented
