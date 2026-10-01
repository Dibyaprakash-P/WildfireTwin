"""Evaluate trained models on the held-out TEST split (unseen spatial blocks).

Usage:  python -m ml.evaluation.evaluate_models [--max-samples N] [--speedup-samples N]

Writes data/models/evaluation/results.json. Only models with a completed
training run (data/models/<type>/latest.json) are evaluated; others are
reported as "not_evaluated".

Reported for each model:
  * mean per-sample metrics (see ml.evaluation.metrics) overall and per horizon
  * inference time: median wall-clock ms per sample, batch size 1, on the
    evaluation device (CUDA-synchronised)
  * speed-up: median WTRS reference re-simulation time for the same
    (t0 state -> t0 + h) on CPU divided by median model inference time.
A persistence baseline (predict "no further growth" = initial mask) is
included as a trivial reference.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import time
from datetime import datetime, timezone

import numpy as np
import torch

from geo import registry
from geo.landscape import Landscape
from geo.rasters import AnalysisGrid
from ml.datasets.dataset import WildfireDataset
from ml.evaluation.metrics import aggregate, mask_metrics
from ml.features import CHANNELS, HORIZON_LABELS
from ml.models.factory import DISPLAY_NAMES, MODEL_TYPES, load_checkpoint, select_device
from simulation.reference import WeatherSeries, mask_ignition, run_reference
from simulation.weather_sources import HISTORY_HOURS

log = logging.getLogger("evaluate")
OUT = registry.path("data/models/evaluation/results.json")
FIRE_CH = CHANNELS.index("fire_t0")


def _latest(mtype: str):
    p = registry.path(f"data/models/{mtype}/latest.json")
    if not p.exists():
        return None
    info = json.loads(p.read_text())
    return registry.path(info["path"].replace("\\", "/")) / "model.pt", info["run_id"]


@torch.no_grad()
def predict_all(model, ds: WildfireDataset, device, bs: int = 16) -> list[np.ndarray]:
    probs = []
    for i in range(0, len(ds), bs):
        xs = torch.stack([ds[j]["x"] for j in range(i, min(i + bs, len(ds)))]).to(device)
        probs.extend(torch.sigmoid(model(xs)).cpu().numpy()[:, 0])
    return probs


@torch.no_grad()
def time_inference(model, ds: WildfireDataset, device, n: int = 100) -> float:
    xs = [ds[i]["x"][None].to(device) for i in range(min(n, len(ds)))]
    for x in xs[:10]:
        model(x)
    times = []
    for x in xs:
        if device.type == "cuda":
            torch.cuda.synchronize()
        t = time.perf_counter()
        model(x)
        if device.type == "cuda":
            torch.cuda.synchronize()
        times.append((time.perf_counter() - t) * 1000)
    return float(np.median(times))


def resimulate_ms(ds: WildfireDataset, n: int, seed: int = 0) -> tuple[float, int]:
    """Median WTRS runtime (ms) to advance the t0 state by the horizon, for n test samples."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(ds), size=min(n, len(ds)), replace=False)
    times = []
    for i in idx:
        row = ds.samples.iloc[i]
        sc = ds.scen.loc[row["scenario_id"]]
        z = ds._scenario(row["scenario_id"])
        grid = AnalysisGrid(**json.loads(sc["grid"]))
        land = Landscape(grid, z["elevation_m"], z["slope_deg"].astype(np.float32), z["aspect_deg"].astype(np.float32),
                         z["fuel_code"], None)
        t0, hz = float(row["t0_min"]), float(row["horizon_min"])
        k0 = int(t0 // 60)
        H = HISTORY_HOURS
        ws = WeatherSeries(z["w_temp"][H + k0:], z["w_rh"][H + k0:], z["w_u"][k0:], z["w_v"][k0:], z["w_precip"][H + k0:],
                           z["w_temp"][:H + k0], z["w_rh"][:H + k0], z["w_precip"][:H + k0], "ERA5", str(sc["start_utc"]))
        m0 = z["arrival_min"] <= t0
        r = run_reference(land, ws, mask_ignition(m0), hz / 60.0, float(sc["live_herb"]), float(sc["live_woody"]))
        times.append(r.result.runtime_s * 1000)
    return float(np.median(times)), len(times)


def strict_mask(ds: WildfireDataset) -> tuple[np.ndarray, dict]:
    """True for test samples whose analysis window does not overlap ANY training window (any band).

    The split assigns scenarios to spatial blocks by ignition location; windows near block borders can still cover
    terrain that appears in training windows. This subset removes that partial landscape overlap.
    """
    from shapely.geometry import box
    from shapely.strtree import STRtree
    sc = ds.scen
    train = [box(*json.loads(b)) for b in sc.loc[sc["split"] == "train", "bbox_wgs84"]]
    tree = STRtree(train)
    clean = {}
    for sid in ds.samples["scenario_id"].unique():
        g = box(*json.loads(sc.loc[sid, "bbox_wgs84"]))
        clean[sid] = not any(g.intersects(train[i]) and g.intersection(train[i]).area > 0 for i in tree.query(g))
    m = ds.samples["scenario_id"].map(clean).to_numpy(dtype=bool)
    return m, {"criterion": "test window has zero area overlap with every training window (all bands)",
               "scenarios": int(sum(clean.values())), "samples": int(m.sum())}


def evaluate(max_samples: int | None, speedup_samples: int) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    device = select_device()
    results = {"generated_utc": datetime.now(timezone.utc).isoformat(), "split": "test",
               "split_strategy": "spatial blocks of 0.5 deg assigned by ignition location (scenarios never shared; 54% of test windows partly overlap training landscapes - see strict subset)",
               "device": str(device), "device_name": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
               "threshold": 0.5, "models": {},
               "evaluated_against": "WTRS reference simulations (simulated; Rothermel + MTT) - not observed ground truth"}
    from ml.datasets.provenance import dataset_card
    ds = None
    for mtype in MODEL_TYPES:
        lt = _latest(mtype)
        if lt is None:
            results["models"][mtype] = {"name": DISPLAY_NAMES[mtype], "status": "not_evaluated",
                                        "reason": "no trained checkpoint"}
            continue
        ck_path, run_id = lt
        model, ck = load_checkpoint(ck_path, device)
        if ds is None:
            ds = WildfireDataset(ck["dataset_version"], "test", augment=False, max_samples=max_samples, seed=7)
            results["dataset_version"] = ck["dataset_version"]
            results["test_samples"] = len(ds)
            results["reference"] = dataset_card(ck["dataset_version"])
            strict, strict_info = strict_mask(ds)
            results["strict_test"] = strict_info
        log.info("evaluating %s (%s) on %d samples", mtype, run_id, len(ds))
        probs = predict_all(model, ds, device)
        rows = []
        for i, p in enumerate(probs):
            s = ds.load(i)
            m = mask_metrics(p, s.y.numpy()[0], s.x.numpy()[FIRE_CH], s.meta["cell_m"])
            m["horizon_min"] = s.meta["horizon_min"]
            rows.append(m)
        results["models"][mtype] = {
            "name": DISPLAY_NAMES[mtype], "status": "evaluated", "run_id": run_id, "checkpoint": ck_path.relative_to(registry.REPO_ROOT).as_posix(),
            "n_params": ck.get("n_params"), "overall": aggregate(rows),
            "per_horizon": {HORIZON_LABELS[int(h)]: aggregate([r for r in rows if r["horizon_min"] == h])
                            for h in sorted({r["horizon_min"] for r in rows})},
            "strict_overall": aggregate([r for r, k in zip(rows, strict) if k]),
            "inference_ms": time_inference(model, ds, device),
            "inference_device": str(device),
            "inference_ms_cpu": time_inference(copy.deepcopy(model).cpu(), ds, torch.device("cpu"), n=30),
        }
    if ds is not None:
        rows = []
        for i in range(len(ds)):
            s = ds.load(i)
            m0 = s.x.numpy()[FIRE_CH]
            m = mask_metrics(m0, s.y.numpy()[0], m0, s.meta["cell_m"])
            m["horizon_min"] = s.meta["horizon_min"]
            rows.append(m)
        results["persistence_baseline"] = {"name": "Persistence (no growth)", "overall": aggregate(rows),
                                           "strict_overall": aggregate([r for r, k in zip(rows, strict) if k])}
        sim_ms, n_sim = resimulate_ms(ds, speedup_samples)
        results["reference_simulation"] = {"simulator": "WTRS-Rothermel-MTT", "median_ms": sim_ms, "samples": n_sim,
                                           "device": "cpu (single-threaded Python)"}
        for v in results["models"].values():
            if v["status"] == "evaluated":
                v["speedup_vs_reference"] = sim_ms / v["inference_ms"] if v["inference_ms"] > 0 else None
                v["speedup_vs_reference_cpu"] = sim_ms / v["inference_ms_cpu"] if v["inference_ms_cpu"] > 0 else None
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2))
    log.info("wrote %s", OUT)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--speedup-samples", type=int, default=150)
    a = ap.parse_args()
    evaluate(a.max_samples, a.speedup_samples)


if __name__ == "__main__":
    main()
