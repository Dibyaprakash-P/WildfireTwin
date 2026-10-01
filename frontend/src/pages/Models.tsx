import { useEffect, useState } from "react";

import { EmptyState, ErrorState, KV, LoadingState, Panel } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { num, utc } from "../lib/format";
import type { ModelStatus } from "../types/api";

type Metrics = Record<string, number>;
interface ModelResult {
  name: string;
  status: "evaluated" | "not_evaluated";
  run_id?: string;
  n_params?: number;
  overall?: Metrics;
  per_horizon?: Record<string, Metrics>;
  inference_ms?: number;
  inference_ms_cpu?: number;
  inference_device?: string;
  speedup_vs_reference?: number;
  speedup_vs_reference_cpu?: number;
}
interface Compare {
  status: "evaluated" | "not_evaluated";
  generated_utc?: string;
  split_strategy?: string;
  test_samples?: number;
  dataset_version?: string;
  device_name?: string;
  models: Record<string, ModelResult>;
  persistence_baseline?: { name: string; overall: Metrics };
  reference_simulation?: { simulator: string; median_ms: number; samples: number; device: string };
}

const ORDER = ["unet", "fno", "physics_fno"];
const NE = <span className="text-dim">Not evaluated</span>;

function cell(m: ModelResult | undefined, f: (m: ModelResult) => string) {
  return m?.status === "evaluated" ? f(m) : NE;
}

