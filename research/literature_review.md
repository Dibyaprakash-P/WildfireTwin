# Literature Review — WildfireTwin

Scope: the 11 PDFs in `Research Papers/`. Each was read from its own text (title page, abstract, methods) using
automated text extraction plus manual reading of the relevant sections. Bibliographic details are taken
**only from the PDFs themselves**. Indexing status (IEEE / Scopus / SCI) is **not claimed** for any paper because
it was not verified from an authoritative source. Reported numbers are quoted as the authors report them; they
are not comparable to WildfireTwin's results (different data, regions, resolutions and targets).

| # | File | Short title | Year | Venue (as printed in the PDF) |
|---|------|-------------|------|-------------------------------|
| 1 | `2010.08895v3.pdf` | Fourier Neural Operator for Parametric PDEs | 2021 | ICLR 2021 (conference paper) |
| 2 | `21-1524.pdf` | Neural Operator: Learning Maps Between Function Spaces | 2023 | Journal of Machine Learning Research 24 |
| 3 | `1711.10561v1.pdf` | Physics Informed Deep Learning (Part I) | 2017 | arXiv preprint 1711.10561 |
| 4 | `1-s2.0-S0893608021001337-am.pdf` | Emulation of wildland fire spread simulation using deep learning | 2021 | Neural Networks (Elsevier), author-accepted manuscript |
| 5 | `2308.02810v1.pdf` | A generative model for surrogates of spatial-temporal wildfire nowcasting | 2023 | "Accepted for publication in IEEE Trans. Emerging Topics in Computational Intelligence" (header of arXiv version) |
| 6 | `2409.00237v1.pdf` | Deep learning surrogate models of JULES-INFERNO | 2024 | arXiv; header states "submitted to IEEE TETCI" |
| 7 | `gmd-19-1027-2026.pdf` | Probabilistic wildfire spread prediction with a denoising diffusion surrogate | 2026 | Geoscientific Model Development 19, 1027–1054 |
| 8 | `remotesensing-16-01467.pdf` | CNN-BiLSTM for near-real-time daily wildfire spread | 2024 | Remote Sensing 16, 1467 (MDPI) |
| 9 | `s41598-024-52821-x.pdf` | Wildfire spreading prediction using multimodal data and DNNs | 2024 | Scientific Reports 14:2606 |
| 10 | `s41598-026-56080-w_reference.pdf` | High-fidelity CNN-based surrogate modeling for wildfire spread forecasting | 2026 | Scientific Reports — *article in press* (unedited manuscript) |
| 11 | `fire-08-00293.pdf` | Generative AI as a Pillar for Predicting 2D and 3D Wildfire Spread (review) | 2025 | Fire 8, 293 (MDPI) |

---

## 1. Fourier Neural Operator for Parametric Partial Differential Equations
- **Authors:** Zongyi Li, Nikola Kovachki, Kamyar Azizzadenesheli, Burigede Liu, Kaushik Bhattacharya, Andrew Stuart, Anima Anandkumar
- **Methodology:** Neural operator whose integral kernel is parameterised directly in Fourier space: each layer
  applies FFT → multiplication of a truncated set of low-frequency modes by learned complex weights → inverse FFT,
  plus a pointwise linear path, followed by a nonlinearity. Lifting and projection networks map to/from a hidden width.
- **Data:** Burgers' equation, Darcy flow, Navier–Stokes (synthetic PDE solutions).
- **Metrics:** relative L2 error; runtime vs. numerical solvers; zero-shot super-resolution.
- **Relevance:** Core architecture of WildfireTwin's main model (`ml/models/fno/model.py`): spectral convolution with
  configurable modes/width/layers, zero-padding for non-periodic domains, positional grid channels. Discretisation
  flexibility is used to share one model across the 30/60/120 m horizon bands.

## 2. Neural Operator: Learning Maps Between Function Spaces with Applications to PDEs
- **Authors:** Nikola Kovachki, Zongyi Li, Burigede Liu, Kamyar Azizzadenesheli, Kaushik Bhattacharya, Andrew Stuart, Anima Anandkumar
- **Methodology:** General neural-operator framework (compositions of linear integral operators and nonlinearities),
  universal-approximation theorem, discretisation invariance; graph, low-rank, multipole and Fourier variants.
- **Data / metrics:** PDE benchmarks; relative errors.
- **Relevance:** Theoretical justification for treating fire-spread forecasting as an *operator* (landscape + weather
  + current fire field → future fire field), see `docs/model_methodology.md`.

