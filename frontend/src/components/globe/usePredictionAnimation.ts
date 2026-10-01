import * as Cesium from "cesium";
import { useEffect, useRef } from "react";

import { apiUrl } from "../../lib/api";
import { useApp, type Layers } from "../../stores/app";
import type { Prediction, PredictionStep } from "../../types/api";
import { HORIZONS } from "../ForecastTimeline";
import type { Ticker } from "./ticker";

/**
 * Forecast animation engine — animates ONLY real model frames.
 *
 * Each available forecast step (status "ok") is one frame: its probability PNG (model output, draped on the
 * globe as an imagery layer, so it conforms to terrain) and, if present, its fire-front PNG (p ≥ 0.5 boundary
 * of the same output). NOW (index 0) shows the observed FIRMS footprint only.
 *
 * Playback: HOLD on a frame, then a short cross-fade (alpha blend) to the next available frame. The blend is a
 * visual transition between two real frames; the UI labels it "VISUAL BLEND … (not a model output)".
 * Unavailable horizons are skipped — no frame is ever synthesised or extrapolated.
 * The engine mutates Cesium layers in the shared ticker; React state is touched only at phase changes.
 */
const HOLD_MS = 1500;
const BLEND_MS = 900;

interface Frame { index: number; step: PredictionStep; prob: Cesium.ImageryLayer; front: Cesium.ImageryLayer | null }

function singleTile(url: string, b: [number, number, number, number]) {
  const [w, s, e, n] = b;
  return Cesium.ImageryLayer.fromProviderAsync(
    Cesium.SingleTileImageryProvider.fromUrl(apiUrl(url), { rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n) }), { alpha: 0 });
}

const smooth = (x: number) => x * x * (3 - 2 * x);

