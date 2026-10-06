"""MTBS thematic burn-severity mosaics: inspection, preprocessing and window extraction.

Product (confirmed from the files, see docs/data_pipeline.md): one categorical band per year, uint8, classes
defined in the FGDC XML shipped inside each ZIP (`eainfo/attr/attrdomv/edom`). Class meanings are parsed from
that XML — never hard-coded. MTBS thresholds the classes per fire from dNBR (or NBR) by analyst interpretation,
so there are no global thresholds and the values must stay categorical:

  * resampling is NEAREST at 30 m (the mosaics share the LANDFIRE 30 m lattice in EPSG:5070, so the clip is an
    exact pixel copy) and MODE when aggregating to the 60 / 120 m analysis grids — never bilinear/average;
  * no categorical → continuous conversion.

Role in WildfireTwin: OBSERVED post-fire context for historical replays. MTBS severity is NOT a training target
or input channel and does not replace WTRS (Rothermel + MTT) targets. It has no time dimension, so it is never
used to score spread at a forecast horizon.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds

from geo import registry
from geo.rasters import LANDFIRE_ORIGIN, AnalysisGrid, TransformLog

log = logging.getLogger(__name__)

PROCESSING_VERSION = "mtbs-severity-1.0"
DEFAULT_OUT_DIR = "data/processed/rasters/mtbs_severity"
DEFAULT_REPORT = "data/metadata/mtbs_severity_preprocess_report.json"
CELL_M = 30.0
YEAR_RE = re.compile(r"mtbs_[A-Za-z]{2}_(\d{4})\.zip$")


class MTBSSeverityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeverityArchive:
    year: int
    zip_path: Path


# ------------------------------------------------------------------ discovery
def configured_years() -> list[int]:
    return [int(y) for y in registry.sources()["mtbs"].get("severity_years", [])]


def discover_archives(pattern: str | None = None) -> dict[int, SeverityArchive]:
    pattern = pattern or registry.sources()["mtbs"]["severity_mosaic_zips"]
    out: dict[int, SeverityArchive] = {}
    for p in registry.glob_paths(pattern):  # relative to the repo, or absolute (tests)
        m = YEAR_RE.search(p.name)
        if m:
            out[int(m.group(1))] = SeverityArchive(int(m.group(1)), p)
    return dict(sorted(out.items()))


def _cfg(key: str, default: str) -> str:
    return registry.sources()["mtbs"].get(key, default)


def output_path(year: int) -> Path:
    return registry.path(_cfg("processed_severity_dir", DEFAULT_OUT_DIR)) / f"mtbs_severity_{year}.tif"


def report_path() -> Path:
    return registry.path(_cfg("severity_report", DEFAULT_REPORT))


# ------------------------------------------------------------------ metadata
def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(registry.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_class_definitions(xml_bytes: bytes) -> dict[int, str]:
    """Class value -> producer definition from the FGDC entity/attribute section."""
    root = ET.fromstring(xml_bytes)
    classes: dict[int, str] = {}
    for edom in root.iter("edom"):
        v, d = edom.findtext("edomv"), edom.findtext("edomvd")
        if v is not None and d is not None and v.strip().lstrip("-").isdigit():
            classes[int(v.strip())] = d.strip()
    return classes


def parse_xml_summary(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)

    def text(path: str) -> str | None:
        t = root.findtext(path)
        return t.strip() if t else None

    return {"title": text(".//citation/citeinfo/title"), "publication_date": text(".//citation/citeinfo/pubdate"),
            "origin": [o.text.strip() for o in root.findall(".//citation/citeinfo/origin") if o.text],
            "doi": next((o.text.strip() for o in root.findall(".//citation/citeinfo/onlink") if o.text and "doi" in o.text), None),
            "time_period": text(".//timeperd//caldate"),
            "class_method": text(".//eainfo/overview/eaover")}


def _members(zf: zipfile.ZipFile) -> tuple[str | None, str | None]:
    names = zf.namelist()
    tif = next((n for n in names if n.lower().endswith((".tif", ".tiff"))), None)
    xml = next((n for n in names if n.lower().endswith(".xml")), None)
    return tif, xml


def raster_stats(path: Path, nodata: float | None) -> dict:
    """Value counts over the whole raster, read block by block (memory-safe for ~800 Mpx mosaics)."""
    counts = np.zeros(256, dtype=np.int64)
    with rasterio.open(path) as ds:
        if ds.dtypes[0] != "uint8":
            raise MTBSSeverityError(f"unexpected dtype {ds.dtypes[0]} (categorical uint8 expected)")
        for _, win in ds.block_windows(1):
            counts += np.bincount(ds.read(1, window=win).ravel(), minlength=256)
    total = int(counts.sum())
    nd = int(counts[int(nodata)]) if nodata is not None else 0
    return {"value_counts": {int(v): int(c) for v, c in enumerate(counts) if c}, "pixels": total,
            "nodata_pixels": nd, "valid_pixels": total - nd, "valid_pct": round(100.0 * (total - nd) / total, 4) if total else 0.0}


def inspect_archive(arc: SeverityArchive, workdir: Path) -> dict:
    """Extract the raster + XML of one ZIP into `workdir` (raw ZIP untouched) and read all metadata."""
    with zipfile.ZipFile(arc.zip_path) as zf:
        tif, xml = _members(zf)
        members = zf.namelist()
        if tif is None:
            raise MTBSSeverityError(f"MTBS {arc.year} archive found but contains no GeoTIFF (members: {members})")
        zf.extract(tif, workdir)
        xml_bytes = zf.read(xml) if xml else None
    tif_path = workdir / tif
    classes = parse_class_definitions(xml_bytes) if xml_bytes else {}
    with rasterio.open(tif_path) as ds:
        if ds.crs is None:
            raise MTBSSeverityError(f"MTBS {arc.year} archive found but raster validation failed: no CRS")
        if ds.count != 1:
            raise MTBSSeverityError(f"MTBS {arc.year} archive found but raster validation failed: {ds.count} bands (1 expected)")
        try:
            cmap = ds.colormap(1)
        except ValueError:
            cmap = None
        meta = {
            "members": members, "raster_member": tif, "metadata_member": xml,
            "crs": ds.crs.to_string(), "epsg": ds.crs.to_epsg(), "transform": list(ds.transform)[:6],
            "bounds": [float(b) for b in ds.bounds],
            "bounds_wgs84": [round(float(b), 5) for b in transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)],
            "width": ds.width, "height": ds.height, "resolution": [abs(ds.res[0]), abs(ds.res[1])],
            "bands": ds.count, "dtype": ds.dtypes[0], "nodata": ds.nodata, "band_descriptions": list(ds.descriptions),
            "tags": ds.tags(), "colormap": {int(k): list(v) for k, v in cmap.items() if k in classes} if cmap else None,
        }
    meta["stats"] = raster_stats(tif_path, meta["nodata"])
    unknown = sorted(set(meta["stats"]["value_counts"]) - set(classes)) if classes else []
    if not classes:
        raise MTBSSeverityError(f"MTBS {arc.year} archive found but raster validation failed: no class definitions in XML")
    if unknown:
        raise MTBSSeverityError(f"MTBS {arc.year} archive found but raster validation failed: undefined values {unknown}")
    meta["class_definitions"] = {str(k): v for k, v in sorted(classes.items())}
    meta["xml"] = parse_xml_summary(xml_bytes) if xml_bytes else None
    meta["_tif_path"] = str(tif_path)
    return meta


# ------------------------------------------------------------------ study-region grid
def region_grid_5070(cell: float = CELL_M) -> tuple[rasterio.Affine, int, int, tuple[float, float, float, float]]:
    """Study bbox (config) in the analysis CRS, snapped outward to the LANDFIRE 30 m lattice."""
    w, s, e, n = registry.study_bbox()
    xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", registry.analysis_crs(), w, s, e, n, densify_pts=101)
    ox, oy = LANDFIRE_ORIGIN
    x0 = ox + np.floor((xmin - ox) / cell) * cell
    x1 = ox + np.ceil((xmax - ox) / cell) * cell
    y1 = oy + np.ceil((ymax - oy) / cell) * cell
    y0 = oy + np.floor((ymin - oy) / cell) * cell
    width, height = int(round((x1 - x0) / cell)), int(round((y1 - y0) / cell))
    return rasterio.Affine(cell, 0, float(x0), 0, -cell, float(y1)), width, height, (float(x0), float(y0), float(x1), float(y1))


def clip_to_region(src_path: Path, tlog: TransformLog, label: str) -> tuple[np.ndarray, rasterio.Affine, str, dict]:
    """Nearest-neighbour warp of the categorical raster onto the 30 m study-region grid (EPSG:5070)."""
    dst_crs = registry.analysis_crs()
    transform, width, height, bounds = region_grid_5070()
    with rasterio.open(src_path) as src:
        nodata = 0 if src.nodata is None else int(src.nodata)
        sb = transform_bounds(dst_crs, src.crs, *bounds, densify_pts=21)
        sxmin, symin, sxmax, symax = src.bounds
        ib = (max(sb[0], sxmin), max(sb[1], symin), min(sb[2], sxmax), min(sb[3], symax))
        if ib[0] >= ib[2] or ib[1] >= ib[3]:
            return np.zeros((0, 0), np.uint8), transform, dst_crs, {"intersects": False}
        # pad by 2 source pixels so rounding never drops a partial edge row/column, then clamp to the dataset
        w0 = from_bounds(*ib, transform=src.transform)
        win = Window(int(np.floor(w0.col_off)) - 2, int(np.floor(w0.row_off)) - 2,
                     int(np.ceil(w0.width)) + 5, int(np.ceil(w0.height)) + 5).intersection(Window(0, 0, src.width, src.height))
        data = src.read(1, window=win)
        win_tr = src.window_transform(win)
        dst = np.full((height, width), nodata, dtype=np.uint8)
        reproject(source=data, destination=dst, src_transform=win_tr, src_crs=src.crs, src_nodata=nodata,
                  dst_transform=transform, dst_crs=dst_crs, dst_nodata=nodata, resampling=Resampling.nearest)
        tlog.add(label, src.crs.to_string(), dst_crs, Resampling.nearest.name, abs(src.res[0]), CELL_M)
        same_grid = (src.crs.to_string() == dst_crs and abs(src.res[0] - CELL_M) < 1e-6
                     and abs(((src.transform.c - transform.c) / CELL_M) % 1) < 1e-6
                     and abs(((src.transform.f - transform.f) / CELL_M) % 1) < 1e-6)
    return dst, transform, dst_crs, {"intersects": True, "source_window": [int(win.col_off), int(win.row_off), int(win.width), int(win.height)],
                                     "pixel_aligned_copy": bool(same_grid), "nodata": nodata}


def write_severity_tif(path: Path, arr: np.ndarray, transform, crs: str, nodata: int, classes: dict, colormap: dict | None,
                       tags: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8",
                       crs=crs, transform=transform, nodata=nodata, compress="deflate", tiled=True,
                       blockxsize=512, blockysize=512) as dst:
        dst.write(arr, 1)
        dst.set_band_description(1, "MTBS thematic burn severity class (categorical)")
        dst.update_tags(1, **{f"CLASS_{k}": v for k, v in classes.items()})
        dst.update_tags(**tags)
        if colormap:
            dst.write_colormap(1, {int(k): tuple(v) for k, v in colormap.items()})
        dst.build_overviews([2, 4, 8, 16], Resampling.mode)


# ------------------------------------------------------------------ pipeline
def process_year(year: int, archives: dict[int, SeverityArchive]) -> dict:
    now = datetime.now(UTC).isoformat()
    base = {"year": year, "processing_version": PROCESSING_VERSION, "processed_utc": now, "data_class": "observed",
            "output_crs": registry.analysis_crs(), "output_resolution_m": CELL_M, "resampling": "nearest",
            "study_region_wgs84": list(registry.study_bbox())}
    arc = archives.get(year)
    if arc is None:
        return base | {"status": "missing", "message": f"MTBS {year} raw file not found"}
    base |= {"source_file": _rel(arc.zip_path),
             "source_sha256": sha256(arc.zip_path), "source_size_bytes": arc.zip_path.stat().st_size}
    out = output_path(year)
    work = Path(tempfile.mkdtemp(prefix=f"mtbs_{year}_"))
    try:
        meta = inspect_archive(arc, work)
        tif = Path(meta.pop("_tif_path"))
        tlog = TransformLog()
        arr, transform, crs, clip = clip_to_region(tif, tlog, f"MTBS severity {year}")
        rec = base | {"source": {k: v for k, v in meta.items() if k not in ("class_definitions", "xml", "stats")},
                      "source_stats": meta["stats"], "class_definitions": meta["class_definitions"],
                      "source_metadata": meta["xml"], "study_region_intersection": clip, "transforms": tlog.entries}
        if not clip["intersects"]:
            out.unlink(missing_ok=True)
            return rec | {"status": "no_intersection",
                          "message": f"MTBS {year} does not intersect the WildfireTwin model domain"}
        nodata = clip["nodata"]
        vals, cnt = np.unique(arr, return_counts=True)
        counts = {int(v): int(c) for v, c in zip(vals, cnt)}
        burned_mapped = sum(c for v, c in counts.items() if v != nodata)
        if not set(counts) <= set(int(k) for k in meta["class_definitions"]):
            raise MTBSSeverityError(f"MTBS {year} clip produced undefined values {sorted(set(counts))}")
        tags = {"SOURCE": rec["source_file"], "SOURCE_SHA256": rec["source_sha256"], "PROCESSING_VERSION": PROCESSING_VERSION,
                "RESAMPLING": "nearest", "DATA_CLASS": "observed", "MTBS_YEAR": str(year),
                "ROLE": "historical validation context only; not a training target"}
        write_severity_tif(out, arr, transform, crs, nodata, meta["class_definitions"], rec["source"]["colormap"], tags)
        rec |= {"status": "processed", "message": f"MTBS {year} processed successfully",
                "output_path": _rel(out),
                "output_bounds": list(transform_bounds_from(transform, arr.shape)), "output_shape": list(arr.shape),
                "output_nodata": nodata, "output_value_counts": counts,
                "valid_pixel_count": burned_mapped, "nodata_pixel_count": counts.get(nodata, 0),
                "class_area_km2_in_domain": {str(v): round(c * CELL_M * CELL_M / 1e6, 4) for v, c in counts.items() if v != nodata}}
        if burned_mapped == 0:
            rec["message"] += " (no mapped fire pixels inside the model domain)"
        return rec
    except MTBSSeverityError as e:
        out.unlink(missing_ok=True)
        return base | {"status": "failed", "message": str(e)}
    except Exception as e:  # unexpected I/O / GDAL failure: report, never hide
        out.unlink(missing_ok=True)
        return base | {"status": "failed", "message": f"MTBS {year} archive found but raster validation failed: {e}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def transform_bounds_from(transform, shape) -> tuple[float, float, float, float]:
    h, w = shape
    return (transform.c, transform.f + transform.e * h, transform.c + transform.a * w, transform.f)


def run(years: list[int] | None = None) -> dict:
    archives = discover_archives()
    want = sorted(set(years or configured_years()) | set(archives))
    results = [process_year(y, archives) for y in want]
    report = {"generated_utc": datetime.now(UTC).isoformat(), "processing_version": PROCESSING_VERSION,
              "product": "MTBS thematic burn-severity mosaic (categorical)", "data_class": "observed",
              "role": "Historical validation context (post-fire severity). NOT a training target or model input.",
              "output_dir": _cfg("processed_severity_dir", DEFAULT_OUT_DIR), "years": results}
    p = report_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def load_report() -> dict | None:
    p = report_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def inventory_status() -> tuple[str, dict]:
    """Truthful status derived from raw files, the report and the processed outputs actually on disk."""
    archives = discover_archives()
    if not archives:
        return "Missing", {}
    rep = load_report()
    if rep is None:
        return "Available — raw only", {"raw_years": sorted(archives)}
    by = {r["year"]: r for r in rep["years"]}
    processed = [y for y, r in by.items() if r["status"] == "processed" and output_path(y).exists()]
    failed = [y for y, r in by.items() if r["status"] == "failed"]
    detail = {"raw_years": sorted(archives), "processed_years": sorted(processed), "failed_years": sorted(failed),
              "no_intersection_years": sorted(y for y, r in by.items() if r["status"] == "no_intersection"),
              "missing_years": sorted(y for y, r in by.items() if r["status"] == "missing")}
    if processed:
        return "Available — processed", detail
    if failed:
        return "Available — preprocessing failed", detail
    return "Available — raw only", detail


# ------------------------------------------------------------------ replay context
def severity_window(year: int, grid: AnalysisGrid, tlog: TransformLog | None = None) -> tuple[np.ndarray, dict] | None:
    """Processed severity for one analysis window: nearest at 30 m, mode at coarser cells. None if unavailable."""
    p = output_path(year)
    if not p.exists():
        return None
    resampling = Resampling.nearest if grid.cell <= CELL_M else Resampling.mode
    with rasterio.open(p) as src:
        nodata = int(src.nodata or 0)
        classes = {int(k.split("_", 1)[1]): v for k, v in src.tags(1).items() if k.startswith("CLASS_")}
        dst = np.full(grid.shape, nodata, dtype=np.uint8)
        reproject(source=rasterio.band(src, 1), destination=dst, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=nodata, dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=nodata,
                  resampling=resampling)
    if tlog is not None:
        tlog.add(f"MTBS severity {year}", grid.crs, grid.crs, resampling.name, CELL_M, grid.cell)
    return dst, {"nodata": nodata, "classes": classes, "resampling": resampling.name}