## 3. Physics Informed Deep Learning (Part I): Data-driven Solutions of Nonlinear PDEs
- **Authors:** Maziar Raissi, Paris Perdikaris, George Em Karniadakis
- **Methodology:** Physics-informed neural networks: the loss combines data misfit with the residual of a governing
  PDE evaluated by automatic differentiation (continuous- and discrete-time formulations).
- **Data / metrics:** Schrödinger, Allen–Cahn, Burgers examples; relative L2 errors.
- **Relevance:** The composite loss `L_total = L_data + λ·L_physics` of the PI-FNO follows this idea. WildfireTwin
  uses finite differences on the predicted arrival-time grid (not autodiff of coordinates) and an anisotropic
  eikonal residual appropriate to fire-front propagation.

## 4. Emulation of wildland fire spread simulation using deep learning
- **Authors:** Frédéric Allaire, Vivien Mallet, Jean-Baptiste Filippi
- **Methodology:** Hybrid deep network combining a convolutional branch (landscape fields around the ignition) with
  scalar inputs to emulate the burned area after one hour returned by the ForeFire simulator (Rothermel-type rate of spread).
- **Data:** Large simulation dataset of ignitions anywhere on Corsica under wide input ranges.
- **Metrics:** MAPE (32.8 % reported on the test set), MSE; speed-up of several thousand vs. the simulator on 32 cores.
- **Relevance:** Closest methodological precedent: learn a fast surrogate from physics-based simulations on real
  landscapes. WildfireTwin predicts full spatial fields (not only area) and reports speed-up the same way
  (measured simulator time / model time).

## 5. A generative model for surrogates of spatial-temporal wildfire nowcasting
- **Authors:** Sibo Cheng, Yike Guo, Rossella Arcucci
- **Methodology:** 3-D VQ-VAE generating spatio-temporal burned-area sequences conditioned on the ecoregion;
  generated data are used to train a surrogate for fire dissemination.
- **Data:** Cellular-automata simulations in the Chimney Fire (2016, California) ecoregion; MODIS/VIIRS active fire
  for the real event.
- **Metrics:** MSE, SSIM, accuracy-type measures.
- **Relevance:** Shows the simulation-to-surrogate pipeline and the use of VIIRS/MODIS for evaluation. Its
  *generative* component is out of scope (project constraint: no generative AI).

## 6. Deep learning surrogate models of JULES-INFERNO for wildfire prediction on a global scale
- **Authors:** Sibo Cheng, Hector Chassagnon, Matthew Kasoar, Yike Guo, Rossella Arcucci
- **Methodology:** Two data-driven surrogates (including ConvLSTM-type models) predicting global burned-area
  fraction iteratively from temperature, vegetation density, soil moisture and previous predictions; fine-tuning for unseen scenarios.
- **Data:** JULES-INFERNO global simulation outputs.
- **Metrics:** Average Error per Pixel (AEP), SSIM; runtime (seconds on a laptop CPU vs hours on HPC).
- **Relevance:** Supports the global-monitoring / local-prediction split: global-scale surrogates work at coarse
  resolution; WildfireTwin instead runs a *local* high-resolution operator around a selected fire.

## 7. A probabilistic approach to wildfire spread prediction using a denoising diffusion surrogate model
- **Authors:** Wenbo Yu, Anirbit Ghosh, Tobias Sebastian Finn, Rossella Arcucci, Marc Bocquet, Sibo Cheng
- **Methodology:** Conditional diffusion model with ensemble sampling vs. a deterministic regression baseline with
  the same network.
- **Data:** Synthetic data from a probabilistic cellular-automata simulator conditioned on canopy cover, vegetation
  density and slope for the Chimney (2016) and Ferguson (2018) fires.
- **Metrics:** MSE, SSIM, FID, and a proposed hit-rate (HR) metric for uncertainty.
- **Relevance:** Highlights uncertainty representation. WildfireTwin does **not** implement uncertainty
  quantification; the UI states that uncertainty is not quantified and generally grows with horizon. Diffusion
  (generative) models are excluded by the project constraints.

