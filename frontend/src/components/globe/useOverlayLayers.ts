import * as Cesium from "cesium";
import { useEffect, useRef } from "react";

import { apiUrl } from "../../lib/api";
import type { Layers, Overlay } from "../../stores/app";

/** Static overlays used by the Simulation and Historical pages (reference runs, replays) + GeoJSON perimeters. */
export function useOverlayLayers(viewer: Cesium.Viewer | null, overlays: Overlay[], geojson: object | null, layers: Layers, opacity: number) {
  const map = useRef(new Map<string, Cesium.ImageryLayer>());
  const geo = useRef<Cesium.GeoJsonDataSource | null>(null);

  useEffect(() => {
    if (!viewer) return;
    const wanted = new Set(overlays.map((o) => o.id));
    for (const [id, layer] of map.current) {
      if (!wanted.has(id)) {
        viewer.imageryLayers.remove(layer, true);
        map.current.delete(id);
      }
    }
    for (const o of overlays) {
      if (map.current.has(o.id)) continue;
      const [w, s, e, n] = o.bounds;
      const layer = Cesium.ImageryLayer.fromProviderAsync(
        Cesium.SingleTileImageryProvider.fromUrl(apiUrl(o.url), { rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n) }), {});
      viewer.imageryLayers.add(layer);
      map.current.set(o.id, layer);
    }
    for (const o of overlays) {
      const layer = map.current.get(o.id)!;
      layer.show = o.kind === "footprint" ? layers.footprint : o.kind === "prediction" ? layers.prediction : true;
      layer.alpha = o.kind === "prediction" || o.kind === "simulation" ? opacity : 1;
      viewer.imageryLayers.raiseToTop(layer);
    }
    viewer.scene.requestRender();
  }, [viewer, overlays, opacity, layers.footprint, layers.prediction]);

  useEffect(() => () => map.current.clear(), []);

  useEffect(() => {
    if (!viewer) return;
    if (geo.current) {
      viewer.dataSources.remove(geo.current, true);
      geo.current = null;
    }
    if (!geojson) return;
    let cancelled = false;
    Cesium.GeoJsonDataSource.load(geojson, {
      clampToGround: true, stroke: Cesium.Color.fromCssColorString("#3dcf7a"), strokeWidth: 2,
      fill: Cesium.Color.fromCssColorString("#3dcf7a").withAlpha(0.08),
    }).then((ds) => {
      if (cancelled || viewer.isDestroyed()) return;
      geo.current = ds;
      viewer.dataSources.add(ds);
      viewer.scene.requestRender();
    });
    return () => { cancelled = true; };
  }, [viewer, geojson]);
}
