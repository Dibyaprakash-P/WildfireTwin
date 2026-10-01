"""Trained-model registry: discovers checkpoints under data/models/<type>/latest.json."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import torch

from backend.app.config import get_settings
from geo import registry
from ml.datasets.provenance import dataset_card
from ml.models.factory import DISPLAY_NAMES, MODEL_TYPES, load_checkpoint, select_device

log = logging.getLogger(__name__)


@dataclass
class LoadedModel:
    model_type: str
    run_id: str
    checkpoint: str
    dataset_version: str
    model: torch.nn.Module
    device: torch.device
    config: dict
    val: dict
    n_params: int | None

    @property
    def version(self) -> str:
        return f"{self.model_type}:{self.run_id}"


class ModelRegistry:
    def __init__(self) -> None:
        self._loaded: dict[str, LoadedModel] = {}
        self._lock = threading.Lock()

    @staticmethod
    def latest_info(mtype: str) -> dict | None:
        p = registry.path(f"data/models/{mtype}/latest.json")
        if not p.exists():
            return None
        info = json.loads(p.read_text())
        run_dir = registry.path(info["path"].replace("\\", "/"))   # runs trained on Windows store backslashes
        summary = run_dir / "summary.json"
        info["summary"] = json.loads(summary.read_text()) if summary.exists() else None
        info["checkpoint"] = (run_dir / "model.pt").relative_to(registry.REPO_ROOT).as_posix()
        info["exists"] = (run_dir / "model.pt").exists()
        return info

    def status(self) -> list[dict]:
        out = []
        for t in MODEL_TYPES:
            info = self.latest_info(t)
            ds_version = ((info or {}).get("summary") or {}).get("dataset_version")
            out.append({"model_type": t, "name": DISPLAY_NAMES[t], "trained": bool(info and info["exists"]),
                        "training_data": dataset_card(ds_version) if ds_version else None,
                        "physics_informed": t == "physics_fno",
                        "run_id": info["run_id"] if info else None,
                        "checkpoint": info["checkpoint"] if info else None,
                        "summary": info["summary"] if info else None,
                        "loaded": t in self._loaded})
        return out

    def get(self, mtype: str) -> LoadedModel | None:
        with self._lock:
            info = self.latest_info(mtype)
            if not info or not info["exists"]:
                return None
            cur = self._loaded.get(mtype)
            if cur and cur.run_id == info["run_id"]:
                return cur
            pref = get_settings().inference_device
            device = select_device("cpu" if pref == "cpu" else "auto")
            model, ck = load_checkpoint(registry.REPO_ROOT / Path(info["checkpoint"]), device)
            lm = LoadedModel(mtype, info["run_id"], info["checkpoint"], ck.get("dataset_version", "?"), model, device,
                             ck["config"], ck.get("val", {}), ck.get("n_params"))
            self._loaded[mtype] = lm
            log.info("loaded model %s on %s", lm.version, device)
            return lm

    def default_type(self) -> str | None:
        pref = get_settings().default_model
        order = [pref] + [t for t in ("physics_fno", "fno", "unet") if t != pref]
        for t in order:
            info = self.latest_info(t)
            if info and info["exists"]:
                return t
        return None


model_registry = ModelRegistry()
