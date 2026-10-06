import { describe, expect, it } from "vitest";

import { decodeInt16, parseWindField, sampleWind, type WindGrid } from "../components/globe/wind/windField";
import * as windModule from "../components/globe/wind/windParticles";
import { advect, autoTier, geodeticToEcef, lonInRange, particleBudget, splitDouble } from "../components/globe/wind/windParticles";

/** 4 × 3 grid (lon 0..270 step 90, lat 90..-90 step -90) with u = column index, v = row index. */
function grid(): WindGrid {
  const nx = 4, ny = 3;
  const u = new Float32Array(nx * ny), v = new Float32Array(nx * ny);
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) { u[j * nx + i] = i; v[j * nx + i] = j; }
  return { nx, ny, lon0: 0, lat0: 90, dlon: 90, dlat: -90, u, v,
    meta: { source: "test", provider: "test", dataClass: "model_analysis", cycle: "", validTime: "", fetchedAt: "", maxSpeed: 3, meanSpeed: 1 } };
}

function b64int16(values: number[]): string {
  const bytes = new Uint8Array(values.length * 2);
  values.forEach((x, i) => { const q = x < 0 ? x + 0x10000 : x; bytes[2 * i] = q & 0xff; bytes[2 * i + 1] = q >> 8; });
  return btoa(String.fromCharCode(...bytes));
}

describe("wind field decoding", () => {
  it("decodes little-endian int16 with scale, including negatives", () => {
    const a = decodeInt16(b64int16([0, 150, -275, 32767]), 0.01, 4);
    expect(Array.from(a).map((x) => Math.round(x * 100) / 100)).toEqual([0, 1.5, -2.75, 327.67]);
  });
  it("rejects a payload whose size does not match the grid (never pads or invents values)", () => {
    expect(() => decodeInt16(b64int16([1, 2, 3]), 0.01, 4)).toThrow(/size mismatch/);
  });
  it("parses the backend payload", () => {
    const g = parseWindField({ source: "NOAA GFS", provider: "NOMADS", data_class: "model_analysis", cycle: "2026-10-05T00:00:00Z",
      valid_time: "2026-10-05T00:00:00Z", fetched_at: "x", grid: { nx: 2, ny: 1, lon0: 0, lat0: 0, dlon: 180, dlat: -1 },
      encoding: { dtype: "int16-le", scale: 0.01 }, stats: { max_speed_ms: 1, mean_speed_ms: 1 }, u: b64int16([100, -100]), v: b64int16([0, 50]) });
    expect(g.u[0]).toBeCloseTo(1);
    expect(g.v[1]).toBeCloseTo(0.5);
    expect(g.meta.cycle).toBe("2026-10-05T00:00:00Z");
  });
});

describe("bilinear sampling", () => {
  const g = grid();
  const out = { u: 0, v: 0 };
  it("returns exact grid values at nodes", () => {
    sampleWind(g, 90, 0, out);
    expect(out.u).toBeCloseTo(1);
    expect(out.v).toBeCloseTo(1);
  });
  it("interpolates between nodes", () => {
    sampleWind(g, 45, 45, out);
    expect(out.u).toBeCloseTo(0.5);
    expect(out.v).toBeCloseTo(0.5);
  });
  it("wraps across the antimeridian / 360° seam", () => {
    sampleWind(g, -45, 0, out); // = 315°: halfway between column 3 (u=3) and column 0 (u=0)
    expect(out.u).toBeCloseTo(1.5);
  });
});

describe("particle advection", () => {
  const uniform = (u: number, v: number): WindGrid => ({ ...grid(), u: new Float32Array(12).fill(u), v: new Float32Array(12).fill(v) });
  it("moves with the wind: eastward u increases longitude, northward v increases latitude", () => {
    const p = { lon: 10, lat: 0 };
    const speed = advect(uniform(10, 0), p, 1, 1000, { u: 0, v: 0 });
    expect(speed).toBeCloseTo(10);
    expect(p.lon).toBeGreaterThan(10);
    expect(p.lat).toBeCloseTo(0);
    const q = { lon: 10, lat: 0 };
    advect(uniform(0, -5), q, 1, 1000, { u: 0, v: 0 });
    expect(q.lat).toBeLessThan(0);
  });
  it("displacement equals speed × flow time (metres → degrees)", () => {
    const p = { lon: 0, lat: 0 };
    advect(uniform(0, 11.132), p, 1, 10_000, { u: 0, v: 0 }); // 111.32 km north
    expect(p.lat).toBeCloseTo(1, 5);
  });
  it("wraps longitude and retires particles at the polar caps", () => {
    const p = { lon: 179.9, lat: 0 };
    advect(uniform(20, 0), p, 1, 5000, { u: 0, v: 0 });
    expect(p.lon).toBeLessThan(-179);
    const polar = { lon: 0, lat: 84.99 };
    expect(advect(uniform(0, 20), polar, 1, 5000, { u: 0, v: 0 })).toBe(-1);
  });
});

describe("geometry helpers", () => {
  it("handles view ranges that extend past ±180°", () => {
    expect(lonInRange(-175, 170, 200)).toBe(true);
    expect(lonInRange(175, -200, -170)).toBe(true);
    expect(lonInRange(0, 170, 200)).toBe(false);
  });
  it("converts geodetic to WGS84 ECEF", () => {
    const o = new Float64Array(3);
    geodeticToEcef(0, 0, o, 0);
    expect(o[0]).toBeCloseTo(6378137, 0);
    geodeticToEcef(0, 90, o, 0);
    expect(o[2]).toBeCloseTo(6356752.3, 0);
  });
  it("splits doubles into float32-safe high/low parts that sum back exactly", () => {
    for (const v of [6378137.123, -4510023.987, 0.5, 65536 * 3 + 0.25]) {
      const [h, l] = splitDouble(v);
      expect(Math.abs(h % 65536)).toBe(0);
      expect(Math.abs(l)).toBeLessThan(65536);
      expect(h + l).toBeCloseTo(v, 9);
    }
  });
});

describe("performance budget", () => {
  it("picks tiers from the device and scales particle counts", () => {
    expect(autoTier(500, 800, 8)).toBe("low");
    expect(autoTier(1920, 1080, 8)).toBe("high");
    expect(autoTier(1366, 768, 4)).toBe("medium");
    expect(particleBudget("high", 1).count).toBe(18_000);
    expect(particleBudget("low", 1).count).toBe(4_000);
    expect(particleBudget("low", 0.1).count).toBe(1_500); // floor
    expect(particleBudget("medium", 1).trail).toBeGreaterThan(particleBudget("low", 1).trail);
  });
});

describe("display time scale", () => {
  it("grows with camera height and boosts close zoom levels without exceeding 4x", () => {
    const { displayTimeScale } = windModule;
    expect(displayTimeScale(17_500_000)).toBeGreaterThan(displayTimeScale(2_000_000));
    expect(displayTimeScale(60_000) / 60_000).toBeGreaterThan(displayTimeScale(17_500_000) / 17_500_000);
    expect(displayTimeScale(1_000) / 1_000).toBeCloseTo((displayTimeScale(17_500_000) / 17_500_000) * 4, 6);
  });
});
