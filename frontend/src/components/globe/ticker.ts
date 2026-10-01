import type * as Cesium from "cesium";

/**
 * One requestAnimationFrame loop per viewer, shared by all globe animations (marker pulse, forecast
 * playback, fire-front glow, wind particles). Subscribers mutate Cesium objects directly — never React
 * state — and return true when they changed something, in which case a single render is requested.
 * The loop runs only while there are subscribers and the tab is visible, capped at ~30 fps
 * (the viewer uses requestRenderMode, so an idle globe costs no GPU time).
 */
export type TickFn = (timeMs: number, dtMs: number) => boolean | void;

export interface Ticker {
  add(fn: TickFn): () => void;
  destroy(): void;
}

const FRAME_MS = 1000 / 30;

export function createTicker(viewer: Cesium.Viewer): Ticker {
  const subs = new Set<TickFn>();
  let raf = 0;
  let last = 0;
  let lastFrame = 0;

  const loop = (t: number) => {
    raf = 0;
    if (viewer.isDestroyed() || subs.size === 0) return;
    if (!document.hidden && t - lastFrame >= FRAME_MS - 1) {
      const dt = last ? Math.min(t - last, 250) : FRAME_MS;
      last = t;
      lastFrame = t;
      let dirty = false;
      for (const fn of subs) {
        try {
          if (fn(t, dt)) dirty = true;
        } catch (e) {
          console.error("globe animation error", e);
        }
      }
      if (dirty) viewer.scene.requestRender();
    }
    raf = requestAnimationFrame(loop);
  };

  return {
    add(fn) {
      subs.add(fn);
      if (!raf) raf = requestAnimationFrame(loop);
      return () => {
        subs.delete(fn);
      };
    },
    destroy() {
      subs.clear();
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    },
  };
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
