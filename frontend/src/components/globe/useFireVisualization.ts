import * as Cesium from "cesium";
import { useEffect, useRef, useState } from "react";

import type { ActiveFiresResponse } from "../../types/api";
import { prefersReducedMotion, type Ticker } from "./ticker";

/**
 * FIRMS fire-event rendering with Cesium primitives (never one DOM/React node per fire).
 *
 *  core   PointPrimitiveCollection, one point per event (or per cluster when zoomed out). Size and colour
 *         from the event's real FRP sum; "recent" (>24 h) events are dimmer.
 *  halo   a second, small collection of soft halos for ACTIVE events/clusters in view only (≤1,200),
 *         rebuilt on camera move-end; the pulse (1.6 s period, small scale/opacity change) mutates
 *         these primitives inside the shared ticker — no React updates per frame.
 *  labels cluster counts at global/continental scale.
 *  select ring + glow + coordinate label for the selected event.
 * Every marker is a FIRMS detection cluster (observed), never a fire perimeter.
 */
export const NEAR_NO_DEPTH = 1.5e6; // points nearer than this are drawn over terrain; farther ones are occluded by the globe

const C_RECENT = Cesium.Color.fromCssColorString("#b8892e");
const C_HALO = Cesium.Color.fromCssColorString("#ff6a1a");
const C_SEL = Cesium.Color.fromCssColorString("#fff1e0");

type Row = ActiveFiresResponse["rows"][number];

export function clusterCell(height: number): number {
  if (height > 6_000_000) return 2;
  if (height > 2_500_000) return 1;
  if (height > 900_000) return 0.5;
  if (height > 350_000) return 0.15;
  return 0;
}

/** Real-FRP-based styling (MW). */
function coreStyle(frp: number | null, det: number, active: boolean) {
  const f = frp ?? 0;
  const color = !active ? C_RECENT
    : f >= 200 ? Cesium.Color.fromCssColorString("#ffe2a8")
    : f >= 50 ? Cesium.Color.fromCssColorString("#ffb347")
    : f >= 5 ? Cesium.Color.fromCssColorString("#ff7a1a")
    : Cesium.Color.fromCssColorString("#ff5426");
  const size = Math.min(9, 3 + Math.log10(1 + f) * 1.6 + Math.log2(det) * 0.4);
  return { color: color.withAlpha(active ? 0.95 : 0.7), size };
}

interface HaloInfo { p: Cesium.PointPrimitive; base: number; alpha: number; phase: number }

