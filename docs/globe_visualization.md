# Globe & Visualization

The 3D globe is a CesiumJS viewer (true WGS84 globe, not a 2D map). All code is in
`frontend/src/components/globe/`; `components/GlobeViewer.tsx` re-exports it for existing pages.

| Module | Responsibility |
|---|---|
| `GlobeViewer.tsx` | orchestration: creates viewer + ticker, picking (click / double-click / hover), domain outline, frame-status banner, camera-dependent updates |
| `viewerSetup.ts` | scene: sun lighting at "now", atmosphere, stars, fog, render settings |
| `imagery.ts` | imagery manager (satellite, dark, dated VIIRS, night lights, boundaries) |
| `terrain.ts` | terrain manager (SRTM / Cesium World Terrain / ellipsoid) and relief (hillshade) layer |
| `useCesiumCamera.ts` | camera controller: zoom feel, limits, collision, fly-to, global view, button zoom |
| `useFireVisualization.ts` | FIRMS markers: cores, clustering, halos + pulse, selected-fire highlight |
| `usePredictionAnimation.ts` | forecast frames, playback engine, fire front, analysis window, observed footprint |
| `useWindLayer.ts` | Open-Meteo wind vector at the selected fire |
| `useOverlayLayers.ts` | static overlays for Simulation / Historical pages, GeoJSON perimeters |
| `MapControls.tsx` | + / − / global view / focus fire, altitude readout |
| `ticker.ts` | single shared `requestAnimationFrame` loop for all animations |

## Globe rendering

* **Lighting:** `globe.enableLighting` with the real sun position for the current time (`clock.currentTime = now`,
  not animated). Cesium measures fade distances from the **Earth's centre**; shading is
  0 % below ~9,600 km altitude (analysis views are readable regardless of local time), ~40 % at the default global
  view and 100 % only far out (`lightingFadeOut/InDistance = 1.6e7 / 3.6e7 m`). Without terrain vertex normals
  Cesium's unlit side drops to 30 % brightness, which made a full-strength night hemisphere black — hence the blend.
* **Atmosphere:** sky atmosphere with reduced brightness/saturation (no strong blue halo), ground atmosphere with
  dynamic sun lighting, `atmosphereLightIntensity 6`, light fog for oblique horizons. The sun disc and moon are
  hidden (no lens glare); the star background is Cesium's Tycho-2 sky box.
* **Imagery (all real, key-free):**
  | Option | Source | Notes |
  |---|---|---|
  | Satellite (default) | Esri World Imagery | slightly muted (brightness 0.92, saturation 0.88) so fire overlays stay brightest |
  | VIIRS *date* | NASA GIBS VIIRS S-NPP Corrected Reflectance, true colour, date of the latest FIRMS acquisition | real clouds of that day |
  | Dark | Esri World Dark Gray Canvas | |
  | Night lights | NASA GIBS VIIRS Black Marble 2016 | `dayAlpha 0`, `nightAlpha 0.45` — night side only, partial so the land stays visible |
  | Boundaries & places | Esri World Boundaries & Places | |
* **Clouds:** no synthetic cloud layer exists. The only cloud source is the dated VIIRS true-colour composite.
  Extension point: add a GIBS cloud-mask / cloud-fraction product in `imagery.ts`.

## Terrain

* Heights: Cesium World Terrain when `VITE_CESIUM_ION_TOKEN` is set; otherwise SRTM 1″ tiles from
  `/api/terrain/{z}/{x}/{y}.bin` (65×65 float32, geographic tiling) inside the local SRTM coverage and the ellipsoid
  (height 0) elsewhere — terrain height is never invented. No vertical exaggeration.
* Relief: `/api/terrain/hillshade/{z}/{x}/{y}.png` — Horn gradients of the same SRTM data, illumination azimuth
  315° / altitude 45°; shadowed slopes darkened, lit slopes slightly brightened, flat ground transparent. The
  layer's opacity follows camera height (`reliefAlpha`): 0 above ~600 km, rising log-linearly to 0.85 below ~12 km.
  (Needed because Cesium's custom heightmap provider supplies no vertex normals, so sunlight alone cannot shade
  relief.)

## Fire markers (observed)

* Cesium `PointPrimitiveCollection`s only — no DOM or React node per fire.
* **Cores:** one per event; size and colour from the event's real FRP sum (5 / 50 / 200 MW steps from red-orange
  to warm yellow); events last detected more than 24 h ago are dimmer amber. Model-domain events have a thin cyan
  outline.
* **Clustering:** grid aggregation by camera height — 2° (>6,000 km), 1°, 0.5°, 0.15°, then individual events below
  350 km. Cluster counts are labelled for the 40 largest clusters. Aggregations are cached per data snapshot.
* **Halos + pulse:** a separate collection of soft halos for *active* events/clusters in view only (≤ 1,200
  individual or 150 clusters), rebuilt on camera move-end. The ticker animates them with a 1.6 s period, ±11 %
  size and 45–100 % of a low base opacity (phase-offset per marker). Disabled with `prefers-reduced-motion`.
* **Depth:** points within 1,500 km of the camera draw over terrain; farther ones are depth-tested so the globe
  hides detections on its far side.
* **Selected fire:** white ring + core, an orange glow that pulses (1.8 s), and a label with event ID and
  coordinates. Markers are detection clusters, never perimeters.

## Camera & zoom

