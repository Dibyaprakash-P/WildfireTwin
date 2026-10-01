import * as Cesium from "cesium";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { type Overlay, useApp } from "../../stores/app";
import type { Prediction } from "../../types/api";
import { LABELS } from "../ForecastTimeline";
import { addBaseImagery, applyImagery, type ImageryHandles } from "./imagery";
import MapControls from "./MapControls";
import { attachTerrain, reliefAlpha, type TerrainHandles } from "./terrain";
import { createTicker, type Ticker } from "./ticker";
import { flyToPoint, FIRE_CLOSE_RANGE_M, useCesiumCamera } from "./useCesiumCamera";
import { useFireVisualization } from "./useFireVisualization";
import { useOverlayLayers } from "./useOverlayLayers";
import { usePredictionAnimation } from "./usePredictionAnimation";
import { useWindLayer } from "./useWindLayer";
import { createViewer } from "./viewerSetup";

export interface GlobeViewerProps {
  overlays?: Overlay[];
  geojson?: object | null;
  prediction?: Prediction | null;   // animated forecast frames (Dashboard)
  showDomain?: boolean;
  className?: string;
}

const DOMAIN = Cesium.Color.fromCssColorString("#4cc3d9");

/**
 * Orchestrates the Cesium globe. Responsibilities are split into managers/hooks:
 * viewerSetup (scene/lighting/atmosphere) · imagery · terrain · useCesiumCamera · useFireVisualization ·
 * usePredictionAnimation · useWindLayer · useOverlayLayers · MapControls. See docs/globe_visualization.md.
 */
