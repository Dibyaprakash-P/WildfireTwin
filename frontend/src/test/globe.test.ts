import { describe, expect, it } from "vitest";

import { availableIndices, stepAt } from "../components/ForecastTimeline";
import { reliefAlpha } from "../components/globe/terrain";
import { aggregate, clusterCell } from "../components/globe/useFireVisualization";
import type { ActiveFiresResponse, PredictionStep } from "../types/api";

const steps: PredictionStep[] = [
  { horizon_min: 10, label: "10m", status: "ok" },
  { horizon_min: 30, label: "30m", status: "unavailable", reason: "Forecast unavailable" },
  { horizon_min: 360, label: "6h", status: "ok" },
  { horizon_min: 4320, label: "72h", status: "ok" },
];

describe("forecast frames", () => {
  it("only real model frames (plus NOW) are playable — unavailable and missing horizons are skipped", () => {
    expect(availableIndices(steps)).toEqual([0, 1, 4, 8]);
    expect(availableIndices(undefined)).toEqual([0]);
  });
  it("maps timeline indices to horizons", () => {
    expect(stepAt(steps, 4)?.label).toBe("6h");
    expect(stepAt(steps, 0)).toBeNull();
    expect(stepAt(steps, 6)).toBeNull(); // 24h not in this prediction -> no frame, never synthesised
  });
});

describe("terrain relief", () => {
  it("is invisible from space and strongest at fire-analysis scale", () => {
    expect(reliefAlpha(17_500_000)).toBe(0);
    expect(reliefAlpha(600_000)).toBe(0);
    expect(reliefAlpha(12_000)).toBeCloseTo(0.85);
    expect(reliefAlpha(500)).toBeCloseTo(0.85);
    expect(reliefAlpha(80_000)).toBeGreaterThan(0.2);
    expect(reliefAlpha(80_000)).toBeLessThan(0.85);
  });
});

describe("fire clustering", () => {
  const rows: ActiveFiresResponse["rows"] = [
    ["A", 40.1, -122.1, 3, 10, 0, "active", true],
    ["B", 40.2, -122.2, 1, 5, 0, "recent", true],
    ["C", -10.0, 20.0, 2, null, 0, "recent", false],
  ];
  it("aggregates by zoom-dependent cell and keeps real totals", () => {
    const cl = aggregate(rows, 1);
    expect(cl).toHaveLength(2);
    const ca = cl.find((c) => c.n === 2)!;
    expect(ca.det).toBe(4);
    expect(ca.frp).toBe(15);
    expect(ca.active).toBe(true);
    expect(ca.lat).toBeCloseTo(40.15);
  });
  it("shows individual detections only when zoomed in", () => {
    expect(clusterCell(17_500_000)).toBeGreaterThan(0);
    expect(clusterCell(100_000)).toBe(0);
  });
});