## 8. CNN-BiLSTM: A Novel Deep Learning Model for Near-Real-Time Daily Wildfire Spread Prediction
- **Authors:** Mohammad Marjani, Masoud Mahdianpari, Fariba Mohammadimanesh
- **Methodology:** CNN feature extraction + bidirectional LSTM over daily sequences; compared with LSTM and CNN-LSTM.
- **Data:** VIIRS active fire; topography (SRTM 30 m elevation, slope, aspect), land cover, temperature, NDVI
  (MODIS MOD13Q1), wind, precipitation, soil moisture, runoff (ERA5-Land 0.1°).
- **Metrics:** IoU, precision, recall, F1 (abstract reports values of 0.58 and 0.73 for validation and training sets).
- **Relevance:** Very similar input stack (VIIRS + SRTM + ERA5 + land cover) and the same metric family (IoU / F1)
  that WildfireTwin reports. Also illustrates training directly on observed VIIRS progression — WildfireTwin uses
  observed VIIRS only for initialisation and replay validation.

## 9. Wildfire spreading prediction using multimodal data and deep neural network approach
- **Authors:** Dmitrii Shadrin, Svetlana Illarionova, Fedor Gubanov, Ksenia Evteeva, Maksim Mironenko, Ivan Levchunets, Roman Belousov, Evgeny Burnaev
- **Methodology:** Segmentation networks (U-Net, U-Net++, MA-Net, DeepLabV3; ResNet18 encoders) predicting fire
  spread 1–5 days ahead; feature-importance analysis.
- **Data:** Siberian fires (Krasnoyarsk, Irkutsk, Sakha); MODIS land cover/LST/ET, Copernicus GLO-30 DEM,
  ERA5-Land weather; 128×128 windows (~21×21 km, ~650 m cells) centred on the ignition; 4:1 train/test split.
- **Metrics:** F1 / Dice, IoU.
- **Relevance:** Supports the 128×128 local-window design centred on the fire, the use of U-Net as a baseline and
  multi-day horizons.

## 10. High-fidelity CNN-based surrogate modeling for wildfire spread forecasting (article in press)
- **Authors:** Saeed Nematshahi, Rui Fan, Amin Khodaei, Erin Belval, Ali Arabnya
- **Methodology:** CNN surrogate trained on FARSITE simulations with LANDFIRE inputs; predicts fire spread at 120 m
  in a fraction of a second; trained on a desktop CPU in under 4 h.
- **Data:** FARSITE reference simulations (validation scenarios are FARSITE outputs).
- **Metrics:** F1 (0.92 reported), precision, recall, accuracy.
- **Relevance:** Direct precedent for the FARSITE-reference → neural-surrogate workflow and LANDFIRE fuels; note the
  paper itself treats FARSITE outputs as the reference, which WildfireTwin labels "simulated", not ground truth.

## 11. Generative AI as a Pillar for Predicting 2D and 3D Wildfire Spread (review)
- **Authors:** Haowen Xu, Sisi Zlatanova, Ruiyu Liang, Ismet Canbulat
- **Methodology:** Systematic review of generative models (GANs, VAEs, transformers) for fire prediction; the authors
  used LLMs for literature synthesis; outlines future directions incl. agentic AI and chatbots.
- **Relevance:** Background only. Its generative-AI / LLM / chatbot directions are explicitly **excluded** by the
  WildfireTwin constraints. Useful for the digital-twin framing and for its survey of physics-based models.

---

## Synthesis — how the papers shaped WildfireTwin

| Design decision | Supported by |
|---|---|
| Learn a fast surrogate of physics-based spread simulations on real landscapes | [4], [10], [5] |
| Fourier neural operator as main model; resolution-flexible bands | [1], [2] |
| Physics-informed composite loss (data + PDE residual) | [3] (adapted to an eikonal fire-arrival formulation) |
| U-Net baseline, 128×128 local windows centred on the fire, multi-day horizons | [9], [8] |
| VIIRS/MODIS + SRTM + ERA5 + land cover input stack | [8], [9], [5] |
| IoU / Dice / F1 / precision / recall metrics; speed-up vs simulator | [4], [8], [9], [10] |
| Report uncertainty limitations honestly instead of fabricating confidence | [7] |
| Global coarse monitoring vs local high-resolution prediction | [6] |

Gaps WildfireTwin addresses within a capstone scope: a *physics-informed neural operator* with an explicit fire-front
(eikonal) residual (none of the wildfire papers above uses an FNO or a PDE-residual loss), an end-to-end
observed-data → forecast → alert loop, and strict separation of observed / simulated / predicted / validated data.
