import { useEffect, useState } from "react";

import { api, errorMessage } from "../lib/api";
import { useApp } from "../stores/app";
import { compass, num, utc } from "../lib/format";
import type { EnvironmentResponse, Valued } from "../types/api";
import { DataClassTag, ErrorState, KV, LoadingState, Panel } from "./ui";

function Src({ v }: { v: Valued<unknown> }) {
  return <span className="text-dim text-2xs" title={`${v.source}${v.timestamp ? ` · ${v.timestamp}` : ""}`}> [{v.units}]</span>;
}

export function useEnvironment(id: string | null) {
  const [data, setData] = useState<EnvironmentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!id) return setData(null);
    let off = false;
    setData(null);
    setError(null);
    api<EnvironmentResponse>(`/api/environment/${id}`)
      .then((d) => {
        if (off) return;
        setData(d);
        const v = d.weather?.current.values;
        if (v && v.wind_speed_10m != null && v.wind_direction_10m != null) {
          useApp.getState().setWind({ lat: d.latitude, lon: d.longitude, speed: v.wind_speed_10m, fromDeg: v.wind_direction_10m,
            time: d.weather!.current.time, source: d.weather!.source });
        }
      })
      .catch((e) => !off && setError(errorMessage(e)));
    return () => { off = true; };
  }, [id, nonce]);
  return { data, error, retry: () => setNonce((n) => n + 1) };
}

export default function EnvironmentPanel({ fireId }: { fireId: string | null }) {
  const { data, error, retry } = useEnvironment(fireId);
  if (!fireId) return null;
  return (
    <Panel title="Current Conditions" right={<DataClassTag c="observed" />}>
      {error && <ErrorState message={error} onRetry={retry} />}
      {!data && !error && <LoadingState label="Loading environment" />}
      {data && (
        <div className="space-y-3">
          <section aria-label="Weather">
            <div className="text-2xs uppercase tracking-[0.14em] text-info mb-1">Weather</div>
            {data.weather ? (() => {
              const c = data.weather.current;
              const u = c.units;
              const s24 = data.weather.summary["24h"];
              return (
                <dl className="m-0">
                  <KV k="Temperature" v={`${num(c.values.temperature_2m, 1)} ${u.temperature_2m ?? ""}`} />
                  <KV k="Rel. humidity" v={`${num(c.values.relative_humidity_2m, 0)} ${u.relative_humidity_2m ?? ""}`} />
                  <KV k="Wind" v={`${num(c.values.wind_speed_10m, 1)} ${u.wind_speed_10m ?? ""} from ${compass(c.values.wind_direction_10m)} (${num(c.values.wind_direction_10m, 0)}°)`} />
                  <KV k="Gusts" v={`${num(c.values.wind_gusts_10m, 1)} ${u.wind_gusts_10m ?? ""}`} />
                  <KV k="Precipitation" v={`${num(c.values.precipitation, 1)} ${u.precipitation ?? ""}`} />
                  {s24 && <KV k="Next 24h mean" v={`${num(s24.temperature_2m, 1)} °C · RH ${num(s24.relative_humidity_2m, 0)}% · ${num(s24.wind_speed_10m, 1)} m/s · ${num(s24.precipitation_sum, 1)} mm`} />}
                  <KV k="Valid" v={utc(c.time)} />
                  <KV k="Source" v={<span className="text-2xs">{data.weather.source}</span>} />
                </dl>
              );
            })() : <ErrorState message={data.weather_error ?? "Weather service unavailable."} onRetry={retry} />}
          </section>
          <section aria-label="Terrain and fuel">
            <div className="text-2xs uppercase tracking-[0.14em] text-info mb-1">Terrain · Fuel · Land</div>
            {data.local.available ? (
              <dl className="m-0">
                <KV k="Elevation" v={<>{num(data.local.terrain.elevation.value as number, 0)}<Src v={data.local.terrain.elevation} /></>} />
                <KV k="Slope" v={<>{num(data.local.terrain.slope.value as number, 1)}<Src v={data.local.terrain.slope} /> · mean {num(data.local.terrain.slope_mean.value as number, 1)}</>} />
                <KV k="Aspect" v={<>{data.local.terrain.aspect.value === null ? "flat" : `${num(data.local.terrain.aspect.value as number, 0)}° ${compass(data.local.terrain.aspect.value as number)}`}<Src v={data.local.terrain.aspect} /></>} />
                <KV k="Fuel model" v={<>{data.local.fuel.fuel_model.value}<Src v={data.local.fuel.fuel_model} /></>} />
                <KV k="Burnable" v={`${num((data.local.fuel.burnable_fraction.value as number) * 100, 0)}% of ${(data.local.window_m / 1000).toFixed(1)} km window`} />
                <KV k="Land cover" v={<>{data.local.land_cover.class.value ?? "n/a"}<Src v={data.local.land_cover.class} /></>} />
                <KV k="Fuel mix" v={<span className="text-2xs">{data.local.fuel.composition.value.slice(0, 3).map((f) => `${f.name} ${(f.fraction * 100).toFixed(0)}%`).join(" · ")}</span>} />
              </dl>
            ) : <p className="text-xs text-warn m-0">{data.local.reason}</p>}
          </section>
          <section aria-label="Fire activity">
            <div className="text-2xs uppercase tracking-[0.14em] text-info mb-1">Fire</div>
            <dl className="m-0">
              <KV k="Active detections" v={data.fire.active_fire_count} />
              <KV k="FRP sum" v={`${num(data.fire.frp_sum_mw, 1)} MW`} />
              <KV k="Latest obs." v={utc(data.fire.latest_observation)} />
              <KV k="By day" v={<span className="text-2xs">{Object.entries(data.fire.detections_by_day).map(([d, n]) => `${d.slice(5)}:${n}`).join(" ")}</span>} />
            </dl>
          </section>
        </div>
      )}
    </Panel>
  );
}