export function useFireVisualization(viewer: Cesium.Viewer | null, ticker: Ticker | null, fires: ActiveFiresResponse | null,
  show: boolean, selectedId: string | null) {
  const cols = useRef<{ core: Cesium.PointPrimitiveCollection; halo: Cesium.PointPrimitiveCollection;
    labels: Cesium.LabelCollection; sel: Cesium.PointPrimitiveCollection; selLabel: Cesium.LabelCollection } | null>(null);
  const halos = useRef<HaloInfo[]>([]);
  const selGlow = useRef<Cesium.PointPrimitive | null>(null);
  const [cell, setCell] = useState<number>(-1);
  const [moveKey, setMoveKey] = useState(0);

  // collections + camera listeners
  useEffect(() => {
    if (!viewer) return;
    const p = viewer.scene.primitives;
    const c = {
      halo: p.add(new Cesium.PointPrimitiveCollection({ blendOption: Cesium.BlendOption.TRANSLUCENT })),
      core: p.add(new Cesium.PointPrimitiveCollection()),
      labels: p.add(new Cesium.LabelCollection()),
      sel: p.add(new Cesium.PointPrimitiveCollection({ blendOption: Cesium.BlendOption.TRANSLUCENT })),
      selLabel: p.add(new Cesium.LabelCollection()),
    };
    cols.current = c;
    const onChange = () => setCell(clusterCell(viewer.camera.positionCartographic.height));
    const onEnd = () => { onChange(); setMoveKey((k) => k + 1); };
    viewer.camera.percentageChanged = 0.15;
    const r1 = viewer.camera.changed.addEventListener(onChange);
    const r2 = viewer.camera.moveEnd.addEventListener(onEnd);
    onEnd();
    return () => {
      r1(); r2();
      if (!viewer.isDestroyed()) for (const col of Object.values(c)) p.remove(col);
      cols.current = null;
    };
  }, [viewer]);

  // cores + cluster labels
  useEffect(() => {
    const c = cols.current;
    if (!viewer || !c || cell < 0) return;
    c.core.removeAll();
    c.labels.removeAll();
    if (fires && show) {
      if (cell === 0) {
        for (const [id, lat, lon, det, frp, , status, dom] of fires.rows) {
          const st = coreStyle(frp, det, status === "active");
          c.core.add({ id: { kind: "event", eventId: id }, position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
            pixelSize: st.size, color: st.color, outlineColor: dom ? Cesium.Color.fromCssColorString("#4cc3d9").withAlpha(0.8) : Cesium.Color.BLACK.withAlpha(0.5),
            outlineWidth: dom ? 1.5 : 0.5, disableDepthTestDistance: NEAR_NO_DEPTH });
        }
      } else {
        for (const cl of aggregate(fires.rows, cell)) {
          const single = cl.n === 1;
          const st = coreStyle(cl.frp, cl.det, cl.active);
          c.core.add({ id: single ? { kind: "event", eventId: cl.id } : { kind: "cluster", lat: cl.lat, lon: cl.lon },
            position: Cesium.Cartesian3.fromDegrees(cl.lon, cl.lat, 0),
            pixelSize: single ? Math.min(st.size, 4) : 3 + Math.min(5, Math.log2(cl.n + 1) * 0.8),
            color: st.color.withAlpha(single ? 0.8 : 0.75), disableDepthTestDistance: NEAR_NO_DEPTH });
        }
        aggregate(fires.rows, cell).filter((x) => x.n >= 15).sort((a, b) => b.det - a.det).slice(0, 40).forEach((cl) =>
          c.labels.add({ position: Cesium.Cartesian3.fromDegrees(cl.lon, cl.lat, 0), text: String(cl.n),
            font: "10px JetBrains Mono", fillColor: Cesium.Color.fromCssColorString("#f2f4f7").withAlpha(0.85),
            pixelOffset: new Cesium.Cartesian2(0, -12), horizontalOrigin: Cesium.HorizontalOrigin.CENTER }));
      }
    }
    viewer.scene.requestRender();
  }, [viewer, fires, show, cell]);

  // halos for active fires in view (rebuilt after camera moves)
  useEffect(() => {
    const c = cols.current;
    if (!viewer || !c) return;
    c.halo.removeAll();
    halos.current = [];
    if (!fires || !show || prefersReducedMotion()) return;
    const h = viewer.camera.positionCartographic.height;
    let cands: { lat: number; lon: number; frp: number; det: number; n: number }[];
    if (cell === 0) {
      const center = viewCenter(viewer);
      const radiusDeg = Math.min(20, (h * 4) / 111_000);
      cands = fires.rows.filter((r) => r[6] === "active" && (!center || (Math.abs(r[1] - center.lat) < radiusDeg && Math.abs(r[2] - center.lon) < radiusDeg * 1.5)))
        .map((r) => ({ lat: r[1], lon: r[2], frp: r[4] ?? 0, det: r[3], n: 1 }));
    } else {
      cands = aggregate(fires.rows, cell).filter((x) => x.active).map((x) => ({ lat: x.lat, lon: x.lon, frp: x.frp ?? 0, det: x.det, n: x.n }));
    }
    cands.sort((a, b) => b.frp - a.frp);
    // individual view: up to 1,200 halos; cluster views: only the 150 strongest clusters, kept small
    for (const [i, cd] of cands.slice(0, cell === 0 ? 1200 : 150).entries()) {
      const base = cell === 0 ? coreStyle(cd.frp, cd.det, true).size * 2.6 : 7 + Math.min(6, Math.log2(cd.n + 1));
      const p = c.halo.add({ position: Cesium.Cartesian3.fromDegrees(cd.lon, cd.lat, 0), pixelSize: base,
        color: C_HALO.withAlpha(0.22), disableDepthTestDistance: NEAR_NO_DEPTH });
      halos.current.push({ p, base, alpha: cell === 0 ? 0.3 : 0.14, phase: (i * 2.399) % (2 * Math.PI) });
    }
    viewer.scene.requestRender();
  }, [viewer, fires, show, cell, moveKey]);

  // selected event: ring + glow + coordinate label
  useEffect(() => {
    const c = cols.current;
    if (!viewer || !c) return;
    c.sel.removeAll();
    c.selLabel.removeAll();
    selGlow.current = null;
    const row = fires?.rows.find((r) => r[0] === selectedId);
    if (row) {
      const pos = Cesium.Cartesian3.fromDegrees(row[2], row[1], 0);
      selGlow.current = c.sel.add({ position: pos, pixelSize: 30, color: Cesium.Color.fromCssColorString("#ff8a2a").withAlpha(0.25),
        disableDepthTestDistance: Number.POSITIVE_INFINITY });
      c.sel.add({ position: pos, pixelSize: 18, color: Cesium.Color.TRANSPARENT, outlineColor: C_SEL, outlineWidth: 1.6,
        disableDepthTestDistance: Number.POSITIVE_INFINITY });
      c.sel.add({ position: pos, pixelSize: 5, color: C_SEL, disableDepthTestDistance: Number.POSITIVE_INFINITY });
      c.selLabel.add({ position: pos, font: "11px JetBrains Mono", fillColor: C_SEL,
        text: `${row[0]}  ${Math.abs(row[1]).toFixed(4)}°${row[1] >= 0 ? "N" : "S"} ${Math.abs(row[2]).toFixed(4)}°${row[2] >= 0 ? "E" : "W"}`,
        showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0f1216").withAlpha(0.85),
        backgroundPadding: new Cesium.Cartesian2(6, 4), pixelOffset: new Cesium.Cartesian2(16, -16),
        horizontalOrigin: Cesium.HorizontalOrigin.LEFT, verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        disableDepthTestDistance: Number.POSITIVE_INFINITY });
    }
    viewer.scene.requestRender();
  }, [viewer, fires, selectedId]);

  // pulse: subtle scale/opacity oscillation of halos + selection glow ("live active fire")
  useEffect(() => {
    if (!ticker || prefersReducedMotion()) return;
    return ticker.add((t) => {
      const list = halos.current;
      const g = selGlow.current;
      if (!list.length && !g) return false;
      const w = (2 * Math.PI * t) / 1600;
      for (const hl of list) {
        const s = 0.5 + 0.5 * Math.sin(w + hl.phase);
        hl.p.pixelSize = hl.base * (0.9 + 0.22 * s);
        hl.p.color = C_HALO.withAlpha(hl.alpha * (0.45 + 0.55 * s), hl.p.color);
      }
      if (g) {
        const s = 0.5 + 0.5 * Math.sin((2 * Math.PI * t) / 1800);
        g.pixelSize = 26 + 10 * s;
        g.color = Cesium.Color.fromCssColorString("#ff8a2a").withAlpha(0.14 + 0.16 * s, g.color);
      }
      return true;
    });
  }, [ticker]);
}

