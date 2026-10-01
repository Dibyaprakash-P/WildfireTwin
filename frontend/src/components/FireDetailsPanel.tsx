import { Crosshair } from "lucide-react";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../lib/api";
import { coord, num, utc } from "../lib/format";
import { useApp } from "../stores/app";
import type { FireDetail } from "../types/api";
import { DataClassTag, EmptyState, ErrorState, KV, LoadingState, Panel } from "./ui";

export function useFireDetail(id: string | null) {
  const [data, setData] = useState<FireDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!id) return setData(null);
    let off = false;
    setLoading(true);
    setError(null);
    api<FireDetail>(`/api/fires/${id}`)
      .then((d) => !off && setData(d))
      .catch((e) => !off && setError(errorMessage(e)))
      .finally(() => !off && setLoading(false));
    return () => { off = true; };
  }, [id, nonce]);
  return { data, error, loading, retry: () => setNonce((n) => n + 1) };
}

export default function FireDetailsPanel({ onAnalyze, analyzing }: { onAnalyze: () => void; analyzing: boolean }) {
  const id = useApp((s) => s.selectedFireId);
  const fires = useApp((s) => s.fires);
  const firesError = useApp((s) => s.firesError);
  const requestFlyTo = useApp((s) => s.requestFlyTo);
  const { data, error, loading, retry } = useFireDetail(id);

  if (!id) {
    return (
      <Panel title="Fire Event" right={<DataClassTag c="observed" />}>
        {firesError ? <ErrorState message={firesError} /> : !fires ? <LoadingState label="Fetching FIRMS data" /> : (
          <>
            <EmptyState message="No fire selected." hint="Click a fire marker on the globe, or search for a place or FE-ID." />
            <div className="rule my-2" />
            <KV k="Events" v={fires.meta.total_events.toLocaleString()} />
            <KV k="Detections" v={fires.meta.total_detections.toLocaleString()} />
            <KV k="Latest acq." v={utc(fires.meta.latest_acquisition)} />
            <KV k="Window from" v={utc(fires.meta.window_start)} />
            <KV k="Source" v={fires.meta.source} />
            <p className="text-2xs text-dim mt-2 leading-relaxed">{fires.meta.note}</p>
          </>
        )}
      </Panel>
    );
  }
  const ev = data?.event;
  return (
    <Panel title="Fire Event" right={<DataClassTag c="observed" />}>
      {loading && !ev && <LoadingState />}
      {error && <ErrorState message={error} onRetry={retry} />}
      {ev && (
        <>
          <dl className="m-0">
            <KV k="ID" v={<span className="text-head">{ev.event_id}</span>} />
            <KV k="Location" v={coord(ev.latitude, ev.longitude)} />
            <KV k="Latitude" v={ev.latitude.toFixed(5)} />
            <KV k="Longitude" v={ev.longitude.toFixed(5)} />
            <KV k="Satellite" v={ev.satellites.join(", ")} />
            <KV k="Instrument" v={ev.instruments.join(", ")} />
            <KV k="First detect" v={utc(ev.first_seen)} />
            <KV k="Last detect" v={utc(ev.last_seen)} />
            <KV k="Detections" v={`${ev.detection_count} (${ev.high_confidence_count} high conf.)`} />
            <KV k="FRP sum / max" v={`${num(ev.frp_sum_mw, 1)} / ${num(ev.frp_max_mw, 1)} MW`} />
            <KV k="Status" v={<span className={ev.status === "active" ? "text-fire" : "text-warn"}>{ev.status.toUpperCase()}</span>} />
            <KV k="Model domain" v={ev.in_model_domain ? <span className="text-info">INSIDE</span> : <span className="text-dim">OUTSIDE</span>} />
          </dl>
          <p className="text-2xs text-dim mt-2 leading-relaxed">
            Footprint = {ev.footprint_method}. Observed active-fire initialisation, not an official perimeter.
          </p>
          <div className="flex gap-2 mt-3">
            <button className="btn-primary flex-1" onClick={onAnalyze} disabled={analyzing || !ev.in_model_domain}
                    title={ev.in_model_domain ? "Run WildfireTwin forecast" : "Model not trained for this region"}>
              {analyzing ? "Running…" : "[ Analyze Fire ]"}
            </button>
            <button className="btn px-2" aria-label="Zoom to fire" onClick={() => requestFlyTo(ev.latitude, ev.longitude, 15000)}>
              <Crosshair size={13} />
            </button>
          </div>
          {!ev.in_model_domain && (
            <p className="text-2xs text-warn mt-2">Model not trained for this region — local terrain/fuel data cover N. California only.</p>
          )}
        </>
      )}
    </Panel>
  );
}
