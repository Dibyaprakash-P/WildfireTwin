import * as Cesium from "cesium";
import { useEffect } from "react";

import { useApp } from "../../stores/app";

/**
 * Camera controller.
 *  - Smooth, inertial wheel/trackpad zoom (zoomFactor 3 instead of 5, higher inertia).
 *  - Limits: 250 m minimum distance to the surface, 45,000 km maximum; terrain collision detection on.
 *  - Mouse: left-drag rotate/pan, right-drag or wheel zoom, middle-drag / ctrl+drag tilt (Cesium defaults).
 *  - flyToPoint uses flyToBoundingSphere so the target ends up centred at an oblique analysis view
 *    (pitch ≈ -42°) with a duration that scales with the distance travelled; Cesium arcs the path
 *    (global → regional → local) automatically.
 */
export const GLOBAL_VIEW = { lon: -110, lat: 32, height: 17_500_000 };
export const FIRE_VIEW_RANGE_M = 16_000;
export const FIRE_CLOSE_RANGE_M = 4_500;
const FIRE_PITCH = Cesium.Math.toRadians(-42);

export function configureCameraController(viewer: Cesium.Viewer) {
  const c = viewer.scene.screenSpaceCameraController;
  c.minimumZoomDistance = 250;
  c.maximumZoomDistance = 45_000_000;
  c.enableCollisionDetection = true;
  c.zoomFactor = 3.0;
  c.inertiaZoom = 0.85;
  c.inertiaSpin = 0.9;
  c.inertiaTranslate = 0.9;
  c.maximumMovementRatio = 0.08;
}

function flightDuration(viewer: Cesium.Viewer, target: Cesium.Cartesian3): number {
  const d = Cesium.Cartesian3.distance(viewer.camera.positionWC, target);
  return Math.min(4.5, Math.max(1.4, 0.9 + 0.55 * Math.log10(Math.max(d, 1000) / 1000)));
}

export function flyToPoint(viewer: Cesium.Viewer, lat: number, lon: number, range = FIRE_VIEW_RANGE_M) {
  const center = Cesium.Cartesian3.fromDegrees(lon, lat, 0);
  viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(center, 10), {
    offset: new Cesium.HeadingPitchRange(viewer.camera.heading > 1e-3 && range < 50_000 ? viewer.camera.heading : 0, FIRE_PITCH, range),
    duration: flightDuration(viewer, center),
    easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
  });
}

export function flyGlobal(viewer: Cesium.Viewer) {
  const dest = Cesium.Cartesian3.fromDegrees(GLOBAL_VIEW.lon, GLOBAL_VIEW.lat, GLOBAL_VIEW.height);
  viewer.camera.flyTo({
    destination: dest, orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
    duration: flightDuration(viewer, dest), easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
  });
}

/** Smooth button zoom along the view direction; never below the minimum distance. */
export function zoomStep(viewer: Cesium.Viewer, zoomIn: boolean) {
  const cam = viewer.camera;
  const h = cam.positionCartographic.height;
  const dist = zoomIn ? Math.min(h * 0.5, Math.max(h - 300, 0)) : -h * 0.9;
  if (Math.abs(dist) < 1) return;
  const dest = Cesium.Cartesian3.add(cam.positionWC, Cesium.Cartesian3.multiplyByScalar(cam.directionWC, dist, new Cesium.Cartesian3()), new Cesium.Cartesian3());
  cam.flyTo({ destination: dest, orientation: { heading: cam.heading, pitch: cam.pitch, roll: cam.roll }, duration: 0.7,
    easingFunction: Cesium.EasingFunction.QUADRATIC_OUT });
}

/** Wires store-driven camera behaviour: search fly-to, selected-fire fly-to, map-control commands. */
export function useCesiumCamera(viewer: Cesium.Viewer | null, selected: { lat: number; lon: number } | null, selectedId: string | null) {
  const flyTo = useApp((s) => s.flyTo);
  const command = useApp((s) => s.cameraCommand);

  useEffect(() => {
    if (viewer) configureCameraController(viewer);
  }, [viewer]);

  useEffect(() => {
    if (!viewer || !flyTo) return;
    const dest = Cesium.Cartesian3.fromDegrees(flyTo.lon, flyTo.lat, flyTo.height);
    viewer.camera.flyTo({ destination: dest, duration: flightDuration(viewer, dest), easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT });
  }, [viewer, flyTo]);

  // Fly when the selection changes (not when fire data refreshes).
  useEffect(() => {
    if (viewer && selected) flyToPoint(viewer, selected.lat, selected.lon);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, selectedId]);

  useEffect(() => {
    if (!viewer || !command) return;
    if (command.kind === "global") flyGlobal(viewer);
    else if (command.kind === "focus" && selected) flyToPoint(viewer, selected.lat, selected.lon);
    else if (command.kind === "zoomIn") zoomStep(viewer, true);
    else if (command.kind === "zoomOut") zoomStep(viewer, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, command]);
}
