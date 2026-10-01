"""Vector I/O without a GDAL/OGR runtime dependency.

Shapefiles (plain or zipped) are read with pure-Python `pyshp`; GeoJSON with
the json module. Geometries become shapely objects in a GeoDataFrame whose CRS
comes from the .prj (WKT) or GeoJSON (EPSG:4326 by specification).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import shapefile
from pyproj import CRS
from shapely.geometry import shape


def _from_reader(r: shapefile.Reader, prj_wkt: str | None,
                 bbox: tuple[float, float, float, float] | None) -> gpd.GeoDataFrame:
    fields = [f[0] for f in r.fields[1:]]
    rows, geoms = [], []
    for i in range(len(r)):
        shp = r.shape(i)
        if shp.shapeType == shapefile.NULL:
            continue
        if bbox is not None and hasattr(shp, "bbox"):
            x0, y0, x1, y1 = shp.bbox
            if x1 < bbox[0] or x0 > bbox[2] or y1 < bbox[1] or y0 > bbox[3]:
                continue
        rows.append(dict(zip(fields, r.record(i))))
        geoms.append(shape(shp.__geo_interface__))
    crs = CRS.from_wkt(prj_wkt) if prj_wkt else None
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=crs)


def read_shapefile_zip(zip_path: Path, shp_name: str | None = None,
                       bbox: tuple[float, float, float, float] | None = None) -> gpd.GeoDataFrame:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        shp = shp_name or next(n for n in names if n.lower().endswith(".shp"))
        stem = shp[:-4]
        def member(ext):
            m = next((n for n in names if n.lower() == (stem + ext).lower()), None)
            return z.open(m) if m else None
        prj = member(".prj")
        prj_wkt = prj.read().decode("utf-8", "ignore") if prj else None
        with member(".shp") as s, member(".shx") as x, member(".dbf") as d:
            # pyshp needs seekable streams; .shx/.dbf are small, .shp is read via a seekable zip stream
            r = shapefile.Reader(shp=s, shx=io.BytesIO(x.read()), dbf=io.BytesIO(d.read()))
            return _from_reader(r, prj_wkt, bbox)


def read_vector(path: Path, bbox: tuple[float, float, float, float] | None = None) -> gpd.GeoDataFrame:
    suf = path.suffix.lower()
    if suf == ".zip":
        return read_shapefile_zip(path, bbox=bbox)
    if suf in (".geojson", ".json"):
        fc = json.loads(path.read_text(encoding="utf-8"))
        feats = fc["features"] if fc.get("type") == "FeatureCollection" else [fc]
        return gpd.GeoDataFrame([f.get("properties") or {} for f in feats],
                                geometry=[shape(f["geometry"]) for f in feats], crs="EPSG:4326")
    if suf == ".shp":
        prj = path.with_suffix(".prj")
        r = shapefile.Reader(str(path))
        return _from_reader(r, prj.read_text() if prj.exists() else None, bbox)
    raise ValueError(f"unsupported vector format: {suf}")


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(gdf.to_crs("EPSG:4326").to_json(default=str), encoding="utf-8")
