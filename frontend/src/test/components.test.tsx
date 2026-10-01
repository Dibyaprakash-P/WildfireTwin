import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AlertPanel from "../components/AlertPanel";
import FireDetailsPanel from "../components/FireDetailsPanel";
import ForecastTimeline, { stepAt } from "../components/ForecastTimeline";
import PredictionPanel from "../components/PredictionPanel";
import { ErrorState } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { compass } from "../lib/format";
import { useApp } from "../stores/app";
import type { Prediction } from "../types/api";

const prediction: Prediction = {
  prediction_id: "PR-TEST", fire_id: "FE-1", data_class: "predicted", product: "Model fire-spread probability",
  model: { type: "fno", name: "FNO", version: "fno:run1", run_id: "run1", checkpoint: "x", dataset_version: "v1", device: "cpu" },
  inputs: {}, uncertainty: "not quantified by this model", total_runtime_ms: 10, limitations: [],
  created_at: "2026-10-01T00:00:00Z", trigger: "user",
  steps: [
    { horizon_min: 10, label: "10m", status: "ok", predicted_area_km2: 0.5, initial_area_km2: 0.4, growth_area_km2: 0.1, cell_m: 30, inference_ms: 3 },
    { horizon_min: 30, label: "30m", status: "unavailable", reason: "Forecast unavailable: test" },
  ],
};

function reset() {
  useApp.setState({ selectedFireId: null, prediction: null, timelineIndex: 0, alerts: [], fires: null, firesError: null });
}

describe("lib", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("maps API errors to ApiError with the backend message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "weather_unavailable", message: "Weather service unavailable." } }), { status: 503 })));
    await expect(api("/api/weather/current")).rejects.toMatchObject({ status: 503, code: "weather_unavailable", message: "Weather service unavailable." });
  });
  it("reports network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api("/api/health")).rejects.toBeInstanceOf(ApiError);
  });
  it("formats compass directions", () => {
    expect(compass(45)).toBe("NE");
    expect(compass(225)).toBe("SW");
    expect(compass(359)).toBe("N");
  });
});

describe("components", () => {
  beforeEach(reset);
  afterEach(() => vi.unstubAllGlobals());

  it("ErrorState renders message and retry", () => {
    const retry = vi.fn();
    render(<ErrorState message="No FIRMS data available." onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No FIRMS data available.");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(retry).toHaveBeenCalled();
  });

  it("FireDetailsPanel shows empty state then loads the selected fire", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      meta: {}, detections: [], detections_truncated: false,
      event: { event_id: "FE-1", status: "active", data_class: "observed", latitude: 41, longitude: -123, bbox: [0, 0, 0, 0],
        detection_count: 3, high_confidence_count: 2, frp_sum_mw: 21, frp_max_mw: 9, first_seen: "2026-09-30T10:00:00Z",
        last_seen: "2026-09-30T10:20:00Z", satellites: ["N20"], instruments: ["VIIRS"], in_model_domain: true, source: "test",
        footprint_method: "clusters" },
    }), { status: 200 })));
    useApp.setState({ firesError: "No FIRMS data available." });
    const { rerender } = render(<MemoryRouter><FireDetailsPanel onAnalyze={() => {}} analyzing={false} /></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("No FIRMS data available.");
    useApp.getState().selectFire("FE-1");
    rerender(<MemoryRouter><FireDetailsPanel onAnalyze={() => {}} analyzing={false} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("FE-1")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /analyze fire/i })).toBeEnabled();
  });

  it("timeline state: selecting a horizon updates the store and unavailable steps are flagged", () => {
    useApp.getState().setPrediction(prediction);
    render(<ForecastTimeline />);
    expect(useApp.getState().timelineIndex).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "30m" }));
    expect(useApp.getState().timelineIndex).toBe(2);
    expect(stepAt(prediction.steps, 2)?.status).toBe("unavailable");
  });

  it("PredictionPanel never shows values for unavailable steps", () => {
    useApp.getState().setPrediction(prediction);
    useApp.getState().setTimelineIndex(2);
    render(<PredictionPanel running={false} error={null} />);
    expect(screen.getByText(/Forecast unavailable/)).toBeInTheDocument();
    useApp.getState().setTimelineIndex(1);
  });

  it("PredictionPanel shows real step values", () => {
    useApp.getState().setPrediction(prediction);
    render(<PredictionPanel running={false} error={null} />);
    expect(screen.getByText("0.50 km²")).toBeInTheDocument();
  });

  it("AlertPanel displays alerts with severity text", () => {
    useApp.setState({ alerts: [{ alert_id: "A1", type: "WEATHER_CHANGE", severity: "HIGH", title: "WEATHER CHANGE",
      lines: ["Wind direction: NE -> SW"], fire_id: "FE-1", prediction_id: null, created_at: "2026-10-01T00:00:00Z",
      acknowledged: false, disclaimer: "" }] });
    render(<AlertPanel fireId="FE-1" />);
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("Wind direction: NE -> SW")).toBeInTheDocument();
  });
});
