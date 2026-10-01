"""Scientific-consistency guarantees (see docs/scientific_audit.md)."""
import pandas as pd
import pytest

from geo import registry
from ml.datasets import dataset as ds_mod
from ml.datasets.provenance import dataset_card

WTRS = registry.path("data/processed/training/wtrs-ncal-v1")
needs_wtrs = pytest.mark.skipif(not (WTRS / "manifest.json").exists(), reason="WTRS dataset not generated")


@needs_wtrs
def test_wtrs_rows_are_labelled_wtrs_not_farsite():
    for name in ("scenarios", "samples"):
        df = pd.read_parquet(WTRS / f"{name}.parquet", columns=["simulation_source", "reference_engine"])
        assert set(df["simulation_source"]) == {"WTRS"}
        assert set(df["reference_engine"]) == {"WTRS-Rothermel-MTT"}
        assert not df["reference_engine"].str.contains("FARSITE|FlamMap", case=False).any()


@needs_wtrs
def test_dataset_card_identifies_reference_method():
    card = dataset_card("wtrs-ncal-v1")
    assert card["simulation_source"] == "WTRS" and "Rothermel" in card["simulation_method"]
    assert "FARSITE" not in card["simulation_method"]
    assert card["forecast_horizons_min"] == [10, 30, 60, 360, 720, 1440, 2880, 4320]


def test_loader_refuses_mixed_engines(tmp_path, monkeypatch):
    d = tmp_path / "mixed-v1"
    d.mkdir()
    rows = [{"scenario_id": "a", "split": "train", "valid": True, "simulation_source": "WTRS"},
            {"scenario_id": "b", "split": "train", "valid": True, "simulation_source": "FARSITE"}]
    pd.DataFrame(rows).to_parquet(d / "samples.parquet")
    pd.DataFrame([{"scenario_id": "a"}, {"scenario_id": "b"}]).to_parquet(d / "scenarios.parquet")
    monkeypatch.setattr(ds_mod, "dataset_dir", lambda v: tmp_path / v)
    with pytest.raises(ValueError, match="mixes reference engines"):
        ds_mod.WildfireDataset("mixed-v1", "train")
