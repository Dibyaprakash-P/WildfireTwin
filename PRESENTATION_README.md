# 🔥 WildfireTwin — Complete Project Explanation

> **Capstone Project — Phase 2 | MCA, PES University**
> **Student:** Dibyaprakash Patnaik (PES1PG25CA058)
> **Guide:** Dr. C. Menaka (CM)

---

## 📌 Table of Contents

1. [What is WildfireTwin? (Simple Explanation)](#1-what-is-wildfiretwin-simple-explanation)
2. [The Problem We Are Solving](#2-the-problem-we-are-solving)
3. [Our Proposed Solution](#3-our-proposed-solution)
4. [How The System Works (Step by Step)](#4-how-the-system-works-step-by-step)
5. [System Architecture (The Big Picture)](#5-system-architecture-the-big-picture)
6. [All Tools & Technologies Used](#6-all-tools--technologies-used)
7. [Data Sources — Where Does The Data Come From?](#7-data-sources--where-does-the-data-come-from)
8. [Machine Learning Models — The Brain of the System](#8-machine-learning-models--the-brain-of-the-system)
9. [The Reference Simulator (Training Data Generator)](#9-the-reference-simulator-training-data-generator)
10. [Database Design — MongoDB Collections](#10-database-design--mongodb-collections)
11. [Frontend — What The User Sees](#11-frontend--what-the-user-sees)
12. [Backend — The Engine Behind the Scenes](#12-backend--the-engine-behind-the-scenes)
13. [Alert System — How Warnings Work](#13-alert-system--how-warnings-work)
14. [Complete Folder Structure Explained](#14-complete-folder-structure-explained)
15. [Key Functions & Files Explained](#15-key-functions--files-explained)
16. [Functional & Non-Functional Requirements](#16-functional--non-functional-requirements)
17. [Users of the System](#17-users-of-the-system)
18. [Scope — What's In and What's Out](#18-scope--whats-in-and-whats-out)
19. [Literature Survey Summary](#19-literature-survey-summary)
20. [Existing Systems We Studied](#20-existing-systems-we-studied)
21. [Evaluation Results — How Good Are the Models?](#21-evaluation-results--how-good-are-the-models)
22. [Limitations (Be Honest About These)](#22-limitations-be-honest-about-these)
23. [How To Explain Each Slide](#23-how-to-explain-each-slide)

---

## 1. What is WildfireTwin? (Simple Explanation)

**WildfireTwin** is a web-based research tool that does two things:

1. **Shows active fires happening around the world right now** on an interactive 3D globe (using NASA satellite data)
2. **Predicts where a fire will spread** in the next 10 minutes to 72 hours using AI (deep learning models)

Think of it like Google Maps but for wildfires — you can see fires on a globe, click on one, and the system tells you "in the next 24 hours, the fire will probably burn this much area in this direction."

### Why is it called "Twin"?
The name comes from the concept of a **Digital Twin** — a virtual copy of a real-world system. We create a "digital twin" of a wildfire: we take real satellite data, real terrain, real weather, and simulate/predict how the fire will behave.

### Key Numbers
| Metric | Value |
|---|---|
| Fire events monitored globally | 18,696 live (NASA FIRMS API, VIIRS NOAA-20, last 2 days, 5 Oct 2026). The number changes daily; the earlier 67,267 came from the archived multi-satellite files ending 30 Sep 2026 |
| Training samples | 22,505 from 2,400 reference simulations |
| Prediction horizons | 8 (10 min, 30 min, 1h, 6h, 12h, 24h, 48h, 72h) |
| Prediction speed | ~3 ms per horizon on GPU |
| Study region | Northern California (40–42°N, 124.5–122°W) |

---

## 2. The Problem We Are Solving

### The Problem (In Simple Words)

**Problem 1: Satellites show WHERE fires burn NOW — not where they WILL spread.**
- NASA's FIRMS satellite system detects active fires globally, but it only tells you current hotspots. It doesn't predict future spread.

**Problem 2: Existing fire simulators are slow and need experts.**
- Tools like FARSITE and FlamMap can predict fire spread, but they are desktop software that requires expert knowledge, manual setup, and minutes-to-hours to run a single scenario. Every time the weather changes, you have to re-run them.

**Problem 3: Data is scattered across different sources.**
- Weather data comes from one place, terrain data from another, fuel/vegetation data from another. They all use different formats, coordinate systems, and units. Combining them manually is tedious.

### Why This Matters
Wildfires cause massive damage every year. Firefighters and disaster managers need **fast, continuously updated** predictions to make life-saving decisions. They can't wait for an expert to manually run a simulator every time conditions change.

---

## 3. Our Proposed Solution

WildfireTwin solves all three problems:

| Problem | Our Solution |
|---|---|
| No spread prediction from satellites | AI models (U-Net, FNO, PI-FNO) predict spread in **milliseconds** |
| Slow simulators need experts | Everything is automated in a **web app** — click a fire and get predictions |
| Data scattered everywhere | System **automatically fetches** and combines data from 7+ sources into a unified grid |

### The Big Idea
1. **Monitor** — Get real-time fire data from NASA satellites (global)
2. **Build a local grid** — For a selected fire, gather terrain, fuel, weather data into a 128x128 pixel grid
3. **Predict** — Feed the grid into trained AI models, get probability maps of where fire will spread
4. **Alert** — If weather changes or fire grows, automatically re-predict and send alerts
5. **Visualize** — Show everything on a beautiful 3D globe in the browser

---

## 4. How The System Works (Step by Step)

Here's the complete flow from start to finish:

```
Step 1: FIRMS Data Arrives
   NASA satellites (VIIRS on Suomi NPP/NOAA-20/21, MODIS on Terra/Aqua)
   detect heat from fires and send data to the FIRMS API

Step 2: Backend Fetches and Clusters
   Our backend calls the FIRMS API, downloads fire detections,
   removes duplicates, and clusters nearby detections into "fire events"
   (detections within 1.5 km over 48 hours = 1 fire event)

Step 3: Display on 3D Globe
   All fire events are shown as markers on a CesiumJS 3D globe
   in the user's browser

Step 4: User Clicks a Fire
   User clicks a fire marker and selects "ANALYZE FIRE"

Step 5: Build Local Analysis Grid
   System creates a 128x128 pixel grid centred on the fire:
   - Elevation from SRTM (slope, aspect calculated)
   - Fuel type from LANDFIRE FBFM40 (40 vegetation categories)
   - Land cover from ESA WorldCover
   - Current fire footprint from FIRMS pixels
   - Weather from Open-Meteo (temperature, humidity, wind, rain)

Step 6: Run AI Model
   The 34-channel input grid is fed into the trained model
   (PI-FNO / FNO / U-Net) and outputs a probability map for each
   of 8 time horizons (10 min to 72 hours)

Step 7: Generate Outputs
   Probability maps are saved as GeoTIFF files (with coordinates)
   and PNG overlays (for displaying on the globe)

Step 8: Show Results
   Results are draped on the 3D globe with a timeline slider
   User can scrub through 10 min to 72 h to see spread progression

Step 9: Monitor and Alert
   Background monitor keeps checking:
   - Did new FIRMS detections arrive?
   - Did weather change significantly?
   If yes, re-run prediction, compare with old prediction, send alert
```

---

## 5. System Architecture (The Big Picture)

The system has **4 main layers**:

```
+-----------------------------------------------------------+
|  LAYER 1: DATA SOURCES (External)                          |
|  NASA FIRMS . Open-Meteo . ERA5 . SRTM . LANDFIRE .       |
|  WorldCover . MTBS                                         |
+----------------------------+------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|  LAYER 2: BACKEND (Python / FastAPI)                       |
|  - FIRMS Ingestion and Clustering                          |
|  - Weather and Environment Service                         |
|  - Inference Service (runs the AI models)                  |
|  - Reference Simulator (Rothermel + MTT)                   |
|  - Monitor and Alerts Engine                               |
|  - Auth (email OTP, JWT tokens, Google Sign-In)            |
+----------------------------+------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|  LAYER 3: ML MODELS (PyTorch)                              |
|  U-Net (baseline) . FNO (main) . Physics-Informed FNO     |
|  Trained on 128x128 grids at 30/60/120 m resolution        |
+----------------------------+------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|  LAYER 4: FRONTEND (React + CesiumJS)                      |
|  3D Globe . Fire Panels . Forecast Timeline .              |
|  Data/Models/Logs Pages . Alerts                           |
+-----------------------------------------------------------+
```

### Storage
- **MongoDB** stores metadata (fire events, predictions, alerts, users) — NOT the actual raster images
- **File System** stores GeoTIFF rasters, PNG overlays, model checkpoints

---

## 6. All Tools & Technologies Used

### Frontend (What the user sees in the browser)

| Tool | What It Is | Why We Use It |
|---|---|---|
| **React 18** | JavaScript UI library by Facebook | Build interactive, component-based user interfaces |
| **TypeScript** | JavaScript with type safety | Catch bugs at compile time, better code quality |
| **Vite 5** | Fast build tool / dev server | Super fast hot reload during development |
| **Tailwind CSS 3** | Utility-first CSS framework | Quickly style components without writing custom CSS |
| **CesiumJS** | 3D globe visualization library | Render the interactive 3D Earth with fire markers and prediction overlays |
| **Recharts** | React charting library | Draw charts (prediction area over time, model comparison) |
| **Zustand** | Lightweight state management | Share state (selected fire, auth, etc.) across components without Redux complexity |
| **Lucide React** | Icon library | Clean, consistent icons throughout the UI |
| **Framer Motion** | Animation library | Smooth transitions and micro-animations |
| **React Router DOM** | Client-side routing | Navigate between pages (Dashboard, Simulation, Models, etc.) without page reload |
| **Inter / JetBrains Mono** | Google Fonts | Modern typography for the UI and code/data display |

### Backend (The server that processes everything)

| Tool | What It Is | Why We Use It |
|---|---|---|
| **Python** | Programming language | The main language for backend, ML, and geospatial processing |
| **FastAPI** | Modern Python web framework | Build REST APIs with automatic docs, validation, async support |
| **Pydantic** | Data validation library | Validate and serialize request/response data with type hints |
| **PyMongo (async)** | MongoDB driver for Python | Connect to and query MongoDB from Python |
| **Uvicorn** | ASGI server | Run the FastAPI application |
| **Argon2-cffi** | Password hashing library | Securely hash user passwords (industry-best Argon2id algorithm) |
| **PyJWT** | JWT token library | Create and verify JSON Web Tokens for authentication |
| **google-auth** | Google OAuth library | Verify Google Sign-In ID tokens |
| **httpx** | Async HTTP client | Make API calls to FIRMS, Open-Meteo, etc. |
| **PyYAML** | YAML parser | Read configuration files (data_sources.yaml, alert_rules.yaml) |
| **Pillow** | Image processing | Generate PNG overlays from prediction arrays |
| **email-validator** | Email validation | Validate email addresses during signup |

### Geospatial (Map and terrain processing)

| Tool | What It Is | Why We Use It |
|---|---|---|
| **rasterio / GDAL** | Raster I/O library | Read/write GeoTIFF files, warp (reproject) rasters between coordinate systems |
| **pyproj** | Coordinate transformation | Convert between coordinate systems (WGS84 to EPSG:5070) |
| **shapely** | Geometric operations | Work with shapes (fire footprints, bounding boxes) |
| **geopandas** | Geospatial DataFrames | Process geospatial vector data (fire perimeters, regions) |
| **xarray** | Multi-dimensional arrays | Read and process ERA5 weather data (NetCDF format) |
| **eccodes** | GRIB file reader | Read ERA5 weather files in GRIB format (from Copernicus) |
| **DuckDB** | In-process SQL database | Fast SQL processing of large FIRMS CSV files without loading all into memory |
| **pyshp** | Shapefile reader | Read MTBS burn perimeter shapefiles |
| **scikit-image** | Image processing | Connected-component labeling for fire clustering |

### Machine Learning

| Tool | What It Is | Why We Use It |
|---|---|---|
| **PyTorch** | Deep learning framework | Build and train neural networks (U-Net, FNO, PI-FNO) |
| **CUDA** | GPU computing | Accelerate model training and inference on NVIDIA GPUs |
| **NumPy** | Numerical computing | Array operations, mathematical computations |
| **SciPy** | Scientific computing | Optimization, signal processing, Dijkstra's algorithm for fire spread |
| **MLflow** | ML experiment tracking | Log training runs, hyperparameters, metrics, and model versions |
| **Matplotlib** | Plotting library | Generate training loss curves and visualizations |

### Database

| Tool | What It Is | Why We Use It |
|---|---|---|
| **MongoDB** | NoSQL document database | Store flexible JSON-like documents (fire events, predictions, users) |

### Deployment

| Tool | What It Is | Why We Use It |
|---|---|---|
| **Docker** | Containerization | Package the entire app into containers for easy deployment |
| **Docker Compose** | Multi-container orchestration | Run backend + frontend + MongoDB together |
| **Nginx** | Web server | Serve the frontend in production |

### Testing

| Tool | What It Is | Why We Use It |
|---|---|---|
| **pytest** | Python test framework | Test backend logic, geospatial functions, ML pipelines |
| **Vitest** | JavaScript test framework | Test frontend React components |
| **pytest-asyncio** | Async test support | Test async FastAPI endpoints |

---

## 7. Data Sources — Where Does The Data Come From?

### 7 External Data Sources

| # | Source | What It Provides | Format | Resolution | Coverage |
|---|---|---|---|---|---|
| 1 | **NASA FIRMS** | Active fire detections (hotspots from satellites) | CSV / API | 375m (VIIRS), 1km (MODIS) | Global, near-real-time |
| 2 | **Open-Meteo** | Live weather forecasts (temperature, wind, humidity, rain) | JSON API | ~10 km | Global, 4-day forecast |
| 3 | **ERA5 (ECMWF/Copernicus)** | Historical hourly weather (for training) | GRIB to NetCDF | 0.25 deg (~28 km) | 2024-2025, study region |
| 4 | **SRTM (NASA)** | Elevation / terrain height | GeoTIFF | 30 m (1 arc-second) | Near-global (60N-56S) |
| 5 | **LANDFIRE** | Fuel/vegetation models (40 types of burnable vegetation) | GeoTIFF | 30 m | Continental US |
| 6 | **ESA WorldCover** | Land cover classes (forest, grass, water, built-up, etc.) | GeoTIFF | 10 m | Global |
| 7 | **MTBS** | Historical burn perimeters (past fire boundaries) | Shapefile | Vector | US, 1984-present |

### How Data Gets Combined
All data is reprojected (converted) onto a common grid:
- **Coordinate system:** EPSG:5070 (Conus Albers Equal-Area — preserves areas, uses metres)
- **Grid size:** 128 x 128 cells
- **Cell size:** 30 m (short horizons), 60 m (medium), 120 m (long horizons)
- **Every reprojection is logged** with the method used (bilinear for elevation, nearest-neighbour for fuel codes, etc.)

### Derived Variables (Computed from raw data)
| Variable | How It's Computed | From |
|---|---|---|
| Slope | Horn (1981) algorithm | Elevation |
| Aspect (downhill direction) | Horn (1981) algorithm | Elevation |
| Dead fuel moisture | Simard (1968) Equilibrium Moisture Content (EMC) | Temperature + Humidity |
| Mid-flame wind speed | Albini and Baughman (1979) wind adjustment factor | 10m wind speed |
| Fire state (initial burned area) | Pixel footprints drawn on grid | FIRMS detections |

---

## 8. Machine Learning Models — The Brain of the System

We built **3 neural network models**, each progressively more advanced:

### Model 1: U-Net (Baseline)

**What is U-Net?**
U-Net is a convolutional neural network (CNN) originally designed for medical image segmentation. It has an **encoder-decoder** structure shaped like the letter "U":
- **Encoder** (left side): Compresses the image, learning "what" features are important
- **Decoder** (right side): Expands back to full size, learning "where" to place predictions
- **Skip connections**: Bridges between encoder and decoder that preserve fine spatial details

**Our U-Net specifics:**
- 4-level deep encoder-decoder
- 32 base channels, GroupNorm normalization, GELU activation
- Input: 34-channel grid (128x128) to Output: 1-channel probability map (128x128)
- Loss function: Binary Cross-Entropy (BCE) + Soft Dice Loss
- **Parameters:** 7,771,969 (~7.7 million)

### Model 2: FNO — Fourier Neural Operator (Main Model)

**What is an FNO?**
A Fourier Neural Operator is a special type of neural network designed to learn mappings between **function spaces** — basically, it learns the physics operator that maps input fields (terrain, fuel, weather, current fire) to output fields (future fire state).

**Why is it special?**
- Regular CNNs use local kernels (3x3 or 5x5 pixels) — they can only see nearby pixels
- FNO uses the **Fourier Transform** (FFT) — it converts the entire grid to frequency space, mixes information **globally** (every pixel talks to every other pixel), then converts back
- This matters because fire spread is influenced by terrain and wind kilometres away, not just adjacent cells
- FNO is approximately **resolution-invariant**: the same model works on 30m, 60m, and 120m grids

**Our FNO specifics:**
- Lifting MLP: 34 + 2 grid channels to 48 hidden channels
- 4 Fourier layers: each does `v = GELU(GroupNorm(FFT_inverse[R * FFT(v)] + W*v))`
  - `R` = complex weights on the lowest 20x20 frequency modes
  - `W` = 1x1 convolution (local path)
- Zero-padding by 16 cells before FFT (fire fields aren't periodic, so we pad)
- Projection MLP to 1 output logit
- **Parameters:** 7,395,601 (~7.4 million)

### Model 3: PI-FNO — Physics-Informed FNO (Advanced Model)

**What makes it "physics-informed"?**
Same FNO backbone, but the loss function includes **physics constraints** — we tell the model "your predictions should obey the laws of fire physics":

**Output:** Instead of directly predicting a burned/unburned mask, it predicts an **arrival-time field** tau(x) — "at what normalised time does the fire reach cell x?" The probability is then derived: `p = sigmoid((1 - tau) / 0.1)`

**Physics Loss Terms:**

| Loss Term | What It Means (Simple) | Formula Concept |
|---|---|---|
| **L_BCE + L_Dice** | Standard data loss — match the reference simulation output | Same as U-Net and FNO |
| **L_tau (arrival time)** | Predicted arrival times should match reference arrival times | Huber loss between predicted and reference tau |
| **L_eikonal** | Fire must spread at the correct speed in every direction (Rothermel speed x gradient of arrival time = 1) | This is the fundamental PDE of fire propagation |
| **L_mono (irreversibility)** | Burned cells must STAY burned — fire can't "un-burn" | Penalize if the model says an already-burning cell has positive arrival time |
| **L_nb (non-burnable)** | Fire can't enter non-burnable areas (water, rock, roads) | Penalize probability on non-burnable fuel codes |

**Weight of physics terms:** lambda_eikonal = 0.1, lambda_mono = lambda_nb = 1.0, linearly ramped over 2 warm-up epochs.

### Input Channels (34 total) — What Goes Into The Models

```
Channel #    Name                         Source
-------------------------------------------------------
1           fire_t0 (current fire mask)   FIRMS
2           elevation (normalised)        SRTM / 500m
3           slope / 45 degrees            Derived from elevation
4           aspect sin                    Derived from elevation
5           aspect cos                    Derived from elevation
6           burnable flag                 LANDFIRE fuel code
7-12        fuel group one-hot            GR, GS, SH, TU, TL, SB
13          1-h dead fuel load            LANDFIRE fuel properties
14          fuel bed depth                LANDFIRE fuel properties
15-21       land cover one-hot            tree, shrub, grass, crop, built, bare, water/wetland
22          temperature at t0             Weather
23          relative humidity at t0       Weather
24          wind u-component at t0        Weather
25          wind v-component at t0        Weather
26          mean temperature over horizon Weather
27          mean RH over horizon          Weather
28          mean wind u over horizon      Weather
29          mean wind v over horizon      Weather
30          precipitation sum             Weather
31          soil moisture                 Weather
32          1-h dead fuel moisture (EMC)  Derived from T + RH
33          horizon (normalised)          System parameter
34          cell size (normalised)        System parameter
```

### Training Details

| Parameter | Value |
|---|---|
| Optimizer | AdamW (lr = 0.001, weight decay = 0.0001) |
| Learning rate schedule | One-Cycle (warmup + cosine decay) |
| Batch size | 16 |
| Max epochs | 40 (with early stopping, patience = 8) |
| Augmentation | Dihedral (flips + 90 degree rotations), with vector field transformation |
| Gradient clipping | 1.0 |
| Random seed | 42 |
| Training hardware | NVIDIA GeForce RTX 5050 Laptop GPU |

---

## 9. The Reference Simulator (Training Data Generator)

### What is WTRS?
WTRS = **WildfireTwin Reference Simulator** — our own in-repo fire spread simulator built in Python. It generates the training data for the ML models.

### How it works (the physics):

**Step 1: Rothermel (1972) Surface Fire Model**
- Takes fuel properties (type, load, depth, moisture) + terrain (slope, aspect) + weather (wind speed/direction, humidity)
- Calculates **Rate of Spread (ROS)** = how fast fire moves forward in metres/minute
- This is THE standard fire spread equation used by all major fire simulators

**Step 2: Anderson (1983) Elliptical Fire Shape**
- Fire doesn't spread equally in all directions — it's driven by wind
- Creates an **ellipse shape**: long axis = wind direction (fire spreads fastest here), narrow sides = perpendicular to wind
- Length-to-breadth ratio depends on wind speed

**Step 3: Minimum Travel Time (MTT) Growth**
- Uses **Dijkstra's algorithm** on a 16-neighbour grid
- Calculates the fastest path from the ignition point to every cell
- Gives an **arrival time** for each cell (when does fire reach this cell?)
- Weather changes hourly

### Training Dataset: `wtrs-ncal-v1`

| Detail | Value |
|---|---|
| Total scenarios | 2,400 (800 per resolution band) |
| Valid samples | 22,505 |
| Resolution bands | Short (30m), Medium (60m), Long (120m) |
| Ignition | Random within study region |
| Weather | ERA5 2024-2025, Jun-Oct, biased towards fire weather |
| Data split | Spatial blocks (0.5 x 0.5 deg), train/val/test by block |

---

## 10. Database Design — MongoDB Collections

MongoDB stores **metadata and operational data** (NOT the actual raster images — those are files on disk).

### Collections (Tables)

| Collection | Purpose | Key Fields |
|---|---|---|
| **users** | Registered user accounts | `_id`, `email` (unique), `password_hash`, `auth_providers[]` |
| **email_verifications** | OTP codes for email verification | hashed OTP, TTL (auto-expires after 5 min) |
| **fire_events** | Clustered fire events from FIRMS | `event_id`, `centroid` (2dsphere index), `detection_count`, `status`, `last_seen` |
| **weather_conditions** | Weather snapshots for fires | `fire_id` links to fire_events, `location` (2dsphere), current values, `fetched_at` |
| **predictions** | Model prediction results | `prediction_id`, `fire_id`, `user_id`, `model`, `steps[]` (8 horizons), `input_hash` |
| **alerts** | System-generated warnings | `alert_id`, `fire_id`, `prediction_id`, `type`, `severity` |
| **model_runs** | ML training run records | `run_id`, `model_type`, `dataset_version`, `best_val` score |
| **simulations** | Reference simulation results | WTRS run outputs with parameters |
| **system_logs** | Application logs | TTL 30 days (auto-cleanup) |

### Relationships
```
users ------1:N------> predictions
fire_events --1:N----> predictions
fire_events --1:N----> alerts
fire_events --1:N----> weather_conditions
predictions --1:N----> alerts
```

### Indexes
- **2dsphere** on `fire_events.centroid` and `weather_conditions.location` — enables fast geo-queries ("find fires near this point")
- **TTL** on `email_verifications` (5 min) and `system_logs` (30 days) — auto-delete old records

---

## 11. Frontend — What The User Sees

### Pages

| Page | What It Does |
|---|---|
| **Dashboard** | 3D CesiumJS globe with fire markers; click a fire, see details, "Analyze Fire" button, get predictions |
| **Simulation** | Run reference simulations (Rothermel+MTT) with custom parameters; import FARSITE/FlamMap results |
| **Data** | Browse and inspect all data sources (FIRMS, weather, terrain, fuel, land cover) |
| **Models** | View trained model details, training history, evaluation metrics, comparison charts |
| **Logs** | Real-time system logs (data ingestion, predictions, errors) |
| **Historical Data** | Replay past fires (2024-2025) with ERA5 weather, compare predictions vs observed FIRMS |
| **Risk Assessment** | View spread risk analysis for selected fires |
| **Alerts** | View all generated alerts with severity levels |
| **Settings** | User preferences, API key configuration |
| **Auth** | Sign up (email + OTP), sign in, Google Sign-In |

### Key Frontend Features
- **3D Globe**: Rotate, zoom, pan; fire markers with zoom-dependent clustering
- **Timeline Slider**: Scrub through prediction horizons (10 min to 72 h)
- **Prediction Overlays**: Probability maps draped on 3D terrain
- **Live Updates (SSE)**: Server-Sent Events push new alerts and prediction updates in real-time
- **Responsive**: Works on different screen sizes

---

## 12. Backend — The Engine Behind the Scenes

### API Endpoints (FastAPI Routers)

| Router File | Endpoints | Purpose |
|---|---|---|
| `auth.py` | `POST /signup`, `POST /verify-email`, `POST /login`, `POST /google-signin` | User authentication |
| `fires.py` | `GET /fires`, `GET /fires/{id}` | List and get fire event details |
| `weather.py` | `GET /weather/{fire_id}` | Get current weather for a fire location |
| `predictions.py` | `POST /predictions`, `GET /predictions/{id}` | Run predictions, get results |
| `simulations.py` | `POST /simulations`, `POST /simulations/import` | Run or import simulations |
| `historical.py` | `GET /historical/fires`, `POST /historical/replay` | Historical fire replay |
| `terrain.py` | `GET /terrain/tiles` | Terrain data for visualization |
| `system.py` | `GET /events/stream` (SSE), `GET /logs`, `GET /health` | System monitoring, live events |

### Key Backend Services

| Service | File | What It Does |
|---|---|---|
| **FIRMS Service** | `services/firms.py` | Fetches fire data from NASA FIRMS API or local files, normalises, deduplicates, clusters into events |
| **Weather Service** | `services/weather.py` | Calls Open-Meteo API, caches responses, stores snapshots, provides weather per fire location |
| **Environment Service** | `services/environment.py` | Builds the local 128x128 grid by combining all data sources (terrain, fuel, land cover, weather, fire state) |
| **Inference Service** | `services/inference.py` | Loads trained PyTorch models, runs prediction for each horizon, generates GeoTIFF + PNG outputs |
| **Prediction Service** | `services/predictions.py` | Orchestrates the full prediction flow: build grid, check cache (input hash), run inference, store in MongoDB, compare with previous, trigger alerts |
| **Monitor Service** | `services/monitor.py` | Background loop (every N seconds): refresh FIRMS, check if weather/fire activity changed, re-predict if needed |
| **Simulation Service** | `services/simulations.py` | Runs WTRS reference simulations in background threads |
| **Historical Service** | `services/historical.py` | Replays past fires using stored FIRMS data + ERA5 weather |
| **Catalog Service** | `services/catalog.py` | Inventories all data files with metadata |
| **Email Service** | `services/email.py` | Generates and validates hashed OTP codes for email verification |

### Authentication Flow
```
1. User enters email + password --> POST /signup
2. Backend hashes password with Argon2id, generates 6-digit OTP
3. OTP is hashed (HMAC) and stored in email_verifications (TTL 5 min)
4. User enters OTP --> POST /verify-email
5. If OTP matches, account activated
6. User logs in --> POST /login --> gets JWT token (HS256)
7. JWT is sent with every API request in the Authorization header
8. Google Sign-In: frontend gets Google ID token, backend verifies with google-auth library
```

---

## 13. Alert System — How Warnings Work

The alert engine checks configurable thresholds and generates alerts with severity levels:

### Alert Types

| Type | Trigger | Example |
|---|---|---|
| **WEATHER_CHANGE** | Wind speed increased, humidity dropped, temperature rose | "Wind speed increased by 7 m/s" = HIGH |
| **FIRE_ACTIVITY_CHANGE** | More FIRMS detections, higher fire radiative power | "Detection count doubled" = WARNING |
| **PREDICTION_CHANGE** | Predicted area changed between consecutive predictions | "Predicted area increased 60%" = WARNING |
| **SPREAD_RISK_CHANGE** | Fire predicted to reach edge of analysis window | "Fire reaches window edge at 24h" = WARNING |
| **DATA_UPDATE** | New data arrived or data source updated | "New FIRMS data available" = INFO |

### Severity Levels
`INFO` then `WARNING` then `HIGH` then `CRITICAL`

### How Thresholds Work (from `config/alert_rules.yaml`)
Example — Wind speed change:
- +4 m/s = WARNING
- +7 m/s = HIGH
- +10 m/s = CRITICAL

All thresholds are configurable in the YAML file. These are research prototype defaults, NOT official emergency criteria.

---

## 14. Complete Folder Structure Explained

```
WildfireTwin/
|-- backend/                    # Python backend (FastAPI)
|   |-- Dockerfile              #   Docker build instructions
|   +-- app/                    #   Main application code
|       |-- main.py             #     App entry point (FastAPI app, startup, MongoDB)
|       |-- config.py           #     Environment variable configuration
|       |-- db.py               #     MongoDB connection, collection setup, indexes
|       |-- api/                #     API route handlers (endpoints)
|       |   |-- auth.py         #       Signup, login, verify, Google sign-in
|       |   |-- fires.py        #       Fire event queries
|       |   |-- weather.py      #       Weather data endpoints
|       |   |-- predictions.py  #       Prediction endpoints
|       |   |-- simulations.py  #       Simulation endpoints
|       |   |-- historical.py   #       Historical replay endpoints
|       |   |-- terrain.py      #       Terrain tile endpoints
|       |   +-- system.py       #       SSE stream, logs, health check
|       |-- services/           #     Business logic services
|       |   |-- firms.py        #       FIRMS data fetching and clustering
|       |   |-- weather.py      #       Open-Meteo API client and caching
|       |   |-- environment.py  #       Build analysis grid from all sources
|       |   |-- inference.py    #       PyTorch model loading and prediction
|       |   |-- predictions.py  #       Prediction orchestration and caching
|       |   |-- monitor.py      #       Background monitoring loop
|       |   |-- simulations.py  #       Reference simulation runner
|       |   |-- historical.py   #       Historical fire replay
|       |   |-- catalog.py      #       Data file inventory
|       |   +-- email.py        #       OTP generation and validation
|       |-- alerts/             #     Alert engine
|       |   |-- engine.py       #       Rule evaluation logic
|       |   +-- store.py        #       Alert persistence and push
|       |-- auth/               #     Authentication helpers
|       |-- schemas/            #     Pydantic request/response models
|       |-- models/             #     Data models / domain objects
|       |-- repositories/       #     Database access layer
|       |-- geospatial/         #     Backend-specific geo utilities
|       |-- ingestion/          #     Data ingestion pipelines
|       |-- ml/                 #     ML integration helpers
|       +-- utils/              #     Utility functions
|
|-- frontend/                   # React frontend
|   |-- index.html              #   HTML entry point
|   |-- package.json            #   NPM dependencies
|   |-- vite.config.ts          #   Vite build configuration
|   |-- tailwind.config.js      #   Tailwind CSS configuration
|   |-- tsconfig.json           #   TypeScript configuration
|   |-- Dockerfile              #   Docker build for frontend
|   |-- nginx.conf              #   Nginx config for production
|   +-- src/                    #   Source code
|       |-- main.tsx            #     React app entry point
|       |-- pages/              #     Page components
|       |   |-- Dashboard.tsx   #       Globe + fire discovery
|       |   |-- Simulation.tsx  #       Run simulations
|       |   |-- Models.tsx      #       Model info and evaluation
|       |   |-- Auth.tsx        #       Login/signup forms
|       |   +-- Misc.tsx        #       Data, Logs, Alerts, Settings, etc.
|       |-- components/         #     Reusable UI components
|       |-- hooks/              #     Custom React hooks
|       |-- layouts/            #     Page layout wrappers
|       |-- lib/                #     Utility libraries
|       |-- services/           #     API client functions
|       |-- stores/             #     Zustand state stores
|       |-- styles/             #     Global CSS
|       |-- types/              #     TypeScript type definitions
|       +-- test/               #     Frontend tests
|
|-- geo/                        # Geospatial processing core
|   |-- rasters.py              #   AnalysisGrid class, GeoTIFF reading/writing, warping
|   |-- terrain.py              #   Slope and aspect calculation (Horn method)
|   |-- fuels.py                #   LANDFIRE FBFM40 fuel model table (40 fuel types)
|   |-- firms.py                #   FIRMS data normalisation and deduplication
|   |-- footprint.py            #   Convert FIRMS pixels to fire mask on grid
|   |-- landscape.py            #   Build complete landscape from all layers
|   |-- landcover.py            #   ESA WorldCover land cover processing
|   |-- weather.py              #   ERA5 reading, Open-Meteo parsing, wind/moisture calcs
|   |-- overlay.py              #   Generate PNG overlays for CesiumJS
|   |-- vectors.py              #   Vector data I/O (shapefiles, GeoJSON)
|   +-- registry.py             #   Data source path registry
|
|-- simulation/                 # Fire spread simulation
|   |-- rothermel.py            #   Rothermel (1972) rate-of-spread model
|   |-- spread.py               #   Elliptical fire shape + MTT solver (Dijkstra)
|   |-- reference.py            #   Orchestrator: run a complete reference simulation
|   |-- weather_sources.py      #   Feed ERA5/Open-Meteo weather into simulations
|   |-- farsite/                #   FARSITE import pipeline
|   |-- flammap/                #   FlamMap import pipeline
|   |-- converters/             #   Convert external simulation outputs
|   |-- scenarios/              #   Scenario definitions
|   +-- outputs/                #   Simulation output storage
|
|-- ml/                         # Machine learning
|   |-- features.py             #   Feature engineering (34 input channels)
|   |-- models/                 #   Model architectures
|   |   |-- factory.py          #     Model factory (create model by name)
|   |   |-- unet/               #     U-Net architecture
|   |   |-- fno/                #     Fourier Neural Operator architecture
|   |   +-- physics_fno/        #     Physics-Informed FNO architecture
|   |-- training/               #   Training scripts
|   |   |-- trainer.py          #     Main training loop (AdamW, OneCycle, early stop)
|   |   |-- train_unet.py       #     Train U-Net entry point
|   |   |-- train_fno.py        #     Train FNO entry point
|   |   +-- train_physics_fno.py#     Train PI-FNO entry point
|   |-- datasets/               #   Dataset generation and PyTorch Dataset class
|   |-- evaluation/             #   Model evaluation and metrics
|   |-- inference/              #   Standalone inference utilities
|   |-- preprocessing/          #   Data preprocessing for ML
|   +-- configs/                #   YAML configs (hyperparameters, channels)
|
|-- config/                     # Configuration files
|   |-- data_sources.yaml       #   Paths to all raw data files
|   +-- alert_rules.yaml        #   Alert threshold definitions
|
|-- data/                       # Processed data and outputs
|   |-- DATA_INVENTORY.md       #   Auto-generated data catalog
|   |-- processed/              #   Processed rasters, weather, vectors
|   |-- models/                 #   Trained model checkpoints and evaluation
|   |-- predictions/            #   Prediction outputs (GeoTIFF, PNG)
|   |-- simulations/            #   Simulation outputs
|   |-- metadata/               #   Data metadata reports
|   +-- mongo/                  #   MongoDB data directory
|
|-- datasets/                   # Raw data downloads (untouched)
|   |-- DL_FIRE_*/              #   FIRMS CSV downloads
|   |-- n*_w*_1arc_v3.tif       #   SRTM elevation tiles
|   |-- landfire_*/             #   LANDFIRE FBFM40 fuel model
|   |-- terrascope_download_*/  #   ESA WorldCover tiles
|   +-- bsp_*/                  #   MTBS burn perimeters
|
|-- scripts/                    # Utility scripts
|   |-- init_env.py             #   Generate .env file with secrets
|   |-- preprocess_firms.py     #   FIRMS CSV to Parquet processing
|   |-- preprocess_era5.py      #   ERA5 GRIB to NetCDF processing
|   |-- preprocess_mtbs.py      #   MTBS shapefile to GeoJSON processing
|   |-- inventory_data.py       #   Auto-generate data inventory
|   |-- write_evaluation_doc.py #   Auto-generate evaluation report
|   |-- start_all.ps1           #   PowerShell script to start all services
|   +-- train_all.ps1           #   PowerShell script to train all models
|
|-- tests/                      # Test suites
|   |-- backend/                #   Backend tests (auth, fires, weather, alerts)
|   |-- geo/                    #   Geospatial function tests
|   +-- ml/                     #   ML pipeline tests
|
|-- docs/                       # Documentation
|   |-- architecture.md         #   System architecture design
|   |-- data_pipeline.md        #   Data processing pipeline
|   |-- model_methodology.md    #   ML model design and training
|   |-- evaluation.md           #   Model evaluation results
|   |-- api.md                  #   API endpoint documentation
|   |-- setup.md                #   Setup and installation guide
|   |-- globe_visualization.md  #   CesiumJS globe implementation
|   |-- scientific_audit.md     #   Scientific accuracy audit
|   |-- wtrs_dataset.md         #   Training dataset documentation
|   +-- farsite_flame_map_workflow.md  # External simulator workflow
|
|-- research/                   # Research materials
|   +-- literature_review.md    #   10-paper literature review
|
|-- docker-compose.yml          # Multi-container Docker setup
|-- requirements.txt            # Python dependencies
|-- pytest.ini                  # Test configuration
|-- .env.example                # Environment variable template
+-- README.md                   # Project readme
```

---

## 15. Key Functions & Files Explained

### Geospatial Core (geo/)

| File | Key Function/Class | What It Does |
|---|---|---|
| `rasters.py` | `AnalysisGrid` class | Defines the 128x128 analysis window — handles coordinate transforms, snaps to LANDFIRE lattice, warps all layers onto common grid |
| `rasters.py` | `warp_to_grid()` | Reprojects any raster onto the analysis grid with logging |
| `terrain.py` | `compute_slope_aspect()` | Horn (1981) algorithm: computes slope (steepness in degrees) and aspect (downhill direction) from elevation |
| `fuels.py` | `FUEL_MODELS` dict | Complete table of all 40 FBFM40 fuel types with their properties (loads, SAV ratios, depth, moisture of extinction) |
| `firms.py` | `normalize_firms()` | Takes raw FIRMS CSV data, standardises column names, parses dates, removes duplicates, assigns detection IDs |
| `footprint.py` | `detections_to_mask()` | Draws FIRMS pixel footprints (scan x track km rectangles) onto the analysis grid to create the initial fire mask |
| `landscape.py` | `build_landscape()` | Combines elevation + slope + aspect + fuel + land cover + fire mask + weather into one analysis package |
| `weather.py` | `read_era5_point()` | Reads ERA5 GRIB file, extracts hourly weather at a given location, converts units (K to C, dewpoint to RH) |
| `weather.py` | `compute_emc()` | Simard (1968) equilibrium moisture content calculation from temperature and humidity |
| `overlay.py` | `probability_to_overlay()` | Converts prediction probability array to coloured transparent PNG for draping on the CesiumJS globe |

### Simulation (simulation/)

| File | Key Function | What It Does |
|---|---|---|
| `rothermel.py` | `rothermel_ros()` | Implements the full Rothermel (1972) equations: reaction intensity to propagating flux to rate of spread, with wind and slope factors |
| `rothermel.py` | `wind_adjustment_factor()` | Albini and Baughman (1979) — converts 10m wind to mid-flame wind based on fuel type |
| `rothermel.py` | `anderson_lb_ratio()` | Anderson (1983) — computes ellipse length-to-breadth ratio from effective wind speed |
| `spread.py` | `minimum_travel_time()` | Dijkstra's algorithm on 16-neighbour grid — finds fastest fire path from ignition to every cell, producing arrival times |
| `reference.py` | `run_reference_simulation()` | Orchestrator: picks random ignition, builds landscape, runs Rothermel + MTT, saves results |

### Machine Learning (ml/)

| File | Key Function/Class | What It Does |
|---|---|---|
| `features.py` | `build_feature_tensor()` | Builds the 34-channel input tensor from landscape + weather data |
| `models/unet/*.py` | `UNet` class | 4-level encoder-decoder CNN with skip connections |
| `models/fno/*.py` | `FNO2d` class | Fourier Neural Operator with 4 spectral layers, zero-padding, spectral convolution |
| `models/physics_fno/*.py` | `PhysicsFNO` class | FNO backbone + arrival-time output + physics loss terms (eikonal, irreversibility, non-burnable) |
| `models/factory.py` | `create_model()` | Factory function — creates the right model by name string ("unet", "fno", "physics_fno") |
| `training/trainer.py` | `Trainer` class | Complete training loop: data loading, loss computation, optimisation, early stopping, checkpointing, MLflow logging |
| `datasets/generate.py` | `generate_dataset()` | Runs 2,400 WTRS simulations, splits into train/val/test, saves as the training dataset |

### Backend Services (backend/app/services/)

| File | Key Function | What It Does |
|---|---|---|
| `firms.py` | `ingest_and_cluster()` | Fetches FIRMS data, deduplicates, clusters detections within 1.5 km over 48h into fire events, updates MongoDB |
| `inference.py` | `run_inference()` | Loads PyTorch model, builds grid, runs model for each horizon, saves GeoTIFF + PNG, returns results |
| `predictions.py` | `create_prediction()` | Full prediction flow: compute input hash, check cache, run inference, compare with previous prediction, generate alerts |
| `monitor.py` | `monitor_loop()` | Background async loop: refresh FIRMS, check each active fire, re-predict if conditions changed materially |
| `weather.py` | `fetch_weather()` | Calls Open-Meteo API, parses response, stores snapshot in MongoDB, returns weather state |

---

## 16. Functional & Non-Functional Requirements

### Functional Requirements

| # | Requirement | Implementation |
|---|---|---|
| FR1 | Display global active fires on an interactive 3D globe | CesiumJS globe + FIRMS API + fire event clustering |
| FR2 | Predict fire spread for 8 time horizons | U-Net / FNO / PI-FNO models with 34-channel input grid |
| FR3 | Automatically re-predict when conditions change | Monitor service + input hash comparison + alert engine |
| FR4 | User authentication with email verification | Argon2id passwords + hashed OTP + JWT + Google Sign-In |
| FR5 | Run reference fire simulations | WTRS (Rothermel + MTT) simulator in Python |
| FR6 | Import external simulation results | FARSITE/FlamMap import pipeline |
| FR7 | Historical fire replay | ERA5 weather + stored FIRMS data + compare predictions vs observations |
| FR8 | Alert generation and notification | Rule engine with configurable thresholds + SSE push |
| FR9 | Data provenance tracking | Every product tagged observed/simulated/predicted/validated |
| FR10 | Model evaluation and comparison | Growth IoU, Dice, Hausdorff distance + per-horizon metrics |

### Non-Functional Requirements

| # | Requirement | How It's Met |
|---|---|---|
| NFR1 | **Performance** — prediction in < 100 ms per horizon | ~3 ms on GPU, ~38 ms on CPU |
| NFR2 | **Scalability** — handle 60,000+ fire events | MongoDB with indexes, efficient clustering |
| NFR3 | **Security** — secure authentication | Argon2id, hashed OTPs, JWT, HTTPS |
| NFR4 | **Usability** — no expertise needed | Web browser only, intuitive UI |
| NFR5 | **Portability** — runs anywhere | Docker Compose packaging |
| NFR6 | **Reliability** — graceful error handling | Fallback to CPU, cached predictions, TTL cleanup |
| NFR7 | **Maintainability** — clear code structure | Modular layers, documentation, tests |
| NFR8 | **Transparency** — all data provenance tracked | Data class labels, transform logs, metadata |

---

## 17. Users of the System

| User Role | What They Can Do |
|---|---|
| **Guest Viewer** | Browse the 3D globe, view fire markers, read fire details, explore data/logs (no prediction or simulation access) |
| **Analyst / Researcher** | Sign in, run predictions, run simulations, replay historical fires, view model evaluations |
| **Disaster-Management User** | Review fire forecasts, monitor alerts, assess spread risk for decision support |
| **System Monitor** | Automated role — the background monitor loop automatically re-forecasts and generates alerts when conditions change |

---

## 18. Scope — What's In and What's Out

### In Scope
- Global fire monitoring (FIRMS from all over the world)
- Spread prediction for fires within Northern California domain (40-42 N, 124.5-122 W)
- Surface fire spread for 8 horizons (10 min to 72 hours)
- Web application with 3D globe, authentication, alerts
- Docker deployment
- Reference simulations (Rothermel + MTT)
- Historical fire replay

### Out of Scope
- Official emergency warnings (this is a research prototype)
- Crown fire modeling (fire that jumps to treetops)
- Fire spotting (embers carried by wind starting new fires)
- Fire suppression modeling (firefighter actions)
- Uncertainty quantification (how confident is the prediction)
- Mobile app
- Global prediction (only N. California domain for now)

---

## 19. Literature Survey Summary

The presentation references 10 IEEE/Scopus-indexed papers (2021-2026):

| # | Paper Focus | Key Takeaway for WildfireTwin |
|---|---|---|
| 1 | Deep Learning fundamentals (Goodfellow et al.) | Foundation for our neural network models |
| 2 | Rothermel fire spread model (1972) | THE physics equation we implement in our simulator |
| 3 | Scott and Burgan fuel models (2005) | 40 fuel model classifications we use from LANDFIRE |
| 4 | DL for fire spread emulation (Allaire et al., 2021) | Showed neural nets can emulate physics simulators |
| 5 | Next Day Wildfire Spread dataset (Huot et al., 2022) | Pioneered ML datasets for wildfire prediction |
| 6 | Neural Operators (Kovachki et al., 2023) | Foundation for our FNO architecture |
| 7 | Generative surrogate for wildfire (Cheng et al., 2023) | Showed surrogate models work for spatial fire prediction |
| 8 | CNN-BiLSTM for fire spread (Marjani et al., 2024) | Combined CNN + LSTM for temporal prediction |
| 9 | Multimodal DNN for fire spread (Shadrin et al., 2024) | Used multiple data modalities (like we do) |
| 10 | ML/DL for wildfire spread review (Andrianarivony et al., 2024) | Comprehensive review of the field |

Additional key references: Fourier Neural Operator paper (Li et al., 2021), Physics-Informed Neural Networks (Raissi et al., 2019).

---

## 20. Existing Systems We Studied

| System | Type | Limitations (Why We're Better) |
|---|---|---|
| **FARSITE** | Desktop physics simulator | Expert-only, manual setup, re-run for each scenario, no live data |
| **FlamMap (MTT)** | Desktop fire behaviour tool | Windows-only desktop app, static weather conditions |
| **NASA FIRMS** | Satellite fire detection | Shows current fires only — NO spread prediction |
| **DL Research Models** | Academic code | Offline code, single dataset, no live data integration, no alerts |

**WildfireTwin combines the best of all:**
- Physics knowledge (Rothermel equation) like FARSITE
- Real-time satellite data like FIRMS
- Fast neural predictions like DL models
- Web-based with live updates (unique to our system)

---

## 21. Evaluation Results — How Good Are the Models?

All three models were evaluated on **5,086 test samples** from unseen spatial regions:

### Overall Performance

| Model | Growth IoU (higher=better) | Growth F1 (higher=better) | Hausdorff Distance (lower=better) | GPU Speed | CPU Speed |
|---|---|---|---|---|---|
| **U-Net** | **0.619** | **0.712** | **374 m** | 2.6 ms | 17 ms |
| **FNO** | 0.561 | 0.662 | 442 m | 2.9 ms | 38 ms |
| **PI-FNO** | 0.578 | 0.678 | 411 m | 2.9 ms | 38 ms |
| *Persistence (do nothing)* | 0.159 | 0.159 | 816 m | -- | -- |

### What These Metrics Mean (Simple)

| Metric | What It Measures | Simple Explanation |
|---|---|---|
| **Growth IoU** | Intersection over Union of new growth area | "Of the cells that either actually grew or were predicted to grow, how many did the model get right?" Higher = better. |
| **Growth F1** | Harmonic mean of precision and recall for growth | Balances "did we predict real growth?" and "did we miss real growth?" |
| **Hausdorff Distance** | Maximum boundary mismatch in metres | "What's the worst-case distance between predicted and actual fire boundary?" Lower = better. |
| **GPU Speed** | Milliseconds per prediction on GPU | How fast the model runs |
| **Speed-up** | How much faster than re-simulating | U-Net is 14x faster than running the physics simulator again |

### Key Takeaway
- All three models are **dramatically better** than "doing nothing" (persistence baseline)
- U-Net is slightly more accurate overall, but PI-FNO improves at longer horizons (48h, 72h)
- All models produce predictions in **2-3 ms on GPU** — practically instant
- These metrics measure agreement with the **reference simulator**, not real-world ground truth

---

## 22. Limitations (Be Honest About These)

When your teacher asks about limitations, mention these honestly:

1. **Training targets are simulations, not real fire observations** — models learn to mimic the Rothermel simulator, not actual fire behaviour
2. **Surface fire only** — no crown fire (fire in treetops), no fire spotting (embers), no suppression effects
3. **Initial state from satellite pixels** — FIRMS gives 375m or 1km pixel footprints, not precise fire perimeters
4. **Weather is spatially uniform** per analysis window — in reality, weather varies across the area
5. **Domain limited to N. California** — needs LANDFIRE fuel data, which is US-only
6. **No uncertainty quantification** — we don't say "we're 80% confident"; we just give a probability map
7. **ERA5 vs Open-Meteo mismatch** — training uses ERA5 weather, live prediction uses Open-Meteo (different resolution/bias)

---

## 23. How To Explain Each Slide

### Slide 1: Title Slide
> "My project is called WildfireTwin. The full title is 'Physics-Informed Neural Operator for Dynamic Wildfire Spread Prediction'. It's my MCA Capstone project under the guidance of Dr. C. Menaka."

### Slide 2: Abstract
> "WildfireTwin is a research prototype that monitors active fires globally using NASA satellite data and predicts where fires will spread using three deep learning models. It takes in satellite fire detections, terrain, vegetation, and weather data, and predicts the burned area at 8 time horizons from 10 minutes to 72 hours. The models are trained on 22,505 samples from 2,400 physics-based simulations."

### Slide 3: Introduction (Problem + Solution + Scope)
> "The problem is that satellites show where fires burn now but not where they'll spread. Existing simulators like FARSITE are slow and need experts. Our solution uses neural networks (U-Net, FNO, Physics-Informed FNO) that predict spread in milliseconds. The scope covers global fire monitoring and prediction in Northern California."

### Slide 4: Literature Survey
> "We reviewed 10 IEEE/Scopus-indexed papers from 2021-2026 covering deep learning for fire spread prediction, neural operators, and physics-informed neural networks. Key papers include the Rothermel fire model, the Fourier Neural Operator paper by Li et al., and the Physics-Informed Neural Networks paper by Raissi et al."

### Slide 5: Background & Comparative Study
> "We studied four existing systems: FARSITE (physics simulator, but desktop-only and slow), FlamMap (static conditions), NASA FIRMS (detects fires but doesn't predict spread), and academic DL models (offline, no live data). WildfireTwin combines the strengths of all four."

### Slide 6: Tools & Technologies + NFRs
> "We use React + CesiumJS for the frontend, FastAPI for the backend, PyTorch for ML, MongoDB for the database, and multiple geospatial libraries like rasterio and GDAL. Non-functional requirements include sub-100ms prediction speed, Docker deployment, and secure authentication."

### Slide 7: Functional Requirements
> "There are four types of users: guest viewers who browse fires, analysts who run predictions and simulations, disaster-management users who review forecasts and alerts, and the system monitor which automatically re-forecasts when conditions change."

### Slide 8: System Architecture
> "The architecture has four layers: data sources (NASA FIRMS, Open-Meteo, ERA5, SRTM, LANDFIRE, WorldCover), the FastAPI backend with services for ingestion, inference, monitoring and alerts, PyTorch ML models (U-Net, FNO, PI-FNO), and the React frontend with a CesiumJS 3D globe. MongoDB stores metadata, files store rasters."

### Slide 9: Database Design
> "We use MongoDB with 9 collections. The main ones are fire_events (with geospatial 2dsphere indexes), predictions (linked to fires and users), weather_conditions, and alerts. We use TTL indexes for auto-cleanup of OTP codes and old logs. Raster images stay as files; MongoDB only stores their paths and metadata."

### Slide 10: References
> "We cite 20 references in IEEE format including foundational works like Rothermel 1972, Deep Learning by Goodfellow, the FNO paper, the PINN paper, and data sources like NASA FIRMS, LANDFIRE, and ERA5."

### Slide 11: Thank You
> "Thank you. I'm ready for questions and a live demonstration of the system."

---

## Pro Tips for the Presentation

- **When asked "why FNO instead of just CNN?"** say: "Fire spread depends on terrain and wind kilometres away, not just adjacent cells. FNO uses Fourier Transform to mix information globally — every pixel talks to every other pixel in one layer."

- **When asked "what makes it physics-informed?"** say: "We add physics constraints to the loss function — the eikonal equation (fire speed times gradient = 1), irreversibility (burned cells stay burned), and non-burnable constraints (fire can't enter water or rock)."

- **When asked "what's the Digital Twin aspect?"** say: "We create a virtual copy of a real wildfire by combining real satellite data, real terrain, real weather, and predicting how the fire will evolve — that's the digital twin."

- **When asked "is this better than FARSITE?"** be honest: "Our models are trained on physics-based simulations similar to FARSITE, so they're surrogates — they approximate the simulator but run 14x faster. They're not necessarily more accurate than FARSITE, but they're much faster and don't need expert setup."
