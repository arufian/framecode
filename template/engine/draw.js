// Drawing toolkit for scenes: textures, hand-drawn strokes, text motion, callouts,
// HUD pieces, captions, a camera, and a small character rig. All sizes are in
// design pixels; cached textures are rebuilt automatically at the current scale.

import { clamp, lerp, EASE, rng, fbm, noise2, createLayer, TAU } from './core.js';

const currentScale = (ctx) => {
  const m = ctx.getTransform();
  return Math.hypot(m.a, m.b) || 1;
};

/**
 * Blur in design pixels. Canvas filters ignore the transform, so a raw `blur(6px)` would
 * look smaller at 4K than at 1080p; this scales it. Pass 0 to clear.
 */
export function setBlur(ctx, px) {
  const real = px * currentScale(ctx);
  ctx.filter = real > 0.25 ? `blur(${real.toFixed(2)}px)` : 'none';
}

const textureCache = new Map();
function cached(key, ctx, w, h, paint) {
  const scale = currentScale(ctx);
  const id = `${key}@${w}x${h}@${scale.toFixed(4)}`;
  if (!textureCache.has(id)) {
    const layer = createLayer(w * scale, h * scale);
    const c = layer.getContext('2d');
    c.scale(scale, scale);
    paint(c, scale);
    textureCache.set(id, layer);
    if (textureCache.size > 64) textureCache.delete(textureCache.keys().next().value);
  }
  return textureCache.get(id);
}

// ------------------------------------------------------------------ colour

export function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export const rgba = (hex, a = 1) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };
export function mixColor(a, b, t) {
  const [r1, g1, b1] = hexToRgb(a), [r2, g2, b2] = hexToRgb(b);
  const c = (x, y) => Math.round(lerp(x, y, t)).toString(16).padStart(2, '0');
  return `#${c(r1, r2)}${c(g1, g2)}${c(b1, b2)}`;
}

// ------------------------------------------------------------------ backgrounds & textures

/** Warm paper: mottled base, fibres, fine grain. Cached per size/scale/options. */
export function paper(ctx, w, h, { base = '#f3ecdf', mottle = 0.07, fibres = 260, seed = 3 } = {}) {
  const layer = cached(`paper:${base}:${mottle}:${fibres}:${seed}`, ctx, w, h, (c, scale) => {
    const r = rng(seed);
    c.fillStyle = base;
    c.fillRect(0, 0, w, h);
    for (let i = 0; i < 90; i++) {
      const x = r() * w, y = r() * h, rad = r.range(80, 420);
      const g = c.createRadialGradient(x, y, 0, x, y, rad);
      const dark = r() < 0.55;
      g.addColorStop(0, dark ? `rgba(120,95,60,${mottle * r()})` : `rgba(255,255,255,${mottle * 1.4 * r()})`);
      g.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = g;
      c.fillRect(x - rad, y - rad, rad * 2, rad * 2);
    }
    c.lineCap = 'round';
    for (let i = 0; i < fibres; i++) {
      const x = r() * w, y = r() * h, len = r.range(6, 26), a = r() * TAU;
      c.strokeStyle = `rgba(110,85,55,${r.range(0.03, 0.08)})`;
      c.lineWidth = r.range(0.4, 1.1);
      c.beginPath();
      c.moveTo(x, y);
      c.quadraticCurveTo(x + Math.cos(a + 0.6) * len * 0.5, y + Math.sin(a + 0.6) * len * 0.5,
        x + Math.cos(a) * len, y + Math.sin(a) * len);
      c.stroke();
    }
    speckle(c, w, h, scale, seed, 10);
  });
  drawLayer(ctx, layer);
}

function speckle(c, w, h, scale, seed, amount) {
  const W = Math.ceil(w * scale), H = Math.ceil(h * scale);
  const img = c.getImageData(0, 0, W, H);
  const d = img.data;
  let s = seed * 9301 + 49297;
  for (let i = 0; i < d.length; i += 4) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const n = ((s >> 8) % (amount * 2 + 1)) - amount;
    d[i] += n; d[i + 1] += n; d[i + 2] += n;
  }
  c.putImageData(img, 0, 0);
}

function drawLayer(ctx, layer) {
  ctx.save();
  const scale = currentScale(ctx);
  ctx.scale(1 / scale, 1 / scale);
  ctx.drawImage(layer, 0, 0);
  ctx.restore();
}

