# API Reference

Base URL: `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs`. All errors use
`{"error": {"code": "...", "message": "...", "details": ...}}`. Endpoints marked 🔒 require
`Authorization: Bearer <JWT>`.

## System
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | MongoDB, FIRMS snapshot, model availability, CUDA, integrations, study region |
| GET | `/api/models` | trained-model registry (run id, checkpoint, training summary) |
| GET | `/api/models/compare` | evaluation results, or `{"status": "not_evaluated"}` |
| GET | `/api/logs?limit&component&level` | stored system events |
| GET | `/api/alerts?fire_id&severity&limit` / `/api/alerts/{id}` | alerts |
| POST 🔒 | `/api/alerts/{id}/ack` | acknowledge |
| GET | `/api/data/catalog` | dataset catalogue with extracted metadata |
| GET | `/api/events/stream` | Server-Sent Events: `log`, `alert`, `prediction`, `simulation`, `fires` |

## Auth
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/auth/signup` | `{email, password, confirm_password}` | 400 "Invalid email address." · 409 account exists · sends 6-digit OTP |
| POST | `/api/auth/verify-otp` | `{email, code}` | expiry 5 min, max 5 attempts → `{access_token, user, message: "Signup successful."}` |
| POST | `/api/auth/resend-otp` | `{email}` | 60 s cooldown, max 5 resends |
| POST | `/api/auth/login` | `{email, password}` | 404 "No account found. Please sign up first." · 401 "Incorrect email or password." |
| GET | `/api/auth/google/config` | | `{configured, client_id}` |
| POST | `/api/auth/google` | `{credential}` (Google ID token) | 503 if `GOOGLE_CLIENT_ID` unset |
| GET 🔒 | `/api/auth/me` | | current user |

## Fires (observed)
| Method | Path | Description |
|---|---|---|
| GET | `/api/fires/active?min_detections&status&in_domain` | compact columnar list of events for the globe |
| GET | `/api/fires?sort=frp|detections|last_seen&limit&offset&in_domain` | paged events |
| GET | `/api/fires/nearby?lat&lon&radius_km&limit` | nearest events |
| GET | `/api/fires/{fire_id}` | event + detections |
| GET | `/api/search?q=` | coordinates, FE-IDs, place names (Open-Meteo geocoding) |

## Weather / environment
| Method | Path | Description |
|---|---|---|
| GET | `/api/weather/current?lat&lon` | Open-Meteo current values + units |
| GET | `/api/weather/forecast?lat&lon` | hourly series + horizon summaries |
| GET | `/api/environment/{fire_id}` | weather, terrain (elevation/slope/aspect), fuel, land cover, fire stats — each with source/units/timestamp |
| GET | `/api/terrain/info`, `/api/terrain/{z}/{x}/{y}.bin` | SRTM heightmap tiles (65×65 float32) for Cesium |

## Predictions (predicted)
| Method | Path | Description |
|---|---|---|
| POST 🔒 | `/api/predictions` | `{fire_id, horizons_min?, model_type?}` → prediction document (cached by input hash) |
| GET | `/api/predictions?fire_id&limit` | list |
| GET | `/api/predictions/{id}` | document |
| GET | `/api/predictions/{id}/timeline` | NOW…72h steps; unavailable steps say "Forecast unavailable" |
| GET | `/files/predictions/{id}/{label}_prob.png|.tif` | overlay / GeoTIFF |

## Simulations (simulated)
| Method | Path | Description |
|---|---|---|
| POST 🔒 | `/api/simulations` | WTRS reference run: `{fire_id | latitude+longitude, ignition, duration_hours ≤72, cell_m 30/60/120, weather_source open_meteo/era5/constant, era5_start?, constant?, live_herb, live_woody}` |
| POST 🔒 | `/api/simulations/import` | multipart: `file`, `kind` (arrival_raster/perimeters), `simulator` (FARSITE/FlamMap/other), `units`, `time_field?` |
| GET | `/api/simulations`, `/api/simulations/{id}` | status / results |

## Historical (observed → validated)
| Method | Path | Description |
|---|---|---|
| GET | `/api/historical?min_year` | burned-area perimeters in/near the study region, with replay availability |
| GET | `/api/historical/{hist_id}` | perimeter GeoJSON, FIRMS detections per day |
| POST 🔒 | `/api/historical/{hist_id}/replay` | `{t0, model_type?}` → predictions from the observed state at t0 with ERA5 weather, compared with the observed FIRMS footprint at t0 + h |