export default function ModelsPage() {
  const [models, setModels] = useState<ModelStatus[] | null>(null);
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState("overall");
  useEffect(() => {
    Promise.all([api<{ models: ModelStatus[] }>("/api/models"), api<Compare>("/api/models/compare")])
      .then(([m, c]) => { setModels(m.models); setCmp(c); })
      .catch((e) => setError(errorMessage(e)));
  }, []);
  const metricsOf = (r?: ModelResult): Metrics | undefined => (horizon === "overall" ? r?.overall : r?.per_horizon?.[horizon]);
  const horizons = cmp?.models ? Object.keys(Object.values(cmp.models).find((m) => m.per_horizon)?.per_horizon ?? {}) : [];

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      {error && <ErrorState message={error} />}
      {!cmp && !error && <LoadingState />}
      {cmp && (
        <Panel title="Model Comparison — held-out test split"
               right={<span className="text-2xs text-dim">{cmp.status === "evaluated" ? `evaluated ${utc(cmp.generated_utc)}` : "Not evaluated"}</span>}>
          {cmp.status === "evaluated" && (
            <div className="text-2xs text-dim mb-2 space-y-0.5">
              <div>Split: {cmp.split_strategy} · test samples: {cmp.test_samples} · dataset: {cmp.dataset_version} · device: {cmp.device_name}</div>
              <div>Targets are WTRS reference simulations (simulated), not observed ground truth. Threshold p ≥ 0.5.</div>
            </div>
          )}
          <div className="flex items-center gap-2 mb-2">
            <label className="label m-0" htmlFor="hz">Horizon</label>
            <select id="hz" className="input w-36 h-7" value={horizon} onChange={(e) => setHorizon(e.target.value)}>
              <option value="overall">all horizons</option>
              {horizons.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse tabular-nums">
              <thead>
                <tr className="text-2xs uppercase tracking-wider text-dim text-left">
                  {["Model", "IoU", "Dice", "Growth IoU", "Growth F1", "Precision", "Recall", "Hausdorff (m)", "HD95 (m)", "MAE", "Inference", "Speed-up"].map((h) => (
                    <th key={h} className="border-b border-line py-1.5 pr-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ORDER.map((t) => {
                  const r = cmp.models[t];
                  const m = metricsOf(r);
                  return (
                    <tr key={t} className="border-b border-line/60">
                      <td className="py-1.5 pr-3 text-head">{r?.name ?? t}</td>
                      {(["iou", "dice", "growth_iou", "growth_f1", "precision", "recall"] as const).map((k) => (
                        <td key={k} className="pr-3">{cell(r, () => num(m?.[k], 3))}</td>
                      ))}
                      <td className="pr-3">{cell(r, () => num(m?.hausdorff_m, 0))}</td>
                      <td className="pr-3">{cell(r, () => num(m?.hd95_m, 0))}</td>
                      <td className="pr-3">{cell(r, () => num(m?.mae, 4))}</td>
                      <td className="pr-3">{cell(r, (x) => `${num(x.inference_ms, 2)} ms (${x.inference_device}) / ${num(x.inference_ms_cpu, 1)} ms cpu`)}</td>
                      <td className="pr-3">{cell(r, (x) => `${num(x.speedup_vs_reference, 0)}× / ${num(x.speedup_vs_reference_cpu, 1)}× cpu`)}</td>
                    </tr>
                  );
                })}
                {cmp.persistence_baseline && horizon === "overall" && (
                  <tr className="text-dim">
                    <td className="py-1.5 pr-3">{cmp.persistence_baseline.name} — reference</td>
                    {(["iou", "dice", "growth_iou", "growth_f1", "precision", "recall"] as const).map((k) => (
                      <td key={k} className="pr-3">{num(cmp.persistence_baseline!.overall[k], 3)}</td>
                    ))}
                    <td className="pr-3">{num(cmp.persistence_baseline.overall.hausdorff_m, 0)}</td>
                    <td className="pr-3">{num(cmp.persistence_baseline.overall.hd95_m, 0)}</td>
                    <td className="pr-3">{num(cmp.persistence_baseline.overall.mae, 4)}</td>
                    <td className="pr-3">—</td><td className="pr-3">—</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {cmp.reference_simulation && (
            <p className="text-2xs text-dim mt-2 mb-0">
              Speed-up = median {cmp.reference_simulation.simulator} re-simulation time ({num(cmp.reference_simulation.median_ms, 1)} ms,
              {" "}{cmp.reference_simulation.device}, n={cmp.reference_simulation.samples}) ÷ median model inference time (batch 1).
              Growth metrics exclude the initial fire given as input.
            </p>
          )}
        </Panel>
      )}
      <div className="grid gap-3 lg:grid-cols-3">
        {!models ? null : models.map((m) => (
          <Panel key={m.model_type} title={m.name}>
            {!m.trained ? <EmptyState message="Not trained." hint={`python -m ml.training.train_${m.model_type}`} /> : (
              <dl className="m-0">
                <KV k="Run" v={<span className="text-2xs break-all">{m.run_id}</span>} />
                <KV k="Checkpoint" v={<span className="text-2xs break-all">{m.checkpoint}</span>} />
                {m.summary && (
                  <>
                    <KV k="Params" v={Number(m.summary.n_params).toLocaleString()} />
                    <KV k="Best epoch" v={`${m.summary.best_epoch} / ${m.summary.epochs_run}`} />
                    <KV k="Val growth IoU" v={num(m.summary.best_val_growth_iou as number, 3)} />
                    <KV k="Train time" v={`${num((m.summary.train_seconds as number) / 60, 1)} min`} />
                    <KV k="Device" v={String(m.summary.device_name)} />
                    <KV k="Samples" v={`${m.summary.train_samples} train / ${m.summary.val_samples} val`} />
                  </>
                )}
              </dl>
            )}
          </Panel>
        ))}
      </div>
      <Panel title="Methodology">
        <ul className="m-0 pl-4 text-xs space-y-1 text-ink/90">
          <li><b className="text-head">U-Net</b> — convolutional encoder–decoder baseline, BCE + Dice loss.</li>
          <li><b className="text-head">FNO</b> — Fourier Neural Operator: spectral convolution layers (truncated Fourier modes) + pointwise linear maps; learns the map from landscape/weather/fire-state fields to the future burned field.</li>
          <li><b className="text-head">Physics-Informed FNO</b> — same backbone predicting fire arrival time; loss = data + λ·(anisotropic eikonal residual with Rothermel/Anderson spread rates + irreversibility + non-burnable fuel constraints).</li>
          <li>Training data: WTRS reference simulations (Rothermel + minimum travel time) on real SRTM/LANDFIRE/WorldCover landscapes driven by ERA5 weather. Spatial-block hold-out split.</li>
        </ul>
      </Panel>
    </div>
  );
}
