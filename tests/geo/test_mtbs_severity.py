"""MTBS thematic burn-severity preprocessing (synthetic archives shaped like the real MTBS mosaics).

The real mosaics are single-band uint8 GeoTIFFs in EPSG:5070 (30 m, nodata 0) with an FGDC XML whose
eainfo/edom entries define classes 0-6. These tests build small archives of that shape in a temporary directory,
so they run without the real data and with any year missing.
"""
import copy
import zipfile

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from geo import mtbs_severity as ms
from geo import registry
from geo.rasters import LANDFIRE_ORIGIN, AnalysisGrid
from ml.evaluation.severity_context import class_roles, severity_context

CLASSES = {0: "Background/No Data", 1: "Unburned/Underburned to Low Burn Severity", 2: "Low burn severity",
           3: "Moderate burn severity", 4: "High Burn Severity", 5: "Increased Greenness/Increased Vegetation Response",
           6: "Non-Processing Area Mask"}
BBOX = (-123.01, 40.99, -122.99, 41.01)   # ~1.7 km study region keeps the arrays tiny


def xml_doc(classes=CLASSES) -> bytes:
    edoms = "".join(f"<attrdomv><edom><edomv>{v}</edomv><edomvd>{d}</edomvd><edomvds>Producer defined</edomvds></edom></attrdomv>"
                    for v, d in classes.items())
    return (f"<?xml version='1.0' encoding='UTF-8'?><metadata><idinfo><citation><citeinfo><origin>U.S. Geological Survey</origin>"
            f"<pubdate>20260918</pubdate><title>MTBS Thematic Burn Severity Mosaic test</title>"
            f"<onlink>https://doi.org/10.5066/P9NETC0T</onlink></citeinfo></citation></idinfo>"
            f"<eainfo><detailed><attr><attrlabl>Value</attrlabl>{edoms}</attr></detailed>"
            f"<overview><eaover>Thresholded from dNBR by MTBS analysts.</eaover></overview></eainfo></metadata>").encode()


def aligned_source(pad_cells: int = 20):
    """EPSG:5070 30 m raster on the LANDFIRE lattice covering BBOX (+pad) with a class pattern."""
    xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", "EPSG:5070", *BBOX, densify_pts=21)
    ox, oy = LANDFIRE_ORIGIN
    x0 = ox + np.floor((xmin - ox) / 30) * 30 - pad_cells * 30
    y1 = oy + np.ceil((ymax - oy) / 30) * 30 + pad_cells * 30
    w = int((xmax - x0) / 30) + 2 * pad_cells + 2
    h = int((y1 - ymin) / 30) + 2 * pad_cells + 2
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 7, size=(h, w), dtype=np.uint8)
    arr[:5, :] = 0                                       # some background / nodata
    return arr, from_origin(x0, y1, 30, 30), "EPSG:5070"


def write_zip(path, year, arr, transform, crs, nodata=0, with_tif=True, with_xml=True, xml=None, colormap=True):
    tif = path.parent / f"mtbs_CA_{year}.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8",
                       crs=crs, transform=transform, nodata=nodata) as ds:
        ds.write(arr, 1)
        if colormap:
            ds.write_colormap(1, {0: (0, 0, 0, 0), 1: (0, 128, 128, 255), 4: (168, 0, 0, 255)})
    with zipfile.ZipFile(path, "w") as z:
        if with_tif:
            z.write(tif, tif.name)
        if with_xml:
            z.writestr(f"mtbs_CA_{year}.xml", xml or xml_doc())
    tif.unlink()
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    cfg = copy.deepcopy(registry.sources())
    cfg["study_region"]["bbox_wgs84"] = list(BBOX)
    cfg["mtbs"]["severity_mosaic_zips"] = str(raw / "mtbs_CA_*.zip")
    cfg["mtbs"]["severity_years"] = [2021, 2022, 2023]
    cfg["mtbs"]["processed_severity_dir"] = str(tmp_path / "processed")
    cfg["mtbs"]["severity_report"] = str(tmp_path / "report.json")
    monkeypatch.setattr(registry, "sources", lambda: cfg)
    return raw


