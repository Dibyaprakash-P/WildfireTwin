import type * as Cesium from "cesium";
import { useEffect, useRef } from "react";

import { ApiError } from "../../lib/api";
import { useApp } from "../../stores/app";
import { BackendGfsWindProvider, type WindFieldProvider, type WindGrid } from "./wind/windField";
import { WindParticleRenderer } from "./wind/windParticles";

/**
 * Global wind-flow layer: loads the real gridded wind field from a WindFieldProvider and drives the WebGL
 * particle renderer.
 *  - The field is fetched when the layer is switched on and refreshed every REFRESH_MS (GFS updates every
 *    6 h; the backend caches it) — never per animation frame.
 *  - Switching the layer off destroys the renderer (animation loop stopped, GL resources released).
 *  - No field → no particles; the status reads "Wind data unavailable". Nothing is synthesised.
 */
const REFRESH_MS = 30 * 60 * 1000;
const provider: WindFieldProvider = new BackendGfsWindProvider();

export function useWindFlow(viewer: Cesium.Viewer | null, enabled: boolean) {
  const settings = useApp((s) => s.windSettings);
  const renderer = useRef<WindParticleRenderer | null>(null);
  const grid = useRef<WindGrid | null>(null);

  // data: fetch while enabled, refresh periodically
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const { setWindStatus } = useApp.getState();
    const load = async () => {
      if (!grid.current) setWindStatus({ state: "loading" });
      try {
        const g = await provider.getWindField();
        if (cancelled) return;
        grid.current = g;
        renderer.current?.setGrid(g);
        setWindStatus({ state: "ok", source: g.meta.source, cycle: g.meta.cycle, maxSpeed: g.meta.maxSpeed });
      } catch (e) {
        if (cancelled) return;
        if (!grid.current) {
          const msg = e instanceof ApiError ? e.message : "Wind data unavailable";
          setWindStatus({ state: "unavailable", message: msg.startsWith("Wind data unavailable") ? msg : `Wind data unavailable (${msg})` });
        }
        // a failed refresh keeps showing the last real field
      }
    };
    void load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [enabled]);

  // renderer lifecycle
  useEffect(() => {
    if (!viewer || !enabled) return;
    let r: WindParticleRenderer;
    try {
      r = new WindParticleRenderer(viewer, grid.current, useApp.getState().windSettings);
    } catch (e) {
      useApp.getState().setWindStatus({ state: "unavailable", message: `Wind layer could not start: ${(e as Error).message}` });
      return;
    }
    renderer.current = r;
    return () => {
      r.destroy();
      if (renderer.current === r) renderer.current = null;
    };
  }, [viewer, enabled]);

  useEffect(() => {
    renderer.current?.setSettings(settings);
  }, [settings]);
}
