import * as Cesium from "cesium";

import { sampleWind, type WindGrid, type WindVector } from "./windField";

/**
 * GPU wind-flow particles drawn over the Cesium globe.
 *
 * Architecture
 *  - A separate, transparent WebGL canvas sits over the Cesium canvas (pointer-events: none) and is redrawn in
 *    its own requestAnimationFrame loop. Cesium keeps requestRenderMode (an idle globe costs no GPU time);
 *    the overlay reads the live camera matrices each frame, so it follows rotation/zoom exactly.
 *  - Particle state (lon, lat, age, lifetime) lives in typed arrays. Each frame every particle is advected by
 *    the bilinearly interpolated real U/V field (windField.ts) — no random or synthetic motion. Particles are
 *    (re)spawned uniformly over the visible part of the globe and respawn when they age out or leave the view.
 *  - Trails: one line segment (previous → new position) per particle per frame is written into a ring of
 *    TRAIL slots (slot-major layout, so one bufferSubData per tick). The simulation runs at a fixed 30 Hz tick
 *    (trail length is a fixed time span on every device); each vertex stores its birth tick and the vertex
 *    shader fades segments by age, so trails are real past positions that fade out.
 *  - Precision: positions are ECEF metres split into high/low float pairs and rendered relative to the
 *    camera (as Cesium does), so trails stay stable at fire-analysis zoom levels. Segments on the far side of
 *    the globe are culled in the vertex shader (horizon test).
 *  - Colour encodes speed with a restrained scale (calm grey-blue → cyan → pale yellow → orange); opacity is
 *    kept low so observed fires and the AI prediction stay visually dominant.
 *  - Performance: no per-particle DOM/React objects, no buffer re-creation per frame, adaptive particle count
 *    ("auto" drops density when the frame rate stays low), loop paused while the tab is hidden, and all GL
 *    resources are released by destroy().
 *
 * Particle on-screen speed: the field is advected in an accelerated time scale proportional to the camera
 * height (like standard wind-flow maps), so flow is readable at every zoom; the *direction* and *relative
 * speed* are the real field values, the absolute animation speed is a display setting.
 */

export type WindPerformance = "auto" | "high" | "medium" | "low";

export interface WindRenderSettings {
  opacity: number;        // 0..1
  density: number;        // multiplier on the performance budget (0.25..1.5)
  speed: number;          // animation speed multiplier (0.25..3)
  performance: WindPerformance;
}

const TRAIL: Record<Exclude<WindPerformance, "auto">, number> = { high: 14, medium: 12, low: 9 }; // slots of TICK_S
const BASE_COUNT: Record<Exclude<WindPerformance, "auto">, number> = { high: 18_000, medium: 10_000, low: 4_000 };
const MIN_COUNT = 1_500;
const FLOATS_PER_VERTEX = 9; // high xyz, low xyz, birth frame, life alpha, speed
const WGS84_A = 6378137.0;
const WGS84_E2 = 6.69437999014e-3;
const DEG = Math.PI / 180;
const DISPLAY_TIME_FACTOR = 0.0055; // seconds of "flow time" per real second, per metre of camera height
const TICK_S = 1 / 30;              // fixed simulation step: trail length is time-based, independent of frame rate
const MAX_TICKS_PER_FRAME = 3;

/** Resolve the performance tier for "auto" from the device (screen size, cores). */
export function autoTier(width: number, height: number, cores: number): Exclude<WindPerformance, "auto"> {
  if (width < 768 || cores <= 2) return "low";
  if (width * height >= 1_600_000 && cores >= 8) return "high";
  return "medium";
}

export function particleBudget(tier: Exclude<WindPerformance, "auto">, density: number): { count: number; trail: number } {
  return { count: Math.max(MIN_COUNT, Math.round(BASE_COUNT[tier] * density)), trail: TRAIL[tier] };
}

