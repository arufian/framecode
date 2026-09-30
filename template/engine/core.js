// Core of the animation engine: time math, easing, springs, noise, frame
// compositing, and the p5.js surface scenes draw with. Pure ES module, shared by
// the browser studio and the headless-Chrome renderer. Every function takes time
// as a (possibly fractional) frame number, so the same code renders studio
// previews, final frames, and motion-blur sub-frames.

import { TRANSITIONS } from './transitions.js';
import { createClip, setFootageLoader, clearFootageMisses, footageMisses, settleFootage } from './media.js';

// ------------------------------------------------------------------ platform

let platform = null;
export const setPlatform = (p) => { platform = p; };
export const getPlatform = () => {
  if (!platform) throw new Error('engine platform not set (browser studio or node renderer sets it)');
  return platform;
};
export const createLayer = (w, h) => getPlatform().createCanvas(Math.max(1, Math.ceil(w)), Math.max(1, Math.ceil(h)));

// ------------------------------------------------------------------ math

export const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const invLerp = (a, b, x) => (b === a ? 0 : (x - a) / (b - a));
export const smoothstep = (a, b, x) => { const t = clamp(invLerp(a, b, x)); return t * t * (3 - 2 * t); };
export const TAU = Math.PI * 2;

/** Map x from [a,b] to [c,d], clamped, optionally eased. interpolate(f, [0, 30], [0, 1], EASE.outExpo) */
export function interpolate(x, [a, b], [c, d], ease = EASE.linear) {
  return lerp(c, d, ease(clamp(invLerp(a, b, x))));
}

// ------------------------------------------------------------------ easing

function cubicBezier(x1, y1, x2, y2) {
  const sample = (a1, a2, t) => ((1 - 3 * a2 + 3 * a1) * t + (3 * a2 - 6 * a1)) * t * t + 3 * a1 * t;
  const slope = (a1, a2, t) => 3 * (1 - 3 * a2 + 3 * a1) * t * t + 2 * (3 * a2 - 6 * a1) * t + 3 * a1;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 6; i++) {
      const err = sample(x1, x2, t) - x;
      const d = slope(x1, x2, t);
      if (Math.abs(err) < 1e-6) break;
      if (Math.abs(d) < 1e-6) break;
      t -= err / d;
    }
    if (t < 0 || t > 1 || Math.abs(sample(x1, x2, t) - x) > 1e-4) {
      let lo = 0, hi = 1;
      for (let i = 0; i < 30; i++) { t = (lo + hi) / 2; if (sample(x1, x2, t) < x) lo = t; else hi = t; }
    }
    return sample(y1, y2, t);
  };
}

export const EASE = {
  linear: (t) => t,
  inQuad: (t) => t * t,
  outQuad: (t) => 1 - (1 - t) * (1 - t),
  inOutQuad: (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2),
  inCubic: (t) => t ** 3,
  outCubic: (t) => 1 - (1 - t) ** 3,
  inOutCubic: (t) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2),
  outQuart: (t) => 1 - (1 - t) ** 4,
  outQuint: (t) => 1 - (1 - t) ** 5,
  inOutSine: (t) => -(Math.cos(Math.PI * t) - 1) / 2,
  outExpo: (t) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t)),
  inOutExpo: (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t < 0.5 ? 2 ** (20 * t - 10) / 2 : (2 - 2 ** (-20 * t + 10)) / 2),
  outBack: (t) => { const c = 1.4; return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2; },
  // Motion-design curves: entrances decelerate hard, exits accelerate gently, moves are symmetric.
  enter: cubicBezier(0.16, 1, 0.3, 1),
  exit: cubicBezier(0.7, 0, 0.84, 0),
  move: cubicBezier(0.65, 0, 0.35, 1),
  emphasized: cubicBezier(0.2, 0, 0, 1),
  bezier: cubicBezier,
};
export const easeByName = (name) => (typeof name === 'function' ? name : EASE[name] || EASE.inOutCubic);

// ------------------------------------------------------------------ springs

export const SPRING = {
  gentle: { stiffness: 120, damping: 20, mass: 1 },  // no visible overshoot
  snappy: { stiffness: 260, damping: 26, mass: 1 },  // quick, tiny settle
  bouncy: { stiffness: 180, damping: 12, mass: 1 },  // playful overshoot, use sparingly
  heavy: { stiffness: 90, damping: 18, mass: 2 },
};

