import { Layers as LayersIcon } from "lucide-react";
import { useState } from "react";

import { type Layers, useApp, type WindPerformance } from "../stores/app";

const TOGGLES: [keyof Layers, string, string][] = [
  ["fires", "Active fires", "Observed NASA FIRMS satellite detections (global)"],
  ["prediction", "AI predicted spread", "WildfireTwin model probability (N. California model domain only)"],
  ["front", "Forecast fire front", "p ≥ 0.5 boundary of the shown model frame"],
  ["footprint", "Observed footprint", "FIRMS pixel footprint used as model input"],
  ["wind", "Wind at fire", "Open-Meteo 10 m observation at the selected fire"],
  ["relief", "Terrain relief", "SRTM hillshade, fades in when zoomed"],
  ["nightLights", "Night lights", "NASA Black Marble 2016, night side only"],
  ["borders", "Boundaries & places", "Esri reference overlay"],
];

const PERF: [WindPerformance, string][] = [["auto", "Auto"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]];

function Slider({ label, value, min, max, step, onChange, fmt }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt: (v: number) => string;
}) {
  return (
    <label className="block">
      <span className="flex justify-between text-2xs text-dim"><span>{label}</span><span className="tabular-nums">{fmt(value)}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
             className="w-full" aria-label={label} />
    </label>
  );
}