def test_zip_discovery_ignores_unrelated_files(env):
    arr, tr, crs = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    write_zip(env / "mtbs_CA_2023.zip", 2023, arr, tr, crs)
    (env / "burn_severity_perimeter_data.zip").write_bytes(b"PK")
    assert sorted(ms.discover_archives()) == [2021, 2023]


def test_class_definitions_come_from_xml():
    assert ms.parse_class_definitions(xml_doc()) == CLASSES
    roles = class_roles(CLASSES, nodata=0)
    assert roles["burned_low_to_high"] == [2, 3, 4]
    assert roles["non_processing"] == [6]
    assert 0 not in roles["mapped"] and 6 not in roles["mapped"]


def test_metadata_extraction_and_crs_detection(env, tmp_path):
    arr, tr, crs = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    meta = ms.inspect_archive(ms.discover_archives()[2021], tmp_path / "work")
    assert meta["epsg"] == 5070 and meta["dtype"] == "uint8" and meta["bands"] == 1 and meta["nodata"] == 0
    assert meta["resolution"] == [30.0, 30.0]
    assert meta["class_definitions"]["4"] == "High Burn Severity"
    st = meta["stats"]
    assert st["pixels"] == arr.size and st["nodata_pixels"] == int((arr == 0).sum())
    assert st["valid_pixels"] == int((arr != 0).sum())


def test_archive_without_raster_is_reported_not_hidden(env):
    arr, tr, crs = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs, with_tif=False)
    rec = ms.process_year(2021, ms.discover_archives())
    assert rec["status"] == "failed"
    assert "MTBS 2021 archive found but contains no GeoTIFF" in rec["message"]
    assert not ms.output_path(2021).exists()


def test_raster_without_crs_fails_validation(env):
    arr, tr, _ = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, None)
    rec = ms.process_year(2021, ms.discover_archives())
    assert rec["status"] == "failed" and "raster validation failed" in rec["message"] and "CRS" in rec["message"]


def test_undefined_values_fail_validation(env):
    arr, tr, crs = aligned_source()
    arr[10, 10] = 9
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    rec = ms.process_year(2021, ms.discover_archives())
    assert rec["status"] == "failed" and "undefined values [9]" in rec["message"]


def test_aligned_clip_is_exact_copy_with_nodata_and_classes_preserved(env):
    arr, tr, crs = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    rec = ms.process_year(2021, ms.discover_archives())
    assert rec["status"] == "processed", rec["message"]
    assert rec["study_region_intersection"]["pixel_aligned_copy"] is True
    with rasterio.open(ms.output_path(2021)) as o:
        out = o.read(1)
        assert o.crs.to_epsg() == 5070 and o.res == (30.0, 30.0) and o.nodata == 0 and o.dtypes[0] == "uint8"
        # exact copy of the source window covering the output
        c0 = int(round((o.transform.c - tr.c) / 30)); r0 = int(round((tr.f - o.transform.f) / 30))
        np.testing.assert_array_equal(out, arr[r0:r0 + o.height, c0:c0 + o.width])
        assert o.tags(1)["CLASS_3"] == "Moderate burn severity" and o.tags()["RESAMPLING"] == "nearest"
        # clipped to (snapped) study region
        xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", "EPSG:5070", *BBOX, densify_pts=21)
        assert o.bounds.left <= xmin < o.bounds.left + 30 and o.bounds.right - 30 < xmax <= o.bounds.right
    assert rec["valid_pixel_count"] + rec["nodata_pixel_count"] == out.size
    assert set(np.unique(out)) <= set(CLASSES)


