import { Crosshair, Globe2, Minus, Plus } from "lucide-react";

import { useApp } from "../../stores/app";

/** Minimal on-map navigation: zoom in/out, global view, focus selected fire, plus altitude readout. */
export default function MapControls({ altitudeRef }: { altitudeRef: React.RefObject<HTMLSpanElement> }) {
  const send = useApp((s) => s.sendCameraCommand);
  const selected = useApp((s) => s.selectedFireId);
  const btn = "w-8 h-8 inline-flex items-center justify-center border-b border-line last:border-b-0 text-ink hover:text-head hover:bg-raised disabled:opacity-35 disabled:cursor-not-allowed";
  return (
    <div className="absolute top-2 right-2 z-10 flex flex-col items-end gap-2">
      <div className="flex flex-col bg-panel/95 border border-line" role="toolbar" aria-label="Map navigation">
        <button className={btn} onClick={() => send("zoomIn")} aria-label="Zoom in" title="Zoom in"><Plus size={13} /></button>
        <button className={btn} onClick={() => send("zoomOut")} aria-label="Zoom out" title="Zoom out"><Minus size={13} /></button>
        <button className={btn} onClick={() => send("global")} aria-label="Global view" title="Global view"><Globe2 size={13} /></button>
        <button className={btn} onClick={() => send("focus")} disabled={!selected} aria-label="Focus selected fire" title="Focus selected fire (or double-click it)"><Crosshair size={13} /></button>
      </div>
      <span ref={altitudeRef} className="bg-panel/90 border border-line px-1.5 py-0.5 text-2xs text-dim tabular-nums" aria-label="Camera altitude" />
    </div>
  );
}
