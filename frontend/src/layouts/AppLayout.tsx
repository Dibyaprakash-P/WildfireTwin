import { LogOut, Menu, Search, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { StatusDot } from "../components/ui";
import { useEventStream, useFires } from "../hooks/useLiveData";
import { api, errorMessage } from "../lib/api";
import { coord } from "../lib/format";
import { useApp } from "../stores/app";
import { useAuth } from "../stores/auth";

const NAV = [
  { n: "01", label: "Dashboard", to: "/" },
  { n: "02", label: "Simulation", to: "/simulation" },
  { n: "03", label: "Data", to: "/data" },
  { n: "04", label: "Models", to: "/models" },
  { n: "05", label: "Logs", to: "/logs" },
];

const SIDEBAR: { title: string; items: { label: string; to: string }[] }[] = [
  { title: "Monitor", items: [
    { label: "Overview", to: "/" }, { label: "Fire Map", to: "/?focus=map" }, { label: "Active Fires", to: "/fires" },
    { label: "Weather Layers", to: "/?focus=weather" }, { label: "FIRMS Data", to: "/data#firms" }, { label: "Alerts", to: "/alerts" },
  ] },
  { title: "Simulation", items: [
    { label: "Run Simulation", to: "/simulation" }, { label: "Configure Inputs", to: "/simulation#inputs" },
    { label: "Results Viewer", to: "/simulation#results" },
  ] },
  { title: "Analysis", items: [
    { label: "Risk Assessment", to: "/risk" }, { label: "Model Comparison", to: "/models" }, { label: "Historical Data", to: "/historical" },
  ] },
  { title: "Settings", items: [
    { label: "Data Sources", to: "/data" }, { label: "Region Settings", to: "/settings#region" }, { label: "Model Parameters", to: "/settings#models" },
  ] },
];

function SearchBox() {
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const requestFlyTo = useApp((s) => s.requestFlyTo);
  const selectFire = useApp((s) => s.selectFire);
  const navigate = useNavigate();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setMsg(null);
    try {
      const r = await api<{ results: { type: string; name: string; latitude: number; longitude: number }[] }>(
        `/api/search?q=${encodeURIComponent(q)}`);
      const hit = r.results[0];
      if (!hit) return setMsg("No match");
      navigate("/");
      if (hit.type === "fire") selectFire(hit.name);
      else requestFlyTo(hit.latitude, hit.longitude, 60000);
      setMsg(hit.name);
    } catch (err) {
      setMsg(errorMessage(err));
    }
  };
  return (
    <form onSubmit={submit} className="relative hidden lg:flex items-center" role="search">
      <Search size={12} className="absolute left-2 text-dim" aria-hidden />
      <input aria-label="Search place, coordinates or fire ID" value={q} onChange={(e) => setQ(e.target.value)}
             placeholder="place · lat,lon · FE-ID" className="input w-56 pl-7 h-7" />
      {msg && <span className="absolute top-8 left-0 text-2xs text-dim bg-panel border border-line px-2 py-1 z-20 whitespace-nowrap">{msg}</span>}
    </form>
  );
}

export default function AppLayout() {
  useFires();
  useEventStream();
  const [drawer, setDrawer] = useState(false);
  const live = useApp((s) => s.live);
  const cursor = useApp((s) => s.cursor);
  const fires = useApp((s) => s.fires);
  const session = useAuth((s) => s.session);
  const logout = useAuth((s) => s.logout);
  const loc = useLocation();

  return (
    <div className="h-full grid grid-rows-[auto_1fr] min-h-0">
      <header className="border-b border-line bg-panel flex items-center gap-4 px-3 h-12 min-w-0">
        <button className="btn h-7 px-2 md:hidden" aria-label="Open navigation" onClick={() => setDrawer(true)}><Menu size={14} /></button>
        <Link to="/" className="flex flex-col leading-none no-underline shrink-0">
          <span className="text-head font-bold tracking-[0.18em] text-[13px]">WILDFIRETWIN</span>
          <span className="text-2xs text-dim tracking-wider mt-1 hidden sm:block">AI-Driven Wildfire Spread Prediction</span>
        </Link>
        <nav aria-label="Primary" className="hidden md:flex items-center gap-1 ml-4">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => `px-2 h-7 inline-flex items-center text-xs uppercase tracking-wider border ${
                isActive ? "border-fire/60 text-head" : "border-transparent text-dim hover:text-ink"}`}>
              <span className="text-fire/80 mr-1.5">[{n.n}]</span>{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4 text-2xs text-dim min-w-0">
          <SearchBox />
          <StatusDot state={live ? "ok" : "warn"} label={live ? "LIVE" : "OFFLINE"} />
          <span className="hidden xl:inline" title="Source of the fire layer">
            FIRMS: <span className="text-ink">{fires?.meta.source ?? "—"}</span>
          </span>
          <span className="hidden lg:inline tabular-nums w-44" aria-live="off">
            {cursor ? coord(cursor.lat, cursor.lon, 3) : "LAT/LON —"}
          </span>
          {session ? (
            <span className="flex items-center gap-2">
              <span className="hidden sm:inline text-ink truncate max-w-40" title={session.user.email}>{session.user.email}</span>
              <button className="btn h-7 px-2" onClick={logout} aria-label="Sign out" title="Sign out"><LogOut size={12} /></button>
            </span>
          ) : (
            <Link to={`/login?next=${encodeURIComponent(loc.pathname)}`} className="btn h-7">Sign in</Link>
          )}
        </div>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-[176px_1fr] min-h-0">
        <aside className={`${drawer ? "fixed inset-0 z-40 bg-bg/95 p-4" : "hidden"} md:block md:static md:p-0 border-r border-line bg-panel overflow-auto`}
               aria-label="Sections">
          {drawer && <button className="btn mb-3 md:hidden" onClick={() => setDrawer(false)} aria-label="Close navigation"><X size={14} /></button>}
          {SIDEBAR.map((g) => (
            <div key={g.title} className="py-2">
              <div className="px-3 pb-1 text-2xs uppercase tracking-[0.16em] text-dim/80">{g.title}</div>
              <ul className="m-0 p-0 list-none">
                {g.items.map((it) => {
                  const active = loc.pathname + loc.search + loc.hash === it.to || (it.to === "/" && loc.pathname === "/" && !loc.search);
                  return (
                    <li key={it.label}>
                      <Link to={it.to} onClick={() => setDrawer(false)}
                        className={`block px-3 py-[5px] text-xs border-l-2 ${active ? "border-fire text-head bg-raised" : "border-transparent text-ink/80 hover:text-head hover:bg-raised/60"}`}>
                        {it.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          <div className="px-3 py-3 text-2xs text-dim/80 border-t border-line leading-relaxed">
            Decision-support research prototype. Not an emergency warning system.
          </div>
        </aside>
        <main className="min-h-0 min-w-0 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