| Setting | Value | Purpose |
|---|---|---|
| `zoomFactor` | 3 (Cesium default 5) | gentler wheel / trackpad steps |
| `inertiaZoom / inertiaSpin / inertiaTranslate` | 0.85 / 0.9 / 0.9 | smooth, inertial motion |
| `minimumZoomDistance` | 250 m | cannot dive into the ground |
| `maximumZoomDistance` | 45,000 km | cannot lose the globe |
| `enableCollisionDetection` | true | terrain collision |
| `maximumMovementRatio` | 0.08 | limits per-event jumps |

* Mouse: left-drag rotate/pan · right-drag or wheel zoom · middle-drag or Ctrl+drag tilt. Panels sit outside the
  canvas, so scrolling them never moves the map.
* **Select a fire** (click) → `flyToBoundingSphere` to a 16 km range at −42° pitch; duration 1.4–4.5 s scaled by
  distance (log), quadratic in/out easing — Cesium arcs the path global → regional → local.
* **Double-click a fire** → selects it and focuses closer (4.5 km). Cesium's default double-click entity tracking is
  removed.
* **Map controls:** + / − (0.7 s eased steps along the view direction), GLOBAL VIEW (smooth return to the 17,500 km
  default view), FOCUS FIRE (re-centre on the selected fire). Altitude readout updates without React re-renders.

## Forecast visualization & animation (predicted)

* **Frames = real model outputs only.** Each forecast step with status `ok` is one frame: the probability PNG and
  the fire-front PNG produced by the backend from the model's probability raster (reprojected EPSG:5070 →
  EPSG:4326 and draped as imagery layers, so they follow the terrain surface). NOW shows the observed FIRMS
  footprint. Missing or unavailable horizons are skipped — no frame is synthesised or extrapolated, and the banner
  reads `PREDICTION UNAVAILABLE · <h>` if the slider is placed on one.
* **Probability ramp (overlay style v4):** p < 0.05 transparent → dark translucent red → orange (≈0.6) → warm orange
  (≈0.9) → small light-orange hot cores only at p ≥ 0.98. Alpha 50–195 so imagery, terrain and boundaries remain
  visible. The legend reads "Fire spread probability 0.0–1.0" (model probability, never "certainty").
* **Fire front:** outer boundary of p ≥ 0.5 of the same frame (interior holes filled first) — geometry of the
  model output, not a generated front. It glows gently (2.2 s) only during playback.
* **Analysis window:** dashed outline of the frame's 128×128 model window (30 / 60 / 120 m cells by horizon).
* **Playback engine:** hold each real frame 1.5 s, then cross-fade 0.9 s to the next available frame (÷ speed:
  0.5×, 1×, 2×, 4×); loops. During a cross-fade the banner shows
  `VISUAL BLEND a → b (transition between model frames, not a model output)`; on a frame it shows
  `MODEL FRAME <h> · <model>`. Pausing mid-blend snaps to the nearer real frame.
* **Timeline sync:** the forecast timeline is the controller — slider, NOW…72h buttons, previous/next (skip
  unavailable horizons), play/pause, speed. Moving the slider pauses playback and jumps to the real frame; the
  prediction summary, preview and metadata follow the same `timelineIndex`.
* Changing the overlay style bumps `OVERLAY_STYLE_VERSION`, which is part of the prediction input hash, so new
  requests regenerate overlays instead of returning cached old-style images.

## Wind (observed)

The selected fire's current Open-Meteo 10 m wind: a downwind arrow (300 m per m/s, ≥ 400 m) with a label, and three
faint markers drifting along it at a rate proportional to the observed speed. A single real observation — no wind
field is interpolated.

## Visual distinction of data classes

| Class | Style |
|---|---|
| Observed FIRMS | orange/red point cores with soft halos |
| Observed footprint | thin cyan outline |
| Predicted | translucent red→orange probability raster + light fire-front line |
| Reference (simulation / historical) | arrival-time ramp (pale→dark red) / green observed outlines |
| Model domain / analysis window | dashed cyan / dashed light grey |

## Performance

* `requestRenderMode` — an idle globe renders only when something changes.
* One shared ticker (≤ 30 fps, paused when the tab is hidden) mutates Cesium primitives/layers directly; React
  state changes only at animation phase changes (a few per second at most).
* Pulse touches ≤ 1,200 primitives; marker collections are rebuilt only on data or cluster-level change; halos only
  on camera move-end.
* Forecast frames are preloaded once per prediction; playback changes layer alpha only.
* Measured (Playwright, Chromium on the dev laptop's Intel integrated GPU via D3D11, 1600×950): main thread
  60 fps in all states; Cesium renders 30/s with the marker pulse, ~57/s during playback; JS heap 188 MB.
  Software rendering (SwiftShader, headless default) is far slower and not representative.

## Error handling

* WebGL failure → message instead of the globe.
* Terrain endpoint unavailable → ellipsoid; hillshade tiles outside coverage return 204 and are skipped.
* Imagery service unavailable → the other basemap options remain selectable.
* No prediction / unavailable horizon → no layer is created; the banner and summary panel say so.

## Testing

* `frontend/src/test/globe.test.ts` — frame availability (unavailable/missing horizons never become frames), relief
  fade, clustering totals.
* `tests/geo/test_overlays.py` — fire front is the outer boundary only, probability PNG transparency, hillshade tiles
  inside/outside coverage.
* Playwright acceptance flow (global → Redding → FIRMS fire → forecast → slider → play/pause → global view).