/** Closed-form damped spring from 0 to 1. `seconds` since release (negative -> 0). */
export function spring(seconds, config = SPRING.gentle) {
  if (seconds <= 0) return 0;
  const { stiffness: k, damping: c, mass: m } = { mass: 1, ...config };
  const w0 = Math.sqrt(k / m);
  const zeta = c / (2 * Math.sqrt(k * m));
  const t = seconds;
  if (zeta < 1) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta);
    return 1 - Math.exp(-zeta * w0 * t) * (Math.cos(wd * t) + ((zeta * w0) / wd) * Math.sin(wd * t));
  }
  if (zeta === 1) return 1 - Math.exp(-w0 * t) * (1 + w0 * t);
  const r1 = -w0 * (zeta - Math.sqrt(zeta * zeta - 1));
  const r2 = -w0 * (zeta + Math.sqrt(zeta * zeta - 1));
  return 1 - (r2 * Math.exp(r1 * t) - r1 * Math.exp(r2 * t)) / (r2 - r1);
}

// ------------------------------------------------------------------ deterministic randomness & noise

export function rng(seed = 1) {
  let a = (typeof seed === 'string' ? hashString(seed) : seed) >>> 0 || 1;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  next.range = (lo, hi) => lo + (hi - lo) * next();
  next.int = (lo, hi) => Math.floor(lo + (hi - lo + 1) * next());
  next.pick = (list) => list[Math.floor(next() * list.length)];
  return next;
}

