import { Layers as LayersIcon } from "lucide-react";
import { useState } from "react";

import { type Layers, useApp } from "../stores/app";

const TOGGLES: [keyof Layers, string, string][] = [
  ["fires", "Active fires", "NASA FIRMS detections (observed)"],
  ["prediction", "Spread probability", "WildfireTwin model output (predicted)"],
  ["front", "Forecast fire front", "p ≥ 0.5 boundary of the shown frame"],
  ["footprint", "Observed footprint", "FIRMS pixel footprint used as model input"],
  ["wind", "Wind at fire", "Open-Meteo 10 m observation"],
  ["relief", "Terrain relief", "SRTM hillshade, fades in when zoomed"],
  ["nightLights", "Night lights", "NASA Black Marble 2016, night side only"],
  ["borders", "Boundaries & places", "Esri reference overlay"],
];

export default function DataLayerControl() {
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  const layers = useApp((s) => s.layers);
  const setLayer = useApp((s) => s.setLayer);
  const opacity = useApp((s) => s.overlayOpacity);
  const setOpacity = useApp((s) => s.setOverlayOpacity);
  const date = useApp((s) => s.fires?.meta.latest_acquisition?.slice(0, 10));
  return (
    <div className="absolute top-2 left-2 z-10 bg-panel/95 border border-line text-xs w-56">
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
          <fieldset className="border-0 p-0 m-0">
            <legend className="label mt-1">Imagery</legend>
            {([["satellite", "Satellite (Esri)"], ["daily", `VIIRS ${date ?? "daily"}`], ["dark", "Dark"]] as const).map(([b, l]) => (
              <label key={b} className="flex items-center gap-1.5 cursor-pointer"
                     title={b === "daily" ? "NASA GIBS VIIRS true colour of the latest FIRMS acquisition date — shows that day's real clouds" : undefined}>
                <input type="radio" name="basemap" checked={layers.imagery === b} onChange={() => setLayer("imagery", b)} /> {l}
              </label>
            ))}
          </fieldset>
          <label className="block">
            <span className="label mt-1">Prediction opacity {Math.round(opacity * 100)}%</span>
            <input type="range" min={0.1} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="w-full" aria-label="Prediction opacity" />
          </label>
          <div className="pt-1 border-t border-line">
            <div className="label mt-1">Fire spread probability</div>
            <div className="h-2 w-full" aria-hidden
                 style={{ background: "linear-gradient(90deg, rgba(110,18,12,0.25) 0%, rgba(110,18,12,0.45) 5%, rgb(185,40,18) 30%, rgb(240,95,25) 60%, rgb(255,140,35) 90%, rgb(255,190,80) 98%, rgb(255,225,150) 100%)" }} />
            <div className="flex justify-between text-2xs text-dim"><span>0.0</span><span>0.5</span><span>1.0</span></div>
            <div className="text-2xs text-dim mt-0.5">Model probability; p &lt; 0.05 not drawn.</div>
            <div className="flex items-center gap-1 text-2xs text-dim mt-1"><span className="w-3 h-[2px] bg-[#ffe196] inline-block" aria-hidden /> forecast fire front (p = 0.5)</div>
            <div className="flex items-center gap-1 text-2xs text-dim"><span className="w-3 h-[2px] bg-info inline-block" aria-hidden /> observed footprint · model domain</div>
            <div className="flex items-center gap-1 text-2xs text-dim"><span className="w-3 h-[1px] border-t border-dashed border-[#c8ced6] inline-block" aria-hidden /> analysis window</div>
            <div className="flex items-center gap-1 text-2xs text-dim"><span className="w-2 h-2 bg-fire inline-block" aria-hidden /> active (&lt;24 h) · <span className="w-2 h-2 bg-[#b8892e] inline-block" aria-hidden /> recent</div>
          </div>
        </div>
      )}
    </div>
  );
}
