"""Live data catalogue must be honest about engines and usage (docs/scientific_audit.md)."""
import pytest

from geo import registry

needs_wtrs = pytest.mark.skipif(not registry.path("data/processed/training/wtrs-ncal-v1/manifest.json").exists(),
                                reason="WTRS dataset not generated")


@needs_wtrs
def test_catalog_status_is_live_and_honest(client):
    cat = client.get("/api/data/catalog").json()
    wtrs = next(e for e in cat["entries"] if e["source"].startswith("WTRS"))
    assert wtrs["status"] == "Generated" and wtrs["engine"] == "Rothermel + MTT" and wtrs["group"] == "simulated"
    assert "FARSITE" not in wtrs["engine"] and wtrs["live"]["valid_samples"] == 22505
    far = next(e for e in cat["entries"] if e["source"].startswith("FARSITE"))
    assert far["group"] == "external" and far["used_in_training"] is False
    assert far["status"] in ("Not present", "Files present · not imported", "Imported")
    sev = next(e for e in cat["entries"] if e["source"].startswith("MTBS thematic"))
    assert sev["used_in_training"] is False and "not yet used" in sev["status"]
    assert all(not e["used_in_training"] for e in cat["entries"] if e["source"].startswith("NASA FIRMS"))
    assert {s["status"] for s in cat["software"]} <= {"Installed", "Not detected"}


def test_models_report_training_provenance(client):
    for m in client.get("/api/models").json()["models"]:
        assert m["physics_informed"] == (m["model_type"] == "physics_fno")
        if m["training_data"]:
            assert m["training_data"]["simulation_source"] == "WTRS"