export function usePredictionAnimation(viewer: Cesium.Viewer | null, ticker: Ticker | null, prediction: Prediction | null,
  layers: Layers, opacity: number) {
  const frames = useRef<Frame[]>([]);
  const footprints = useRef(new Map<string, Cesium.ImageryLayer>());
  const windowEntity = useRef<Cesium.Entity | null>(null);
  const eng = useRef({ from: 0, to: 0, f: 0, elapsed: 0, phase: "hold" as "hold" | "blend", settled: 0 });
  const opts = useRef({ layers, opacity });
  opts.current = { layers, opacity };
  const index = useApp((s) => s.timelineIndex);
  const playing = useApp((s) => s.playing);

  const available = (): number[] => [0, ...frames.current.map((f) => f.index)];

  const bandFor = (i: number): string | undefined => {
    const fr = frames.current.find((f) => f.index === i) ?? frames.current[0];
    return fr?.step.band;
  };

  /** Apply alphas for a blend between frame indices a → b at fraction f (f = 0 means exactly frame a). */
  const apply = (a: number, b: number, f: number, t?: number) => {
    if (!viewer || viewer.isDestroyed()) return;
    const { layers: L, opacity: op } = opts.current;
    // restrained fire-front glow while playing; static when paused (no idle rendering cost)
    const glow = t === undefined ? 1 : 0.78 + 0.22 * Math.sin((2 * Math.PI * t) / 2200);
    for (const fr of frames.current) {
      const w = fr.index === a ? 1 - f : fr.index === b ? f : 0;
      fr.prob.alpha = op * w;
      fr.prob.show = L.prediction && w > 0.001;
      if (fr.front) {
        fr.front.alpha = Math.min(1, w * glow);
        fr.front.show = L.front && L.prediction && w > 0.001;
      }
    }
    const shown = f < 0.5 ? a : b;
    const band = bandFor(shown);
    for (const [bd, layer] of footprints.current) layer.show = L.footprint && bd === band;
    const fr = frames.current.find((x) => x.index === shown);
    if (windowEntity.current) windowEntity.current.show = !!fr;
    if (fr?.step.bounds_wgs84 && windowEntity.current?.polyline) {
      const [w, s, e, n] = fr.step.bounds_wgs84;
      windowEntity.current.polyline.positions = new Cesium.ConstantProperty(Cesium.Cartesian3.fromDegreesArray([w, s, e, s, e, n, w, n, w, s]));
    }
  };

  // (re)build layers for a new prediction
  useEffect(() => {
    if (!viewer) return;
    const L = viewer.imageryLayers;
    const created: Cesium.ImageryLayer[] = [];
    frames.current = [];
    footprints.current = new Map();
    if (prediction) {
      for (const s of prediction.steps) {
        const i = HORIZONS.indexOf(s.horizon_min) + 1;
        if (s.status !== "ok" || !s.overlay_url || !s.bounds_wgs84 || i < 1) continue;
        const prob = singleTile(s.overlay_url, s.bounds_wgs84);
        const front = s.front_url ? singleTile(s.front_url, s.bounds_wgs84) : null;
        L.add(prob); created.push(prob);
        if (front) { L.add(front); created.push(front); }
        frames.current.push({ index: i, step: s, prob, front });
        if (s.band && s.footprint_url && s.footprint_bounds_wgs84 && !footprints.current.has(s.band)) {
          const fp = singleTile(s.footprint_url, s.footprint_bounds_wgs84);
          fp.alpha = 1;
          L.add(fp); created.push(fp);
          footprints.current.set(s.band, fp);
        }
      }
      frames.current.sort((a, b) => a.index - b.index);
      windowEntity.current = viewer.entities.add({
        polyline: { positions: [], width: 1, clampToGround: true,
          material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString("#c8ced6").withAlpha(0.55), dashLength: 10 }) },
      });
    }
    const st = useApp.getState();
    eng.current = { from: st.timelineIndex, to: st.timelineIndex, f: 0, elapsed: 0, phase: "hold", settled: st.timelineIndex };
    apply(st.timelineIndex, st.timelineIndex, 0);
    viewer.scene.requestRender();
    const ent = windowEntity.current;
    return () => {
      if (viewer.isDestroyed()) return;
      for (const l of created) L.remove(l, true);
      if (ent) viewer.entities.remove(ent);
      windowEntity.current = null;
      frames.current = [];
      footprints.current = new Map();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, prediction]);

  // manual timeline changes (slider / prev / next) jump straight to the real frame
  useEffect(() => {
    const e = eng.current;
    if (index === e.settled && e.phase === "hold") return;
    eng.current = { from: index, to: index, f: 0, elapsed: 0, phase: "hold", settled: index };
    apply(index, index, 0);
    useApp.getState().setAnimPhase({ kind: "frame", index });
    viewer?.scene.requestRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  // layer toggles / opacity
  useEffect(() => {
    const e = eng.current;
    apply(e.from, e.to, e.phase === "blend" ? smooth(e.f) : 0);
    viewer?.scene.requestRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.prediction, layers.front, layers.footprint, opacity]);

  // playback + fire-front glow
  useEffect(() => {
    if (!ticker) return;
    return ticker.add((t, dt) => {
      if (!frames.current.length) return false;
      const st = useApp.getState();
      const e = eng.current;
      if (!st.playing) return false;
      {
        const avail = available();
        e.elapsed += dt * st.playbackSpeed;
        if (e.phase === "hold" && e.elapsed >= HOLD_MS) {
          const k = avail.indexOf(e.from);
          e.to = avail[(k + 1) % avail.length];
          e.phase = "blend";
          e.elapsed = 0;
          st.setAnimPhase({ kind: "blend", from: e.from, to: e.to });
        } else if (e.phase === "blend") {
          e.f = Math.min(1, e.elapsed / BLEND_MS);
          if (e.f >= 1) {
            e.from = e.to; e.f = 0; e.phase = "hold"; e.elapsed = 0; e.settled = e.from;
            st.setTimelineIndex(e.from);
            st.setAnimPhase({ kind: "frame", index: e.from });
          }
        }
      }
      apply(e.from, e.to, e.phase === "blend" ? smooth(e.f) : 0, t);
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  // pausing mid-blend snaps to the nearer real frame
  useEffect(() => {
    if (playing) return;
    const e = eng.current;
    if (e.phase !== "blend") {
      apply(e.from, e.from, 0);          // static (non-glowing) front when paused
      viewer?.scene.requestRender();
      return;
    }
    const target = e.f < 0.5 ? e.from : e.to;
    eng.current = { from: target, to: target, f: 0, elapsed: 0, phase: "hold", settled: target };
    const st = useApp.getState();
    st.setTimelineIndex(target);
    st.setAnimPhase({ kind: "frame", index: target });
    apply(target, target, 0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  return { hasFrames: () => frames.current.length > 0 };
}