/** Diagonal stripes (pass `offset` = time * speed for a slow drift). */
export function stripes(ctx, w, h, { colors = ['#efe6d4', '#dfe7ea'], width = 90, angle = -35, offset = 0 } = {}) {
  ctx.save();
  ctx.fillStyle = colors[0];
  ctx.fillRect(0, 0, w, h);
  ctx.translate(w / 2, h / 2);
  ctx.rotate((angle * Math.PI) / 180);
  const L = Math.hypot(w, h);
  const period = width * colors.length;
  const shift = ((offset % period) + period) % period;
  for (let x = -L / 2 - period + shift; x < L / 2 + period; x += period) {
    for (let k = 1; k < colors.length; k++) {
      ctx.fillStyle = colors[k];
      ctx.fillRect(x + k * width, -L / 2, width, L);
    }
  }
  ctx.restore();
}

/** Blueprint / night grid with a soft centre glow. `drift` pans the grid. */
export function blueprint(ctx, w, h, { bg = '#0d1733', line = '#2a3d74', major = '#3b55a0', step = 48, drift = 0, glow = '#1f3a8a' } = {}) {
  ctx.save();
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.6);
  g.addColorStop(0, rgba(glow, 0.35));
  g.addColorStop(1, rgba(glow, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  const off = ((drift % step) + step) % step;
  for (let i = -1, x = off - step; x < w + step; x += step, i++) {
    ctx.strokeStyle = i % 4 === 0 ? rgba(major, 0.55) : rgba(line, 0.45);
    ctx.lineWidth = i % 4 === 0 ? 1.2 : 0.7;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let i = -1, y = off - step; y < h + step; y += step, i++) {
    ctx.strokeStyle = i % 4 === 0 ? rgba(major, 0.55) : rgba(line, 0.45);
    ctx.lineWidth = i % 4 === 0 ? 1.2 : 0.7;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  ctx.restore();
}

export function vignette(ctx, w, h, { strength = 0.35, color = '#000000' } = {}) {
  const g = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.35, w / 2, h / 2, Math.hypot(w, h) * 0.6);
  g.addColorStop(0, rgba(color, 0));
  g.addColorStop(1, rgba(color, strength));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

export function glow(ctx, x, y, radius, color, alpha = 0.6) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, radius);
  g.addColorStop(0, rgba(color, alpha));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
}

/** Film grain overlay; changes every frame, which also prevents gradient banding after encoding. */
export function grain(ctx, w, h, frame, { amount = 0.06, size = 256 } = {}) {
  const tile = cached(`grain:${size}`, ctx, size, size, (c, scale) => {
    const S = Math.ceil(size * scale);
    const img = c.getImageData(0, 0, S, S);
    const r = rng(11);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.floor(r() * 255);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    c.putImageData(img, 0, 0);
  });
  const r = rng(Math.floor(frame) + 1);
  ctx.save();
  ctx.globalAlpha = amount;
  ctx.globalCompositeOperation = 'overlay';
  const scale = currentScale(ctx);
  ctx.scale(1 / scale, 1 / scale);
  const S = tile.width, W = w * scale, H = h * scale;
  const ox = -Math.floor(r() * S), oy = -Math.floor(r() * S);
  for (let x = ox; x < W; x += S) for (let y = oy; y < H; y += S) ctx.drawImage(tile, x, y);
  ctx.restore();
}

// ------------------------------------------------------------------ paths & hand-drawn strokes

export function roundRect(ctx, x, y, w, h, r = 12) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function lengths(points) {
  const out = [0];
  for (let i = 1; i < points.length; i++) {
    out.push(out[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]));
  }
  return out;
}

/** Point and tangent angle at fraction p along a polyline. */
export function pointAt(points, p) {
  const acc = lengths(points);
  const target = clamp(p) * acc[acc.length - 1];
  let i = 1;
  while (i < acc.length - 1 && acc[i] < target) i++;
  const seg = Math.max(1e-9, acc[i] - acc[i - 1]);
  const t = (target - acc[i - 1]) / seg;
  const [x0, y0] = points[i - 1], [x1, y1] = points[i];
  return { x: lerp(x0, x1, t), y: lerp(y0, y1, t), angle: Math.atan2(y1 - y0, x1 - x0) };
}

