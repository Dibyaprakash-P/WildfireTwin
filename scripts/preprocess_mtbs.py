"""Extract MTBS burned-area perimeters intersecting the (buffered) study region.

Usage: python -m scripts.preprocess_mtbs
Output: data/processed/vectors/mtbs_perimeters_region.geojson (+ metadata report)
"""

from __future__ import annotations

import json
import logging


from geo import registry
from geo.vectors import read_shapefile_zip, write_geojson

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    cfg = registry.sources()["mtbs"]
    zp = registry.path(cfg["perimeters_zip"])
    w, s, e, n = registry.study_bbox()
    bbox = (w - 0.5, s - 0.5, e + 0.5, n + 0.5)
    gdf = read_shapefile_zip(zp, "bsp_perims_DD.shp", bbox=bbox)
    logging.info("read %d perimeters; columns=%s; crs=%s", len(gdf), list(gdf.columns), gdf.crs)
    out = registry.path(cfg["processed_perimeters"])
    out.parent.mkdir(parents=True, exist_ok=True)
    write_geojson(gdf, out)
    rep = {"rows": int(len(gdf)), "columns": list(gdf.columns), "crs": str(gdf.crs), "bbox_filter": bbox}
    for c in gdf.columns:
        if "date" in c.lower() or c.lower() in ("year", "ig_date"):
            rep[f"range_{c}"] = [str(gdf[c].min()), str(gdf[c].max())]
    registry.path("data/metadata/mtbs_preprocess_report.json").write_text(json.dumps(rep, indent=2, default=str))
    print(gdf.drop(columns="geometry").head(5).to_string())


if __name__ == "__main__":
    main()