function viewCenter(viewer: Cesium.Viewer): { lat: number; lon: number } | null {
  const canvas = viewer.scene.canvas;
  const p = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2));
  if (!p) return null;
  const c = Cesium.Cartographic.fromCartesian(p);
  return { lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude) };
}

interface Cluster { id: string; n: number; det: number; frp: number | null; lat: number; lon: number; active: boolean }

const aggCache = new WeakMap<Row[], Map<number, Cluster[]>>();

/** Grid aggregation of events (cached per data snapshot and cell size). */
export function aggregate(rows: Row[], cell: number): Cluster[] {
  let byCell = aggCache.get(rows);
  if (!byCell) { byCell = new Map(); aggCache.set(rows, byCell); }
  const hit = byCell.get(cell);
  if (hit) return hit;
  const m = new Map<string, Cluster>();
  for (const [id, lat, lon, det, frp, , status] of rows) {
    const key = `${Math.floor(lat / cell)}:${Math.floor(lon / cell)}`;
    const a = m.get(key);
    if (a) {
      a.n += 1; a.det += det; a.lat += lat; a.lon += lon; a.active ||= status === "active";
      a.frp = (a.frp ?? 0) + (frp ?? 0);
    } else m.set(key, { id, n: 1, det, frp, lat, lon, active: status === "active" });
  }
  const out = [...m.values()].map((a) => ({ ...a, lat: a.lat / a.n, lon: a.lon / a.n }));
  byCell.set(cell, out);
  return out;
}