/** Sub-path from 0 to fraction p (for draw-on strokes). */
export function partial(points, p) {
  if (p >= 1) return points;
  const acc = lengths(points);
  const target = clamp(p) * acc[acc.length - 1];
  const out = [points[0]];
  for (let i = 1; i < points.length; i++) {
    if (acc[i] <= target) { out.push(points[i]); continue; }
    const t = (target - acc[i - 1]) / Math.max(1e-9, acc[i] - acc[i - 1]);
    out.push([lerp(points[i - 1][0], points[i][0], t), lerp(points[i - 1][1], points[i][1], t)]);
    break;
  }
  return out;
}

/** Resample a polyline to evenly spaced points (so wobble looks uniform). */
export function resample(points, spacing = 6) {
  const acc = lengths(points);
  const total = acc[acc.length - 1];
  const n = Math.max(2, Math.ceil(total / spacing));
  return Array.from({ length: n + 1 }, (_, i) => { const q = pointAt(points, i / n); return [q.x, q.y]; });
}

/**
 * Hand-drawn wobble. `boil` (frames per second of re-draw, e.g. 8) makes the line
 * "boil" like traditional animation; 0 keeps it still.
 */
export function wobble(points, { amp = 1.6, freq = 0.02, seed = 1, t = 0, boil = 0 } = {}) {
  const phase = boil ? Math.floor(t * boil) * 13.7 : 0;
  return resample(points, 5).map(([x, y], i, arr) => {
    const [px, py] = arr[Math.max(0, i - 1)], [nx, ny] = arr[Math.min(arr.length - 1, i + 1)];
    const len = Math.hypot(nx - px, ny - py) || 1;
    const nxv = -(ny - py) / len, nyv = (nx - px) / len;
    const d = noise2(i * freq * 5 + phase, seed) * amp;
    return [x + nxv * d, y + nyv * d];
  });
}

export function strokePath(ctx, points, { width = 3, color = '#1d1d1f', cap = 'round', alpha = 1, dash = null } = {}) {
  if (points.length < 2) return;
  ctx.save();
  ctx.globalAlpha *= alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = cap;
  ctx.lineJoin = 'round';
  if (dash) ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
  ctx.stroke();
  ctx.restore();
}

/** Draw-on sketch stroke: wobble + partial reveal + a slightly offset second pass. */
export function sketch(ctx, points, { p = 1, width = 3, color = '#1d1d1f', seed = 1, amp = 1.4, t = 0, boil = 0, double = true } = {}) {
  if (p <= 0) return;
  const main = partial(wobble(points, { amp, seed, t, boil }), p);
  strokePath(ctx, main, { width, color });
  if (double) strokePath(ctx, partial(wobble(points, { amp: amp * 1.3, seed: seed + 5, t, boil }), p * 0.97), { width: width * 0.45, color, alpha: 0.45 });
}

export const circlePoints = (cx, cy, r, { start = -Math.PI / 2, overshoot = 0.08, n = 64 } = {}) =>
  Array.from({ length: n + 1 }, (_, i) => {
    const a = start + (i / n) * TAU * (1 + overshoot);
    const rr = r * (1 + 0.015 * Math.sin(a * 3));
    return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
  });

export const rectPoints = (x, y, w, h) => [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y + 1]];

// ------------------------------------------------------------------ text

export const font = (size, weight = 400, family = 'Inter', style = 'normal') => `${style} ${weight} ${size}px "${family}"`;

/** Split into lines that fit maxWidth. Spaces break Latin text; CJK breaks between characters. */
export function wrapText(ctx, text, maxWidth) {
  const out = [];
  for (const paragraph of String(text).split('\n')) {
    const tokens = /\s/.test(paragraph) ? paragraph.split(/(\s+)/) : Array.from(paragraph);
    let line = '';
    for (const token of tokens) {
      const next = line + token;
      if (line.trim() && ctx.measureText(next).width > maxWidth) { out.push(line.trimEnd()); line = token.trimStart(); }
      else line = next;
    }
    out.push(line.trimEnd());
  }
  return out;
}

