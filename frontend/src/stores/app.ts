import { create } from "zustand";

import type { WindPerformance, WindRenderSettings } from "../components/globe/wind/windParticles";
import type { ActiveFiresResponse, Alert, LogEntry, Prediction } from "../types/api";

export interface Overlay {
  id: string;
  url: string;
  bounds: [number, number, number, number];
  kind: "prediction" | "footprint" | "simulation" | "observed";
}

export interface Layers {
  fires: boolean;
  imagery: "satellite" | "dark" | "daily";
  terrain: boolean;
  relief: boolean;
  nightLights: boolean;
  prediction: boolean;
  front: boolean;
  footprint: boolean;
  borders: boolean;
  wind: boolean;       // single Open-Meteo observation at the selected fire
  windFlow: boolean;   // global wind-flow particles (NOAA GFS 10 m field)
}

/** What the globe is currently showing on the forecast timeline (set by the animation engine at phase changes only). */
export type AnimPhase = { kind: "frame"; index: number } | { kind: "blend"; from: number; to: number };

/** Status of the global wind field used by the wind-flow layer (never substituted by synthetic data). */
export type WindFieldStatus =
  | { state: "idle" | "loading" }
  | { state: "ok"; source: string; cycle: string; maxSpeed: number }
  | { state: "unavailable"; message: string };

export type { WindPerformance, WindRenderSettings };

export interface WindObs { lat: number; lon: number; speed: number; fromDeg: number; time: string; source: string }

interface AppState {
  fires: ActiveFiresResponse | null;
  firesError: string | null;
  setFires: (f: ActiveFiresResponse | null, err?: string | null) => void;

  selectedFireId: string | null;
  selectFire: (id: string | null) => void;
  flyTo: { lat: number; lon: number; height: number; key: number } | null;
  requestFlyTo: (lat: number, lon: number, height?: number) => void;

  prediction: Prediction | null;
  setPrediction: (p: Prediction | null) => void;
  timelineIndex: number;            // 0 = NOW, 1..8 = horizons
  setTimelineIndex: (i: number) => void;
  playing: boolean;
  setPlaying: (v: boolean) => void;
  playbackSpeed: number;            // 0.5 | 1 | 2 | 4
  setPlaybackSpeed: (v: number) => void;
  animPhase: AnimPhase;
  setAnimPhase: (p: AnimPhase) => void;
  cameraCommand: { kind: "global" | "focus" | "zoomIn" | "zoomOut"; key: number } | null;
  sendCameraCommand: (kind: "global" | "focus" | "zoomIn" | "zoomOut") => void;
  overlayOpacity: number;
  setOverlayOpacity: (v: number) => void;
  extraOverlays: Overlay[];         // simulation / historical overlays
  setExtraOverlays: (o: Overlay[]) => void;

  layers: Layers;
  setLayer: <K extends keyof Layers>(k: K, v: Layers[K]) => void;

  wind: WindObs | null;
  setWind: (w: WindObs | null) => void;
  windSettings: WindRenderSettings;
  setWindSettings: (p: Partial<WindRenderSettings>) => void;
  windStatus: WindFieldStatus;
  setWindStatus: (s: WindFieldStatus) => void;

  cursor: { lat: number; lon: number } | null;
  setCursor: (c: { lat: number; lon: number } | null) => void;

  logs: LogEntry[];
  pushLog: (l: LogEntry) => void;
  setLogs: (l: LogEntry[]) => void;
  alerts: Alert[];
  pushAlert: (a: Alert) => void;
  setAlerts: (a: Alert[]) => void;
  live: boolean;
  setLive: (v: boolean) => void;
}

const MAX_LOGS = 400;

export const useApp = create<AppState>((set) => ({
  fires: null,
  firesError: null,
  setFires: (fires, err = null) => set({ fires, firesError: err }),

  selectedFireId: null,
  selectFire: (id) => set({ selectedFireId: id, prediction: null, timelineIndex: 0, wind: null, playing: false,
    animPhase: { kind: "frame", index: 0 } }),
  flyTo: null,
  requestFlyTo: (lat, lon, height = 25000) => set({ flyTo: { lat, lon, height, key: Date.now() } }),

  prediction: null,
  setPrediction: (prediction) => set({ prediction, timelineIndex: prediction ? 1 : 0, playing: false,
    animPhase: { kind: "frame", index: prediction ? 1 : 0 } }),
  timelineIndex: 0,
  setTimelineIndex: (timelineIndex) => set({ timelineIndex }),
  playing: false,
  setPlaying: (playing) => set({ playing }),
  playbackSpeed: 1,
  setPlaybackSpeed: (playbackSpeed) => set({ playbackSpeed }),
  animPhase: { kind: "frame", index: 0 },
  setAnimPhase: (animPhase) => set({ animPhase }),
  cameraCommand: null,
  sendCameraCommand: (kind) => set({ cameraCommand: { kind, key: Date.now() } }),
  overlayOpacity: 0.85,
  setOverlayOpacity: (overlayOpacity) => set({ overlayOpacity }),
  extraOverlays: [],
  setExtraOverlays: (extraOverlays) => set({ extraOverlays }),

  layers: { fires: true, imagery: "satellite", terrain: true, relief: true, nightLights: true, prediction: true, front: true,
    footprint: true, borders: true, wind: true, windFlow: true },
  setLayer: (k, v) => set((s) => ({ layers: { ...s.layers, [k]: v } })),

  wind: null,
  setWind: (wind) => set({ wind }),
  windSettings: { opacity: 0.55, density: 1, speed: 1, performance: "auto" },
  setWindSettings: (p) => set((s) => ({ windSettings: { ...s.windSettings, ...p } })),
  windStatus: { state: "idle" },
  setWindStatus: (windStatus) => set({ windStatus }),

  cursor: null,
  setCursor: (cursor) => set({ cursor }),

  logs: [],
  pushLog: (l) => set((s) => ({ logs: [l, ...s.logs].slice(0, MAX_LOGS) })),
  setLogs: (logs) => set({ logs }),
  alerts: [],
  pushAlert: (a) => set((s) => ({ alerts: [a, ...s.alerts.filter((x) => x.alert_id !== a.alert_id)].slice(0, 200) })),
  setAlerts: (alerts) => set({ alerts }),
  live: false,
  setLive: (live) => set({ live }),
}));
