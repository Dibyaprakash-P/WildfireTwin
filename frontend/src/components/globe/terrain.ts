import * as Cesium from "cesium";

import { api, apiUrl } from "../../lib/api";

/**
 * Terrain manager.
 *  - Cesium World Terrain when VITE_CESIUM_ION_TOKEN is set.
 *  - Otherwise heights come from the local SRTM 1" mosaic via /api/terrain tiles; outside the SRTM
 *    coverage the ellipsoid (height 0) is used — terrain height is never invented. No vertical exaggeration.
 *  - Relief shading: SRTM hillshade tiles (/api/terrain/hillshade) whose opacity grows as the camera
 *    descends, so the globe stays smooth from space and relief becomes prominent at fire-analysis scale.
 */
const ION_TOKEN = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined;
const TILE = 65;

interface TerrainInfo { bounds_wgs84: [number, number, number, number] }

export interface TerrainHandles {
  hillshade: Cesium.ImageryLayer | null;
  coverage: [number, number, number, number] | null;
  source: string;
}

function srtmProvider(bounds: [number, number, number, number]) {
  const [bw, bs, be, bn] = bounds;
  return new Cesium.CustomHeightmapTerrainProvider({
    width: TILE,
    height: TILE,
    callback: (x: number, y: number, level: number) => {
      const size = 180 / 2 ** level;
      const w = -180 + x * size, n = 90 - y * size, e = w + size, s = n - size;
      if (e <= bw || w >= be || s >= bn || n <= bs || level < 5) return new Float32Array(TILE * TILE);
      return fetch(apiUrl(`/api/terrain/${level}/${x}/${y}.bin`))
        .then((r) => (r.ok ? r.arrayBuffer() : new ArrayBuffer(TILE * TILE * 4)))
        .then((b) => new Float32Array(b))
        .catch(() => new Float32Array(TILE * TILE));
    },
  });
}

export async function attachTerrain(viewer: Cesium.Viewer): Promise<TerrainHandles> {
  let info: TerrainInfo | null = null;
  try {
    info = await api<TerrainInfo>("/api/terrain/info");
  } catch {
    /* backend terrain unavailable: ellipsoid fallback */
  }
  if (viewer.isDestroyed()) return { hillshade: null, coverage: null, source: "none" };
  let source = "ellipsoid (terrain unavailable)";
  try {
    if (ION_TOKEN) {
      Cesium.Ion.defaultAccessToken = ION_TOKEN;
      viewer.terrainProvider = await Cesium.createWorldTerrainAsync({ requestVertexNormals: true });
      source = "Cesium World Terrain";
    } else if (info) {
      viewer.terrainProvider = srtmProvider(info.bounds_wgs84);
      source = "SRTM 1″ (local coverage)";
    }
  } catch {
    source = "ellipsoid (terrain unavailable)";
  }
  let hillshade: Cesium.ImageryLayer | null = null;
  if (info) {
    const [w, s, e, n] = info.bounds_wgs84;
    const provider = new Cesium.UrlTemplateImageryProvider({
      url: apiUrl("/api/terrain/hillshade/{z}/{x}/{y}.png"),
      tilingScheme: new Cesium.GeographicTilingScheme(),
      tileWidth: 256, tileHeight: 256, minimumLevel: 0, maximumLevel: 14,
      rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n),
      credit: new Cesium.Credit("Relief: SRTM hillshade"),
    });
    provider.errorEvent.addEventListener((err: Cesium.TileProviderError) => { err.retry = false; });
    hillshade = new Cesium.ImageryLayer(provider, { alpha: 0 });
    viewer.imageryLayers.add(hillshade);
  }
  viewer.scene.requestRender();
  return { hillshade, coverage: info?.bounds_wgs84 ?? null, source };
}

/** Relief opacity by camera height: 0 above ~600 km, rising to 0.85 below ~12 km (log-linear). */
export function reliefAlpha(height: number): number {
  const hi = Math.log10(600_000), lo = Math.log10(12_000);
  const t = (hi - Math.log10(Math.max(height, 1))) / (hi - lo);
  return 0.85 * Math.min(1, Math.max(0, t));
}
