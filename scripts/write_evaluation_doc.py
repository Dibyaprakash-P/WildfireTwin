"""Render docs/evaluation.md from data/models/evaluation/results.json (measured values only).

Usage: python -m scripts.write_evaluation_doc
"""

from __future__ import annotations

import json

from geo import registry

R = registry.REPO_ROOT
ORDER = ["unet", "fno", "physics_fno"]
COLS = [("iou", "IoU", 3), ("dice", "Dice", 3), ("growth_iou", "Growth IoU", 3), ("growth_f1", "Growth F1", 3),
        ("precision", "Precision", 3), ("recall", "Recall", 3), ("hausdorff_m", "Hausdorff (m)", 0),
        ("hd95_m", "HD95 (m)", 0), ("mae", "MAE", 4), ("area_error_pct", "Area error (%)", 1)]


def f(v, d):
    return "n/a" if v is None or v != v else f"{v:.{d}f}"


def main() -> None:
    p = R / "data/models/evaluation/results.json"
    head = ["# Evaluation", ""]
    if not p.exists():
        (R / "docs/evaluation.md").write_text("\n".join(head + ["**Not evaluated.** Run `python -m ml.evaluation.evaluate_models`."]))
        return
    r = json.loads(p.read_text())
    L = head + [
        f"_Generated from `data/models/evaluation/results.json` ({r['generated_utc'][:19]}Z). All values are measured; nothing is hand-entered._",
        "",
        "## Protocol",
        f"* Test split: {r['split_strategy']}; **{r.get('test_samples', 'n/a')} samples**; dataset `{r.get('dataset_version', 'n/a')}`.",
        "* Evaluated against: **WTRS reference simulations (simulated; internal Rothermel + MTT pipeline, not FARSITE)** - "
        "not observed ground truth. Probability threshold 0.5.",
        f"* Reference dataset: `{(r.get('reference') or {}).get('dataset_version', r.get('dataset_version'))}`, "
        f"simulation_source `{(r.get('reference') or {}).get('simulation_source', 'n/a')}`, "
        f"engine `{(r.get('reference') or {}).get('reference_engine', 'n/a')}`.",
        "* Observed-data comparisons (predicted vs FIRMS footprints) are single-case historical replays, reported separately "
        "in the app; they are not part of this table.",
        "* Growth metrics are computed on cells that were *not* burning at t0 (the initial fire is an input, so full-mask "
        "IoU/Dice are inflated by it). Hausdorff distances are between mask boundaries, in metres.",
        f"* Inference time: median per sample, batch 1, on {r['device_name']} ({r['device']}) and on CPU.",
        "* Speed-up: median WTRS re-simulation time for the same t0→t0+h step (CPU, Python) ÷ median model time.",
        "",
        "## Overall (all horizons)",
        "",
        "| Model | " + " | ".join(c[1] for c in COLS) + " | Inference GPU (ms) | Inference CPU (ms) | Speed-up GPU | Speed-up CPU |",
        "|---|" + "---|" * (len(COLS) + 4),
    ]
    for t in ORDER:
        m = r["models"].get(t, {})
        if m.get("status") != "evaluated":
            L.append(f"| {m.get('name', t)} | " + " | ".join(["Not evaluated"] * (len(COLS) + 4)) + " |")
            continue
        o = m["overall"]
        L.append(f"| {m['name']} | " + " | ".join(f(o.get(k), d) for k, _, d in COLS)
                 + f" | {f(m['inference_ms'], 2)} | {f(m['inference_ms_cpu'], 1)} | {f(m.get('speedup_vs_reference'), 0)}× | {f(m.get('speedup_vs_reference_cpu'), 1)}× |")
    if "persistence_baseline" in r:
        o = r["persistence_baseline"]["overall"]
        L.append(f"| _{r['persistence_baseline']['name']}_ | " + " | ".join(f(o.get(k), d) for k, _, d in COLS) + " | — | — | — | — |")
    rs = r.get("reference_simulation")
    if rs:
        L += ["", f"Reference re-simulation: median {rs['median_ms']:.1f} ms over {rs['samples']} test samples ({rs['device']})."]
    st = r.get("strict_test")
    if st:
        L += ["", f"## Strict test subset ({st['samples']} samples, {st['scenarios']} scenarios)", "",
              f"Criterion: {st['criterion']}. The split assigns scenarios to 0.5° blocks by ignition location; 128x128 "
              "windows near block borders can cover terrain also seen in training windows. This subset removes that overlap.", "",
              "| Model | IoU | Dice | Growth IoU | Growth F1 | Hausdorff (m) |", "|---|---|---|---|---|---|"]
        for t in ORDER:
            m = r["models"].get(t, {})
            so = m.get("strict_overall")
            if m.get("status") == "evaluated" and so:
                L.append(f"| {m['name']} | {f(so['iou'], 3)} | {f(so['dice'], 3)} | {f(so['growth_iou'], 3)} | {f(so['growth_f1'], 3)} | {f(so['hausdorff_m'], 0)} |")
        ps = (r.get("persistence_baseline") or {}).get("strict_overall")
        if ps:
            L.append(f"| _Persistence (no growth)_ | {f(ps['iou'], 3)} | {f(ps['dice'], 3)} | {f(ps['growth_iou'], 3)} | {f(ps['growth_f1'], 3)} | {f(ps['hausdorff_m'], 0)} |")
    L += ["", "## Per horizon — Growth IoU / IoU / Hausdorff (m)", ""]
    labels = None
    for t in ORDER:
        m = r["models"].get(t, {})
        if m.get("status") == "evaluated":
            labels = list(m["per_horizon"].keys())
            break
    if labels:
        L += ["| Model | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
        for t in ORDER:
            m = r["models"].get(t, {})
            if m.get("status") != "evaluated":
                continue
            cells = [f"{f(m['per_horizon'][h]['growth_iou'], 3)} / {f(m['per_horizon'][h]['iou'], 3)} / {f(m['per_horizon'][h]['hausdorff_m'], 0)}"
                     for h in labels]
            L.append(f"| {m['name']} | " + " | ".join(cells) + " |")
    L += ["", "## Training runs", "", "| Model | Run | Params | Best epoch | Val growth IoU | Train time (min) |", "|---|---|---|---|---|---|"]
    for t in ORDER:
        lt = R / f"data/models/{t}/latest.json"
        if not lt.exists():
            continue
        info = json.loads(lt.read_text())
        s = json.loads((R / info["path"].replace("\\", "/") / "summary.json").read_text())
        L.append(f"| {t} | {s['run_id']} | {s['n_params']:,} | {s['best_epoch']} / {s['epochs_run']} | {s['best_val_growth_iou']:.3f} | {s['train_seconds'] / 60:.1f} |")
    L += ["", "## Interpretation guidance", "",
          "* Rankings are not asserted here; differences should be judged together with the per-horizon table and with",
          "  the fact that all models share data, features, augmentation and training budget.",
          "* Results measure agreement with the reference simulator on unseen landscapes, not real-world forecast skill.",
          "  Single-case comparisons with observed FIRMS footprints are available through the Historical replay page.",
          ""]
    (R / "docs/evaluation.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote docs/evaluation.md")


if __name__ == "__main__":
    main()