/** Multi-line text. Returns { width, height, lines }. */
export function text(ctx, str, x, y, { size = 48, weight = 400, family = 'Inter', color = '#111', align = 'left',
  baseline = 'alphabetic', maxWidth = Infinity, lineHeight = 1.25, letterSpacing = 0, alpha = 1 } = {}) {
  ctx.save();
  ctx.font = font(size, weight, family);
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  if (letterSpacing) ctx.letterSpacing = `${letterSpacing}px`;
  ctx.globalAlpha *= alpha;
  const lines = wrapText(ctx, str, maxWidth);
  let width = 0;
  lines.forEach((line, i) => { ctx.fillText(line, x, y + i * size * lineHeight); width = Math.max(width, ctx.measureText(line).width); });
  ctx.restore();
  return { width, height: lines.length * size * lineHeight, lines };
}

/**
 * Word-by-word entrance: each word rises, un-blurs, and fades in, staggered.
 * p = 0..1 over the whole sentence (e.g. s.enter(0.2, 1.4, EASE.linear)).
 */
export function wordsIn(ctx, str, x, y, p, { size = 64, weight = 700, family = 'Inter', color = '#111', align = 'left',
  maxWidth = Infinity, lineHeight = 1.15, rise = 0.45, overlap = 3, blur = 6 } = {}) {
  ctx.save();
  ctx.font = font(size, weight, family);
  ctx.textBaseline = 'alphabetic';
  const lines = wrapText(ctx, str, maxWidth).map((line) => line.split(/(\s+)/).filter((w) => w.length));
  const total = lines.reduce((n, l) => n + l.filter((w) => w.trim()).length, 0);
  let index = 0;
  lines.forEach((words, li) => {
    const lineWidth = ctx.measureText(words.join('')).width;
    let cx = align === 'center' ? x - lineWidth / 2 : align === 'right' ? x - lineWidth : x;
    for (const word of words) {
      const wWidth = ctx.measureText(word).width;
      if (word.trim()) {
        const local = EASE.enter(clamp((p * (total + overlap - 1) - index) / overlap));
        if (local > 0.001) {
          ctx.save();
          ctx.globalAlpha *= local;
          if (blur && local < 0.99) ctx.filter = `blur(${((1 - local) * blur * currentScale(ctx)).toFixed(2)}px)`;
          ctx.fillStyle = color;
          ctx.fillText(word, cx, y + li * size * lineHeight + (1 - local) * size * rise);
          ctx.restore();
        }
        index++;
      }
      cx += wWidth;
    }
  });
  ctx.restore();
  return { lines: lines.length, height: lines.length * size * lineHeight };
}

/** Typewriter with a blinking caret. p = 0..1 of characters shown; t = seconds (caret blink). */
export function typewriter(ctx, str, x, y, p, t, { size = 28, weight = 500, family = 'JetBrains Mono', color = '#2f5bea',
  caret = true, lineHeight = 1.4 } = {}) {
  const chars = Array.from(str);
  const shown = chars.slice(0, Math.floor(clamp(p) * chars.length + 1e-6)).join('');
  const lines = shown.split('\n');
  ctx.save();
  ctx.font = font(size, weight, family);
  ctx.fillStyle = color;
  ctx.textBaseline = 'alphabetic';
  lines.forEach((line, i) => ctx.fillText(line, x, y + i * size * lineHeight));
  const typing = p > 0 && p < 1;
  if (caret && (typing || Math.floor(t * 1.8) % 2 === 0)) {
    const last = lines[lines.length - 1];
    const cx = x + ctx.measureText(last).width + 3;
    const cy = y + (lines.length - 1) * size * lineHeight;
    ctx.fillRect(cx, cy - size * 0.8, Math.max(2, size * 0.09), size * 0.95);
  }
  ctx.restore();
}

/** Count-up number string: countUp(0, 20998, p, { suffix: ' km³' }). */
export function countUp(from, to, p, { decimals = 0, prefix = '', suffix = '', separator = ',' } = {}) {
  const v = lerp(from, to, clamp(p));
  const [int, dec] = v.toFixed(decimals).split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, separator);
  return `${prefix}${grouped}${dec ? '.' + dec : ''}${suffix}`;
}

// ------------------------------------------------------------------ callouts & HUD

/**
 * Annotation: a pulsing dot on the subject, an elbow leader line that draws on,
 * then the label. p = 0..1 (use s.life(...) so it also exits).
 */
