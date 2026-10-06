"""Global gridded 10 m wind field for the globe's wind-flow layer.

Source: NOAA GFS 1.0° global analysis (forecast hour 000), U and V wind components at 10 m above ground,
downloaded from the NOMADS GRIB filter (public, no key) and decoded with eccodes (GRIB2 template 5.3).

  * Real data only. If no cycle can be downloaded/decoded the service raises WindFieldUnavailable and the
    API returns 503 "Wind data unavailable" — no field is interpolated, extrapolated or invented.
  * Data class: model analysis (GFS f000) — not an observation and not a WildfireTwin prediction.
  * Freshness: GFS runs every 6 h (00/06/12/18 UTC) and appears on NOMADS ~3.5–5 h later. The newest cycle is
    looked for at most every REFRESH_S; the last good field is kept in memory and on disk (survives restarts).
  * Purpose: visualisation of atmospheric flow only. It is NOT an input of the WildfireTwin spread models
    (those use Open-Meteo at the fire location / ERA5 in training).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np

from geo import registry

log = logging.getLogger(__name__)

NOMADS_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_1p00.pl"
REFRESH_S = 30 * 60           # look for a newer cycle at most every 30 min
PUBLISH_DELAY_H = 3.5         # a GFS cycle is normally complete on NOMADS ~3.5-5 h after its nominal time
MAX_CYCLES_BACK = 6           # try up to 36 h of cycles before giving up
SCALE = 0.01                  # transport encoding: int16 = round(value / SCALE)  (±327 m/s range, 1 cm/s steps)
CACHE_DIR = registry.path("data/processed/weather/wind")


class WindFieldUnavailable(RuntimeError):
    pass


@dataclass
class WindField:
    cycle: datetime            # GFS cycle (= analysis valid time for f000)
    fetched_at: datetime
    nx: int
    ny: int
    lon0: float                # longitude of first column (deg, 0..360 convention allowed)
    lat0: float                # latitude of first row (deg)
    dlon: float
    dlat: float                # negative when rows run north -> south
    u: np.ndarray              # (ny, nx) float32, m/s, eastward
    v: np.ndarray              # (ny, nx) float32, m/s, northward

    def to_payload(self) -> dict:
        def enc(a: np.ndarray) -> str:
            q = np.clip(np.round(a / SCALE), -32767, 32767).astype("<i2")
            return base64.b64encode(q.tobytes()).decode("ascii")

        speed = np.hypot(self.u, self.v)
        return {
            "source": "NOAA GFS 1.0° global analysis (f000), 10 m above ground",
            "provider": "NOAA NCEP / NOMADS",
            "data_class": "model_analysis",
            "variables": {"u": "UGRD 10 m (eastward, m/s)", "v": "VGRD 10 m (northward, m/s)"},
            "cycle": self.cycle.isoformat().replace("+00:00", "Z"),
            "valid_time": self.cycle.isoformat().replace("+00:00", "Z"),
            "fetched_at": self.fetched_at.isoformat().replace("+00:00", "Z"),
            "grid": {"nx": self.nx, "ny": self.ny, "lon0": self.lon0, "lat0": self.lat0,
                     "dlon": self.dlon, "dlat": self.dlat},
            "encoding": {"dtype": "int16-le", "scale": SCALE, "order": "row-major, row = latitude"},
            "stats": {"max_speed_ms": round(float(speed.max()), 2), "mean_speed_ms": round(float(speed.mean()), 2)},
            "u": enc(self.u),
            "v": enc(self.v),
            "note": "Visualisation layer only; not used by the WildfireTwin spread models.",
        }


def candidate_cycles(now: datetime, n: int = MAX_CYCLES_BACK) -> list[datetime]:
    """Newest-first GFS cycles that should already be published at `now`."""
    t = now.astimezone(UTC) - timedelta(hours=PUBLISH_DELAY_H)
    first = t.replace(hour=(t.hour // 6) * 6, minute=0, second=0, microsecond=0)
    return [first - timedelta(hours=6 * k) for k in range(n)]


def nomads_params(cycle: datetime) -> dict[str, str]:
    hh = f"{cycle.hour:02d}"
    return {
        "dir": f"/gfs.{cycle:%Y%m%d}/{hh}/atmos",
        "file": f"gfs.t{hh}z.pgrb2.1p00.f000",
        "var_UGRD": "on", "var_VGRD": "on", "lev_10_m_above_ground": "on",
    }


def decode_grib(blob: bytes, cycle: datetime) -> WindField:
    """Decode the two-message (UGRD, VGRD) GRIB2 file with eccodes."""
    import eccodes  # imported lazily: native library, only needed when a field is actually decoded

    fields: dict[str, np.ndarray] = {}
    grid: dict[str, float] = {}
    off = 0
    while True:
        start = blob.find(b"GRIB", off)
        if start < 0:
            break
        length = int.from_bytes(blob[start + 8:start + 16], "big")
        g = eccodes.codes_new_from_message(blob[start:start + length])
        try:
            name = eccodes.codes_get(g, "shortName")
            ni, nj = eccodes.codes_get(g, "Ni"), eccodes.codes_get(g, "Nj")
            vals = eccodes.codes_get_values(g).astype(np.float32).reshape(nj, ni)
            j_pos = eccodes.codes_get(g, "jScansPositively")
            grid = {
                "nx": ni, "ny": nj,
                "lon0": eccodes.codes_get(g, "longitudeOfFirstGridPointInDegrees"),
                "lat0": eccodes.codes_get(g, "latitudeOfFirstGridPointInDegrees"),
                "dlon": eccodes.codes_get(g, "iDirectionIncrementInDegrees"),
                "dlat": eccodes.codes_get(g, "jDirectionIncrementInDegrees") * (1 if j_pos else -1),
            }
            if name in ("10u", "u10", "u"):
                fields["u"] = vals
            elif name in ("10v", "v10", "v"):
                fields["v"] = vals
        finally:
            eccodes.codes_release(g)
        off = start + length
    if "u" not in fields or "v" not in fields:
        raise WindFieldUnavailable(f"GRIB for {cycle:%Y-%m-%d %HZ} lacks 10 m U/V")
    u, v = fields["u"], fields["v"]
    if not (np.isfinite(u).all() and np.isfinite(v).all()) or float(np.hypot(u, v).max()) > 150:
        raise WindFieldUnavailable("decoded wind field failed sanity checks")
    return WindField(cycle=cycle, fetched_at=datetime.now(UTC), u=u, v=v,
                     nx=int(grid["nx"]), ny=int(grid["ny"]), lon0=float(grid["lon0"]), lat0=float(grid["lat0"]),
                     dlon=float(grid["dlon"]), dlat=float(grid["dlat"]))


class WindFieldService:
    def __init__(self) -> None:
        self._field: WindField | None = None
        self._checked = 0.0
        self._lock = asyncio.Lock()

    # ---- disk cache (raw GRIB bytes of the last good cycle) ----
    def _cache_path(self, cycle: datetime):
        return CACHE_DIR / f"gfs_{cycle:%Y%m%d%H}_10m_uv.grib2"

    def _load_disk(self) -> WindField | None:
        if not CACHE_DIR.exists():
            return None
        for p in sorted(CACHE_DIR.glob("gfs_*_10m_uv.grib2"), reverse=True):
            try:
                cycle = datetime.strptime(p.name[4:14], "%Y%m%d%H").replace(tzinfo=UTC)
                f = decode_grib(p.read_bytes(), cycle)
                f.fetched_at = datetime.fromtimestamp(p.stat().st_mtime, UTC)
                return f
            except Exception as e:  # corrupt cache file: ignore it
                log.warning("wind cache %s unreadable: %s", p.name, e)
        return None

    def _save_disk(self, cycle: datetime, blob: bytes) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._cache_path(cycle).write_bytes(blob)
            for old in CACHE_DIR.glob("gfs_*_10m_uv.grib2"):
                if old.name != self._cache_path(cycle).name:
                    old.unlink(missing_ok=True)
        except OSError as e:
            log.warning("could not cache wind field: %s", e)

    async def _download(self, cycle: datetime) -> bytes | None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0), follow_redirects=True) as client:
            r = await client.get(NOMADS_FILTER, params=nomads_params(cycle))
        if r.status_code != 200 or not r.content.startswith(b"GRIB"):
            return None
        return r.content

    async def get(self) -> WindField:
        async with self._lock:
            if self._field is None:
                self._field = await asyncio.to_thread(self._load_disk)
            if time.monotonic() - self._checked >= REFRESH_S or self._field is None:
                self._checked = time.monotonic()
                try:
                    await self._refresh()
                except Exception as e:  # network/decoder problems: keep the last good field if there is one
                    log.warning("wind field refresh failed: %s", e)
            if self._field is None:
                raise WindFieldUnavailable("no GFS wind field could be downloaded")
            return self._field

    async def _refresh(self) -> None:
        for cycle in candidate_cycles(datetime.now(UTC)):
            if self._field is not None and cycle <= self._field.cycle:
                return  # already have this (or a newer) cycle
            blob = await self._download(cycle)
            if blob is None:
                continue
            field = await asyncio.to_thread(decode_grib, blob, cycle)
            self._field = field
            await asyncio.to_thread(self._save_disk, cycle, blob)
            log.info("wind field updated: GFS %s (%dx%d)", f"{cycle:%Y-%m-%d %HZ}", field.nx, field.ny)
            return


wind_field_service = WindFieldService()
