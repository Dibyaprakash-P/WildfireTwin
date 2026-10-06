import { api } from "../../../lib/api";

/**
 * Wind-field data interface for the globe's wind-flow layer.
 *
 * The renderer only depends on `WindGrid` + `sampleWind`, never on a specific data source. The current
 * provider reads the backend's NOAA GFS 1° 10 m U/V analysis (/api/wind/field). If the backend cannot supply a
 * field the provider throws and the UI shows "Wind data unavailable" — no wind vector is ever invented.
 */
export interface WindGridMeta {
  source: string;
  provider: string;
  dataClass: string;
  cycle: string;
  validTime: string;
  fetchedAt: string;
  maxSpeed: number;
  meanSpeed: number;
}

export interface WindGrid {
  nx: number;
  ny: number;
  lon0: number;   // longitude of column 0 (deg)
  lat0: number;   // latitude of row 0 (deg)
  dlon: number;
  dlat: number;   // negative when rows run north -> south
  u: Float32Array; // eastward m/s, row-major (row = latitude)
  v: Float32Array; // northward m/s
  meta: WindGridMeta;
}

export interface WindVector { u: number; v: number }

export interface WindFieldProvider {
  readonly id: string;
  /** Fetch the latest available global field. Throws if no real field is available. */
  getWindField(): Promise<WindGrid>;
}

interface WindFieldResponse {
  source: string;
  provider: string;
  data_class: string;
  cycle: string;
  valid_time: string;
  fetched_at: string;
  grid: { nx: number; ny: number; lon0: number; lat0: number; dlon: number; dlat: number };
  encoding: { dtype: string; scale: number };
  stats: { max_speed_ms: number; mean_speed_ms: number };
  u: string;
  v: string;
}

/** Decode a base64 little-endian int16 array scaled by `scale` into float32. */
export function decodeInt16(b64: string, scale: number, expected: number): Float32Array {
  const bin = atob(b64);
  if (bin.length !== expected * 2) throw new Error(`wind grid size mismatch (${bin.length / 2} != ${expected})`);
  const out = new Float32Array(expected);
  for (let i = 0; i < expected; i++) {
    let x = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
    if (x & 0x8000) x -= 0x10000;
    out[i] = x * scale;
  }
  return out;
}

export function parseWindField(r: WindFieldResponse): WindGrid {
  if (r.encoding.dtype !== "int16-le") throw new Error(`unsupported wind encoding ${r.encoding.dtype}`);
  const n = r.grid.nx * r.grid.ny;
  return {
    ...r.grid,
    u: decodeInt16(r.u, r.encoding.scale, n),
    v: decodeInt16(r.v, r.encoding.scale, n),
    meta: { source: r.source, provider: r.provider, dataClass: r.data_class, cycle: r.cycle, validTime: r.valid_time,
      fetchedAt: r.fetched_at, maxSpeed: r.stats.max_speed_ms, meanSpeed: r.stats.mean_speed_ms },
  };
}

/** NOAA GFS 10 m wind served (and cached) by the WildfireTwin backend. */
export class BackendGfsWindProvider implements WindFieldProvider {
  readonly id = "noaa-gfs-1p00";
  async getWindField(): Promise<WindGrid> {
    return parseWindField(await api<WindFieldResponse>("/api/wind/field"));
  }
}

/**
 * Bilinear interpolation of the U/V field at (lon, lat) in degrees, wrapping in longitude.
 * Writes into `out` (no allocation — called for every particle every frame) and returns it.
 */
export function sampleWind(g: WindGrid, lon: number, lat: number, out: WindVector): WindVector {
  let fx = (lon - g.lon0) / g.dlon;
  fx = ((fx % g.nx) + g.nx) % g.nx;
  let fy = (lat - g.lat0) / g.dlat;
  if (fy < 0) fy = 0;
  else if (fy > g.ny - 1) fy = g.ny - 1;
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const x1 = (x0 + 1) % g.nx;
  const y1 = Math.min(y0 + 1, g.ny - 1);
  const tx = fx - x0;
  const ty = fy - y0;
  const i00 = y0 * g.nx + x0, i10 = y0 * g.nx + x1, i01 = y1 * g.nx + x0, i11 = y1 * g.nx + x1;
  const w00 = (1 - tx) * (1 - ty), w10 = tx * (1 - ty), w01 = (1 - tx) * ty, w11 = tx * ty;
  out.u = g.u[i00] * w00 + g.u[i10] * w10 + g.u[i01] * w01 + g.u[i11] * w11;
  out.v = g.v[i00] * w00 + g.v[i10] * w10 + g.v[i01] * w01 + g.v[i11] * w11;
  return out;
}
