import * as Cesium from "cesium";

/**
 * Creates the Cesium viewer with a natural Earth-observation look:
 *  - real sun position for "now" (day/night terminator), lighting faded out when zoomed in so local
 *    analysis views stay readable regardless of local time,
 *  - understated sky atmosphere + ground atmosphere, real star background (Cesium Tycho-2 sky box),
 *  - fog for the horizon at oblique views, no lens-flare sun / moon.
 * Imagery and terrain are attached by imagery.ts / terrain.ts.
 */
export function createViewer(host: HTMLElement): Cesium.Viewer {
  const viewer = new Cesium.Viewer(host, {
    baseLayer: false,
    baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false,
    animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
    requestRenderMode: true, maximumRenderTimeChange: Infinity, msaaSamples: 4,
  });
  const scene = viewer.scene;
  const globe = scene.globe;

  // Real sun position at the current time; the clock does not animate (a static "now" terminator).
  viewer.clock.currentTime = Cesium.JulianDate.now();
  viewer.clock.shouldAnimate = false;

  scene.backgroundColor = Cesium.Color.fromCssColorString("#020305");
  globe.baseColor = Cesium.Color.fromCssColorString("#0b1a2b"); // shown only before imagery tiles load
  globe.enableLighting = true;
  globe.dynamicAtmosphereLighting = true;
  globe.dynamicAtmosphereLightingFromSun = true;
  globe.showGroundAtmosphere = true;
  globe.atmosphereLightIntensity = 6.0;
  globe.atmosphereBrightnessShift = -0.15;
  // Day/night shading blends in with camera distance (Cesium measures it from the Earth's CENTRE):
  // none below ~9,600 km altitude (analysis views readable at any local time), ~40 % at the default global view
  // (~23,900 km from the centre) so the real terminator and night lights show without a black night hemisphere,
  // full strength only when zoomed far out.
  globe.lightingFadeOutDistance = 1.6e7;
  globe.lightingFadeInDistance = 3.6e7;
  globe.nightFadeOutDistance = 1.6e7;
  globe.nightFadeInDistance = 3.6e7;
  globe.depthTestAgainstTerrain = false;
  globe.maximumScreenSpaceError = 1.5; // slightly sharper imagery/terrain than the default 2
  globe.tileCacheSize = 400;

  if (scene.skyAtmosphere) {
    scene.skyAtmosphere.show = true;
    scene.skyAtmosphere.brightnessShift = -0.18; // understated limb, no strong blue halo
    scene.skyAtmosphere.saturationShift = -0.2;
  }
  if (scene.skyBox) scene.skyBox.show = true;    // real star catalogue background
  if (scene.sun) scene.sun.show = false;          // avoid lens glare
  if (scene.moon) scene.moon.show = false;
  scene.fog.enabled = true;
  scene.fog.density = 1.0e-4;
  scene.highDynamicRange = false;

  // Remove Cesium's default double-click "track entity" behaviour; our own handler focuses fires.
  viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

  viewer.camera.setView({
    destination: Cesium.Cartesian3.fromDegrees(-110, 32, 17_500_000),
    orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
  });
  return viewer;
}
