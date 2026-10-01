"""FIRMS active-fire service: ingestion (API or local files) + clustering into fire events.

Fire events
-----------
FIRMS detections are pixel-centre points (VIIRS ~375 m, MODIS ~1 km). A fire
event is a connected cluster of detections whose centres are within
CLUSTER_RADIUS_KM of another detection in the cluster, over the active window
(`firms_active_hours`, default 48 h before the latest acquisition). Cluster
membership is an observed active-fire footprint, NOT an official perimeter.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from backend.app.config import get_settings
from backend.app.utils.events import emit
from geo import registry
from geo.firms import normalize_dataframe

log = logging.getLogger(__name__)

CLUSTER_RADIUS_KM = 1.5
EARTH_R_KM = 6371.0088
KEEP_COLS = ["detection_id", "latitude", "longitude", "acq_datetime", "satellite", "instrument", "product",
             "confidence_raw", "confidence_class", "brightness_k", "bright_t31_k", "frp_mw", "scan_km", "track_km",
             "daynight", "version", "source"]


def _xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def cluster_detections(lat: np.ndarray, lon: np.ndarray, radius_km: float = CLUSTER_RADIUS_KM) -> np.ndarray:
    n = len(lat)
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    pts = _xyz(lat, lon)
    chord = 2.0 * np.sin(radius_km / EARTH_R_KM / 2.0)
    pairs = cKDTree(pts).query_pairs(chord, output_type="ndarray")
    g = coo_matrix((np.ones(len(pairs), dtype=np.int8), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    _, labels = connected_components(g, directed=False)
    return labels


def in_study_region(lon: float, lat: float) -> bool:
    w, s, e, n = registry.study_bbox()
    return w <= lon <= e and s <= lat <= n


@dataclass
class FirmsSnapshot:
    detections: pd.DataFrame        # active-window detections, with `cluster` column
    events: pd.DataFrame            # one row per event
    source: str
    latest_acq: datetime | None
    loaded_at: datetime
    window_start: datetime | None


class FirmsService:
    def __init__(self) -> None:
        self.snapshot: FirmsSnapshot | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- ingestion
    async def _fetch_api(self) -> pd.DataFrame | None:
        s = get_settings()
        if not s.firms_map_key:
            return None
        url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{s.firms_map_key}/"
               f"{s.firms_api_source}/world/{s.firms_api_days}")
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(url)
                r.raise_for_status()
            raw = pd.read_csv(io.StringIO(r.text), dtype={"acq_time": str})
            df, rep = normalize_dataframe(raw, "firms_api", product=s.firms_api_source)
            await emit("firms", f"FIRMS API ({s.firms_api_source}, {s.firms_api_days}d): {rep['output_rows']} detections",
                       report=rep)
            return df
        except Exception as exc:
            await emit("firms", f"FIRMS API request failed, falling back to local files: {type(exc).__name__}", "WARNING")
            return None

    def _load_local(self) -> pd.DataFrame | None:
        p = registry.path(registry.sources()["firms"]["processed_recent"])
        if not p.exists():
            return None
        df = pd.read_parquet(p, columns=KEEP_COLS)
        df["acq_datetime"] = pd.to_datetime(df["acq_datetime"], utc=True)
        return df

    async def refresh(self) -> FirmsSnapshot | None:
        async with self._lock:
            await emit("firms", "Fetching FIRMS active-fire data...")
            df = await self._fetch_api()
            source = "firms_api"
            if df is None:
                df = await asyncio.to_thread(self._load_local)
                source = "firms_local_nrt"
            if df is None or df.empty:
                await emit("firms", "No FIRMS data available.", "WARNING")
                self.snapshot = FirmsSnapshot(pd.DataFrame(columns=KEEP_COLS + ["cluster"]), pd.DataFrame(), "none",
                                              None, datetime.now(timezone.utc), None)
                return self.snapshot
            snap = await asyncio.to_thread(self._build, df, source)
            prev = self.snapshot
            self.snapshot = snap
            await emit("firms", f"Active fire points loaded: {len(snap.detections)} detections, {len(snap.events)} events "
                                f"(source={source}, latest={snap.latest_acq:%Y-%m-%d %H:%M}Z)",
                       detections=len(snap.detections), events=len(snap.events), source=source)
            if prev is not None and prev.latest_acq != snap.latest_acq:
                await emit("firms", "New FIRMS acquisitions detected", latest=str(snap.latest_acq))
            return snap

    def _build(self, df: pd.DataFrame, source: str) -> FirmsSnapshot:
        s = get_settings()
        latest = df["acq_datetime"].max().to_pydatetime()
        start = latest - timedelta(hours=s.firms_active_hours)
        d = df[df["acq_datetime"] >= start].reset_index(drop=True).copy()
        d["cluster"] = cluster_detections(d["latitude"].to_numpy(), d["longitude"].to_numpy())
        d["_high"] = (d["confidence_class"] == "high").astype(np.int32)
        g = d.groupby("cluster")
        sats = d[["cluster", "satellite"]].drop_duplicates().groupby("cluster")["satellite"].agg(lambda c: sorted(map(str, c)))
        insts = d[["cluster", "instrument"]].drop_duplicates().groupby("cluster")["instrument"].agg(lambda c: sorted(map(str, c)))
        first_det = d.sort_values("acq_datetime").groupby("cluster")["detection_id"].first()
        ev = pd.DataFrame({
            "count": g.size(),
            "lat": g["latitude"].mean(), "lon": g["longitude"].mean(),
            "lat_min": g["latitude"].min(), "lat_max": g["latitude"].max(),
            "lon_min": g["longitude"].min(), "lon_max": g["longitude"].max(),
            "frp_sum": g["frp_mw"].sum(min_count=1), "frp_max": g["frp_mw"].max(),
            "first_seen": g["acq_datetime"].min(), "last_seen": g["acq_datetime"].max(),
            "n_high": g["_high"].sum(),
            "satellites": sats, "instruments": insts,
        })
        d = d.drop(columns="_high")
        ev["event_id"] = ["FE-" + hashlib.md5(x.encode()).hexdigest()[:10].upper() for x in first_det.loc[ev.index]]
        ev["status"] = np.where(ev["last_seen"] >= latest - timedelta(hours=24), "active", "recent")
        ev["in_model_domain"] = [in_study_region(lo, la) for lo, la in zip(ev["lon"], ev["lat"])]
        ev = ev.reset_index().rename(columns={"cluster": "cluster"})
        return FirmsSnapshot(d, ev, source, latest, datetime.now(timezone.utc), start)

    # ------------------------------------------------------------- queries
    def event_row(self, event_id: str) -> pd.Series | None:
        if self.snapshot is None or self.snapshot.events.empty:
            return None
        m = self.snapshot.events[self.snapshot.events["event_id"] == event_id]
        return None if m.empty else m.iloc[0]

    def event_detections(self, event_id: str) -> pd.DataFrame:
        row = self.event_row(event_id)
        if row is None:
            return pd.DataFrame(columns=KEEP_COLS)
        d = self.snapshot.detections
        return d[d["cluster"] == row["cluster"]].sort_values("acq_datetime")


firms_service = FirmsService()


def event_to_dict(r: pd.Series, snap: FirmsSnapshot) -> dict:
    def iso(t):
        return pd.Timestamp(t).isoformat() if pd.notna(t) else None
    return {
        "event_id": r["event_id"], "status": r["status"], "data_class": "observed",
        "latitude": float(r["lat"]), "longitude": float(r["lon"]),
        "bbox": [float(r["lon_min"]), float(r["lat_min"]), float(r["lon_max"]), float(r["lat_max"])],
        "detection_count": int(r["count"]), "high_confidence_count": int(r["n_high"]),
        "frp_sum_mw": None if pd.isna(r["frp_sum"]) else float(r["frp_sum"]),
        "frp_max_mw": None if pd.isna(r["frp_max"]) else float(r["frp_max"]),
        "first_seen": iso(r["first_seen"]), "last_seen": iso(r["last_seen"]),
        "satellites": list(r["satellites"]), "instruments": list(r["instruments"]),
        "in_model_domain": bool(r["in_model_domain"]),
        "source": snap.source, "footprint_method": f"connected clusters of detection centres within {CLUSTER_RADIUS_KM} km",
    }


def detection_to_dict(d: pd.Series) -> dict:
    out = {k: (None if pd.isna(d[k]) else d[k]) for k in KEEP_COLS if k in d}
    out["acq_datetime"] = pd.Timestamp(d["acq_datetime"]).isoformat()
    for k in ("latitude", "longitude", "brightness_k", "bright_t31_k", "frp_mw", "scan_km", "track_km"):
        if out.get(k) is not None:
            out[k] = float(out[k])
    return out
