import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import AlertPanel from "../components/AlertPanel";
import DataLayerControl from "../components/DataLayerControl";
import EnvironmentPanel from "../components/EnvironmentPanel";
import FireDetailsPanel from "../components/FireDetailsPanel";
import ForecastTimeline from "../components/ForecastTimeline";
import GlobeViewer from "../components/GlobeViewer";
import PredictionPanel from "../components/PredictionPanel";
import SystemLogPanel from "../components/SystemLogPanel";
import { EmptyState, Panel } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useApp } from "../stores/app";
import { useAuth } from "../stores/auth";
import type { Prediction } from "../types/api";

const MODEL_OPTIONS = [
  { v: "", l: "Default (best available)" },
  { v: "physics_fno", l: "Physics-Informed FNO" },
  { v: "fno", l: "FNO" },
  { v: "unet", l: "U-Net (baseline)" },
];

function PreviewChart({ p }: { p: Prediction | null }) {
  const data = (p?.steps ?? []).map((s) => ({ h: s.label, area: s.status === "ok" ? Number(s.predicted_area_km2?.toFixed(3)) : null }));
  if (!p) return <EmptyState message="No prediction yet." />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
        <CartesianGrid stroke="rgb(34 41 51)" vertical={false} />
        <XAxis dataKey="h" tick={{ fill: "rgb(128 138 150)", fontSize: 10, fontFamily: "JetBrains Mono" }} stroke="rgb(34 41 51)" />
        <YAxis tick={{ fill: "rgb(128 138 150)", fontSize: 10, fontFamily: "JetBrains Mono" }} stroke="rgb(34 41 51)" />
        <Tooltip contentStyle={{ background: "rgb(15 18 22)", border: "1px solid rgb(34 41 51)", fontSize: 11, fontFamily: "JetBrains Mono" }}
                 formatter={(v) => [v == null ? "unavailable" : `${v} km²`, "predicted area"]} />
        <Bar dataKey="area" fill="rgb(255 122 26)" isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function Dashboard() {
  const selected = useApp((s) => s.selectedFireId);
  const prediction = useApp((s) => s.prediction);
  const setPrediction = useApp((s) => s.setPrediction);
  const session = useAuth((s) => s.session);
  const navigate = useNavigate();
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState("");


  const analyze = async () => {
    if (!selected) return;
    if (!session) return navigate(`/login?next=${encodeURIComponent("/")}`);
    setRunning(true);
    setError(null);
    try {
      const p = await api<Prediction>("/api/predictions", { method: "POST", json: { fire_id: selected, model_type: model || null } });
      setPrediction(p);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto lg:overflow-hidden flex flex-col lg:grid lg:grid-rows-[1fr_auto] min-h-0">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] lg:min-h-0">
        <div className="relative h-[58vh] lg:h-auto lg:min-h-[320px]">
          <GlobeViewer prediction={prediction} />
          <DataLayerControl />
          <div className="absolute bottom-2 left-2 text-2xs text-dim bg-panel/90 border border-line px-2 py-1">
            Fires: NASA FIRMS (observed) · Imagery © Esri, Maxar, Earthstar · NASA GIBS · Terrain/relief: SRTM (local)
          </div>
        </div>
        <div className="border-l border-line lg:overflow-auto lg:min-h-0 flex flex-col gap-px bg-line [&>section]:shrink-0">
          <FireDetailsPanel onAnalyze={analyze} analyzing={running} />
          <EnvironmentPanel fireId={selected} />
          <PredictionPanel running={running} error={error} />
          <AlertPanel fireId={selected} limit={4} />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] xl:grid-cols-[260px_300px_1fr_1fr] border-t border-line h-auto xl:h-[190px] gap-px bg-line">
        <Panel title="Simulation Control">
          <label className="label" htmlFor="model-select">Model</label>
          <select id="model-select" className="input mb-2" value={model} onChange={(e) => setModel(e.target.value)}>
            {MODEL_OPTIONS.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
          </select>
          <button className="btn-primary w-full" disabled={!selected || running} onClick={analyze}>
            {running ? "Running…" : "[ Run WildfireTwin ]"}
          </button>
          <button className="btn w-full mt-2" onClick={() => navigate("/simulation")}>Reference simulation →</button>
        </Panel>
        <Panel title="Prediction Preview" bodyClass="p-2 h-[150px]"><PreviewChart p={prediction} /></Panel>
        <div className="panel"><ForecastTimeline /></div>
        <SystemLogPanel className="h-[190px] xl:h-auto" limit={40} />
      </div>
    </div>
  );
}
