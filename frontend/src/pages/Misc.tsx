import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import AlertPanel from "../components/AlertPanel";
import GlobeViewer from "../components/GlobeViewer";
import SystemLogPanel from "../components/SystemLogPanel";
import { DataClassTag, EmptyState, ErrorState, KV, LoadingState, Panel, SeverityTag } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { compass, coord, num, utc } from "../lib/format";
import { type Overlay, useApp } from "../stores/app";
import { useAuth } from "../stores/auth";
import type { Alert, LogEntry } from "../types/api";

/* ------------------------------------------------------------------ Data catalog */
interface CatalogEntry {
  source: string; type: string; status: string; date_range: string; spatial_resolution: string; purpose: string;
  format: string; crs: string; local_path: string; preprocessing: string; data_class: string; notes?: string;
  group: "observed" | "simulated" | "external"; used_in_training: boolean; roles: string[]; role_note?: string | null;
  engine?: string; live?: Record<string, unknown>;
}
interface Catalog {
  generated_utc: string; groups: Record<string, string>; entries: CatalogEntry[];
  software: { name: string; status: string; path: string | null; engines: string[]; note: string }[];
}

const STATUS_OK = ["Available", "Generated", "Imported", "Installed"];

function statusClass(s: string) {
  if (STATUS_OK.includes(s) || s === "Available — processed") return "text-ok";
  if (s.startsWith("Online")) return "text-info";
  if (s.startsWith("Missing")) return "text-crit";
  return "text-warn";
}