/** WGS84 geodetic (deg, height 0) → ECEF metres. Allocation-free variant writes into `out` at `o`. */
export function geodeticToEcef(lonDeg: number, latDeg: number, out: Float64Array, o: number): void {
  const lon = lonDeg * DEG, lat = latDeg * DEG;
  const sl = Math.sin(lat), cl = Math.cos(lat);
  const n = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
  out[o] = n * cl * Math.cos(lon);
  out[o + 1] = n * cl * Math.sin(lon);
  out[o + 2] = n * (1 - WGS84_E2) * sl;
}

/** Split a double into a float32-friendly high part (multiple of 65536) and a small low remainder. */
export function splitDouble(v: number): [number, number] {
  const high = v >= 0 ? Math.floor(v / 65536) * 65536 : -Math.floor(-v / 65536) * 65536;
  return [high, v - high];
}

/**
 * Seconds of flow time per real second at camera height `h` (m). Proportional to height so on-screen motion
 * is similar at every zoom, with a gentle boost (≤ 4×) below ~2,000 km so calm local winds stay readable.
 * Display setting only: directions and relative speeds remain the real field values.
 */
export function displayTimeScale(h: number): number {
  const boost = Math.min(4, Math.max(1, (2_000_000 / h) ** 0.35));
  return h * DISPLAY_TIME_FACTOR * boost;
}

/** Is `lon` (−180..180) inside [w, e], where the range may extend past ±180 (antimeridian / padding)? */
export function lonInRange(lon: number, w: number, e: number): boolean {
  return (lon >= w && lon <= e) || (lon + 360 >= w && lon + 360 <= e) || (lon - 360 >= w && lon - 360 <= e);
}

/**
 * Move one particle along the real field (bilinear U/V). Returns the local wind speed (m/s), or -1 if the
 * particle should respawn (non-finite data or polar cap). `flowTimeScale` = seconds of flow time per real
 * second for the current zoom/speed setting.
 */
export function advect(g: WindGrid, pos: { lon: number; lat: number }, dtSec: number, flowTimeScale: number, tmp: WindVector): number {
  sampleWind(g, pos.lon, pos.lat, tmp);
  const speed = Math.hypot(tmp.u, tmp.v);
  if (!Number.isFinite(speed)) return -1;
  const t = dtSec * flowTimeScale; // seconds of flow time
  const cosLat = Math.max(0.05, Math.cos(pos.lat * DEG));
  pos.lat += (tmp.v * t) / 111_320;
  pos.lon += (tmp.u * t) / (111_320 * cosLat);
  if (pos.lon > 180) pos.lon -= 360;
  else if (pos.lon < -180) pos.lon += 360;
  if (pos.lat > 85 || pos.lat < -85) return -1;
  return speed;
}

const VS = `
attribute vec3 a_high;
attribute vec3 a_low;
attribute vec3 a_info;      // x = birth frame, y = life alpha (fade in/out), z = wind speed m/s
uniform mat4 u_viewProj;    // projection * view rotation (camera at origin)
uniform vec3 u_camHigh;
uniform vec3 u_camLow;
uniform vec3 u_cam;         // camera ECEF (float approximation, horizon test only)
uniform float u_frame;
uniform float u_trail;
varying float v_alpha;
varying float v_speed;
void main() {
  vec3 r = (a_high - u_camHigh) + (a_low - u_camLow);   // camera-relative position, precise
  vec3 p = r + u_cam;                                    // ECEF (approximate)
  float visible = step(dot(p, r), 0.0);                  // point faces the camera: dot(P, C - P) > 0
  float age = u_frame - a_info.x;
  float fade = clamp(1.0 - age / u_trail, 0.0, 1.0);
  v_alpha = visible * fade * a_info.y;
  v_speed = a_info.z;
  gl_Position = u_viewProj * vec4(r, 1.0);
}`;