export function hashString(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

const hash2 = (x, y, seed) => {
  let h = Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(seed, 2147483647);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};

/** Smooth 2D value noise in [-1, 1]. */
export function noise2(x, y = 0, seed = 0) {
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash2(xi, yi, seed), b = hash2(xi + 1, yi, seed);
  const c = hash2(xi, yi + 1, seed), d = hash2(xi + 1, yi + 1, seed);
  return (lerp(lerp(a, b, u), lerp(c, d, u), v)) * 2 - 1;
}

/** Fractal noise (octaves of noise2), roughly in [-1, 1]. */
export function fbm(x, y = 0, seed = 0, octaves = 4) {
  let sum = 0, amp = 0.5, freq = 1, norm = 0;
  for (let i = 0; i < octaves; i++) {
    sum += amp * noise2(x * freq, y * freq, seed + i * 17);
    norm += amp; amp *= 0.5; freq *= 2;
  }
  return sum / norm;
}

// ------------------------------------------------------------------ project & timeline

/** Declare a video project. Scenes are keyed by the storyboard `component` name. */
export function defineProject(project) {
  return { fonts: [], images: {}, scenes: {}, ...project };
}

/** Everything a scene needs to know about "now", with timing helpers bound to it. */
export function sceneContext(project, scene, frame) {
  const { timeline } = project;
  const fps = timeline.fps;
  const local = frame - scene.from;
  const lines = (scene.lines || []).map((id) => timeline.lines.find((l) => l.id === id)).filter(Boolean)
    .map((l) => ({ ...l, start: (l.from - scene.from) / fps, end: (l.from - scene.from + l.durationInFrames) / fps }));
  const exitEnd = scene.durationInFrames - scene.outFrames / 2;
  const s = {
    project, scene, timeline, lines,
    w: timeline.width, h: timeline.height, fps,
    frame: local, t: local / fps, globalFrame: frame, globalT: frame / fps,
    duration: scene.durationInFrames, seconds: scene.durationInFrames / fps,
    inFrames: scene.inFrames, outFrames: scene.outFrames,
    params: scene.params || {}, assets: project.assets,
    state: project.sceneState?.[scene.id],
    /** 0 -> 1 entrance starting `delay` seconds into the scene. */
    enter: (delay = 0, dur = 0.8, ease = EASE.enter) => ease(clamp((local / fps - delay) / dur)),
    /** 1 -> 0 exit that finishes at the outgoing transition midpoint (or scene end). */
    exit: (dur = 0.5, ease = EASE.exit, lead = 0) =>
      1 - ease(clamp((local - (exitEnd - (dur + lead) * fps)) / (dur * fps))),
    /** enter * exit: element visibility over its whole life in the scene. */
    life: (delay = 0, dur = 0.8, exitDur = 0.5) => s.enter(delay, dur) * s.exit(exitDur),
    spring: (delay = 0, config = SPRING.gentle) => spring(local / fps - delay, config),
    /** Progress through the n-th voice line of this scene (0-based): {start, end, p, active}. */
    line: (n) => {
      const l = lines[n];
      if (!l) return { start: 0, end: 0, p: 0, active: false, text: '' };
      const p = clamp((local / fps - l.start) / Math.max(1e-6, l.end - l.start));
      return { ...l, p, active: local / fps >= l.start && local / fps < l.end };
    },
    /** True while any voice line of this scene is being spoken (drives mouth/talk animation). */
    speaking: () => lines.some((l) => local / fps >= l.start && local / fps < l.end),
  };
  return s;
}

export function activeScenes(timeline, frame) {
  return timeline.scenes.filter((s) => frame >= s.from && frame < s.from + s.durationInFrames);
}

export function sceneAt(timeline, frame) {
  const active = activeScenes(timeline, frame);
  return active[active.length - 1] || timeline.scenes[timeline.scenes.length - 1];
}

// ------------------------------------------------------------------ p5 surface

/**
 * The offscreen p5 instance every scene, background, and overlay draws with. It is
 * created once; the engine drives it frame by frame (p5's own draw loop never runs).
 */
async function createSurface(w, h) {
  const { p5, container } = getPlatform();
  if (!p5) throw new Error('engine platform has no p5 constructor');
  const surface = { p: null, density: 0, now: 0 };
  surface.p = await new Promise((resolve, reject) => {
    new p5((p) => {
      p.setup = () => {
        try {
          p.createCanvas(w, h);
          p.noLoop();
          p.millis = () => surface.now; // the caller's clock, never wall-clock time
          resolve(p);
        } catch (error) {
          reject(error);
        }
      };
    }, container);
  });
  return surface;
}

/**
 * Run fn(p) on the p5 surface and composite the result onto ctx (design pixels).
 * Before each call the surface matches the output scale, is cleared, reseeds
 * random()/noise() from clock.seed, and maps frameCount/millis()/deltaTime to the
 * clock, so p5 code is deterministic, seek-safe, and identical across workers.
 */
function paint(ctx, project, scale, clock, fn) {
  const surface = project.surface;
  const { p } = surface;
  if (surface.density !== scale) { p.pixelDensity(scale); surface.density = scale; }
  const seed = hashString(String(clock.seed));
  p.randomSeed(seed);
  p.noiseSeed(seed);
  p.angleMode(p.RADIANS);
  p.frameCount = Math.floor(clock.frame);
  p.deltaTime = 1000 / clock.fps;
  surface.now = (clock.frame / clock.fps) * 1000;
  p.clear();
  const renderer = p._renderer;
  const depth = renderer._pushPopDepth;
  p.push();
  try {
    fn(p);
  } finally {
    // One pop for our push, plus any the caller forgot, so no state leaks into the next draw.
    if (typeof depth === 'number') while (renderer._pushPopDepth > depth) p.pop();
    else p.pop();
  }
  ctx.drawImage(p.canvas, 0, 0, p.width, p.height);
}

// ------------------------------------------------------------------ rendering

function drawScene(ctx, project, scene, frame, scale) {
  const module = project.scenes[scene.component];
  if (!module) throw new Error(`scene component "${scene.component}" (scene ${scene.id}) is not registered in project.js`);
  const s = sceneContext(project, scene, frame);
  paint(ctx, project, scale, { seed: scene.id, frame: s.frame, fps: s.fps }, (p) => module.draw(p, s));
}

/**
 * Draw one frame. `scale` maps design pixels (timeline width/height) to canvas pixels.
 * During a transition both scenes render into offscreen layers and the transition composites them.
 */
export function renderFrame(ctx, project, frame, scale = 1, cache = {}) {
  const { timeline } = project;
  clearFootageMisses();
  const W = timeline.width * scale, H = timeline.height * scale;
  frame = clamp(frame, 0, timeline.durationInFrames - 1e-6);
  const env = { w: timeline.width, h: timeline.height, scale, frame, t: frame / timeline.fps, fps: timeline.fps, project };
  ctx.save();
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, timeline.width, timeline.height);
  ctx.fillStyle = project.backgroundColor || '#000000'; // video has no alpha: studio and render agree
  ctx.fillRect(0, 0, timeline.width, timeline.height);
  const clock = { frame, fps: timeline.fps };
  if (project.background) paint(ctx, project, scale, { ...clock, seed: 'background' }, (p) => project.background(p, env));

  const active = activeScenes(timeline, frame);
  if (active.length === 1 || active.length > 2) {
    drawScene(ctx, project, active[active.length - 1], frame, scale);
  } else if (active.length === 2) {
    const [a, b] = active;
    const spec = a.transitionOut;
    const start = b.from;
    const raw = clamp((frame - start) / Math.max(1, spec.durationInFrames));
    const layerFor = (key) => {
      if (!cache[key] || cache[key].width !== Math.ceil(W) || cache[key].height !== Math.ceil(H)) cache[key] = createLayer(W, H);
      const layer = cache[key];
      const lctx = layer.getContext('2d');
      lctx.setTransform(1, 0, 0, 1, 0, 0);
      lctx.clearRect(0, 0, layer.width, layer.height);
      lctx.setTransform(scale, 0, 0, scale, 0, 0);
      return { layer, lctx };
    };
    const A = layerFor('__a'), B = layerFor('__b');
    drawScene(A.lctx, project, a, frame, scale);
    drawScene(B.lctx, project, b, frame, scale);
    const transition = TRANSITIONS[spec.type] || TRANSITIONS.fade;
    const params = spec.params || {};
    const p = easeByName(params.ease || transition.ease || 'inOutCubic')(raw);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    transition.draw(ctx, A.layer, B.layer, p, params, { ...env, W, H, raw, cache });
    ctx.restore();
  }
  if (project.overlay) paint(ctx, project, scale, { ...clock, seed: 'overlay' }, (p) => project.overlay(p, env));
  ctx.restore();
}