def test_reprojection_from_geographic_source_keeps_categories(env):
    # EPSG:4326 categorical source -> EPSG:5070; nearest neighbour must not create new values
    w, s, e, n = BBOX
    res = 0.0004
    tr = from_origin(w - 0.01, n + 0.01, res, res)
    h, wd = int((n - s + 0.02) / res), int((e - w + 0.02) / res)
    arr = np.where((np.indices((h, wd)).sum(0) // 7) % 2 == 0, 2, 4).astype(np.uint8)
    write_zip(env / "mtbs_CA_2022.zip", 2022, arr, tr, "EPSG:4326")
    rec = ms.process_year(2022, ms.discover_archives())
    assert rec["status"] == "processed", rec["message"]
    assert rec["transforms"][0]["reprojected"] and rec["transforms"][0]["resampling"] == "nearest"
    with rasterio.open(ms.output_path(2022)) as o:
        assert o.crs.to_epsg() == 5070
        assert set(np.unique(o.read(1))) <= {2, 4}          # no interpolated (e.g. 3) values


def test_coarse_window_uses_mode_not_interpolation(env):
    arr, tr, crs = aligned_source()
    arr[:] = 2
    arr[::2, ::2] = 4                                     # 25 % class 4 -> mode must stay 2, never 3
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    assert ms.process_year(2021, ms.discover_archives())["status"] == "processed"
    lon, lat = (BBOX[0] + BBOX[2]) / 2, (BBOX[1] + BBOX[3]) / 2
    sev30, info30 = ms.severity_window(2021, AnalysisGrid.centered(lon, lat, 30, 16))
    sev120, info120 = ms.severity_window(2021, AnalysisGrid.centered(lon, lat, 120, 4))
    assert info30["resampling"] == "nearest" and info120["resampling"] == "mode"
    assert set(np.unique(sev30)) <= {2, 4}
    assert set(np.unique(sev120)) == {2}
    assert info120["classes"][4] == "High Burn Severity"


def test_no_intersection_and_missing_year_do_not_stop_other_years(env):
    arr, tr, crs = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    far = from_origin(-1_000_000, 1_000_000, 30, 30)       # far outside the study region
    write_zip(env / "mtbs_CA_2023.zip", 2023, arr, far, crs)
    rep = ms.run()
    by = {r["year"]: r for r in rep["years"]}
    assert by[2021]["status"] == "processed"
    assert by[2022]["status"] == "missing" and by[2022]["message"] == "MTBS 2022 raw file not found"
    assert by[2023]["status"] == "no_intersection"
    assert by[2023]["message"] == "MTBS 2023 does not intersect the WildfireTwin model domain"
    assert by[2021]["source_sha256"] and by[2021]["processing_version"] == ms.PROCESSING_VERSION


def test_inventory_status_reflects_real_processing_state(env):
    assert ms.inventory_status()[0] == "Missing"
    arr, tr, crs = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, crs)
    assert ms.inventory_status()[0] == "Available — raw only"            # no report yet
    ms.run()
    status, detail = ms.inventory_status()
    assert status == "Available — processed" and detail["processed_years"] == [2021]
    ms.output_path(2021).unlink()                                         # report says processed, file gone
    assert ms.inventory_status()[0] == "Available — raw only"


def test_inventory_status_failed(env):
    arr, tr, _ = aligned_source()
    write_zip(env / "mtbs_CA_2021.zip", 2021, arr, tr, None)
    ms.run()
    assert ms.inventory_status()[0] == "Available — preprocessing failed"


def test_severity_context_is_context_not_accuracy():
    sev = np.array([[0, 0, 2, 2],
                    [0, 3, 3, 4],
                    [6, 4, 4, 1],
                    [0, 0, 5, 1]], dtype=np.uint8)
    pred = np.zeros_like(sev, dtype=bool)
    pred[:2, :] = True                                  # 8 predicted cells: 3 background, 5 mapped
    c = severity_context(sev, CLASSES, 0, pred, cell_m=30.0)
    assert c["predicted_outside_final_extent_frac"] == pytest.approx(3 / 8, abs=1e-4)
    # final low..high pixels: 2,2,3,3,4,4,4 = 7; predicted among them: 2,2,3,3,4 = 5
    assert c["final_low_to_high_area_in_forecast_frac"] == pytest.approx(5 / 7, abs=1e-4)
    assert "Non-Processing Area Mask" not in c["final_severity_area_km2"]
    assert c["predicted_area_by_final_severity_km2"]["Outside final mapped extent"] == pytest.approx(3 * 900 / 1e6)
    # perimeter mask removes pixels of other fires in the same yearly mosaic
    fire = np.zeros_like(sev, dtype=bool)
    fire[:, 2:] = True
    c2 = severity_context(sev, CLASSES, 0, pred, 30.0, fire_mask=fire)
    assert c2["final_mapped_area_km2"] < c["final_mapped_area_km2"]
    assert not any(k in c for k in ("iou", "dice", "confusion_matrix"))