export function DataPage() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Catalog>("/api/data/catalog").then(setCat).catch((e) => setError(errorMessage(e))); }, []);
  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      {error && <ErrorState message={error} />}
      {!cat && !error && <LoadingState />}
      {cat && (["observed", "simulated", "external"] as const).map((g) => {
        const rows = cat.entries.filter((e) => e.group === g);
        if (!rows.length) return null;
        return (
          <Panel key={g} title={cat.groups[g] ?? g}
                 right={<span className="text-2xs text-dim">status checked live · metadata extracted {utc(cat.generated_utc)}</span>}>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="text-2xs uppercase tracking-wider text-dim text-left">
                    {["Source", "Type", "Status", "Date range", "Spatial res.", "CRS", "Used in training", "Actual roles", "Class", "Preprocessing"].map((h) => (
                      <th key={h} className="border-b border-line py-1.5 pr-3 font-medium">{h}</th>))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.source} id={e.source.toLowerCase().includes("firms") ? "firms" : undefined} className="border-b border-line/60 align-top">
                      <td className="py-1.5 pr-3 text-head">{e.source}<div className="text-2xs text-dim break-all">{e.local_path}</div></td>
                      <td className="pr-3">{e.type}<div className="text-2xs text-dim">{e.format}</div></td>
                      <td className={`pr-3 ${statusClass(e.status)}`}>
                        {e.status}
                        {e.live && "valid_samples" in e.live && (
                          <div className="text-2xs text-dim">{String(e.live.scenarios)} scenarios · {String(e.live.valid_samples)} valid samples</div>)}
                        {e.live && "expected_location" in e.live && <div className="text-2xs text-dim">expected: {String(e.live.expected_location)}</div>}
                      </td>
                      <td className="pr-3 tabular-nums">{e.date_range}</td>
                      <td className="pr-3">{e.spatial_resolution}</td>
                      <td className="pr-3 text-2xs">{e.crs}</td>
                      <td className={`pr-3 ${e.used_in_training ? "text-ok" : "text-dim"}`}>{e.used_in_training ? "YES" : "NO"}</td>
                      <td className="pr-3 text-2xs">
                        {e.roles.length ? <ul className="m-0 pl-3">{e.roles.map((r) => <li key={r}>{r}</li>)}</ul> : <span className="text-warn">not used by the current pipeline</span>}
                        {e.role_note && <div className="text-dim mt-1">{e.role_note}</div>}
                      </td>
                      <td className="pr-3"><DataClassTag c={e.data_class as "observed"} engine={e.engine} /></td>
                      <td className="pr-3 text-2xs">{e.preprocessing}{e.notes && <div className="text-dim mt-1">{e.notes}</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        );
      })}
      {cat && (
        <Panel title="Installed research software (not data)">
          <dl className="m-0">
            {cat.software.map((s) => (
              <div key={s.name}>
                <KV k={s.name} v={<span className={statusClass(s.status)}>{s.status}{s.path ? ` · ${s.path}` : ""}{s.engines.length ? ` · ${s.engines.join(", ")}` : ""}</span>} />
                <p className="text-2xs text-dim m-0 mt-1">{s.note}</p>
              </div>
            ))}
          </dl>
        </Panel>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Logs */
export function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[] | null>(null);
  const [component, setComponent] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<{ logs: LogEntry[] }>(`/api/logs?limit=500${component ? `&component=${component}` : ""}`)
      .then((r) => setLogs(r.logs)).catch((e) => setError(errorMessage(e)));
  }, [component]);
  return (
    <div className="h-full grid grid-rows-[auto_1fr] p-3 gap-3 min-h-0">
      <div className="flex items-center gap-2">
        <label className="label m-0" htmlFor="comp">Component</label>
        <select id="comp" className="input w-48 h-7" value={component} onChange={(e) => setComponent(e.target.value)}>
          {["", "system", "firms", "weather", "prediction", "simulation", "monitor", "alerts", "auth", "historical"].map((c) => (
            <option key={c} value={c}>{c || "all"}</option>))}
        </select>
      </div>
      <div className="grid lg:grid-cols-2 gap-3 min-h-0">
        <Panel title="Stored log (MongoDB system_logs)" bodyClass="p-0">
          {error && <div className="p-3"><ErrorState message={error} /></div>}
          {!logs && !error && <div className="p-3"><LoadingState /></div>}
          {logs && (logs.length === 0 ? <div className="p-3"><EmptyState message="No log entries." /></div> : (
            <ol className="m-0 p-2 list-none text-2xs leading-[17px]">
              {logs.map((l, i) => (
                <li key={i} className={l.level === "ERROR" ? "text-crit" : l.level === "WARNING" ? "text-warn" : ""}>
                  <span className="text-dim">[{utc(l.ts, true)}]</span> <span className="text-dim">{l.level.padEnd(7)} {l.component.padEnd(10)}</span> {l.message}
                </li>))}
            </ol>))}
        </Panel>
        <SystemLogPanel limit={300} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Active fires list */
export function FiresPage() {
  const fires = useApp((s) => s.fires);
  const selectFire = useApp((s) => s.selectFire);
  const navigate = useNavigate();
  const [onlyDomain, setOnlyDomain] = useState(false);
  const rows = useMemo(() => (fires?.rows ?? []).filter((r) => !onlyDomain || r[7])
    .sort((a, b) => (b[4] ?? 0) - (a[4] ?? 0)).slice(0, 300), [fires, onlyDomain]);
  return (
    <div className="h-full overflow-auto p-3">
      <Panel title="Active Fires (FIRMS, clustered events)" right={<DataClassTag c="observed" />}>
        <label className="flex items-center gap-2 text-xs mb-2"><input type="checkbox" checked={onlyDomain} onChange={(e) => setOnlyDomain(e.target.checked)} /> Only inside model domain</label>
        {!fires ? <LoadingState /> : rows.length === 0 ? <EmptyState message="No FIRMS data available." /> : (
          <table className="w-full text-xs border-collapse tabular-nums">
            <thead><tr className="text-2xs uppercase tracking-wider text-dim text-left">
              {["Event", "Location", "Detections", "FRP sum (MW)", "Last seen", "Status", "Domain"].map((h) => <th key={h} className="border-b border-line py-1.5 pr-3 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r[0]} className="border-b border-line/60 hover:bg-raised cursor-pointer" onClick={() => { selectFire(r[0]); navigate("/"); }}>
                  <td className="py-1 pr-3 text-head"><button className="underline-offset-2 hover:underline">{r[0]}</button></td>
                  <td className="pr-3">{coord(r[1], r[2], 3)}</td>
                  <td className="pr-3">{r[3]}</td>
                  <td className="pr-3">{num(r[4], 1)}</td>
                  <td className="pr-3">{utc(new Date(r[5] * 1000).toISOString())}</td>
                  <td className={`pr-3 ${r[6] === "active" ? "text-fire" : "text-warn"}`}>{r[6]}</td>
                  <td className="pr-3">{r[7] ? <span className="text-info">inside</span> : "—"}</td>
                </tr>))}
            </tbody>
          </table>
        )}
        <p className="text-2xs text-dim mt-2">Showing the top 300 events by FRP. {fires?.meta.note}</p>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ Alerts */
export function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const session = useAuth((s) => s.session);
  const live = useApp((s) => s.alerts);
  useEffect(() => { api<{ alerts: Alert[] }>("/api/alerts?limit=200").then((r) => setAlerts(r.alerts)).catch(() => setAlerts([])); }, [live.length]);
  const [running, setRunning] = useState(false);
  const runMonitor = async () => {
    setRunning(true);
    try { await api("/api/monitor/run", { method: "POST" }); } catch { /* errors surface in the log stream */ }
    setRunning(false);
  };
  const ack = async (id: string) => {
    await api(`/api/alerts/${id}/ack`, { method: "POST" });
    setAlerts((a) => a?.map((x) => (x.alert_id === id ? { ...x, acknowledged: true } : x)) ?? null);
  };
  return (
    <div className="h-full overflow-auto p-3">
      <Panel title="Alerts">
        <div className="flex items-start gap-3 mb-2">
          <p className="text-2xs text-dim m-0 flex-1">Raised by explicit, configurable rules (config/alert_rules.yaml). Decision-support output — not official warnings.
            The monitor refreshes FIRMS + weather automatically; fires predicted in the last 24 h are re-forecast when inputs change.</p>
          {session && <button className="btn" onClick={runMonitor} disabled={running}>{running ? "Refreshing…" : "[ Run refresh now ]"}</button>}
        </div>
        {!alerts ? <LoadingState /> : alerts.length === 0 ? <EmptyState message="No alerts." /> : (
          <ul className="m-0 p-0 list-none space-y-2">
            {alerts.map((a) => (
              <li key={a.alert_id} className={`border border-line p-2 ${a.acknowledged ? "opacity-60" : ""}`}>
                <div className="flex items-center gap-2"><SeverityTag s={a.severity} /><span className="text-head text-xs">[ {a.title} ]</span>
                  <span className="text-2xs text-dim">{a.type} · {a.fire_id ?? "global"}</span>
                  <span className="ml-auto text-2xs text-dim">{utc(a.created_at)}</span>
                  {session && !a.acknowledged && <button className="btn h-6" onClick={() => ack(a.alert_id)}>ack</button>}</div>
                <ul className="m-0 mt-1 p-0 list-none text-xs">{a.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
              </li>))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ Risk assessment */
export function RiskPage() {
  const prediction = useApp((s) => s.prediction);
  const selected = useApp((s) => s.selectedFireId);
  const navigate = useNavigate();
  const ok = (prediction?.steps ?? []).filter((s) => s.status === "ok");
  return (
    <div className="h-full overflow-auto p-3 grid gap-3 lg:grid-cols-[1fr_360px]">
      <Panel title="Risk Assessment — model-derived decision support" right={<DataClassTag c="predicted" />}>
        {!prediction ? (
          <EmptyState message={selected ? "Run a forecast for the selected fire first." : "Select a fire and run a forecast."}
                      hint="Risk factors below are computed only from actual model outputs and observed inputs." />
        ) : (
          <>
            <table className="w-full text-xs border-collapse tabular-nums">
              <thead><tr className="text-2xs uppercase tracking-wider text-dim text-left">
                {["Horizon", "Pred. area km²", "Growth km²", "Spread dir.", "Wind (mean) from", "Wind alignment", "Edge reached"].map((h) => <th key={h} className="border-b border-line py-1.5 pr-3 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {ok.map((s) => {
                  const u = s.weather?.u_mean_ms ?? null, v = s.weather?.v_mean_ms ?? null;
                  const windTo = u != null && v != null ? (Math.atan2(u, v) * 180 / Math.PI + 360) % 360 : null;
                  const windFrom = windTo != null ? (windTo + 180) % 360 : null;
                  const align = windTo != null && s.spread_bearing_deg != null
                    ? Math.cos(((s.spread_bearing_deg - windTo) * Math.PI) / 180) : null;
                  return (
                    <tr key={s.label} className="border-b border-line/60">
                      <td className="py-1 pr-3 text-head">{s.label}</td>
                      <td className="pr-3">{num(s.predicted_area_km2, 2)}</td>
                      <td className="pr-3">{num(s.growth_area_km2, 2)}</td>
                      <td className="pr-3">{s.spread_bearing_deg == null ? "—" : `${num(s.spread_bearing_deg, 0)}° ${compass(s.spread_bearing_deg)}`}</td>
                      <td className="pr-3">{windFrom == null ? "—" : `${compass(windFrom)} ${num(Math.hypot(u!, v!), 1)} m/s`}</td>
                      <td className="pr-3">{align == null ? "—" : `${num(align, 2)} (cos)`}</td>
                      <td className="pr-3">{s.touches_window_edge ? <span className="text-warn">yes</span> : "no"}</td>
                    </tr>);
                })}
              </tbody>
            </table>
            <p className="text-2xs text-dim mt-2">Wind alignment = cosine between the predicted spread direction and the horizon-mean downwind direction (+1 aligned, −1 opposed). No official risk classes are assigned.</p>
          </>
        )}
        <button className="btn mt-3" onClick={() => navigate("/")}>← Dashboard</button>
      </Panel>
      <AlertPanel fireId={selected} limit={10} />
    </div>
  );
}

/* ------------------------------------------------------------------ Settings (read-only view of server configuration) */
export function SettingsPage() {
  const [h, setH] = useState<Record<string, unknown> | null>(null);
  const [m, setM] = useState<{ models: { model_type: string; name: string; trained: boolean; run_id: string | null }[] } | null>(null);
  useEffect(() => {
    api<Record<string, unknown>>("/api/health").then(setH).catch(() => {});
    api<typeof m>("/api/models").then(setM).catch(() => {});
  }, []);
  const region = h?.study_region as { name: string; bbox_wgs84: number[]; analysis_crs: string } | undefined;
  const integ = h?.integrations as Record<string, unknown> | undefined;
  return (
    <div className="h-full overflow-auto p-3 grid gap-3 lg:grid-cols-2">
      <Panel title="Region Settings" className="" >
        <div id="region" />
        {!region ? <LoadingState /> : (
          <dl className="m-0">
            <KV k="Study region" v={region.name} />
            <KV k="BBox (W,S,E,N)" v={region.bbox_wgs84.join(", ")} />
            <KV k="Analysis CRS" v={region.analysis_crs} />
            <KV k="Window" v="128 × 128 cells; 30 m (≤1 h), 60 m (6–12 h), 120 m (24–72 h)" />
          </dl>
        )}
        <p className="text-2xs text-dim">Configured in config/data_sources.yaml and ml/configs/*.yaml (server side).</p>
      </Panel>
      <Panel title="Data Sources / Integrations">
        {!integ ? <LoadingState /> : (
          <dl className="m-0">
            <KV k="FIRMS API key" v={integ.firms_api ? "configured" : "not configured — local NRT files used"} />
            <KV k="Google OAuth" v={integ.google_oauth ? "configured" : "not configured (GOOGLE_CLIENT_ID)"} />
            <KV k="Email provider" v={String(integ.email_provider)} />
            <KV k="Monitor" v={`${integ.monitor ? "on" : "off"} · every ${integ.monitor_interval_s}s`} />
            <KV k="CUDA" v={h?.cuda ? "available" : "not available (CPU inference)"} />
          </dl>
        )}
      </Panel>
      <Panel title="Model Parameters">
        <div id="models" />
        {!m ? <LoadingState /> : (
          <dl className="m-0">{m.models.map((x) => <KV key={x.model_type} k={x.name} v={x.trained ? x.run_id : "not trained"} />)}</dl>
        )}
        <p className="text-2xs text-dim">Hyper-parameters: ml/configs/unet.yaml, fno.yaml, physics_fno.yaml. Alert thresholds: config/alert_rules.yaml.</p>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ Historical */
interface HistFire { hist_id: string; name: string; ignition_date: string; acres: number; area_km2: number; program: string;
  latitude: number; longitude: number; in_model_domain: boolean; era5_available: boolean; replay_available: boolean }
interface HistDetail extends HistFire { perimeter_geojson: object; firms_detections: number; firms_first: string | null;
  firms_last: string | null; detections_by_day: Record<string, number>; validation_note: string;
  mtbs_severity?: { year: number; available: boolean; note: string } }
interface SeverityContext { available: boolean; reason?: string; year?: number; resampling?: string; mapped_fire_in_window?: boolean;
  final_mapped_area_km2?: number; final_severity_area_km2?: Record<string, number>;
  predicted_area_by_final_severity_km2?: Record<string, number>; predicted_outside_final_extent_frac?: number | null;
  final_low_to_high_area_in_forecast_frac?: number | null }
interface ReplayStep { horizon_min: number; label: string; status: string; reason?: string; bounds_wgs84?: [number, number, number, number];
  overlay_url?: string; observed_url?: string; footprint_url?: string; observed_detections?: number;
  metrics_vs_observed?: Record<string, number>; weather?: Record<string, number>; mtbs_severity_context?: SeverityContext }
interface Replay { replay_id: string; t0: string; model: { type: string; version: string }; initial_detections: number; steps: ReplayStep[] }

export function HistoricalPage() {
  const [fires, setFires] = useState<HistFire[] | null>(null);
  const [sel, setSel] = useState<HistDetail | null>(null);
  const [t0, setT0] = useState("");
  const [replay, setReplay] = useState<Replay | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const session = useAuth((s) => s.session);
  const navigate = useNavigate();
  const requestFlyTo = useApp((s) => s.requestFlyTo);
  useEffect(() => { api<{ fires: HistFire[] }>("/api/historical").then((r) => setFires(r.fires)).catch((e) => setError(errorMessage(e))); }, []);
  const open = async (id: string) => {
    setReplay(null); setError(null);
    try {
      const d = await api<HistDetail>(`/api/historical/${id}`);
      setSel(d);
      const days = Object.keys(d.detections_by_day);
      setT0(days.length > 1 ? `${days[1]}T00:00` : `${d.ignition_date}T23:00`);
      requestFlyTo(d.latitude, d.longitude, 60000);
    } catch (e) { setError(errorMessage(e)); }
  };
  const run = async () => {
    if (!sel) return;
    if (!session) return navigate("/login?next=/historical");
    setBusy(true); setError(null);
    try {
      const r = await api<Replay>(`/api/historical/${sel.hist_id}/replay`, { method: "POST", json: { t0 } });
      setReplay(r); setStep(r.steps.findIndex((s) => s.status === "ok"));
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const cur = replay?.steps[step];
  const overlays: Overlay[] = cur?.status === "ok" && cur.bounds_wgs84 ? [
    { id: `hp-${replay!.replay_id}-${cur.label}`, url: cur.overlay_url!, bounds: cur.bounds_wgs84, kind: "prediction" },
    { id: `ho-${replay!.replay_id}-${cur.label}`, url: cur.observed_url!, bounds: cur.bounds_wgs84, kind: "observed" },
    { id: `hf-${replay!.replay_id}-${cur.label}`, url: cur.footprint_url!, bounds: cur.bounds_wgs84, kind: "footprint" },
  ] : [];
  return (
    <div className="h-full overflow-y-auto xl:overflow-hidden grid grid-cols-1 xl:grid-cols-[340px_1fr_360px] min-h-0 gap-px bg-line">
      <div className="overflow-auto bg-bg">
        <Panel title="Historical Wildfires" right={<DataClassTag c="observed" />}>
          {error && <ErrorState message={error} />}
          {!fires ? <LoadingState /> : (
            <ul className="m-0 p-0 list-none">
              {fires.map((f) => (
                <li key={f.hist_id}>
                  <button onClick={() => open(f.hist_id)} className={`w-full text-left px-1 py-1 text-xs border-l-2 ${sel?.hist_id === f.hist_id ? "border-ok bg-raised" : "border-transparent hover:bg-raised"}`}>
                    <span className="text-head">{f.name}</span> <span className="text-dim">{f.ignition_date}</span>
                    <span className="float-right tabular-nums">{Math.round(f.acres).toLocaleString()} ac</span>
                    <div className="text-2xs text-dim">{f.program} · {f.replay_available ? <span className="text-ok">replay available</span> : !f.in_model_domain ? "outside model domain" : "no ERA5 for this date"}</div>
                  </button>
                </li>))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="relative h-[55vh] xl:h-auto min-h-[360px] bg-bg">
        <GlobeViewer overlays={overlays} geojson={sel?.perimeter_geojson ?? null} />
        <div className="absolute top-2 left-2 bg-panel/95 border border-line px-2 py-1 text-2xs text-dim space-y-0.5">
          <div><span className="text-ok">■</span> final burned-area perimeter (observed)</div>
          <div><span className="text-info">□</span> FIRMS footprint at t0 (observed, model input)</div>
          <div><span style={{ color: "rgb(120,220,140)" }}>□</span> FIRMS footprint at t0+h (observed, validation)</div>
          <div><span className="text-fire">■</span> model fire-spread probability (predicted)</div>
        </div>
      </div>
      <div className="overflow-auto bg-bg flex flex-col gap-px">
        <Panel title="Replay & Validation" right={<DataClassTag c="validated" engine="single case vs FIRMS" />}>
          {!sel ? <EmptyState message="Select a historical fire." /> : (
            <>
              <dl className="m-0">
                <KV k="Fire" v={sel.name} />
                <KV k="Ignition" v={sel.ignition_date} />
                <KV k="Final area" v={`${num(sel.area_km2, 1)} km² (${sel.program})`} />
                <KV k="FIRMS dets." v={`${sel.firms_detections} (${utc(sel.firms_first)} → ${utc(sel.firms_last)})`} />
              </dl>
              <p className="text-2xs text-dim">{sel.validation_note}</p>
              {sel.mtbs_severity && <p className="text-2xs text-dim">MTBS {sel.mtbs_severity.year} severity: {sel.mtbs_severity.available ? "processed" : "not available"} — {sel.mtbs_severity.note}</p>}
              {sel.replay_available ? (
                <>
                  <label className="label" htmlFor="t0">t0 (UTC)</label>
                  <input id="t0" type="datetime-local" className="input mb-2" value={t0} onChange={(e) => setT0(e.target.value)} />
                  <button className="btn-primary w-full" onClick={run} disabled={busy}>{busy ? "Running…" : "[ Replay forecast ]"}</button>
                </>
              ) : <p className="text-xs text-warn">Replay unavailable: {sel.in_model_domain ? "ERA5 does not cover this date" : "outside the local data domain"}.</p>}
            </>
          )}
        </Panel>
        {replay && (
          <Panel title={`Validation vs observed — ${replay.model.type}`}>
            <div className="flex gap-1 mb-2 flex-wrap">
              {replay.steps.map((s, i) => (
                <button key={s.label} onClick={() => setStep(i)} disabled={s.status !== "ok"}
                        className={`btn h-6 px-2 ${i === step ? "border-fire text-head" : ""}`}>{s.label}</button>))}
            </div>
            {cur?.status === "ok" && cur.metrics_vs_observed ? (
              <dl className="m-0">
                <KV k="IoU" v={num(cur.metrics_vs_observed.iou, 3)} />
                <KV k="Dice / F1" v={num(cur.metrics_vs_observed.dice, 3)} />
                <KV k="Growth IoU" v={num(cur.metrics_vs_observed.growth_iou, 3)} />
                <KV k="Precision" v={num(cur.metrics_vs_observed.precision, 3)} />
                <KV k="Recall" v={num(cur.metrics_vs_observed.recall, 3)} />
                <KV k="Hausdorff" v={`${num(cur.metrics_vs_observed.hausdorff_m, 0)} m`} />
                <KV k="Area pred/obs" v={`${num(cur.metrics_vs_observed.area_pred_km2, 2)} / ${num(cur.metrics_vs_observed.area_true_km2, 2)} km²`} />
                <KV k="Obs. detections" v={cur.observed_detections} />
                <KV k="ERA5 wx" v={`${num(cur.weather?.temperature_mean_c, 1)} °C · RH ${num(cur.weather?.rh_mean_pct, 0)}% · ${num(cur.weather?.wind_mean_ms, 1)} m/s from ${compass(cur.weather?.wind_from_deg)}`} />
              </dl>
            ) : <p className="text-xs text-warn">{cur?.reason ?? "Forecast unavailable"}</p>}
            <p className="text-2xs text-dim mt-2">Single-case comparison with satellite-pixel footprints; not a statistical validation.</p>
          </Panel>
        )}
        {replay && cur?.status === "ok" && cur.mtbs_severity_context && (
          <Panel title="Post-fire severity context — MTBS" right={<DataClassTag c="observed" />}>
            <SeverityContextView c={cur.mtbs_severity_context} />
          </Panel>
        )}
      </div>
    </div>
  );
}

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)} %`;
}

/** MTBS context: observed post-fire severity — explicitly not a spread metric (no timing in the product). */
function SeverityContextView({ c }: { c: SeverityContext }) {
  if (!c.available) return <p className="text-xs text-warn">{c.reason}</p>;
  if (!c.mapped_fire_in_window) return <p className="text-xs text-dim">No MTBS {c.year} severity mapped for this fire inside the analysis window.</p>;
  const rows = (o?: Record<string, number>) => Object.entries(o ?? {});
  return (
    <>
      <dl className="m-0">
        <KV k="MTBS year" v={`${c.year} · ${c.resampling} resampling`} />
        <KV k="Final mapped area" v={`${num(c.final_mapped_area_km2, 2)} km² (in window)`} />
        <KV k="Pred. beyond final extent" v={pct(c.predicted_outside_final_extent_frac)} />
        <KV k="Final low–high area reached" v={pct(c.final_low_to_high_area_in_forecast_frac)} />
      </dl>
      <div className="label mt-2">Final severity in window (km²)</div>
      <dl className="m-0">{rows(c.final_severity_area_km2).map(([k, v]) => <KV key={k} k={k} v={num(v, 2)} />)}</dl>
      <div className="label mt-2">Predicted area (p ≥ 0.5) by final severity (km²)</div>
      <dl className="m-0">{rows(c.predicted_area_by_final_severity_km2).map(([k, v]) => <KV key={k} k={k} v={num(v, 2)} />)}</dl>
      <p className="text-2xs text-dim mt-2">
        MTBS is a categorical post-fire severity map of the final extent (no timing). It is context, not a spread
        metric: the FIRMS comparison above remains the validation. No mapping from burn probability to severity is made.
      </p>
    </>
  );
}
