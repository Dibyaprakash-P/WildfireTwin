export type DataClass = "observed" | "simulated" | "predicted" | "validated";

export interface ActiveFiresResponse {
  meta: FiresMeta & { count: number; total_events: number; total_detections: number };
  columns: string[];
  rows: [string, number, number, number, number | null, number, "active" | "recent", boolean][];
}

export interface FiresMeta {
  source: string;
  latest_acquisition: string | null;
  window_start: string | null;
  loaded_at: string;
  data_class: DataClass;
  note: string;
}

export interface FireEvent {
  event_id: string;
  status: string;
  data_class: DataClass;
  latitude: number;
  longitude: number;
  bbox: [number, number, number, number];
  detection_count: number;
  high_confidence_count: number;
  frp_sum_mw: number | null;
  frp_max_mw: number | null;
  first_seen: string | null;
  last_seen: string | null;
  satellites: string[];
  instruments: string[];
  in_model_domain: boolean;
  source: string;
  footprint_method: string;
}

export interface Detection {
  detection_id: string;
  latitude: number;
  longitude: number;
  acq_datetime: string;
  satellite: string;
  instrument: string;
  confidence_raw: string | null;
  confidence_class: string | null;
  frp_mw: number | null;
  brightness_k: number | null;
  daynight: string | null;
  source: string;
}

export interface FireDetail {
  meta: FiresMeta;
  event: FireEvent;
  detections: Detection[];
  detections_truncated: boolean;
}

export interface Valued<T = number | string | null> {
  value: T;
  units: string;
  source: string;
  timestamp: string | null;
}

export interface WeatherBlock {
  source: string;
  fetched_at: string;
  current: { time: string; values: Record<string, number | null>; units: Record<string, string | null> };
  summary: Record<string, Record<string, number | null>>;
  grid_elevation_m: number | null;
}

export interface EnvironmentResponse {
  fire_id: string;
  latitude: number;
  longitude: number;
  weather: WeatherBlock | null;
  weather_error: string | null;
  local:
    | { available: false; reason: string }
    | {
        available: true;
        window_m: number;
        terrain: Record<string, Valued<number | number[] | null>>;
        fuel: { fuel_model: Valued<string>; burnable_fraction: Valued<number>; composition: Valued<{ code: number; name: string; fraction: number }[]> };
        land_cover: { class: Valued<string | null>; composition: Valued<{ code: number; name: string; fraction: number }[] | null> };
      };
  fire: {
    active_fire_count: number;
    high_confidence_count: number;
    frp_sum_mw: number | null;
    frp_max_mw: number | null;
    latest_observation: string | null;
    first_observation: string | null;
    satellites: string[];
    footprint_method: string;
    detections_by_day: Record<string, number>;
    source: string;
  };
}

export interface PredictionStep {
  horizon_min: number;
  label: string;
  band?: string;
  cell_m?: number;
  status: "ok" | "unavailable" | "not_requested";
  reason?: string;
  message?: string;
  inference_ms?: number;
  predicted_area_km2?: number;
  initial_area_km2?: number;
  growth_area_km2?: number;
  spread_bearing_deg?: number | null;
  max_spread_distance_km?: number | null;
  touches_window_edge?: boolean;
  overlay_url?: string;
  front_url?: string;
  overlay_style?: number;
  footprint_url?: string;
  bounds_wgs84?: [number, number, number, number];
  footprint_bounds_wgs84?: [number, number, number, number];
  weather?: Record<string, number | null>;
  weather_meta?: Record<string, unknown>;
}

export interface Prediction {
  prediction_id: string;
  fire_id: string;
  data_class: "predicted";
  product: string;
  model: { type: string; name: string; version: string; run_id: string; checkpoint: string; dataset_version: string; device: string };
  inputs: Record<string, unknown>;
  steps: PredictionStep[];
  uncertainty: string;
  total_runtime_ms: number;
  limitations: string[];
  created_at: string;
  trigger: string;
  cause?: string | null;
  cached?: boolean;
  previous_prediction_id?: string | null;
}

export interface Alert {
  alert_id: string;
  type: string;
  severity: "INFO" | "WARNING" | "HIGH" | "CRITICAL";
  title: string;
  lines: string[];
  fire_id: string | null;
  prediction_id: string | null;
  created_at: string;
  acknowledged: boolean;
  disclaimer: string;
}

export interface LogEntry {
  ts: string;
  level: string;
  component: string;
  message: string;
}

export interface User {
  id: string;
  email: string;
  auth_providers: string[];
  created_at: string;
}

export interface ModelStatus {
  model_type: string;
  name: string;
  trained: boolean;
  run_id: string | null;
  checkpoint: string | null;
  summary: Record<string, unknown> | null;
}
