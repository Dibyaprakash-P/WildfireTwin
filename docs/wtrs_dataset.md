# WTRS Dataset — `wtrs-ncal-v1`

Every value below was read from the code (`ml/datasets/generate.py`, `simulation/*`), the configuration
(`ml/configs/dataset.yaml`) or the generated files (`data/processed/training/wtrs-ncal-v1/`) during the scientific
audit (2026-10-01). Where something is not recorded, it says so.

## Identity

| Field | Value |
|---|---|
| dataset_version | `wtrs-ncal-v1` |
| simulation_source | `WTRS` (WildfireTwin Reference Simulator — internal pipeline) |
| reference_engine | `WTRS-Rothermel-MTT`, simulator version `1.0.0` |
| simulation_method | Rothermel (1972) surface rate of spread with Scott & Burgan (2005) FBFM40 fuels, Anderson (1983) elliptical fire shape, minimum-travel-time growth (time-dependent Dijkstra on a 16-neighbour stencil), hourly ERA5 weather |
| FARSITE / FlamMap involved | **No.** No FARSITE or FlamMap executable or output was used to produce any sample. |
| data class | simulated (reference simulation — not observed ground truth) |
| generated | 2026-10-01 05:43:51 UTC, 7 worker processes, 554 s total |
| location | `data/processed/training/wtrs-ncal-v1/` — `scenarios/<id>.npz`, `scenarios.parquet`, `samples.parquet`, `manifest.json` |
| provenance columns | `simulation_source`, `reference_engine`, `simulation_method`, `source_version` on every scenario and sample row (added non-destructively during the audit; originals kept as `*.pre_provenance.parquet`) |

## Scenario generation

| Item | Implementation |
|---|---|
| Region | study bbox 40–42°N, 124.5–122°W (N. California); a window is accepted only if ≥ 98 % of SRTM and LANDFIRE cells are valid |
| Ignition | location drawn uniformly in the bbox; ignition = a random **burnable** cell inside the central 40–60 % of the 128×128 window; single-cell point ignition |
| Weather | ERA5 hourly (0.25°, bilinear at window centre); start hour drawn uniformly from Jun–Oct 2024 and 2025 hours, then **accepted with probability clip(mean Fosberg FFWI over the first 12 h / 25, 0.1, 1)** — deliberately over-samples fire weather; not climatological |
| Dead fuel moisture | Simard (1968) EMC: 1-h = current EMC, 10-h = 24-h mean, 100-h = 72-h mean; floor 25 % after ≥ 1 mm rain in 24 h (heuristic) |
| Live fuel moisture | scenario parameter, uniform herb 0.30–0.90, woody 0.70–1.20 (fraction); not observed |
| Terrain | SRTM 1″ warped to the window (bilinear ≤ 30 m, average otherwise); Horn slope/aspect |
| Fuel | LANDFIRE 2025 FBFM40 (nearest at 30 m, mode at 60/120 m) |
| Land cover | ESA WorldCover 2021 (stored; used as model input, not by the simulator) — present for 100 % of scenarios |
| Grid | 128 × 128, EPSG:5070, snapped to the LANDFIRE 30 m lattice |
| Random seed | 20260101 (+ per-band, per-scenario offsets) |

| Band | Cell | Scenarios | Simulated duration | t0 (h) | Horizons | Median sim runtime |
|---|---|---|---|---|---|---|
| short | 30 m | 800 | 5 h | 1, 2, 4 | 10, 30, 60 min | 0.04 s |
| medium | 60 m | 800 | 36 h | 2, 6, 12, 24 | 6 h, 12 h | 0.29 s |
| long | 120 m | 800 | 120 h | 6, 12, 24, 48 | 24 h, 48 h, 72 h | 1.12 s |

**Output per scenario:** continuous fire arrival time (minutes) per cell + the hourly weather series (72 h history +
simulated hours). 260 scenarios (11 %) did not spread beyond the ignition cell (e.g. wet fuel or non-spreading
weather); their samples are kept as genuine "no growth" cases.

## Samples

Sample = (state at t0, state at t0 + h) from one scenario: input fire mask = arrival ≤ t0, target = arrival ≤ t0 + h.

| | Count |
|---|---|
| Scenarios | 2,400 |
| Samples | 23,200 |
| Valid samples | **22,505** |
| Invalid — target within 2 cells of the window edge (truncated spread) | 695 |
| Invalid — empty initial fire | 0 |

| Horizon | Samples | Valid | Median growth (cells) |
|---|---|---|---|
| 10 min | 2,400 | 2,399 | 1 |
| 30 min | 2,400 | 2,398 | 3 |
| 1 h | 2,400 | 2,397 | 6 |
| 6 h | 3,200 | 3,147 | 35 |
| 12 h | 3,200 | 3,111 | 88 |
| 24 h | 3,200 | 3,133 | 82 |
| 48 h | 3,200 | 3,026 | 226 |
| 72 h | 3,200 | 2,894 | 420 |

(24 h and 6–12 h are in different bands with different cell sizes, so cell counts are not directly comparable.)

## Split and leakage audit

**Implemented:** the bbox is divided into 20 blocks of 0.5° × 0.5°; whole blocks are assigned (fixed seed) to
train (13), val (3) and test (4). Each scenario is assigned by the block containing its **ignition location**
(verified for all 2,400 scenarios). All samples of a scenario are in the same split.

| Split | Scenarios | Valid samples |
|---|---|---|
| train | 1,529 | 14,447 |
| val | 312 | 2,972 |
| test | 559 | 5,086 |

| Leakage type | Finding |
|---|---|
| Scenario / time-slice overlap | **None** — no scenario contributes to more than one split |
| Spatial (landscape) overlap | **Present.** Windows extend up to 7.7 km (120 m band) beyond the ignition, so they cross block borders. 54 % of test windows (66 % of val) intersect at least one training window; the median overlap fraction for test is 3.8 % but the 90th percentile is 90 % (a small 30 m test window near a border can lie inside a 120 m training window). Earlier documentation understated this. |
| Temporal overlap | **Present by design.** All splits draw weather from the same 2024–2025 fire seasons; there is no temporal hold-out. Different blocks at the same hour can share similar ERA5 weather. |
| Measured effect | Strict test subset with zero window overlap (2,308 samples, 257 scenarios): growth IoU changes by ≤ 0.007 for every model (see `docs/evaluation.md`), so the landscape overlap does not materially inflate the reported scores. |

## What is not documented in the current implementation

* The exact ignition-acceptance count (how many candidate locations / start hours were rejected) — not recorded.
* Per-scenario FFWI acceptance probability — only the FFWI value is stored (`ffwi_start`).
* Canopy / crown-fire parameters — not part of WTRS (surface fire only).

## Consumers

`ml/datasets/dataset.py` (`WildfireDataset`) → U-Net, FNO and PI-FNO training (`ml/training/trainer.py`) and the test
evaluation (`ml/evaluation/evaluate_models.py`). The loader refuses datasets that mix `simulation_source` values.