const FS = `
precision mediump float;
varying float v_alpha;
varying float v_speed;
uniform float u_opacity;
vec3 speedColor(float s) {
  vec3 calm = vec3(0.62, 0.70, 0.80);   // < ~3 m/s  grey-blue
  vec3 mod_ = vec3(0.35, 0.74, 0.88);   // ~8 m/s    cyan
  vec3 fresh = vec3(0.96, 0.88, 0.52);  // ~14 m/s   pale yellow
  vec3 strong = vec3(1.00, 0.60, 0.28); // >= 20 m/s orange
  if (s < 8.0) return mix(calm, mod_, smoothstep(2.0, 8.0, s));
  if (s < 14.0) return mix(mod_, fresh, (s - 8.0) / 6.0);
  return mix(fresh, strong, clamp((s - 14.0) / 6.0, 0.0, 1.0));
}
void main() {
  float a = v_alpha * u_opacity;
  if (a < 0.004) discard;
  gl_FragColor = vec4(speedColor(v_speed) * a, a);   // premultiplied alpha
}`;

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type);
  if (!s) throw new Error("WebGL shader allocation failed");
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(`wind shader: ${gl.getShaderInfoLog(s)}`);
  return s;
}

export class WindParticleRenderer {
  private readonly viewer: Cesium.Viewer;
  private readonly canvas: HTMLCanvasElement;
  private readonly gl: WebGLRenderingContext;
  private readonly program: WebGLProgram;
  private readonly shaders: WebGLShader[];
  private readonly loc: Record<string, WebGLUniformLocation | null>;
  private readonly attr: { high: number; low: number; info: number };
  private buffer: WebGLBuffer | null = null;
  private grid: WindGrid | null;
  private settings: WindRenderSettings;
  private tier: Exclude<WindPerformance, "auto">;
  private autoScale = 1;           // reduced by the adaptive controller in "auto" mode

  private count = 0;
  private trail = 0;
  private lon = new Float64Array(0);
  private lat = new Float64Array(0);
  private age = new Float32Array(0);
  private life = new Float32Array(0);
  private prev = new Float64Array(0); // previous ECEF xyz per particle
  private slot = new Float32Array(0);  // scratch for one trail slot (count × 2 vertices)
  private frame = 1;
  private acc = 0;

  private raf = 0;
  private lastT = 0;
  private slowFrames = 0;
  private fastFrames = 0;
  private spawn: { w: number; s: number; e: number; n: number } | null = null;
  private readonly removeCamListener: () => void;
  private readonly tmp: WindVector = { u: 0, v: 0 };
  private readonly pos = { lon: 0, lat: 0 };
  private readonly ecef = new Float64Array(3);
  private readonly viewProj = new Float32Array(16);
  private readonly viewScratch = new Cesium.Matrix4();
  private readonly vpScratch = new Cesium.Matrix4();
  private destroyed = false;

