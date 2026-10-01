"""Resolve data-source paths from config/data_sources.yaml."""

from __future__ import annotations

import glob
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "data_sources.yaml"


@lru_cache(maxsize=1)
def sources() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def path(rel: str) -> Path:
    return REPO_ROOT / rel


def glob_paths(pattern: str) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(REPO_ROOT / pattern)))


def study_bbox() -> tuple[float, float, float, float]:
    w, s, e, n = sources()["study_region"]["bbox_wgs84"]
    return float(w), float(s), float(e), float(n)


def analysis_crs() -> str:
    return sources()["study_region"]["analysis_crs"]
