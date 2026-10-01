# Evaluation

_Generated from `data/models/evaluation/results.json` (2026-10-01T17:08:52Z). All values are measured; nothing is hand-entered._

## Protocol
* Test split: spatial blocks of 0.5 deg assigned by ignition location (scenarios never shared; 54% of test windows partly overlap training landscapes - see strict subset); **5086 samples**; dataset `wtrs-ncal-v1`.
* Evaluated against: **WTRS reference simulations (simulated; internal Rothermel + MTT pipeline, not FARSITE)** - not observed ground truth. Probability threshold 0.5.
* Reference dataset: `wtrs-ncal-v1`, simulation_source `WTRS`, engine `WTRS-Rothermel-MTT`.
* Observed-data comparisons (predicted vs FIRMS footprints) are single-case historical replays, reported separately in the app; they are not part of this table.
* Growth metrics are computed on cells that were *not* burning at t0 (the initial fire is an input, so full-mask IoU/Dice are inflated by it). Hausdorff distances are between mask boundaries, in metres.
* Inference time: median per sample, batch 1, on NVIDIA GeForce RTX 5050 Laptop GPU (cuda) and on CPU.
* Speed-up: median WTRS re-simulation time for the same t0→t0+h step (CPU, Python) ÷ median model time.

## Overall (all horizons)

| Model | IoU | Dice | Growth IoU | Growth F1 | Precision | Recall | Hausdorff (m) | HD95 (m) | MAE | Area error (%) | Inference GPU (ms) | Inference CPU (ms) | Speed-up GPU | Speed-up CPU |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| U-Net | 0.741 | 0.827 | 0.619 | 0.712 | 0.876 | 0.852 | 374 | 265 | 0.0079 | 107.6 | 2.60 | 17.0 | 14× | 2.1× |
| FNO | 0.698 | 0.795 | 0.561 | 0.662 | 0.839 | 0.839 | 442 | 304 | 0.0088 | 175.2 | 2.91 | 37.8 | 12× | 0.9× |
| Physics-Informed FNO | 0.708 | 0.802 | 0.578 | 0.678 | 0.838 | 0.851 | 411 | 295 | 0.0101 | 170.1 | 2.90 | 37.9 | 12× | 0.9× |
| _Persistence (no growth)_ | 0.429 | 0.517 | 0.159 | 0.159 | 1.000 | 0.429 | 816 | 714 | 0.0179 | -57.1 | — | — | — | — |

Reference re-simulation: median 35.4 ms over 150 test samples (cpu (single-threaded Python)).

## Strict test subset (2308 samples, 257 scenarios)

Criterion: test window has zero area overlap with every training window (all bands). The split assigns scenarios to 0.5° blocks by ignition location; 128x128 windows near block borders can cover terrain also seen in training windows. This subset removes that overlap.

| Model | IoU | Dice | Growth IoU | Growth F1 | Hausdorff (m) |
|---|---|---|---|---|---|
| U-Net | 0.770 | 0.848 | 0.613 | 0.701 | 212 |
| FNO | 0.730 | 0.819 | 0.554 | 0.648 | 266 |
| Physics-Informed FNO | 0.741 | 0.827 | 0.573 | 0.667 | 241 |
| _Persistence (no growth)_ | 0.513 | 0.603 | 0.191 | 0.191 | 471 |

## Per horizon — Growth IoU / IoU / Hausdorff (m)

| Model | 10m | 30m | 1h | 6h | 12h | 24h | 48h | 72h |
|---|---|---|---|---|---|---|---|---|
| U-Net | 0.542 / 0.896 / 21 | 0.574 / 0.817 / 29 | 0.596 / 0.764 / 43 | 0.625 / 0.740 / 182 | 0.645 / 0.709 / 287 | 0.646 / 0.710 / 549 | 0.644 / 0.675 / 812 | 0.647 / 0.666 / 930 |
| FNO | 0.519 / 0.896 / 22 | 0.534 / 0.811 / 31 | 0.564 / 0.748 / 45 | 0.561 / 0.694 / 203 | 0.570 / 0.644 / 333 | 0.580 / 0.659 / 595 | 0.574 / 0.611 / 945 | 0.570 / 0.593 / 1212 |
| Physics-Informed FNO | 0.536 / 0.895 / 21 | 0.566 / 0.814 / 30 | 0.561 / 0.744 / 44 | 0.574 / 0.699 / 198 | 0.582 / 0.652 / 322 | 0.596 / 0.670 / 587 | 0.600 / 0.637 / 869 | 0.598 / 0.621 / 1068 |

## Training runs

| Model | Run | Params | Best epoch | Val growth IoU | Train time (min) |
|---|---|---|---|---|---|
| unet | unet-20261001-054841 | 7,771,969 | 33 / 40 | 0.702 | 40.9 |
| fno | fno-20261001-062945 | 7,395,601 | 33 / 40 | 0.646 | 56.9 |
| physics_fno | physics_fno-20261001-072651 | 7,395,601 | 36 / 40 | 0.662 | 85.8 |

## Interpretation guidance

* Rankings are not asserted here; differences should be judged together with the per-horizon table and with
  the fact that all models share data, features, augmentation and training budget.
* Results measure agreement with the reference simulator on unseen landscapes, not real-world forecast skill.
  Single-case comparisons with observed FIRMS footprints are available through the Historical replay page.