  constructor(viewer: Cesium.Viewer, grid: WindGrid | null, settings: WindRenderSettings) {
    this.viewer = viewer;
    this.grid = grid;
    this.settings = settings;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "wt-wind-canvas";
    this.canvas.setAttribute("aria-hidden", "true");
    Object.assign(this.canvas.style, { position: "absolute", inset: "0", width: "100%", height: "100%", pointerEvents: "none", zIndex: "1" });
    viewer.container.appendChild(this.canvas);
    const gl = this.canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: true, depth: false, stencil: false });
    if (!gl) {
      this.canvas.remove();
      throw new Error("WebGL unavailable for wind particles");
    }
    this.gl = gl;
    const vs = compile(gl, gl.VERTEX_SHADER, VS);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FS);
    const prog = gl.createProgram();
    if (!prog) throw new Error("WebGL program allocation failed");
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(`wind program: ${gl.getProgramInfoLog(prog)}`);
    this.program = prog;
    this.shaders = [vs, fs];
    this.loc = Object.fromEntries(["u_viewProj", "u_camHigh", "u_camLow", "u_cam", "u_frame", "u_trail", "u_opacity"]
      .map((n) => [n, gl.getUniformLocation(prog, n)]));
    this.attr = { high: gl.getAttribLocation(prog, "a_high"), low: gl.getAttribLocation(prog, "a_low"), info: gl.getAttribLocation(prog, "a_info") };

    this.tier = this.resolveTier();
    this.allocate();
    this.updateSpawnRegion();
    let lastCam = 0;
    this.removeCamListener = viewer.camera.changed.addEventListener(() => {
      const now = performance.now();
      if (now - lastCam > 150) { lastCam = now; this.updateSpawnRegion(); }
    });
    viewer.camera.percentageChanged = Math.min(viewer.camera.percentageChanged, 0.15);
    this.raf = requestAnimationFrame(this.loop);
  }

  setGrid(grid: WindGrid | null): void {
    this.grid = grid;
    this.resetParticles();
  }

  setSettings(s: WindRenderSettings): void {
    const prevTier = this.tier, prevDensity = this.settings.density;
    this.settings = s;
    if (s.performance !== "auto") this.autoScale = 1;
    this.tier = this.resolveTier();
    if (this.tier !== prevTier || s.density !== prevDensity) this.allocate();
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this.removeCamListener();
    const gl = this.gl;
    if (this.buffer) gl.deleteBuffer(this.buffer);
    for (const sh of this.shaders) gl.deleteShader(sh);
    gl.deleteProgram(this.program);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    this.canvas.remove();
  }

  // ------------------------------------------------------------------ internals
  private resolveTier(): Exclude<WindPerformance, "auto"> {
    if (this.settings.performance !== "auto") return this.settings.performance;
    return autoTier(window.innerWidth, window.innerHeight, navigator.hardwareConcurrency || 4);
  }

  private allocate(): void {
    const { count, trail } = particleBudget(this.tier, this.settings.density * this.autoScale);
    this.count = count;
    this.trail = trail;
    this.lon = new Float64Array(count);
    this.lat = new Float64Array(count);
    this.age = new Float32Array(count);
    this.life = new Float32Array(count);
    this.prev = new Float64Array(count * 3);
    this.slot = new Float32Array(count * 2 * FLOATS_PER_VERTEX);
    const gl = this.gl;
    if (this.buffer) gl.deleteBuffer(this.buffer);
    this.buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    // birth frame -1e9 everywhere → every slot fully faded until written
    const init = new Float32Array(trail * count * 2 * FLOATS_PER_VERTEX);
    for (let i = 6; i < init.length; i += FLOATS_PER_VERTEX) init[i] = -1e9;
    gl.bufferData(gl.ARRAY_BUFFER, init, gl.DYNAMIC_DRAW);
    this.frame = 1;
    this.resetParticles();
  }

  private resetParticles(): void {
    for (let i = 0; i < this.count; i++) this.respawn(i, true);
  }

  private updateSpawnRegion(): void {
    if (this.destroyed || this.viewer.isDestroyed()) return;
    const r = this.viewer.camera.computeViewRectangle(this.viewer.scene.globe.ellipsoid);
    if (!r) { this.spawn = null; return; }
    let w = r.west / DEG, e = r.east / DEG;
    if (e < w) e += 360; // crosses the antimeridian
    const pad = Math.max(1, (e - w) * 0.05);
    this.spawn = { w: w - pad, e: e + pad, s: Math.max(-85, r.south / DEG - pad), n: Math.min(85, r.north / DEG + pad) };
    if (e - w > 300) this.spawn = null;
  }

  private facesCamera(x: number, y: number, z: number): boolean {
    const c = this.viewer.camera.positionWC;
    return x * (c.x - x) + y * (c.y - y) + z * (c.z - z) > 0;
  }

  private respawn(i: number, randomAge: boolean): void {
    const sp = this.spawn;
    let lon = 0, lat = 0;
    for (let tries = 0; tries < 8; tries++) {
      if (sp) {
        const s = Math.sin(sp.s * DEG), n = Math.sin(sp.n * DEG);
        lat = Math.asin(s + Math.random() * (n - s)) / DEG;   // area-uniform in latitude
        lon = sp.w + Math.random() * (sp.e - sp.w);
      } else {
        lat = Math.asin(2 * Math.random() - 1) / DEG;
        lon = Math.random() * 360 - 180;
      }
      if (lon > 180) lon -= 360;
      geodeticToEcef(lon, lat, this.ecef, 0);
      if (this.facesCamera(this.ecef[0], this.ecef[1], this.ecef[2])) break;
    }
    this.lon[i] = lon;
    this.lat[i] = Math.max(-84.9, Math.min(84.9, lat));
    const life = 50 + Math.random() * 90; // ticks (≈1.7–4.7 s)
    this.life[i] = life;
    this.age[i] = randomAge ? Math.random() * life : 0;
    this.prev[3 * i] = this.ecef[0];
    this.prev[3 * i + 1] = this.ecef[1];
    this.prev[3 * i + 2] = this.ecef[2];
  }

  private writeVertex(o: number, x: number, y: number, z: number, birth: number, lifeA: number, speed: number): void {
    const b = this.slot;
    // inline splitDouble (hot path: no tuple allocations)
    const hx = x >= 0 ? Math.floor(x / 65536) * 65536 : -Math.floor(-x / 65536) * 65536;
    const hy = y >= 0 ? Math.floor(y / 65536) * 65536 : -Math.floor(-y / 65536) * 65536;
    const hz = z >= 0 ? Math.floor(z / 65536) * 65536 : -Math.floor(-z / 65536) * 65536;
    b[o] = hx; b[o + 1] = hy; b[o + 2] = hz;
    b[o + 3] = x - hx; b[o + 4] = y - hy; b[o + 5] = z - hz;
    b[o + 6] = birth; b[o + 7] = lifeA; b[o + 8] = speed;
  }

  private step(dtSec: number): void {
    const g = this.grid;
    const h = Math.max(800, this.viewer.camera.positionCartographic.height);
    const flowScale = displayTimeScale(h) * this.settings.speed;
    const birth = this.frame;
    for (let i = 0; i < this.count; i++) {
      const px = this.prev[3 * i], py = this.prev[3 * i + 1], pz = this.prev[3 * i + 2];
      let speed = -1;
      if (g) {
        this.pos.lon = this.lon[i];
        this.pos.lat = this.lat[i];
        speed = advect(g, this.pos, dtSec, flowScale, this.tmp);
        this.lon[i] = this.pos.lon;
        this.lat[i] = this.pos.lat;
      }
      this.age[i] += 1;
      const sp = this.spawn;
      const outside = sp !== null && (this.lat[i] < sp.s || this.lat[i] > sp.n || !lonInRange(this.lon[i], sp.w, sp.e));
      const o = i * 2 * FLOATS_PER_VERTEX;
      if (speed < 0 || this.age[i] > this.life[i] || outside) {
        this.respawn(i, false);
        // degenerate segment: never draw a line across the jump
        this.writeVertex(o, this.prev[3 * i], this.prev[3 * i + 1], this.prev[3 * i + 2], birth, 0, 0);
        this.writeVertex(o + FLOATS_PER_VERTEX, this.prev[3 * i], this.prev[3 * i + 1], this.prev[3 * i + 2], birth, 0, 0);
        continue;
      }
      geodeticToEcef(this.lon[i], this.lat[i], this.ecef, 0);
      const t = this.age[i] / this.life[i];
      const lifeA = Math.min(1, Math.sin(Math.PI * t) * 1.6);   // fade in, hold, fade out
      this.writeVertex(o, px, py, pz, birth, lifeA, speed);
      this.writeVertex(o + FLOATS_PER_VERTEX, this.ecef[0], this.ecef[1], this.ecef[2], birth, lifeA, speed);
      this.prev[3 * i] = this.ecef[0];
      this.prev[3 * i + 1] = this.ecef[1];
      this.prev[3 * i + 2] = this.ecef[2];
    }
  }

  private draw(): void {
    const gl = this.gl;
    const cw = this.canvas.clientWidth, ch = this.canvas.clientHeight;
    if (cw === 0 || ch === 0) return;
    const pr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = Math.round(cw * pr), hgt = Math.round(ch * pr);
    if (this.canvas.width !== w || this.canvas.height !== hgt) { this.canvas.width = w; this.canvas.height = hgt; }

    const cam = this.viewer.camera;
    // rotation only: positions are camera-relative
    const view = Cesium.Matrix4.setTranslation(cam.viewMatrix, Cesium.Cartesian3.ZERO, this.viewScratch);
    const vp = Cesium.Matrix4.multiply(cam.frustum.projectionMatrix, view, this.vpScratch);
    for (let k = 0; k < 16; k++) this.viewProj[k] = vp[k];
    const c = cam.positionWC;
    const [chx, clx] = splitDouble(c.x), [chy, cly] = splitDouble(c.y), [chz, clz] = splitDouble(c.z);

    gl.viewport(0, 0, w, hgt);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.program);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniformMatrix4fv(this.loc.u_viewProj, false, this.viewProj);
    gl.uniform3f(this.loc.u_camHigh, chx, chy, chz);
    gl.uniform3f(this.loc.u_camLow, clx, cly, clz);
    gl.uniform3f(this.loc.u_cam, c.x, c.y, c.z);
    gl.uniform1f(this.loc.u_frame, this.frame);
    gl.uniform1f(this.loc.u_trail, this.trail);
    gl.uniform1f(this.loc.u_opacity, this.settings.opacity);

    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    const stride = FLOATS_PER_VERTEX * 4;
    gl.enableVertexAttribArray(this.attr.high);
    gl.vertexAttribPointer(this.attr.high, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(this.attr.low);
    gl.vertexAttribPointer(this.attr.low, 3, gl.FLOAT, false, stride, 12);
    gl.enableVertexAttribArray(this.attr.info);
    gl.vertexAttribPointer(this.attr.info, 3, gl.FLOAT, false, stride, 24);
    gl.drawArrays(gl.LINES, 0, this.trail * this.count * 2);
  }

  private upload(): void {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferSubData(gl.ARRAY_BUFFER, (this.frame % this.trail) * this.slot.byteLength, this.slot);
  }

  /** "auto" mode: shrink density after ~2 s below ~35 fps, grow back slowly when there is headroom. */
  private adapt(dtMs: number): void {
    if (this.settings.performance !== "auto") return;
    if (dtMs > 28) { this.slowFrames++; this.fastFrames = 0; } else if (dtMs < 18) { this.fastFrames++; this.slowFrames = 0; }
    if (this.slowFrames > 120 && this.autoScale > 0.3) {
      this.autoScale *= 0.75; this.slowFrames = 0; this.allocate();
    } else if (this.fastFrames > 600 && this.autoScale < 1) {
      this.autoScale = Math.min(1, this.autoScale / 0.75); this.fastFrames = 0; this.allocate();
    }
  }

  private loop = (t: number): void => {
    if (this.destroyed) return;
    this.raf = requestAnimationFrame(this.loop);
    if (this.viewer.isDestroyed()) { this.destroy(); return; }
    if (document.hidden) { this.lastT = 0; return; }
    const dtMs = this.lastT ? Math.min(t - this.lastT, 100) : 16.7;
    this.lastT = t;
    if (this.frame > 1e7) this.allocate(); // keep frame counters exactly representable in float32
    // fixed-rate simulation; every tick writes one trail slot, every display frame redraws
    this.acc = Math.min(this.acc + dtMs / 1000, TICK_S * MAX_TICKS_PER_FRAME);
    while (this.acc >= TICK_S) {
      this.acc -= TICK_S;
      this.step(TICK_S);
      this.upload();
      this.frame += 1;
    }
    this.draw();
    this.adapt(dtMs);
  };
}
