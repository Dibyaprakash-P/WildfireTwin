import { useCallback, useEffect } from "react";

import { api, apiUrl, errorMessage } from "../lib/api";
import { useApp } from "../stores/app";
import type { ActiveFiresResponse, Alert, LogEntry } from "../types/api";

/** Loads the global fire layer once and refreshes it when the backend reports new FIRMS data. */
export function useFires() {
  const setFires = useApp((s) => s.setFires);
  const load = useCallback(async () => {
    try {
      setFires(await api<ActiveFiresResponse>("/api/fires/active"));
    } catch (e) {
      setFires(null, errorMessage(e));
    }
  }, [setFires]);
  useEffect(() => {
    if (!useApp.getState().fires) void load();
  }, [load]);
  return load;
}

/** Initial logs + alerts, then live updates over Server-Sent Events. */
export function useEventStream() {
  const { pushLog, pushAlert, setLogs, setAlerts, setLive } = useApp.getState();
  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    api<{ logs: LogEntry[] }>("/api/logs?limit=150").then((r) => !cancelled && setLogs(r.logs)).catch(() => {});
    api<{ alerts: Alert[] }>("/api/alerts?limit=50").then((r) => !cancelled && setAlerts(r.alerts)).catch(() => {});
    try {
      es = new EventSource(apiUrl("/api/events/stream"));
      es.onopen = () => setLive(true);
      es.onerror = () => setLive(false);
      es.addEventListener("log", (e) => pushLog(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("alert", (e) => pushAlert(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("fires", () => {
        api<ActiveFiresResponse>("/api/fires/active").then((f) => useApp.getState().setFires(f)).catch(() => {});
      });
      es.addEventListener("prediction", (e) => {
        const p = JSON.parse((e as MessageEvent).data) as { prediction_id: string; fire_id: string; trigger: string };
        const st = useApp.getState();
        if (p.trigger !== "user" && st.selectedFireId === p.fire_id) {
          api<import("../types/api").Prediction>(`/api/predictions/${p.prediction_id}`)
            .then((pred) => useApp.getState().setPrediction(pred))
            .catch(() => {});
        }
      });
    } catch {
      setLive(false);
    }
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [pushAlert, pushLog, setAlerts, setLive, setLogs]);
}
