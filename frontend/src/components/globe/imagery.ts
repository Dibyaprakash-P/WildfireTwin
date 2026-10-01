import * as Cesium from "cesium";

import type { Layers } from "../../stores/app";

/**
 * Imagery manager. All sources are real, key-free services:
 *  satellite  Esri World Imagery (natural-colour mosaic)                         — default
 *  dark       Esri World Dark Gray Canvas                                         — technical/low-contrast
 *  daily      NASA GIBS VIIRS S-NPP Corrected Reflectance (true colour) for one   — shows that day's REAL clouds
 *             acquisition date (the latest FIRMS acquisition date)
 *  nightLights NASA GIBS VIIRS Black Marble 2016 — night side only (dayAlpha 0)
 *  borders    Esri World Boundaries & Places reference overlay
 * There is no separate synthetic cloud layer: the dated VIIRS composite is the only cloud source used.
 * Extension point: a GIBS cloud-mask/cloud-fraction product can be added here as another layer.
 */
const ESRI = "https://services.arcgisonline.com/ArcGIS/rest/services";
const GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";

export interface ImageryHandles {
  satellite: Cesium.ImageryLayer;
  dark: Cesium.ImageryLayer;
  nightLights: Cesium.ImageryLayer;
  borders: Cesium.ImageryLayer;
  daily: Cesium.ImageryLayer | null;
  dailyDate: string | null;
}

function esri(path: string, opts: Partial<Cesium.ImageryLayer.ConstructorOptions> = {}) {
  return Cesium.ImageryLayer.fromProviderAsync(Cesium.ArcGisMapServerImageryProvider.fromUrl(`${ESRI}/${path}/MapServer`), opts);
}

function gibs(layer: string, date: string, matrix: string, ext: "png" | "jpg", maxLevel: number, credit: string) {
  return new Cesium.UrlTemplateImageryProvider({
    url: `${GIBS}/${layer}/default/${date}/${matrix}/{z}/{y}/{x}.${ext}`,
    maximumLevel: maxLevel,
    credit: new Cesium.Credit(credit),
  });
}

export function addBaseImagery(viewer: Cesium.Viewer): ImageryHandles {
  const L = viewer.imageryLayers;
  // Slightly muted so fire overlays remain the brightest elements on screen.
  const satellite = esri("World_Imagery", { brightness: 0.92, contrast: 1.06, saturation: 0.88, gamma: 1.05 });
  const dark = esri("Canvas/World_Dark_Gray_Base");
  const nightLights = new Cesium.ImageryLayer(
    gibs("VIIRS_Black_Marble", "2016-01-01", "GoogleMapsCompatible_Level8", "png", 8, "NASA Black Marble 2016 (GIBS)"),
    { dayAlpha: 0.0, nightAlpha: 0.45, brightness: 1.8 },  // partial: lights show, satellite stays visible
  );
  const borders = esri("Reference/World_Boundaries_and_Places", { alpha: 0.75 });
  L.add(satellite);
  L.add(dark);
  L.add(nightLights);
  L.add(borders);
  dark.show = false;
  return { satellite, dark, nightLights, borders, daily: null, dailyDate: null };
}

/** Lazily create the dated VIIRS true-colour layer just above the base layers. */
export function ensureDaily(viewer: Cesium.Viewer, h: ImageryHandles, date: string): Cesium.ImageryLayer {
  if (h.daily && h.dailyDate === date) return h.daily;
  if (h.daily) viewer.imageryLayers.remove(h.daily, true);
  h.daily = new Cesium.ImageryLayer(
    gibs("VIIRS_SNPP_CorrectedReflectance_TrueColor", date, "GoogleMapsCompatible_Level9", "jpg", 9,
      `NASA GIBS VIIRS S-NPP true colour ${date}`),
    { brightness: 0.95 },
  );
  viewer.imageryLayers.add(h.daily, viewer.imageryLayers.indexOf(h.dark) + 1);
  h.dailyDate = date;
  return h.daily;
}

export function applyImagery(viewer: Cesium.Viewer, h: ImageryHandles, layers: Layers, dailyDate: string | null) {
  h.satellite.show = layers.imagery === "satellite" || layers.imagery === "daily";
  h.dark.show = layers.imagery === "dark";
  if (layers.imagery === "daily" && dailyDate) ensureDaily(viewer, h, dailyDate).show = true;
  else if (h.daily) h.daily.show = false;
  h.nightLights.show = layers.nightLights && layers.imagery !== "dark";
  h.borders.show = layers.borders;
  viewer.scene.requestRender();
}