export default function DataLayerControl() {
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  const layers = useApp((s) => s.layers);
  const setLayer = useApp((s) => s.setLayer);
  const opacity = useApp((s) => s.overlayOpacity);
  const setOpacity = useApp((s) => s.setOverlayOpacity);
  const date = useApp((s) => s.fires?.meta.latest_acquisition?.slice(0, 10));
  const wind = useApp((s) => s.windSettings);
  const setWind = useApp((s) => s.setWindSettings);
  const windStatus = useApp((s) => s.windStatus);
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const mult = (v: number) => `${v.toFixed(2).replace(/\.?0+$/, "")}×`;

  return (
    <div className="absolute top-2 left-2 z-10 bg-panel/95 border border-line text-xs w-60 max-h-[calc(100%-1rem)] overflow-y-auto">
      <button className="w-full flex items-center gap-2 px-2 h-7 text-2xs uppercase tracking-[0.14em] text-dim hover:text-ink"
              onClick={() => setOpen(!open)} aria-expanded={open}>
        <LayersIcon size={12} aria-hidden /> Layers
      </button>
      {open && (
        <div className="px-2 pb-2 space-y-1.5">
          {TOGGLES.map(([k, l, hint]) => (
            <label key={k} className="flex items-center gap-2 cursor-pointer" title={hint}>
              <input type="checkbox" checked={layers[k] as boolean} onChange={(e) => setLayer(k, e.target.checked as never)} /> {l}
            </label>
          ))}

          <fieldset className="border-0 p-0 m-0 pt-1 border-t border-line">
            <legend className="label mt-1">Atmosphere</legend>
            <label className="flex items-center gap-2 cursor-pointer" title="Animated particles following the real NOAA GFS 10 m wind field (global)">
              <input type="checkbox" checked={layers.windFlow} onChange={(e) => setLayer("windFlow", e.target.checked)} /> Wind flow
            </label>
            <div className="text-2xs mt-0.5" role="status" aria-live="polite">
              {!layers.windFlow ? <span className="text-dim">Off — animation stopped</span>
                : windStatus.state === "ok" ? <span className="text-dim">NOAA GFS 1° · 10 m · {windStatus.cycle.slice(0, 13).replace("T", " ")}Z analysis</span>
                : windStatus.state === "unavailable" ? <span className="text-warn">{windStatus.message}</span>
                : <span className="text-dim">Loading wind field…</span>}
            </div>
            {layers.windFlow && (
              <div className="space-y-1 mt-1">
                <Slider label="Opacity" value={wind.opacity} min={0.15} max={1} step={0.05} onChange={(v) => setWind({ opacity: v })} fmt={pct} />
                <Slider label="Particle density" value={wind.density} min={0.25} max={1.5} step={0.05} onChange={(v) => setWind({ density: v })} fmt={mult} />
                <Slider label="Animation speed" value={wind.speed} min={0.25} max={3} step={0.25} onChange={(v) => setWind({ speed: v })} fmt={mult} />
                <label className="flex items-center justify-between text-2xs text-dim">
                  <span>Performance</span>
                  <select value={wind.performance} onChange={(e) => setWind({ performance: e.target.value as WindPerformance })}
                          className="bg-raised border border-line text-ink text-2xs px-1 py-0.5" aria-label="Wind rendering performance">
                    {PERF.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
              </div>
            )}
          </fieldset>

          <fieldset className="border-0 p-0 m-0">
            <legend className="label mt-1">Imagery</legend>
            {([["satellite", "Satellite (Esri)"], ["daily", `VIIRS ${date ?? "daily"}`], ["dark", "Dark"]] as const).map(([b, l]) => (
              <label key={b} className="flex items-center gap-1.5 cursor-pointer"
                     title={b === "daily" ? "NASA GIBS VIIRS true colour of the latest FIRMS acquisition date — shows that day's real clouds" : undefined}>
                <input type="radio" name="basemap" checked={layers.imagery === b} onChange={() => setLayer("imagery", b)} /> {l}
              </label>
            ))}
          </fieldset>
          <Slider label="Prediction opacity" value={opacity} min={0.1} max={1} step={0.05} onChange={setOpacity} fmt={pct} />

          <div className="pt-1 border-t border-line space-y-1" aria-label="Legend">
            <div className="label mt-1">Legend</div>
            <div className="flex items-center gap-1.5 text-2xs text-ink">
              <span className="w-2 h-2 rounded-full bg-fire inline-block" aria-hidden /> Observed FIRMS detection
            </div>
            <div className="flex items-center gap-1 text-2xs text-dim pl-3.5">
              active (&lt;24 h) · <span className="w-2 h-2 rounded-full bg-[#b8892e] inline-block" aria-hidden /> recent
            </div>
            <div className="text-2xs text-ink mt-1">AI predicted spread <span className="text-dim">(N. California only)</span></div>
            <div className="h-2 w-full" aria-hidden
                 style={{ background: "linear-gradient(90deg, rgba(110,18,12,0.25) 0%, rgba(110,18,12,0.45) 5%, rgb(185,40,18) 30%, rgb(240,95,25) 60%, rgb(255,140,35) 90%, rgb(255,190,80) 98%, rgb(255,225,150) 100%)" }} />
            <div className="flex justify-between text-2xs text-dim"><span>p 0.0</span><span>0.5</span><span>1.0</span></div>
            <div className="flex items-center gap-1 text-2xs text-dim"><span className="w-3 h-[2px] bg-[#ffe196] inline-block" aria-hidden /> forecast fire front (p = 0.5)</div>
            <div className="flex items-center gap-1 text-2xs text-dim"><span className="w-3 h-[2px] bg-info inline-block" aria-hidden /> observed footprint · model domain</div>
            <div className="flex items-center gap-1 text-2xs text-dim"><span className="w-3 h-[1px] border-t border-dashed border-[#c8ced6] inline-block" aria-hidden /> analysis window</div>
            {layers.windFlow && (
              <>
                <div className="text-2xs text-ink mt-1">Wind flow <span className="text-dim">(atmospheric flow, not fire spread)</span></div>
                <div className="h-1.5 w-full" aria-hidden
                     style={{ background: "linear-gradient(90deg, rgb(128,148,173) 0%, rgb(89,189,224) 40%, rgb(245,224,133) 70%, rgb(255,153,71) 100%)" }} />
                <div className="flex justify-between text-2xs text-dim"><span>Low</span><span>8</span><span>14</span><span>20+ m/s High</span></div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