export function callout(ctx, p, { x, y, tx, ty, label, sub = '', color = '#1d1d1f', accent = '#e4572e', size = 26, t = 0, family = 'Inter' }) {
  if (p <= 0) return;
  const dot = EASE.outBack(clamp(p / 0.25));
  ctx.save();
  ctx.globalAlpha *= clamp(p * 4);
  ctx.fillStyle = accent;
  ctx.beginPath(); ctx.arc(x, y, 6 * dot, 0, TAU); ctx.fill();
  const pulse = (t * 0.9) % 1;
  ctx.strokeStyle = rgba(accent, 0.6 * (1 - pulse));
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(x, y, 6 + 18 * pulse, 0, TAU); ctx.stroke();
  const pts = [[x, y], [x + (tx - x) * 0.35, ty], [tx, ty]]; // elbow leader line
  strokePath(ctx, partial(pts, EASE.move(clamp((p - 0.15) / 0.45))), { width: 2, color });
  const lp = EASE.enter(clamp((p - 0.5) / 0.5));
  if (lp > 0) {
    const right = tx >= x;
    ctx.globalAlpha *= lp;
    text(ctx, label, tx + (right ? 12 : -12), ty - 6 + (1 - lp) * 10, { size, weight: 600, color, align: right ? 'left' : 'right', family });
    if (sub) text(ctx, sub, tx + (right ? 12 : -12), ty + size * 0.9 + (1 - lp) * 10, { size: size * 0.62, color: rgba(color.length === 7 ? color : '#1d1d1f', 0.65), align: right ? 'left' : 'right', family });
  }
  ctx.restore();
}

/** Small chapter title with an underline that draws on (top-left chrome). */
export function chapter(ctx, label, p, { x = 64, y = 72, size = 26, color = '#1d1d1f', accent = '#e4572e', family = 'Inter' } = {}) {
  if (p <= 0) return;
  ctx.save();
  ctx.globalAlpha *= clamp(p * 3);
  ctx.font = font(size, 600, family);
  const width = ctx.measureText(label).width;
  ctx.fillStyle = color;
  ctx.fillText(label, x, y + (1 - EASE.enter(clamp(p * 1.5))) * 12);
  ctx.fillStyle = accent;
  ctx.fillRect(x, y + 12, width * EASE.move(clamp((p - 0.2) / 0.8)), 3);
  ctx.restore();
}

export function progressRing(ctx, p, { x, y, r = 16, color = '#e4572e', track = 'rgba(0,0,0,0.15)', width = 3, label = '', labelColor = '#1d1d1f', family = 'Inter' }) {
  ctx.save();
  ctx.lineWidth = width;
  ctx.strokeStyle = track;
  ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.stroke();
  ctx.strokeStyle = color;
  ctx.lineCap = 'round';
  ctx.beginPath(); ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + TAU * clamp(p)); ctx.stroke();
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.arc(x, y, r * 0.28, 0, TAU); ctx.fill();
  if (label) text(ctx, label, x, y + r + 22, { size: 14, color: labelColor, align: 'center', family });
  ctx.restore();
}

/**
 * Burned-in captions for the voice line playing at env.frame. Each line eases in
 * and out; speakers can have their own colour: { colors: { narrator: '#fff', dot: '#ffb347' } }.
 */
export function captions(ctx, env, { size = 38, weight = 600, family = 'Inter', colors = {}, color = '#ffffff',
  box = 'rgba(0,0,0,0.55)', bottom = 90, maxWidth = 0.72, fade = 0.15 } = {}) {
  const { timeline } = env.project;
  const line = timeline.lines.find((l) => env.frame >= l.from && env.frame < l.from + l.durationInFrames);
  if (!line) return;
  const t = (env.frame - line.from) / timeline.fps;
  const remaining = (line.from + line.durationInFrames - env.frame) / timeline.fps;
  const a = EASE.enter(clamp(t / fade)) * clamp(remaining / fade);
  ctx.save();
  ctx.font = font(size, weight, family);
  const lines = wrapText(ctx, line.text, env.w * maxWidth);
  const lh = size * 1.3;
  const blockH = lines.length * lh;
  const top = env.h - bottom - blockH;
  ctx.globalAlpha *= a;
  if (box) {
    const width = Math.max(...lines.map((l) => ctx.measureText(l).width));
    ctx.fillStyle = box;
    roundRect(ctx, env.w / 2 - width / 2 - 22, top - 12 + (1 - a) * 6, width + 44, blockH + 18, 14);
    ctx.fill();
  }
  ctx.fillStyle = colors[line.speaker] || color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  lines.forEach((l, i) => ctx.fillText(l, env.w / 2, top + i * lh + (1 - a) * 6));
  ctx.restore();
}

