"""Global wind field (NOAA GFS) used by the globe's wind-flow layer."""
import base64
from datetime import UTC, datetime

import numpy as np
import pytest

from backend.app.services import wind_field as wf


def test_candidate_cycles_respect_publication_delay():
    # 05:00 UTC: the 00Z cycle is only ~5 h old -> newest candidate is 00Z (06Z not yet published)
    cycles = wf.candidate_cycles(datetime(2026, 10, 5, 5, 0, tzinfo=UTC), n=3)
    assert cycles == [datetime(2026, 10, 5, 0, tzinfo=UTC), datetime(2026, 10, 4, 18, tzinfo=UTC),
                      datetime(2026, 10, 4, 12, tzinfo=UTC)]
    # 02:00 UTC: previous day's 18Z
    assert wf.candidate_cycles(datetime(2026, 10, 5, 2, 0, tzinfo=UTC), n=1)[0] == datetime(2026, 10, 4, 18, tzinfo=UTC)


def test_nomads_request_selects_only_10m_uv_analysis():
    p = wf.nomads_params(datetime(2026, 10, 5, 6, tzinfo=UTC))
    assert p["dir"] == "/gfs.20261005/06/atmos"
    assert p["file"] == "gfs.t06z.pgrb2.1p00.f000"
    assert p["var_UGRD"] == p["var_VGRD"] == p["lev_10_m_above_ground"] == "on"


def test_payload_round_trips_and_is_labelled_as_model_analysis():
    u = np.array([[1.5, -2.25], [0.0, 30.0]], dtype=np.float32)
    v = np.array([[0.0, 4.0], [-1.0, 0.5]], dtype=np.float32)
    f = wf.WindField(cycle=datetime(2026, 10, 5, tzinfo=UTC), fetched_at=datetime(2026, 10, 5, 4, tzinfo=UTC),
                     nx=2, ny=2, lon0=0.0, lat0=90.0, dlon=180.0, dlat=-180.0, u=u, v=v)
    p = f.to_payload()
    assert p["data_class"] == "model_analysis" and "GFS" in p["source"]
    assert p["cycle"] == "2026-10-05T00:00:00Z"
    dec = np.frombuffer(base64.b64decode(p["u"]), dtype="<i2").astype(np.float32) * p["encoding"]["scale"]
    np.testing.assert_allclose(dec.reshape(2, 2), u, atol=0.006)
    assert p["stats"]["max_speed_ms"] == pytest.approx(30.0, abs=0.01)


async def test_unavailable_when_nothing_can_be_downloaded(monkeypatch, tmp_path):
    """No network / no published cycle -> WindFieldUnavailable (never a synthetic field)."""
    svc = wf.WindFieldService()
    monkeypatch.setattr(wf, "CACHE_DIR", tmp_path)

    async def no_data(cycle):
        return None

    monkeypatch.setattr(svc, "_download", no_data)
    with pytest.raises(wf.WindFieldUnavailable):
        await svc.get()


def test_decode_real_gfs_message_if_eccodes_available():
    eccodes = pytest.importorskip("eccodes")
    # Build a tiny GRIB2 pair from eccodes' own sample so the decoder is exercised without network access.
    msgs = []
    for name, val in (("10u", 3.0), ("10v", -4.0)):
        g = eccodes.codes_grib_new_from_samples("GRIB2")
        eccodes.codes_set(g, "discipline", 0)
        eccodes.codes_set(g, "parameterCategory", 2)
        eccodes.codes_set(g, "parameterNumber", 2 if name == "10u" else 3)
        eccodes.codes_set(g, "typeOfFirstFixedSurface", 103)
        eccodes.codes_set(g, "scaledValueOfFirstFixedSurface", 10)
        n = eccodes.codes_get(g, "numberOfValues")
        eccodes.codes_set_values(g, np.full(n, val))
        msgs.append(eccodes.codes_get_message(g))
        eccodes.codes_release(g)
    f = wf.decode_grib(b"".join(msgs), datetime(2026, 10, 5, tzinfo=UTC))
    assert f.u.shape == (f.ny, f.nx)
    assert float(f.u.mean()) == pytest.approx(3.0, abs=0.01)
    assert float(f.v.mean()) == pytest.approx(-4.0, abs=0.01)
