"""Bulk-normalize the locally downloaded FIRMS CSVs with DuckDB.

Produces two Parquet files (schema = geo.firms.NORMALIZED_COLUMNS):

* firms_region.parquet         all detections (2010-2026, every product) inside the
                               study bbox buffered by 0.5 deg — used for historical
                               analysis, validation and observed fire-state initialisation.
* firms_recent_global.parquet  global NRT detections from the last `recent_days`
                               days present in the local files — used by the globe
                               when no FIRMS MAP_KEY is configured.

Usage:  python -m scripts.preprocess_firms
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import duckdb

from geo import registry

BUFFER_DEG = 0.5


def _select_sql(files: list[str], has_type: bool = True) -> str:
    file_list = ", ".join(f"'{f}'" for f in files)
    type_expr = "TRY_CAST(type AS INTEGER)" if has_type else "NULL::INTEGER"
    return f"""
    SELECT
        latitude::DOUBLE AS latitude,
        longitude::DOUBLE AS longitude,
        strptime(acq_date || ' ' || lpad(acq_time, 4, '0'), '%Y-%m-%d %H%M') AS acq_dt_naive,
        satellite, instrument,
        regexp_extract(filename, 'fire_(?:archive|nrt)_([A-Z0-9]+-C[0-9]+)_', 1) AS product,
        confidence AS confidence_raw,
        TRY_CAST(brightness AS DOUBLE) AS brightness_k,
        TRY_CAST(bright_t31 AS DOUBLE) AS bright_t31_k,
        TRY_CAST(frp AS DOUBLE) AS frp_mw,
        TRY_CAST(scan AS DOUBLE) AS scan_km,
        TRY_CAST(track AS DOUBLE) AS track_km,
        daynight, version,
        {type_expr} AS fire_type,
        CASE WHEN filename LIKE '%fire_nrt_%' THEN 'firms_local_nrt' ELSE 'firms_local_archive' END AS source
    FROM read_csv([{file_list}], header=true, union_by_name=true, filename=true,
                  all_varchar=true, ignore_errors=true)
    """


def _finalize_sql(inner: str, where: str) -> str:
    return f"""
    WITH raw AS ({inner}),
    f AS (
        SELECT *, acq_dt_naive AS acq_datetime FROM raw
        WHERE latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180
          AND acq_dt_naive IS NOT NULL AND {where}
    ),
    ided AS (
        SELECT substr(md5(printf('%s|%sZ|%.5f|%.5f', satellite,
                     strftime(acq_dt_naive, '%Y-%m-%dT%H:%M'), latitude, longitude)), 1, 16) AS detection_id, *
        FROM f
    )
    SELECT detection_id, latitude, longitude, acq_datetime, satellite, instrument, product,
           confidence_raw,
           CASE
             WHEN lower(confidence_raw) = 'l' THEN 'low'
             WHEN lower(confidence_raw) = 'n' THEN 'nominal'
             WHEN lower(confidence_raw) = 'h' THEN 'high'
             WHEN TRY_CAST(confidence_raw AS DOUBLE) < 30 THEN 'low'
             WHEN TRY_CAST(confidence_raw AS DOUBLE) < 80 THEN 'nominal'
             WHEN TRY_CAST(confidence_raw AS DOUBLE) >= 80 THEN 'high'
           END AS confidence_class,
           brightness_k, bright_t31_k, frp_mw, scan_km, track_km, daynight, version, fire_type, source
    FROM ided
    QUALIFY row_number() OVER (PARTITION BY detection_id ORDER BY source) = 1
    """


def main() -> None:
    cfg = registry.sources()["firms"]
    files = [str(p).replace("\\", "/") for p in registry.glob_paths(cfg["raw_glob"])]
    nrt_files = [f for f in files if "fire_nrt_" in f]
    out_region = registry.path(cfg["processed_region"])
    out_recent = registry.path(cfg["processed_recent"])
    out_region.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads TO 8")
    con.execute("SET TimeZone='UTC'")
    report: dict = {"generated_utc": datetime.now(timezone.utc).isoformat(), "files": len(files)}

    w, s, e, n = registry.study_bbox()
    where = (f"longitude BETWEEN {w - BUFFER_DEG} AND {e + BUFFER_DEG} "
             f"AND latitude BETWEEN {s - BUFFER_DEG} AND {n + BUFFER_DEG}")
    t0 = time.time()
    # Materialise first: a single CTE + QUALIFY over read_csv triggers a DuckDB internal error.
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw_rows AS SELECT * FROM ({_select_sql(files)}) WHERE {where}")
    con.execute(f"COPY ({_finalize_sql('SELECT * FROM raw_rows', 'true')}) TO '{out_region.as_posix()}' (FORMAT PARQUET)")
    rs = con.execute(f"SELECT count(*), min(acq_datetime), max(acq_datetime) FROM '{out_region.as_posix()}'").fetchone()
    report["region"] = {"bbox_buffered": [w - BUFFER_DEG, s - BUFFER_DEG, e + BUFFER_DEG, n + BUFFER_DEG],
                        "rows": rs[0], "min": str(rs[1]), "max": str(rs[2]), "seconds": round(time.time() - t0, 1)}
    print("region", report["region"], flush=True)

    t0 = time.time()
    max_date = con.execute(
        f"SELECT max(strptime(acq_date, '%Y-%m-%d')) FROM read_csv([{', '.join(repr(f) for f in nrt_files)}], "
        "header=true, all_varchar=true, union_by_name=true)").fetchone()[0]
    days = int(cfg["recent_days"])
    where_recent = f"acq_dt_naive >= TIMESTAMP '{max_date}' - INTERVAL {days - 1} DAY"
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw_rows AS SELECT * FROM ({_select_sql(nrt_files, has_type=False)}) WHERE {where_recent}")
    con.execute(f"COPY ({_finalize_sql('SELECT * FROM raw_rows', 'true')}) TO '{out_recent.as_posix()}' (FORMAT PARQUET)")
    rr = con.execute(f"SELECT count(*), min(acq_datetime), max(acq_datetime) FROM '{out_recent.as_posix()}'").fetchone()
    report["recent_global"] = {"rows": rr[0], "min": str(rr[1]), "max": str(rr[2]), "days": days,
                               "seconds": round(time.time() - t0, 1)}
    print("recent", report["recent_global"], flush=True)
    meta = registry.path("data/metadata/firms_preprocess_report.json")
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