// ------------------------------------------------------------------ camera

/** Look at (x, y) with zoom/rotation; everything drawn in fn() moves together. */
export function camera(ctx, w, h, { x = w / 2, y = h / 2, zoom = 1, rotate = 0 } = {}, fn) {
  ctx.save();
  ctx.translate(w / 2, h / 2);
  ctx.scale(zoom, zoom);
  ctx.rotate(rotate);
  ctx.translate(-x, -y);
  fn();
  ctx.restore();
}

/** Parallax layer: depth 0 = fixed to screen, 1 = moves with the camera. */
export function parallax(ctx, w, h, cam, depth, fn) {
  camera(ctx, w, h, { x: lerp(w / 2, cam.x ?? w / 2, depth), y: lerp(h / 2, cam.y ?? h / 2, depth),
    zoom: lerp(1, cam.zoom ?? 1, depth), rotate: (cam.rotate ?? 0) * depth }, fn);
}

// ------------------------------------------------------------------ images

export function imageCover(ctx, img, x, y, w, h, { focusX = 0.5, focusY = 0.5 } = {}) {
  const s = Math.max(w / img.width, h / img.height);
  const iw = img.width * s, ih = img.height * s;
  ctx.drawImage(img, x - (iw - w) * focusX, y - (ih - h) * focusY, iw, ih);
}

