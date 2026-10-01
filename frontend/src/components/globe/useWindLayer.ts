import * as Cesium from "cesium";
import { useEffect, useRef } from "react";

import type { WindObs } from "../../stores/app";
import { NEAR_NO_DEPTH } from "./useFireVisualization";
import { prefersReducedMotion, type Ticker } from "./ticker";

/**
 * Wind at the selected fire — the single observed Open-Meteo 10 m wind (speed, direction FROM).
 * Drawn as a downwind arrow (length 300 m per m/s, min 400 m) plus three faint markers that drift along it
 * at a rate proportional to the observed speed. Only one real observation is shown; no wind field is
 * interpolated or invented.
 */
const CYAN = Cesium.Color.fromCssColorString("#4cc3d9");

export function useWindLayer(viewer: Cesium.Viewer | null, ticker: Ticker | null, wind: WindObs | null, show: boolean) {
  const particles = useRef<{ col: Cesium.PointPrimitiveCollection; pts: Cesium.PointPrimitive[]; a: Cesium.Cartesian3; b: Cesium.Cartesian3; speed: number } | null>(null);

  useEffect(() => {
    if (!viewer) return;
    const old = viewer.entities.getById("wind-arrow");
    if (old) viewer.entities.remove(old);
    if (particles.current) {
      if (!viewer.isDestroyed()) viewer.scene.primitives.remove(particles.current.col);
      particles.current = null;
    }
    if (!wind || !show) return void viewer.scene.requestRender();
    const toRad = Cesium.Math.toRadians((wind.fromDeg + 180) % 360);
    const len = Math.max(400, wind.speed * 300);
    const dLat = (len * Math.cos(toRad)) / 111_320;
    const dLon = (len * Math.sin(toRad)) / (111_320 * Math.cos(Cesium.Math.toRadians(wind.lat)));
    const a = Cesium.Cartesian3.fromDegrees(wind.lon, wind.lat, 0);
    const b = Cesium.Cartesian3.fromDegrees(wind.lon + dLon, wind.lat + dLat, 0);
    viewer.entities.add({
      id: "wind-arrow",
      polyline: { positions: [a, b], width: 9, clampToGround: true, material: new Cesium.PolylineArrowMaterialProperty(CYAN.withAlpha(0.85)) },
      position: b,
      label: {
        text: `WIND ${wind.speed.toFixed(1)} m/s FROM ${Math.round(wind.fromDeg)}° · Open-Meteo`, font: "10px JetBrains Mono",
        fillColor: CYAN, pixelOffset: new Cesium.Cartesian2(0, 16), verticalOrigin: Cesium.VerticalOrigin.TOP, disableDepthTestDistance: NEAR_NO_DEPTH,
        showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0f1216").withAlpha(0.85),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 400_000),
      },
    });
    if (wind.speed > 0.2 && !prefersReducedMotion()) {
      const col = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
      const pts = [0, 1, 2].map(() => col.add({ position: a, pixelSize: 3, color: CYAN.withAlpha(0.0), disableDepthTestDistance: NEAR_NO_DEPTH }));
      particles.current = { col, pts, a, b, speed: wind.speed };
    }
    viewer.scene.requestRender();
  }, [viewer, wind, show]);

  useEffect(() => {
    if (!ticker) return;
    const tmp = new Cesium.Cartesian3();
    return ticker.add((t) => {
      const p = particles.current;
      if (!p) return false;
      const period = Math.max(1500, 6000 / Math.max(p.speed, 0.5)); // faster wind -> faster drift
      p.pts.forEach((pt, i) => {
        const u = ((t / period) + i / 3) % 1;
        pt.position = Cesium.Cartesian3.lerp(p.a, p.b, u, tmp);
        pt.color = CYAN.withAlpha(0.75 * Math.sin(Math.PI * u), pt.color);
      });
      return true;
    });
  }, [ticker]);
}
