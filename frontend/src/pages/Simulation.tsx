import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import GlobeViewer from "../components/GlobeViewer";
import { DataClassTag, EmptyState, ErrorState, KV, LoadingState, Panel } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num, utc } from "../lib/format";
import { type Overlay, useApp } from "../stores/app";
import { useAuth } from "../stores/auth";

interface Sim {
  simulation_id: string;
  kind: "reference_wtrs" | "imported";
  simulator: string;
  status: "running" | "done" | "failed";
  error?: string;
  created_at: string;
  fire_id?: string | null;
  request?: Record<string, unknown>;
  runtime_s?: number;
  final_area_km2?: number;
  area_series?: { hour: number; burned_area_km2: number }[];
  overlay_url?: string;
  bounds_wgs84?: [number, number, number, number];
  footprint_url?: string | null;
  grid?: { cell: number; size: number };
  weather_summary?: Record<string, number>;
  weather_source_label?: string;
  touches_window_edge?: boolean;
  import_meta?: Record<string, unknown>;
  max_arrival_min?: number;
}

export default function SimulationPage() {
  const session = useAuth((s) => s.session);
  const selected = useApp((s) => s.selectedFireId);
  const fires = useApp((s) => s.fires);
  const navigate = useNavigate();
  const domainFires = useMemo(() => (fires?.rows ?? []).filter((r) => r[7]).map((r) => r[0]), [fires]);

  const [fireId, setFireId] = useState<string>(selected ?? "");
  const [useFire, setUseFire] = useState(true);
  const [lat, setLat] = useState("41.25");
  const [lon, setLon] = useState("-123.47");
  const [duration, setDuration] = useState(24);
  const [cell, setCell] = useState(60);
  const [wsrc, setWsrc] = useState<"open_meteo" | "era5" | "constant">("open_meteo");
  const [era5Start, setEra5Start] = useState("2024-08-10T18:00");
  const [cw, setCw] = useState({ temperature_c: 30, rh_pct: 20, wind_speed_ms: 5, wind_from_deg: 270 });
  const [herb, setHerb] = useState(0.6);
  const [woody, setWoody] = useState(0.9);

  const [engine, setEngine] = useState<"wtrs" | "import">("wtrs");
  const [sims, setSims] = useState<Sim[] | null>(null);
  const [active, setActive] = useState<Sim | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<{ simulations: Sim[] }>("/api/simulations?limit=30");
      setSims(r.simulations);
      setActive((a) => (a ? r.simulations.find((s) => s.simulation_id === a.simulation_id) ?? a : r.simulations[0] ?? null));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!sims?.some((s) => s.status === "running")) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [sims, load]);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!session) return navigate("/login?next=/simulation");
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        ignition: useFire ? "fire_footprint" : "point", duration_hours: duration, cell_m: cell, weather_source: wsrc,
        live_herb: herb, live_woody: woody,
      };
      if (useFire) body.fire_id = fireId;
      else { body.latitude = Number(lat); body.longitude = Number(lon); }
      if (wsrc === "era5") body.era5_start = era5Start;
      if (wsrc === "constant") body.constant = cw;
      const s = await api<Sim>("/api/simulations", { method: "POST", json: body });
      setActive(s);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (active?.status !== "done" || !active.bounds_wgs84) return;
    const [w, s_, e, n] = active.bounds_wgs84;
    const span = Math.max(e - w, n - s_);
    useApp.getState().requestFlyTo((s_ + n) / 2, (w + e) / 2, Math.max(8000, span * 111000 * 1.6));
  }, [active?.simulation_id, active?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const runModel = () => {
    if (!fireId) return;
    useApp.getState().selectFire(fireId);
    navigate("/");
  };

  const overlays: Overlay[] = active?.status === "done" && active.overlay_url && active.bounds_wgs84
    ? [{ id: `sim-${active.simulation_id}`, url: active.overlay_url, bounds: active.bounds_wgs84, kind: "simulation" as const },
       ...(active.footprint_url ? [{ id: `simfp-${active.simulation_id}`, url: active.footprint_url, bounds: active.bounds_wgs84, kind: "footprint" as const }] : [])]
    : [];

  return (
    <div className="h-full overflow-y-auto xl:overflow-hidden grid grid-cols-1 xl:grid-cols-[360px_1fr_340px] min-h-0 gap-px bg-line">
      <div className="overflow-auto bg-bg flex flex-col gap-px">
        <Panel title="Reference engine">
          <div role="radiogroup" aria-label="Reference engine" className="grid grid-cols-2 gap-px bg-line border border-line">
            {([["wtrs", "WTRS / Rothermel + MTT", "in-app reference simulator"], ["import", "Import FARSITE / FlamMap", "external offline output"]] as const).map(([k, l, d]) => (
              <button key={k} role="radio" aria-checked={engine === k} onClick={() => setEngine(k)}
                      className={`text-left px-2 py-1.5 text-xs ${engine === k ? "bg-raised text-head border-l-2 border-warn" : "bg-panel text-dim hover:text-ink border-l-2 border-transparent"}`}>
                [ {l} ]<div className="text-2xs text-dim">{d}</div>
              </button>
            ))}
          </div>
          <p className="text-2xs text-dim mt-2 mb-0">Different engines — results are labelled with their engine and never mixed. Both are reference simulations (simulated), not observed data.</p>
        </Panel>
        {engine === "wtrs" && <Panel title="Configure Inputs" right={<DataClassTag c="simulated" engine="Rothermel + MTT" />}>
          <form onSubmit={run} id="inputs" className="space-y-3">
            <fieldset className="border-0 p-0 m-0">
              <legend className="label">Fire / ignition</legend>
              <label className="flex items-center gap-2 text-xs mb-1"><input type="radio" checked={useFire} onChange={() => setUseFire(true)} /> Observed FIRMS footprint</label>
              {useFire && (
                <select className="input mb-2" value={fireId} onChange={(e) => setFireId(e.target.value)} aria-label="Fire event in model domain">
                  <option value="">— select fire in model domain ({domainFires.length}) —</option>
                  {domainFires.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              )}
              <label className="flex items-center gap-2 text-xs"><input type="radio" checked={!useFire} onChange={() => setUseFire(false)} /> Point ignition</label>
              {!useFire && (
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <input className="input" aria-label="Latitude" value={lat} onChange={(e) => setLat(e.target.value)} />
                  <input className="input" aria-label="Longitude" value={lon} onChange={(e) => setLon(e.target.value)} />
                </div>
              )}
            </fieldset>
            <div className="grid grid-cols-2 gap-2">
              <label><span className="label">Duration (h)</span>
                <input type="number" min={1} max={72} className="input" value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></label>
              <label><span className="label">Cell size / terrain grid</span>
                <select className="input" value={cell} onChange={(e) => setCell(Number(e.target.value))}>
                  {[30, 60, 120].map((c) => <option key={c} value={c}>{c} m × 128</option>)}
                </select></label>
            </div>
            <label className="block"><span className="label">Weather source</span>
              <select className="input" value={wsrc} onChange={(e) => setWsrc(e.target.value as typeof wsrc)}>
                <option value="open_meteo">Open-Meteo forecast (from now)</option>
                <option value="era5">ERA5 historical (2024–2025)</option>
                <option value="constant">Constant wind conditions</option>
              </select></label>
            {wsrc === "era5" && <label className="block"><span className="label">Start (UTC)</span>
              <input type="datetime-local" className="input" value={era5Start} onChange={(e) => setEra5Start(e.target.value)} /></label>}
            {wsrc === "constant" && (
              <div className="grid grid-cols-2 gap-2">
                {(["wind_speed_ms", "wind_from_deg", "temperature_c", "rh_pct"] as const).map((k) => (
                  <label key={k}><span className="label">{k.replace(/_/g, " ")}</span>
                    <input type="number" className="input" value={cw[k]} onChange={(e) => setCw({ ...cw, [k]: Number(e.target.value) })} /></label>
                ))}
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <label><span className="label">Live herb FM</span><input type="number" step={0.05} className="input" value={herb} onChange={(e) => setHerb(Number(e.target.value))} /></label>
              <label><span className="label">Live woody FM</span><input type="number" step={0.05} className="input" value={woody} onChange={(e) => setWoody(Number(e.target.value))} /></label>
            </div>
            <p className="text-2xs text-dim m-0">Fuel: LANDFIRE FBFM40 · Terrain: SRTM slope/aspect · Live fuel moisture is a scenario parameter (fraction), not observed.</p>
            {error && <ErrorState message={error} />}
            <button className="btn-primary w-full" disabled={busy || (useFire && !fireId)}>{busy ? "Starting…" : "[ Run Reference Simulation · WTRS ]"}</button>
            <button type="button" className="btn w-full" disabled={!fireId} onClick={runModel}>[ Run WildfireTwin ] → dashboard</button>
          </form>
        </Panel>}
        {engine === "import" && <ImportPanel onImported={(s) => { setActive(s); void load(); }} />}
      </div>
      <div className="relative h-[55vh] xl:h-auto min-h-[360px] bg-bg">
        <GlobeViewer overlays={overlays} />
        <div className="absolute top-2 left-2 bg-panel/95 border border-line px-2 py-1 text-2xs text-dim max-w-md">
          <span className="text-warn">REFERENCE SIMULATION</span> (physics-based, simulated) — distinct from <span className="text-fire">NEURAL PREDICTION</span> on the dashboard.
          {active?.status === "done" && <div className="mt-1">Arrival time: pale = early → dark red = late</div>}
        </div>
      </div>
      <div className="overflow-auto bg-bg flex flex-col gap-px" id="results">
        <Panel title="Results Viewer">
          {!active ? <EmptyState message="No simulation selected." /> : (
            <dl className="m-0">
              <KV k="ID" v={active.simulation_id} />
              <KV k="Engine" v={active.kind === "imported" ? <DataClassTag c="simulated" engine={`${active.simulator} (imported)`} /> : <DataClassTag c="simulated" engine="Rothermel + MTT (WTRS)" />} />
              <KV k="Status" v={active.status === "failed" ? <span className="text-crit">FAILED — {active.error}</span> : active.status.toUpperCase()} />
              {active.status === "running" && <LoadingState label="Simulating" />}
              {active.runtime_s !== undefined && <KV k="Runtime" v={`${num(active.runtime_s, 2)} s (CPU)`} />}
              {active.final_area_km2 !== undefined && <KV k="Final area" v={`${num(active.final_area_km2, 2)} km²`} />}
              {active.grid && <KV k="Grid" v={`${active.grid.size}² @ ${active.grid.cell} m`} />}
              {active.weather_source_label && <KV k="Weather" v={<span className="text-2xs">{active.weather_source_label}</span>} />}
              {active.weather_summary && <KV k="Mean wx" v={`${num(active.weather_summary.temperature_c, 1)} °C · RH ${num(active.weather_summary.rh_pct, 0)}% · ${num(active.weather_summary.wind_speed_ms, 1)} m/s from ${num(active.weather_summary.wind_from_deg, 0)}°`} />}
              {active.touches_window_edge && <p className="text-2xs text-warn">Fire reached the window edge; growth beyond it is not simulated.</p>}
              {active.import_meta && <KV k="Import" v={<span className="text-2xs">{JSON.stringify(active.import_meta)}</span>} />}
            </dl>
          )}
          {active?.area_series && (
            <div className="h-36 mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={active.area_series} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                  <XAxis dataKey="hour" tick={{ fill: "rgb(128 138 150)", fontSize: 10 }} stroke="rgb(34 41 51)" />
                  <YAxis tick={{ fill: "rgb(128 138 150)", fontSize: 10 }} stroke="rgb(34 41 51)" />
                  <Tooltip contentStyle={{ background: "rgb(15 18 22)", border: "1px solid rgb(34 41 51)", fontSize: 11 }} />
                  <Line dataKey="burned_area_km2" stroke="rgb(232 179 57)" dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>
        <Panel title="Recent Simulations">
          {!sims ? <LoadingState /> : sims.length === 0 ? <EmptyState message="No simulations yet." /> : (
            <ul className="m-0 p-0 list-none">
              {sims.map((s) => (
                <li key={s.simulation_id}>
                  <button onClick={() => setActive(s)} className={`w-full text-left text-xs py-1 px-1 border-l-2 ${active?.simulation_id === s.simulation_id ? "border-warn bg-raised" : "border-transparent hover:bg-raised"}`}>
                    {s.simulation_id} · {s.kind === "imported" ? `${s.simulator} (imported)` : "WTRS · Rothermel+MTT"} · {s.status} <span className="text-dim text-2xs">{utc(s.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

function ImportPanel({ onImported }: { onImported: (s: Sim) => void }) {
  const session = useAuth((s) => s.session);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("arrival_raster");
  const [simulator, setSimulator] = useState("FARSITE");
  const [units, setUnits] = useState("");
  const [timeField, setTimeField] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setMsg(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    fd.append("simulator", simulator);
    fd.append("units", units);
    if (timeField) fd.append("time_field", timeField);
    try {
      onImported(await api<Sim>("/api/simulations/import", { method: "POST", body: fd }));
      setMsg("Imported.");
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Import Simulation Result" right={<DataClassTag c="simulated" engine="FARSITE / FlamMap" />}>
      <form onSubmit={submit} className="space-y-2">
        <p className="text-2xs text-dim m-0">Offline FARSITE / FlamMap outputs: arrival-time raster (.tif / .asc+.prj in .zip) or timed perimeters (.zip shapefile / .geojson).</p>
        <input type="file" aria-label="Simulation file" className="text-xs" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <div className="grid grid-cols-3 gap-2">
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
            <option value="arrival_raster">arrival raster</option><option value="perimeters">perimeters</option>
          </select>
          <select className="input" value={simulator} onChange={(e) => setSimulator(e.target.value)} aria-label="Simulator">
            <option>FARSITE</option><option>FlamMap</option><option>other</option>
          </select>
          <select className="input" value={units} onChange={(e) => setUnits(e.target.value)} aria-label="Time units of the export">
            <option value="" disabled>units…</option><option>minutes</option><option>hours</option>
          </select>
        </div>
        {kind === "perimeters" && <input className="input" placeholder="time field name" value={timeField} onChange={(e) => setTimeField(e.target.value)} aria-label="Time field" />}
        {msg && <p className="text-xs m-0">{msg}</p>}
        <p className="text-2xs text-dim m-0">Choose the time units shown in your FARSITE/FlamMap run settings — they are not assumed.</p>
        <button className="btn w-full" disabled={!file || !units || busy || !session}>{session ? "[ Import Result ]" : "Sign in to import"}</button>
      </form>
    </Panel>
  );
}