/** Paint an image in with soft brush dabs along a zig-zag path (p = 0..1). */
export function brushReveal(ctx, img, x, y, w, h, p, { seed = 4, rows = 7, brush = 0.16 } = {}) {
  if (p <= 0) return;
  if (p >= 1) { ctx.drawImage(img, x, y, w, h); return; }
  const scale = currentScale(ctx);
  const layer = createLayer(w * scale, h * scale);
  const c = layer.getContext('2d');
  c.scale(scale, scale);
  c.drawImage(img, 0, 0, w, h);
  c.globalCompositeOperation = 'destination-in';
  const r = rng(seed);
  const dabs = 220;
  const radius = brush * Math.min(w, h);
  for (let i = 0; i < dabs * p; i++) {
    const q = i / dabs;
    const row = Math.floor(q * rows);
    const along = (q * rows) % 1;
    const px = (row % 2 ? 1 - along : along) * w + r.range(-0.04, 0.04) * w;
    const py = ((row + 0.5) / rows) * h + fbm(q * 9, 0, seed) * h * 0.05;
    const g = c.createRadialGradient(px, py, 0, px, py, radius);
    g.addColorStop(0, 'rgba(0,0,0,1)');
    g.addColorStop(0.6, 'rgba(0,0,0,0.85)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = g;
    c.fillRect(px - radius, py - radius, radius * 2, radius * 2);
  }
  ctx.save();
  ctx.scale(1 / scale, 1 / scale);
  ctx.drawImage(layer, x * scale, y * scale);
  ctx.restore();
}

// ------------------------------------------------------------------ character rig

/** Eyelid closure 0..1: natural blinks every 2.5-5.5 s (deterministic per seed). */
export function blink(t, seed = 1) {
  const r = rng(seed);
  let at = r.range(0.8, 2.5);
  while (at < t - 0.2) at += r.range(2.5, 5.5) + (r() < 0.15 ? 0.25 : 0);
  const d = t - at;
  return d < 0 || d > 0.16 ? 0 : Math.sin((d / 0.16) * Math.PI);
}

/** Mouth openness while speaking: lively but smooth pseudo lip-flap. */
export function talk(t, speaking, seed = 2) {
  if (!speaking) return 0;
  return clamp(0.35 + 0.65 * Math.abs(noise2(t * 7.5, 0.5, seed)) * (0.6 + 0.4 * Math.abs(Math.sin(t * 17))));
}

/**
 * A friendly blob character. Idle breathing, squash & stretch, blinking, eye
 * direction, talking mouth, blush, and hand-drawn outline boil are built in.
 */
export function mascot(ctx, { x, y, size = 180, t = 0, body = '#fffaf0', outline = '#1d1d1f', cheek = '#ff9a8b',
  look = [0, 0], mood = 'happy', mouth = 0, seed = 1, squash = 0, wave = 0, boil = 8 } = {}) {
  const breathe = Math.sin(t * TAU * 0.35) * 0.018;
  const sy = 1 + breathe - squash * 0.12, sx = 1 - breathe * 0.6 + squash * 0.1;
  const bob = Math.sin(t * TAU * 0.35 + 0.6) * size * 0.012;
  ctx.save();
  ctx.translate(x, y + bob);
  // shadow
  ctx.fillStyle = 'rgba(0,0,0,0.12)';
  ctx.beginPath(); ctx.ellipse(0, size * 0.06, size * 0.34 * sx, size * 0.05, 0, 0, TAU); ctx.fill();
  // feet & arms
  const legs = [[-0.13, 0], [0.13, 0]];
  for (const [lx] of legs) sketch(ctx, [[lx * size, -size * 0.12], [lx * size, 0], [lx * size * 1.4, 0]], { width: size * 0.022, color: outline, seed: seed + lx * 10, t, boil, double: false, amp: 0.6 });
  const waveA = Math.sin(t * TAU * 2.2) * wave;
  sketch(ctx, [[-size * 0.33 * sx, -size * 0.42], [-size * 0.46, -size * (0.36 + 0.14 * waveA)], [-size * 0.52, -size * (0.3 + 0.28 * waveA)]], { width: size * 0.02, color: outline, seed: seed + 3, t, boil, double: false, amp: 0.6 });
  sketch(ctx, [[size * 0.33 * sx, -size * 0.42], [size * 0.44, -size * 0.36], [size * 0.5, -size * 0.3]], { width: size * 0.02, color: outline, seed: seed + 4, t, boil, double: false, amp: 0.6 });
  // body (egg), squash anchored at the feet
  ctx.save();
  ctx.scale(sx, sy);
  const eggPts = Array.from({ length: 73 }, (_, i) => {
    const a = (i / 72) * TAU;
    const r = size * 0.36 * (1 + 0.16 * Math.max(0, -Math.sin(a)));
    return [Math.cos(a) * size * 0.33, -size * 0.45 + Math.sin(a) * r * 1.05];
  });
  ctx.fillStyle = body;
  ctx.beginPath(); eggPts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath(); ctx.fill();
  sketch(ctx, eggPts, { width: size * 0.022, color: outline, seed, t, boil, amp: 0.9 });
  // face
  const [lx, ly] = look;
  const eyeY = -size * 0.52, eyeDX = size * 0.1;
  const lid = blink(t, seed);
  for (const side of [-1, 1]) {
    const ex = side * eyeDX + lx * size * 0.03, ey = eyeY + ly * size * 0.02;
    ctx.save();
    ctx.translate(ex, ey);
    ctx.scale(1, Math.max(0.08, 1 - lid));
    ctx.fillStyle = outline;
    ctx.beginPath(); ctx.ellipse(0, 0, size * 0.042, size * (mood === 'surprised' ? 0.065 : 0.055), 0, 0, TAU); ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.beginPath(); ctx.arc(size * 0.012, -size * 0.022, size * 0.014, 0, TAU); ctx.fill();
    ctx.restore();
    ctx.fillStyle = rgba(cheek, 0.55);
    ctx.beginPath(); ctx.ellipse(side * size * 0.19, eyeY + size * 0.09, size * 0.045, size * 0.022, 0, 0, TAU); ctx.fill();
  }
  const my = eyeY + size * 0.12;
  ctx.strokeStyle = outline; ctx.fillStyle = outline;
  ctx.lineWidth = size * 0.018; ctx.lineCap = 'round';
  if (mouth > 0.05) {
    ctx.beginPath(); ctx.ellipse(0, my + size * 0.01, size * 0.035, size * 0.012 + size * 0.04 * mouth, 0, 0, TAU); ctx.fill();
  } else if (mood === 'surprised') {
    ctx.beginPath(); ctx.arc(0, my + size * 0.01, size * 0.022, 0, TAU); ctx.stroke();
  } else {
    const curve = mood === 'happy' ? 0.035 : mood === 'sad' ? -0.03 : 0.004;
    ctx.beginPath(); ctx.moveTo(-size * 0.045, my); ctx.quadraticCurveTo(0, my + size * curve * 2, size * 0.045, my); ctx.stroke();
  }
  ctx.restore();
  ctx.restore();
}
