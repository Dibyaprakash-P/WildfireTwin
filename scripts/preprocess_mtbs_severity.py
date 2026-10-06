"""Preprocess the local MTBS thematic burn-severity mosaics (categorical) onto the study region.

Usage: python -m scripts.preprocess_mtbs_severity [--years 2020 2021 ...]

Reads datasets/bsp_*/mtbs_CA_<year>.zip (never modified; members extracted to a temporary directory), validates
each raster against the class definitions in its XML, clips it to the configured study region, warps it with
NEAREST resampling onto the LANDFIRE-aligned 30 m EPSG:5070 grid and writes
  data/processed/rasters/mtbs_severity/mtbs_severity_<year>.tif
  data/metadata/mtbs_severity_preprocess_report.json
A missing, invalid or non-intersecting year is reported and does not stop the other years.
MTBS severity is observed post-fire context for historical replays — not a training target.
"""

from __future__ import annotations

import argparse
import logging

from geo import mtbs_severity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years", type=int, nargs="*", help="subset of years (default: configured + discovered)")
    args = ap.parse_args()
    rep = mtbs_severity.run(args.years)
    for r in rep["years"]:
        extra = ""
        if r["status"] == "processed":
            extra = f"  -> {r['output_path']}  {r['output_shape'][1]}x{r['output_shape'][0]}  mapped px {r['valid_pixel_count']:,}"
        logging.info("[%s] %s%s", r["status"].upper(), r["message"], extra)
    logging.info("report: %s", mtbs_severity.report_path())


if __name__ == "__main__":
    main()
