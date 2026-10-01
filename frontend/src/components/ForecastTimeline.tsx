import { Pause, Play, SkipBack, SkipForward } from "lucide-react";

import { useApp } from "../stores/app";
import type { PredictionStep } from "../types/api";

export const HORIZONS = [10, 30, 60, 360, 720, 1440, 2880, 4320];
export const LABELS = ["NOW", "10m", "30m", "1h", "6h", "12h", "24h", "48h", "72h"];
export const SPEEDS = [0.5, 1, 2, 4];

export function stepAt(steps: PredictionStep[] | undefined, index: number): PredictionStep | null {
  if (!steps || index === 0) return null;
  return steps.find((s) => s.horizon_min === HORIZONS[index - 1]) ?? null;
}

/** Indices with real model output (plus NOW). Navigation and playback only visit these. */
export function availableIndices(steps: PredictionStep[] | undefined): number[] {
  return [0, ...HORIZONS.map((h, i) => (steps?.find((s) => s.horizon_min === h && s.status === "ok") ? i + 1 : -1)).filter((i) => i > 0)];
}

/** NOW → 72 h controller for the globe. Unavailable steps are marked and never interpolated. */
export default function ForecastTimeline() {
  const prediction = useApp((s) => s.prediction);
  const index = useApp((s) => s.timelineIndex);
  const setIndex = useApp((s) => s.setTimelineIndex);
  const playing = useApp((s) => s.playing);
  const setPlaying = useApp((s) => s.setPlaying);
  const speed = useApp((s) => s.playbackSpeed);
  const setSpeed = useApp((s) => s.setPlaybackSpeed);
  const steps = prediction?.steps;
  const avail = availableIndices(steps);
  const canPlay = !!prediction && avail.length > 1;

  const step = (dir: 1 | -1) => {
    setPlaying(false);
    const k = avail.indexOf(index);
    const next = k < 0 ? avail.find((i) => (dir > 0 ? i > index : i < index)) ?? index : avail[Math.min(avail.length - 1, Math.max(0, k + dir))];
    setIndex(next);
  };
  const ctl = "btn h-7 px-2";
  return (
    <div className="flex flex-col gap-1.5 px-3 py-2" aria-label="Forecast timeline">
      <div className="flex items-center justify-between gap-2 text-2xs uppercase tracking-[0.14em] text-dim">
        <span>Forecast timeline</span>
        <span className="truncate">{prediction ? `${prediction.model.name} · ${prediction.prediction_id}` : "no forecast"}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 min-w-0">
        <button className={ctl} onClick={() => step(-1)} disabled={!canPlay} aria-label="Previous forecast frame" title="Previous frame"><SkipBack size={12} /></button>
        <button className={`${ctl} ${playing ? "border-fire/70 text-fire" : ""}`} onClick={() => setPlaying(!playing)} disabled={!canPlay}
                aria-label={playing ? "Pause forecast animation" : "Play forecast animation"} title={playing ? "Pause" : "Play"}>
          {playing ? <Pause size={12} /> : <Play size={12} />}
        </button>
        <button className={ctl} onClick={() => step(1)} disabled={!canPlay} aria-label="Next forecast frame" title="Next frame"><SkipForward size={12} /></button>
        <input type="range" min={0} max={8} step={1} value={index}
               onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }}
               disabled={!prediction} aria-label="Forecast horizon" aria-valuetext={LABELS[index]}
               className="flex-1 min-w-[90px] accent-[rgb(var(--c-fire))] mx-1" />
        <label className="sr-only" htmlFor="speed">Playback speed</label>
        <select id="speed" className="input h-7 w-16 px-1" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} disabled={!canPlay} title="Playback speed">
          {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
      </div>
      <ol className="grid grid-cols-9 m-0 p-0 list-none text-2xs">
        {LABELS.map((l, i) => {
          const s = stepAt(steps, i);
          const ok = i === 0 || s?.status === "ok";
          return (
            <li key={l} className="text-center">
              <button onClick={() => { if (!prediction) return; setPlaying(false); setIndex(i); }} disabled={!prediction}
                className={`w-full py-0.5 border-t-2 ${i === index ? "border-fire text-head" : "border-line text-dim"} ${!ok && prediction ? "line-through opacity-60" : ""}`}
                title={!ok && prediction ? s?.reason ?? "Forecast unavailable" : l}>
                {l}
              </button>
            </li>
          );
        })}
      </ol>
      <p className="text-2xs text-dim m-0">Frames are real model outputs; playback cross-fades between them for readability. Forecast uncertainty generally increases with horizon.</p>
    </div>
  );
}
