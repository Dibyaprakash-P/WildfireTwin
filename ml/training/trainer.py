"""Shared training loop for U-Net, FNO and PI-FNO.

Artifacts (data/models/<type>/<run_id>/):
    model.pt         best checkpoint (state_dict + config + channel list + dataset version)
    config.yaml      exact configuration used
    history.csv      per-epoch train/val losses and val metrics
    loss_curve.png   training / validation loss curves
    summary.json     best epoch, best val metrics, device, timings
data/models/<type>/latest.json points at the most recent completed run.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch.utils.data import DataLoader

from geo import registry
from ml.datasets.dataset import WildfireDataset
from ml.features import CHANNELS
from ml.models.factory import build_model, select_device
from ml.models.physics_fno.physics import PhysicsWeights, physics_losses, reference_residual

log = logging.getLogger("train")
FIRE_CH, BURN_CH = CHANNELS.index("fire_t0"), CHANNELS.index("burnable")
MODELS_DIR = registry.path("data/models")


def seed_everything(seed: int) -> None:
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def dice_loss(logits: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    p = torch.sigmoid(logits)
    inter = (p * y).sum(dim=(1, 2, 3))
    return (1 - (2 * inter + 1) / (p.sum(dim=(1, 2, 3)) + y.sum(dim=(1, 2, 3)) + 1)).mean()


def compute_losses(model, batch, cfg, device, epoch: int) -> dict[str, torch.Tensor]:
    x, y = batch["x"].to(device), batch["y"].to(device)
    tcfg = cfg["training"]
    is_pi = cfg["model"]["type"] == "physics_fno"
    if is_pi:
        tau = model.forward_tau(x)
        logits = model.logits_from_tau(tau)
    else:
        logits = model(x)
    out = {"bce": F.binary_cross_entropy_with_logits(logits, y), "dice": dice_loss(logits, y)}
    total = tcfg["bce_weight"] * out["bce"] + tcfg["dice_weight"] * out["dice"]
    if is_pi:
        out["tau"] = F.smooth_l1_loss(tau, batch["tau"].to(device), beta=0.1)
        total = total + tcfg.get("tau_weight", 1.0) * out["tau"]
        pc = cfg["physics"]
        if pc.get("enabled", True):
            ramp = min(1.0, (epoch + 1) / max(1, pc.get("warmup_epochs", 1)))
            pw = PhysicsWeights(pc["lambda_eik"] * ramp, pc["lambda_mono"] * ramp, pc["lambda_nb"] * ramp)
            ph = physics_losses(tau, x, batch["phys"].to(device), batch["horizon_min"].to(device),
                                batch["cell_m"].to(device), BURN_CH, FIRE_CH, pw)
            out.update({f"phys_{k}": v for k, v in ph.items()})
            total = total + ph["physics"]
    out["total"] = total
    out["_logits"] = logits
    return out


@torch.no_grad()
def batch_scores(logits: torch.Tensor, y: torch.Tensor, x: torch.Tensor) -> tuple[float, float, float, float]:
    """Return summed (tp, fp+fn) for full mask and growth region, micro-averaged over the batch."""
    pred = logits > 0
    t = y > 0.5
    m0 = x[:, FIRE_CH:FIRE_CH + 1] > 0.5
    tp = (pred & t).sum().item(); err = (pred ^ t).sum().item()
    gp, gt = pred & ~m0, t & ~m0
    gtp = (gp & gt).sum().item(); gerr = (gp ^ gt).sum().item()
    return tp, err, gtp, gerr


def run(cfg: dict, dev: bool = False, max_train: int | None = None) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seed_everything(cfg["experiment"]["seed"])
    device = select_device()
    mtype = cfg["model"]["type"]
    run_id = f"{mtype}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    out = MODELS_DIR / mtype / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    dcfg, tcfg = cfg["data"], cfg["training"]
    if dev:
        tcfg = tcfg | {"epochs": 2, "batch_size": 4}
        cfg["training"] = tcfg
        max_train = max_train or 64
    train_ds = WildfireDataset(dcfg["dataset_version"], "train", dcfg["bands"], augment=dcfg.get("augment", True),
                               max_samples=max_train, seed=cfg["experiment"]["seed"])
    val_ds = WildfireDataset(dcfg["dataset_version"], "val", dcfg["bands"], augment=False,
                             max_samples=32 if dev else 1500, seed=1)
    nw = 0 if dev else int(os.environ.get("WT_WORKERS", "4"))
    kw = dict(num_workers=nw, persistent_workers=nw > 0, pin_memory=device.type == "cuda")
    g = torch.Generator(); g.manual_seed(cfg["experiment"]["seed"])
    train_dl = DataLoader(train_ds, batch_size=tcfg["batch_size"], shuffle=True, drop_last=True, generator=g, **kw)
    val_dl = DataLoader(val_ds, batch_size=tcfg["batch_size"], shuffle=False, **kw)

    model = build_model(cfg).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["learning_rate"], weight_decay=tcfg["weight_decay"])
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=tcfg["learning_rate"], total_steps=tcfg["epochs"] * len(train_dl))
    log.info("model=%s params=%d device=%s train=%d val=%d", mtype, n_params, device, len(train_ds), len(val_ds))

    mlf = _mlflow_start(cfg, run_id)
    history, best, best_epoch, patience = [], -1.0, -1, 0
    t_start = time.time()
    for epoch in range(tcfg["epochs"]):
        model.train()
        sums: dict[str, float] = {}
        n = 0
        te = time.time()
        for batch in train_dl:
            losses = compute_losses(model, batch, cfg, device, epoch)
            opt.zero_grad(set_to_none=True)
            losses["total"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step()
            for k, v in losses.items():
                if not k.startswith("_"):
                    sums[k] = sums.get(k, 0.0) + float(v.detach())
            n += 1
        row = {"epoch": epoch, **{f"train_{k}": v / max(n, 1) for k, v in sums.items()}, "epoch_s": time.time() - te}
        row.update(validate(model, val_dl, cfg, device, epoch))
        history.append(row)
        log.info("epoch %d %s", epoch, {k: round(v, 4) for k, v in row.items() if isinstance(v, float)})
        if mlf:
            mlf.log_metrics({k: v for k, v in row.items() if isinstance(v, (int, float))}, step=epoch)
        score = row["val_growth_iou"]
        if score > best:
            best, best_epoch, patience = score, epoch, 0
            torch.save({"state_dict": model.state_dict(), "config": cfg, "channels": CHANNELS, "epoch": epoch,
                        "val": {k: v for k, v in row.items() if k.startswith("val_")}, "run_id": run_id,
                        "dataset_version": dcfg["dataset_version"], "n_params": n_params}, out / "model.pt")
        else:
            patience += 1
            if patience >= tcfg["early_stopping_patience"]:
                log.info("early stopping at epoch %d (best %d)", epoch, best_epoch)
                break
    _write_history(out, history)
    summary = {"run_id": run_id, "model_type": mtype, "best_epoch": best_epoch, "best_val_growth_iou": best,
               "best_val": history[best_epoch] if best_epoch >= 0 else None, "epochs_run": len(history),
               "train_seconds": time.time() - t_start, "device": str(device),
               "device_name": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
               "n_params": n_params, "dataset_version": dcfg["dataset_version"], "dev_mode": dev,
               "train_samples": len(train_ds), "val_samples": len(val_ds),
               "finished_utc": datetime.now(timezone.utc).isoformat()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    if not dev:
        (MODELS_DIR / mtype / "latest.json").write_text(json.dumps({"run_id": run_id, "path": out.relative_to(registry.REPO_ROOT).as_posix()}))
    if mlf:
        mlf.log_artifacts(str(out)); mlf.end_run()
    return out


@torch.no_grad()
def validate(model, dl, cfg, device, epoch) -> dict[str, float]:
    model.eval()
    sums: dict[str, float] = {}
    n = 0
    tp = err = gtp = gerr = 0.0
    resid = []
    for batch in dl:
        losses = compute_losses(model, batch, cfg, device, epoch)
        for k, v in losses.items():
            if not k.startswith("_"):
                sums[k] = sums.get(k, 0.0) + float(v)
        a, b, c, d = batch_scores(losses["_logits"], batch["y"].to(device), batch["x"].to(device))
        tp += a; err += b; gtp += c; gerr += d
        if cfg["model"]["type"] == "physics_fno" and epoch == 0:
            resid.append(reference_residual(batch["tau"].to(device), batch["x"].to(device), batch["phys"].to(device),
                                            batch["horizon_min"].to(device), batch["cell_m"].to(device), BURN_CH, FIRE_CH))
        n += 1
    out = {f"val_{k}": v / max(n, 1) for k, v in sums.items()}
    out["val_iou"] = tp / (tp + err) if tp + err else float("nan")
    out["val_growth_iou"] = gtp / (gtp + gerr) if gtp + gerr else float("nan")
    if resid:
        out["reference_eikonal_abs_log_residual"] = float(np.mean(resid))
    return out


def _write_history(out: Path, history: list[dict]) -> None:
    keys = sorted({k for r in history for k in r})
    with open(out / "history.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader(); w.writerows(history)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ep = [r["epoch"] for r in history]
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.5))
        ax[0].plot(ep, [r["train_total"] for r in history], label="train")
        ax[0].plot(ep, [r["val_total"] for r in history], label="val")
        ax[0].set_title("total loss"); ax[0].set_xlabel("epoch"); ax[0].legend()
        ax[1].plot(ep, [r["val_iou"] for r in history], label="val IoU")
        ax[1].plot(ep, [r["val_growth_iou"] for r in history], label="val growth IoU")
        ax[1].set_xlabel("epoch"); ax[1].legend()
        fig.tight_layout(); fig.savefig(out / "loss_curve.png", dpi=110); plt.close(fig)
    except Exception as exc:  # plotting is optional
        log.warning("loss curve not written: %s", exc)


def _mlflow_start(cfg: dict, run_id: str):
    if os.environ.get("WT_MLFLOW", "1") != "1":
        return None
    try:
        import mlflow
    except Exception:
        return None
    try:
        mlflow.set_tracking_uri("sqlite:///" + (registry.REPO_ROOT / "mlflow.db").as_posix())
        mlflow.set_experiment(cfg["experiment"]["name"])
        mlflow.start_run(run_name=run_id)
        flat = {"model": cfg["model"]["type"], "dataset_version": cfg["data"]["dataset_version"],
                **{f"model.{k}": v for k, v in cfg["model"].items()},
                **{f"train.{k}": v for k, v in cfg["training"].items()},
                **{f"physics.{k}": v for k, v in cfg.get("physics", {}).items()}}
        mlflow.log_params(flat)
        return mlflow
    except Exception as exc:
        log.warning("MLflow disabled: %s", exc)
        return None


def cli(default_config: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(registry.REPO_ROOT / "ml" / "configs" / default_config))
    ap.add_argument("--dev", action="store_true", help="tiny CPU/GPU smoke run (2 epochs, 64 samples)")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--max-train", type=int)
    a = ap.parse_args()
    cfg = yaml.safe_load(Path(a.config).read_text())
    if a.epochs:
        cfg["training"]["epochs"] = a.epochs
    path = run(cfg, dev=a.dev, max_train=a.max_train)
    print(f"artifacts: {path}")