/**
 * renderFrame, repeated until every footage frame it draws is loaded (at most a few
 * passes; prefetching makes most frames one pass). The renderer uses this, so each
 * rendered frame shows the exact footage frame for its time.
 */
export async function renderFrameReady(ctx, project, frame, scale = 1, cache = {}) {
  for (let pass = 0; pass < 6; pass++) {
    renderFrame(ctx, project, frame, scale, cache);
    if (!footageMisses()) return;
    await settleFootage();
  }
  throw new Error(`frame ${frame}: footage frames still missing after 6 passes`);
}

// ------------------------------------------------------------------ loading (platform-agnostic)

export async function loadProject(project, { loadJSON, loadImage, loadFont, loadBitmap }, timelinePath = 'src/timeline.json') {
  project.timeline = await loadJSON(timelinePath);
  for (const font of project.fonts) await loadFont(font);
  project.surface = await createSurface(project.timeline.width, project.timeline.height);
  project.assets = { images: {}, footage: {} };
  for (const [name, src] of Object.entries(project.images)) project.assets.images[name] = await loadImage(src);
  // Media prepared by media.py visuals: art/images and footage clips, by ledger name.
  const media = await loadJSON('public/media.json').catch(() => null);
  if (media && media.version) {
    for (const [name, src] of Object.entries(media.images || {})) {
      if (!project.assets.images[name]) project.assets.images[name] = await loadImage(src);
    }
    for (const [name, meta] of Object.entries(media.footage || {})) project.assets.footage[name] = createClip(name, meta);
  }
  if (loadBitmap) setFootageLoader(loadBitmap);
  const missing = project.timeline.scenes.filter((s) => !project.scenes[s.component]).map((s) => `${s.id}:${s.component}`);
  if (missing.length) throw new Error(`timeline scenes without a registered component: ${missing.join(', ')}`);
  project.sceneState = {};
  for (const scene of project.timeline.scenes) {
    const module = project.scenes[scene.component];
    if (module.setup) {
      project.sceneState[scene.id] = await module.setup({
        w: project.timeline.width, h: project.timeline.height, fps: project.timeline.fps,
        params: scene.params || {}, assets: project.assets, scene, timeline: project.timeline,
      });
    }
  }
  if (project.setup) await project.setup({ timeline: project.timeline, assets: project.assets });
  return project;
}
