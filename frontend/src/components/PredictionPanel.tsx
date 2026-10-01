import { compass, num, utc } from "../lib/format";
import { useApp } from "../stores/app";
import { LABELS, stepAt } from "./ForecastTimeline";
import { DataClassTag, EmptyState, ErrorState, KV, LoadingState, Panel } from "./ui";

export default function PredictionPanel({ running, error }: { running: boolean; error: string | null }) {
  const prediction = useApp((s) => s.prediction);
  const index = useApp((s) => s.timelineIndex);
  const selected = useApp((s) => s.selectedFireId);
  const step = stepAt(prediction?.steps, index);

  return (
    <Panel title="Prediction Summary" right={<DataClassTag c="predicted" />}>
      {running && <LoadingState label="Running WildfireTwin prediction" />}
      {error && <ErrorState message={error} />}
      {!prediction && !running && !error && (
        <EmptyState message={selected ? "Prediction unavailable — not yet run." : "Select a fire to forecast."}
                    hint="Press ANALYZE FIRE to run the trained model for all horizons." />
      )}
      {prediction && (
        <dl className="m-0">
          <KV k="Model" v={`${prediction.model.name}`} />
          <KV k="Version" v={<span className="text-2xs break-all">{prediction.model.version}</span>} />
          <KV k="Dataset" v={prediction.model.dataset_version} />
          <KV k="Created" v={`${utc(prediction.created_at)}${prediction.cached ? " (cached)" : ""}`} />
          <KV k="Trigger" v={`${prediction.trigger}${prediction.cause ? ` — ${prediction.cause}` : ""}`} />
          <div className="rule my-2" />
          <KV k="Horizon" v={<span className="text-head">{LABELS[index]}</span>} />
          {index === 0 && <KV k="State" v="Observed footprint (initialisation)" />}
          {index > 0 && (!step || step.status !== "ok") && (
            <p className="text-xs text-warn m-0 py-1">Forecast unavailable{step?.reason ? `: ${step.reason}` : ""}</p>
          )}
          {step?.status === "ok" && (
            <>
              <KV k="Pred. area" v={<span className="text-fire">{num(step.predicted_area_km2, 2)} km²</span>} />
              <KV k="Initial area" v={`${num(step.initial_area_km2, 2)} km²`} />
              <KV k="Growth" v={`${num(step.growth_area_km2, 2)} km²`} />
              <KV k="Spread dir." v={step.spread_bearing_deg == null ? "—" : `${num(step.spread_bearing_deg, 0)}° ${compass(step.spread_bearing_deg)}`} />
              <KV k="Max dist." v={step.max_spread_distance_km == null ? "—" : `${num(step.max_spread_distance_km, 2)} km`} />
              <KV k="Grid" v={`128×128 @ ${step.cell_m} m`} />
              <KV k="Inference" v={`${num(step.inference_ms, 1)} ms`} />
              {step.weather && (
                <KV k="Wx (mean)" v={<span className="text-2xs">{num(step.weather.temp_mean_c, 1)} °C · RH {num(step.weather.rh_mean_pct, 0)}% · u {num(step.weather.u_mean_ms, 1)} v {num(step.weather.v_mean_ms, 1)} m/s</span>} />
              )}
              {step.touches_window_edge && <p className="text-2xs text-warn m-0 mt-1">Predicted spread reaches the window edge; growth beyond it is not modelled.</p>}
            </>
          )}
          <p className="text-2xs text-dim mt-2 mb-0 leading-relaxed">
            Product: model fire-spread probability (≥ 0.5 counted as burned). {prediction.uncertainty}.
          </p>
        </dl>
      )}
    </Panel>
  );
}
