"""Alert engine: explicit, configurable change detection -> alert candidates.

Pure functions (no I/O) so the logic is unit-testable; persistence happens in
backend.app.alerts.store. Only values from actual data / model outputs appear
in alert details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from geo import registry

SEVERITIES = ["INFO", "WARNING", "HIGH", "CRITICAL"]
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg: float | None) -> str:
    return "n/a" if deg is None else COMPASS[int(((deg % 360) + 11.25) // 22.5) % 16]


@lru_cache(maxsize=1)
def rules() -> dict:
    return yaml.safe_load((registry.REPO_ROOT / "config" / "alert_rules.yaml").read_text())


def level_for(value: float, levels: dict[str, float]) -> str | None:
    """Highest severity whose threshold is met (value >= threshold)."""
    hit = None
    for sev in SEVERITIES:
        if sev in levels and value >= levels[sev]:
            hit = sev
    return hit


def max_sev(*sevs: str | None) -> str | None:
    s = [x for x in sevs if x]
    return max(s, key=SEVERITIES.index) if s else None


@dataclass
class AlertCandidate:
    type: str
    severity: str
    title: str
    lines: list[str]
    details: dict = field(default_factory=dict)


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def weather_change(prev: dict, new: dict) -> AlertCandidate | None:
    """prev/new: dicts with wind_speed_10m (m/s), wind_direction_10m (deg), temperature_2m (C), relative_humidity_2m (%)."""
    r = rules()["weather_change"]
    sevs, lines, det = [], [], {}
    ws0, ws1 = prev.get("wind_speed_10m"), new.get("wind_speed_10m")
    wd0, wd1 = prev.get("wind_direction_10m"), new.get("wind_direction_10m")
    if ws0 is not None and ws1 is not None:
        s = level_for(abs(ws1 - ws0), r["wind_speed_delta_ms"])
        if s:
            sevs.append(s)
            lines.append(f"Wind speed: {ws0 * 3.6:.0f} -> {ws1 * 3.6:.0f} km/h")
        det["wind_speed_ms"] = [ws0, ws1]
    if None not in (ws0, ws1, wd0, wd1):
        dr = r["wind_direction_delta_deg"]
        if ws0 >= dr["min_speed_ms"] and ws1 >= dr["min_speed_ms"]:
            s = level_for(angle_diff(wd0, wd1), dr["levels"])
            if s:
                sevs.append(s)
                lines.append(f"Wind direction: {compass(wd0)} -> {compass(wd1)}")
        det["wind_direction_deg"] = [wd0, wd1]
    t0, t1 = prev.get("temperature_2m"), new.get("temperature_2m")
    if t0 is not None and t1 is not None:
        s = level_for(abs(t1 - t0), r["temperature_delta_c"])
        if s:
            sevs.append(s)
            lines.append(f"Temperature: {t0:.0f} -> {t1:.0f} °C")
        det["temperature_c"] = [t0, t1]
    h0, h1 = prev.get("relative_humidity_2m"), new.get("relative_humidity_2m")
    if h0 is not None and h1 is not None:
        s = level_for(h0 - h1, r["humidity_drop_pct"]) if h1 < h0 else None
        if h1 <= r["low_humidity_pct"]["HIGH"] and h0 > r["low_humidity_pct"]["HIGH"]:
            s = max_sev(s, "HIGH")
        if s:
            sevs.append(s)
            lines.append(f"Humidity: {h0:.0f}% -> {h1:.0f}%")
        det["relative_humidity_pct"] = [h0, h1]
    sev = max_sev(*sevs)
    if not sev:
        return None
    return AlertCandidate("WEATHER_CHANGE", sev, "WEATHER CHANGE", lines, det)


def fire_activity_change(prev: dict, new: dict) -> AlertCandidate | None:
    r = rules()["fire_activity_change"]
    c0, c1 = prev.get("detection_count", 0), new.get("detection_count", 0)
    sevs, lines = [], []
    if c0 > 0 and c1 - c0 >= r["min_new_detections"]:
        s = level_for(c1 / c0, r["detection_count_ratio"])
        if s:
            sevs.append(s)
            lines.append(f"Active-fire detections: {c0} -> {c1}")
    f0, f1 = prev.get("frp_sum_mw"), new.get("frp_sum_mw")
    if f0 and f1 and f0 > 0:
        s = level_for(f1 / f0, r["frp_ratio"])
        if s:
            sevs.append(s)
            lines.append(f"Total FRP: {f0:.0f} -> {f1:.0f} MW")
    sev = max_sev(*sevs)
    if not sev:
        return None
    return AlertCandidate("FIRE_ACTIVITY_CHANGE", sev, "FIRE ACTIVITY CHANGE", lines,
                          {"detection_count": [c0, c1], "frp_sum_mw": [f0, f1]})


def prediction_change(prev_steps: list[dict], new_steps: list[dict], prob_diffs: dict[str, float] | None = None,
                      cause: str | None = None) -> AlertCandidate | None:
    r = rules()["prediction_change"]
    prev = {s["label"]: s for s in prev_steps if s.get("status") == "ok"}
    sevs, lines, det = [], [], {}
    for s in new_steps:
        if s.get("status") != "ok" or s["label"] not in prev:
            continue
        a0, a1 = prev[s["label"]]["predicted_area_km2"], s["predicted_area_km2"]
        if max(a0, a1) < r["min_area_km2"]:
            continue
        pct = (a1 - a0) / a0 * 100 if a0 > 0 else float("inf")
        lv = level_for(abs(pct), r["area_change_pct"])
        pd_ = (prob_diffs or {}).get(s["label"])
        lv = max_sev(lv, level_for(pd_, r["mean_abs_prob_diff"]) if pd_ is not None else None)
        det[s["label"]] = {"previous_area_km2": a0, "new_area_km2": a1, "change_pct": pct, "mean_abs_prob_diff": pd_}
        if lv:
            sevs.append(lv)
            lines.append(f"{s['label']} predicted area: {a0:.2f} -> {a1:.2f} km²")
    sev = max_sev(*sevs)
    if not sev:
        return None
    if cause:
        lines.append(f"Cause: {cause}")
    return AlertCandidate("PREDICTION_CHANGE", sev, "PREDICTION UPDATE", lines, det)


def spread_risk_change(prev_steps: list[dict], new_steps: list[dict]) -> AlertCandidate | None:
    horizons = set(rules()["spread_risk_change"]["edge_reached_horizons"])
    was = {s["label"] for s in prev_steps if s.get("touches_window_edge")}
    newly = [s for s in new_steps if s.get("touches_window_edge") and s["horizon_min"] in horizons and s["label"] not in was]
    if not newly:
        return None
    labels = ", ".join(s["label"] for s in newly)
    return AlertCandidate("SPREAD_RISK_CHANGE", "WARNING", "SPREAD EXTENT", [
        f"Predicted spread reaches the analysis-window edge at {labels}",
        "Spread beyond the window is not modelled; consider a larger window"], {"horizons": labels})
