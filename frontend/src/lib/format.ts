const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

export const dash = "—";

export function num(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return dash;
  return `${v.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

export function coord(lat: number, lon: number, digits = 4): string {
  return `${Math.abs(lat).toFixed(digits)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(digits)}°${lon >= 0 ? "E" : "W"}`;
}

export function compass(deg: number | null | undefined): string {
  if (deg === null || deg === undefined) return dash;
  return COMPASS[Math.floor((((deg % 360) + 360) % 360 + 11.25) / 22.5) % 16];
}

export function utc(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return dash;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = d.toISOString().replace("T", " ");
  return `${withSeconds ? s.slice(0, 19) : s.slice(0, 16)}Z`;
}

export function clock(iso: string): string {
  const d = new Date(iso);
  return d.toISOString().slice(11, 19);
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return dash;
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function horizonLabel(min: number): string {
  return min < 60 ? `${min}m` : `${min / 60}h`;
}