export default function GlobeViewer({ overlays = [], geojson = null, prediction = null, showDomain = true, className = "" }: GlobeViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const altRef = useRef<HTMLSpanElement>(null);
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [terrainSource, setTerrainSource] = useState<string>("");
  const imagery = useRef<ImageryHandles | null>(null);
  const terrain = useRef<TerrainHandles | null>(null);

  const fires = useApp((s) => s.fires);
  const layers = useApp((s) => s.layers);
  const selected = useApp((s) => s.selectedFireId);
  const opacity = useApp((s) => s.overlayOpacity);
  const wind = useApp((s) => s.wind);
  const animPhase = useApp((s) => s.animPhase);

  // ---------------------------------------------------------------- init (once)
  useEffect(() => {
    if (!host.current) return;
    let v: Cesium.Viewer;
    try {
      v = createViewer(host.current);
    } catch (e) {
      setErr(`3D globe could not start (WebGL required): ${(e as Error).message}`);
      return;
    }
    imagery.current = addBaseImagery(v);
    if (import.meta.env.DEV) (window as unknown as { __wtViewer?: Cesium.Viewer }).__wtViewer = v; // dev/test inspection only
    const tk = createTicker(v);
    setViewer(v);
    setTicker(tk);
    attachTerrain(v).then((t) => {
      terrain.current = t;
      setTerrainSource(t.source);
      updateCameraDependent(v);
    });

    const handler = new Cesium.ScreenSpaceEventHandler(v.scene.canvas);
    handler.setInputAction((ev: { position: Cesium.Cartesian2 }) => {
      const id = v.scene.pick(ev.position)?.id as { kind?: string; eventId?: string; lat?: number; lon?: number } | undefined;
      if (id?.kind === "event" && id.eventId) useApp.getState().selectFire(id.eventId);
      else if (id?.kind === "cluster" && id.lat !== undefined && id.lon !== undefined) {
        const h = v.camera.positionCartographic.height;
        v.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(id.lon, id.lat, Math.max(h / 3.5, 60_000)), duration: 1.4,
          easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT });
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    handler.setInputAction((ev: { position: Cesium.Cartesian2 }) => {
      const id = v.scene.pick(ev.position)?.id as { kind?: string; eventId?: string } | undefined;
      const st = useApp.getState();
      const sel = id?.kind === "event" ? id.eventId : null;
      if (!sel) return;
      if (st.selectedFireId !== sel) st.selectFire(sel);
      const row = st.fires?.rows.find((r) => r[0] === sel);
      if (row) flyToPoint(v, row[1], row[2], FIRE_CLOSE_RANGE_M);
    }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    let lastMove = 0;
    handler.setInputAction((ev: { endPosition: Cesium.Cartesian2 }) => {
      const now = performance.now();
      if (now - lastMove < 80) return;
      lastMove = now;
      const c = v.camera.pickEllipsoid(ev.endPosition, v.scene.globe.ellipsoid);
      if (!c) return useApp.getState().setCursor(null);
      const carto = Cesium.Cartographic.fromCartesian(c);
      useApp.getState().setCursor({ lat: Cesium.Math.toDegrees(carto.latitude), lon: Cesium.Math.toDegrees(carto.longitude) });
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    // Camera-dependent visuals (relief opacity, altitude readout) — direct DOM / Cesium updates, no React state.
    const updateCameraDependent = (vv: Cesium.Viewer) => {
      if (vv.isDestroyed()) return;
      const h = vv.camera.positionCartographic.height;
      const hs = terrain.current?.hillshade;
      if (hs) hs.alpha = useApp.getState().layers.relief ? reliefAlpha(h) : 0;
      if (altRef.current) altRef.current.textContent = `ALT ${h >= 10_000 ? `${(h / 1000).toFixed(0)} km` : `${(h / 1000).toFixed(2)} km`}`;
    };
    const rm = v.camera.changed.addEventListener(() => updateCameraDependent(v));
    const rm2 = v.camera.moveEnd.addEventListener(() => updateCameraDependent(v));
    updateCameraDependent(v);

    return () => {
      rm(); rm2();
      handler.destroy();
      tk.destroy();
      if (!v.isDestroyed()) v.destroy();
      setViewer(null);
      setTicker(null);
    };
  }, []);

  // ---------------------------------------------------------------- imagery / relief toggles
  const dailyDate = fires?.meta.latest_acquisition?.slice(0, 10) ?? null;
  useEffect(() => {
    if (!viewer || !imagery.current) return;
    applyImagery(viewer, imagery.current, layers, dailyDate);
    const hs = terrain.current?.hillshade;
    if (hs) hs.alpha = layers.relief ? reliefAlpha(viewer.camera.positionCartographic.height) : 0;
    viewer.scene.requestRender();
  }, [viewer, layers, dailyDate]);

  // ---------------------------------------------------------------- feature hooks
  const selectedRow = useMemo(() => fires?.rows.find((r) => r[0] === selected) ?? null, [fires, selected]);
  const selectedPoint = selectedRow ? { lat: selectedRow[1], lon: selectedRow[2] } : null;
  useCesiumCamera(viewer, selectedPoint, selected);
  useFireVisualization(viewer, ticker, fires, layers.fires, selected);
  usePredictionAnimation(viewer, ticker, prediction, layers, opacity);
  useWindLayer(viewer, ticker, wind, layers.wind);
  useOverlayLayers(viewer, overlays, geojson, layers, opacity);

  // ---------------------------------------------------------------- model domain outline
  useEffect(() => {
    if (!viewer) return;
    const ent = viewer.entities.getById("model-domain");
    if (!showDomain) {
      if (ent) viewer.entities.remove(ent);
      return;
    }
    if (ent) return;
    api<{ study_region: { bbox_wgs84: [number, number, number, number] } }>("/api/health").then((h) => {
      const [w, s, e, n] = h.study_region.bbox_wgs84;
      if (viewer.isDestroyed() || viewer.entities.getById("model-domain")) return;
      viewer.entities.add({ id: "model-domain", polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([w, s, e, s, e, n, w, n, w, s]), width: 1.2, clampToGround: true,
        material: new Cesium.PolylineDashMaterialProperty({ color: DOMAIN.withAlpha(0.65), dashLength: 12 }) } });
      viewer.scene.requestRender();
    }).catch(() => {});
  }, [viewer, showDomain]);

  if (err) return <div role="alert" className="flex h-full items-center justify-center text-xs text-crit p-6">{err}</div>;

  const okSteps = new Set((prediction?.steps ?? []).filter((s) => s.status === "ok").map((s) => s.label));
  const phaseText = !prediction ? null
    : animPhase.kind === "blend"
      ? `VISUAL BLEND ${LABELS[animPhase.from]} → ${LABELS[animPhase.to]} (transition between model frames, not a model output)`
      : animPhase.index === 0 ? "NOW · observed FIRMS footprint"
        : okSteps.has(LABELS[animPhase.index]) ? `MODEL FRAME ${LABELS[animPhase.index]} · ${prediction.model.name}`
          : `PREDICTION UNAVAILABLE · ${LABELS[animPhase.index]}`;

  return (
    <div className={`relative h-full w-full ${className}`}>
      <div ref={host} className="h-full w-full" aria-label="3D globe with active fire detections" role="application" />
      <MapControls altitudeRef={altRef} />
      {phaseText && (
        <div className={`absolute top-2 left-1/2 -translate-x-1/2 z-10 bg-panel/90 border px-2 py-1 text-2xs tracking-wider ${
          animPhase.kind === "blend" ? "border-line text-dim" : phaseText.startsWith("PREDICTION UNAVAILABLE") ? "border-warn/60 text-warn" : "border-fire/50 text-fire"}`}
          role="status" aria-live="polite">{phaseText}</div>
      )}
      {terrainSource && <span className="sr-only">Terrain: {terrainSource}</span>}
    </div>
  );
}
