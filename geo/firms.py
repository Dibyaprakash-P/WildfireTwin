"""NASA FIRMS active-fire normalization.

Both locally downloaded FIRMS CSVs and the FIRMS area API (same CSV columns)
are mapped onto one internal detection schema:

    detection_id, latitude, longitude, acq_datetime (UTC), satellite,
    instrument, product, confidence_raw, confidence_class, brightness_k,
    bright_t31_k, frp_mw, scan_km, track_km, daynight, version, fire_type,
    source

No field is invented: columns absent in the source are left null
(e.g. `type` is only present in archive files, not in NRT files).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd

FILENAME_RE = re.compile(r"fire_(?P<kind>archive|nrt)_(?P<product>[A-Z0-9]+-C[0-9]+)_\d+\.csv$", re.I)

# MODIS numeric confidence classes as documented in the FIRMS MODIS user guide
# (low < 30, nominal 30-79, high >= 80). VIIRS reports l / n / h directly.
_VIIRS_CONF = {"l": "low", "n": "nominal", "h": "high"}

NORMALIZED_COLUMNS = [
    "detection_id", "latitude", "longitude", "acq_datetime", "satellite", "instrument",
    "product", "confidence_raw", "confidence_class", "brightness_k", "bright_t31_k",
    "frp_mw", "scan_km", "track_km", "daynight", "version", "fire_type", "source",
]


def parse_filename(path: str | Path) -> tuple[str | None, str | None]:
    m = FILENAME_RE.search(Path(path).name)
    if not m:
        return None, None
    return m.group("kind").lower(), m.group("product").upper()


def confidence_class(raw: object) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip().lower()
    if s in _VIIRS_CONF:
        return _VIIRS_CONF[s]
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 30:
        return "low"
    if v < 80:
        return "nominal"
    return "high"


def make_detection_id(satellite: str, acq_iso: str, lat: float, lon: float) -> str:
    key = f"{satellite}|{acq_iso}|{lat:.5f}|{lon:.5f}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def normalize_dataframe(df: pd.DataFrame, source: str, product: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Normalize a FIRMS CSV frame. Returns (frame, report) where report counts dropped rows."""
    report = {"input_rows": int(len(df)), "dropped_malformed": 0, "dropped_duplicates": 0}
    if df.empty:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS), report
    d = df.copy()
    d.columns = [c.strip().lower() for c in d.columns]
    lat = pd.to_numeric(d.get("latitude"), errors="coerce")
    lon = pd.to_numeric(d.get("longitude"), errors="coerce")
    t = d.get("acq_time").astype(str).str.strip().str.zfill(4)
    dt = pd.to_datetime(d.get("acq_date").astype(str) + " " + t, format="%Y-%m-%d %H%M", errors="coerce", utc=True)
    ok = lat.between(-90, 90) & lon.between(-180, 180) & dt.notna()
    report["dropped_malformed"] = int((~ok).sum())
    d, lat, lon, dt = d[ok], lat[ok], lon[ok], dt[ok]

    out = pd.DataFrame({
        "latitude": lat.astype(float),
        "longitude": lon.astype(float),
        "acq_datetime": dt,
        "satellite": d.get("satellite").astype(str),
        "instrument": d.get("instrument").astype(str),
        "product": product,
        "confidence_raw": d.get("confidence").astype(str) if "confidence" in d else None,
        "brightness_k": pd.to_numeric(d.get("brightness", d.get("bright_ti4")), errors="coerce"),
        "bright_t31_k": pd.to_numeric(d.get("bright_t31", d.get("bright_ti5")), errors="coerce"),
        "frp_mw": pd.to_numeric(d.get("frp"), errors="coerce"),
        "scan_km": pd.to_numeric(d.get("scan"), errors="coerce"),
        "track_km": pd.to_numeric(d.get("track"), errors="coerce"),
        "daynight": d.get("daynight").astype(str) if "daynight" in d else None,
        "version": d.get("version").astype(str) if "version" in d else None,
        "fire_type": pd.to_numeric(d["type"], errors="coerce") if "type" in d else np.nan,
        "source": source,
    })
    out["confidence_class"] = out["confidence_raw"].map(confidence_class)
    iso = out["acq_datetime"].dt.strftime("%Y-%m-%dT%H:%MZ")
    out["detection_id"] = [
        make_detection_id(s, a, la, lo)
        for s, a, la, lo in zip(out["satellite"], iso, out["latitude"], out["longitude"])
    ]
    before = len(out)
    out = out.drop_duplicates("detection_id")
    report["dropped_duplicates"] = int(before - len(out))
    report["output_rows"] = int(len(out))
    return out[NORMALIZED_COLUMNS].reset_index(drop=True), report
