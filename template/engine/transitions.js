// Scene transitions. Each one composites the exiting layer A and the entering
// layer B at eased progress p (0 -> 1). Contexts arrive in canvas pixels with an
// identity transform; design-pixel sizes are multiplied by env.scale.
//
// Rules that keep them smooth: the exiting scene stays opaque underneath (no
// brightness dip), motion peaks mid-transition, and blur tracks velocity.

import { clamp, lerp, fbm, createLayer } from './core.js';

const velocity = (raw) => Math.sin(Math.PI * clamp(raw)); // 0 at the ends, 1 mid-transition

function drawScaled(ctx, layer, scale, alpha = 1, blur = 0, dx = 0, dy = 0, originX = 0.5, originY = 0.5) {
  const { width: W, height: H } = layer;
  ctx.save();
  ctx.globalAlpha = alpha;
  if (blur > 0.25) ctx.filter = `blur(${blur.toFixed(2)}px)`;
  const ox = W * originX, oy = H * originY;
  ctx.translate(ox + dx, oy + dy);
  ctx.scale(scale, scale);
  ctx.drawImage(layer, -ox, -oy);
  ctx.restore();
}

function scratch(env, key) {
  const { W, H, cache } = env;
  if (!cache[key] || cache[key].width !== Math.ceil(W) || cache[key].height !== Math.ceil(H)) cache[key] = createLayer(W, H);
  const layer = cache[key];
  const c = layer.getContext('2d');
  c.setTransform(1, 0, 0, 1, 0, 0);
  c.globalCompositeOperation = 'source-over';
  c.globalAlpha = 1;
  c.filter = 'none';
  c.clearRect(0, 0, layer.width, layer.height);
  return { layer, c };
}

/** Rotate local (u along the travel direction, v across it) into canvas coordinates. */
function frameFor(env, angleDeg) {
  const a = (angleDeg * Math.PI) / 180;
  const cx = env.W / 2, cy = env.H / 2;
  const L = Math.hypot(env.W, env.H);
  const toCanvas = (u, v) => [cx + u * Math.cos(a) - v * Math.sin(a), cy + u * Math.sin(a) + v * Math.cos(a)];
  return { L, toCanvas };
}

const DIRECTION_ANGLE = { right: 0, down: 90, left: 180, up: 270 };
const angleOf = (params, fallback = 'right') =>
  params.angle ?? DIRECTION_ANGLE[params.direction || fallback] ?? 0;

export const TRANSITIONS = {
  cut: { ease: 'linear', draw: (ctx, A, B) => ctx.drawImage(B, 0, 0) },

  // Entering scene fades in over the opaque exiting scene. params.through: '#000' dips through a colour.
  fade: {
    ease: 'inOutSine',
    draw(ctx, A, B, p, params, env) {
      if (params.through) {
        ctx.drawImage(p < 0.5 ? A : B, 0, 0);
        ctx.globalAlpha = 1 - Math.abs(p - 0.5) * 2;
        ctx.fillStyle = params.through;
        ctx.fillRect(0, 0, env.W, env.H);
        ctx.globalAlpha = 1;
        return;
      }
      ctx.drawImage(A, 0, 0);
      ctx.globalAlpha = p;
      ctx.drawImage(B, 0, 0);
      ctx.globalAlpha = 1;
    },
  },

  // Soft focus-pull: A defocuses and drifts forward while B comes into focus on top.
  dissolve: {
    ease: 'inOutCubic',
    draw(ctx, A, B, p, params, env) {
      const blur = (params.blur ?? 16) * env.scale;
      drawScaled(ctx, A, 1 + 0.035 * p, 1, blur * p);
      drawScaled(ctx, B, 1.035 - 0.035 * p, p, blur * (1 - p));
    },
  },

  // Push through the frame: A scales up and away, B settles in from slightly small.
  zoom: {
    ease: 'inOutCubic',
    draw(ctx, A, B, p, params, env) {
      const [ox, oy] = params.center || [0.5, 0.5];
      const blur = (params.blur ?? 10) * env.scale * velocity(env.raw);
      const reverse = params.direction === 'out';
      drawScaled(ctx, A, reverse ? 1 - 0.18 * p : 1 + 0.35 * p, 1, blur, 0, 0, ox, oy);
      drawScaled(ctx, B, reverse ? 1.25 - 0.25 * p : 0.82 + 0.18 * p, clamp(p * 1.6), blur * 0.6, 0, 0, ox, oy);
    },
  },

  // Both scenes travel together; blur follows speed. params.direction: left|right|up|down (where B comes from).
  slide: {
    ease: 'inOutCubic',
    draw(ctx, A, B, p, params, env) {
      const dir = params.direction || 'right';
      const horizontal = dir === 'left' || dir === 'right';
      const size = horizontal ? env.W : env.H;
      const sign = dir === 'right' || dir === 'down' ? -1 : 1;
      const offset = sign * p * size;
      const blur = (params.blur ?? 8) * env.scale * velocity(env.raw);
      const [ax, ay] = horizontal ? [offset, 0] : [0, offset];
      const [bx, by] = horizontal ? [offset - sign * size, 0] : [0, offset - sign * size];
      drawScaled(ctx, A, 1, 1, blur, ax, ay);
      drawScaled(ctx, B, 1, 1, blur, bx, by);
    },
  },

  // Feathered wipe at any angle. params.angle (deg) or direction; params.feather (0-1); params.edge colour line.
  wipe: {
    ease: 'inOutCubic',
    draw(ctx, A, B, p, params, env) {
      ctx.drawImage(A, 0, 0);
      const { L, toCanvas } = frameFor(env, angleOf(params));
      const feather = (params.feather ?? 0.18) * L;
      const edge = lerp(-L / 2 - feather, L / 2 + feather, p);
      const { layer, c } = scratch(env, '__wipe');
      c.drawImage(B, 0, 0);
      c.globalCompositeOperation = 'destination-in';
      const [x0, y0] = toCanvas(edge - feather, 0);
      const [x1, y1] = toCanvas(edge, 0);
      const g = c.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, 'rgba(0,0,0,1)');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = g;
      c.fillRect(0, 0, env.W, env.H);
      ctx.drawImage(layer, 0, 0);
      if (params.edge) {
        const [ex0, ey0] = toCanvas(edge - feather * 0.5, -L);
        const [ex1, ey1] = toCanvas(edge - feather * 0.5, L);
        ctx.strokeStyle = params.edge;
        ctx.globalAlpha = velocity(env.raw);
        ctx.lineWidth = 3 * env.scale;
        ctx.beginPath(); ctx.moveTo(ex0, ey0); ctx.lineTo(ex1, ey1); ctx.stroke();
        ctx.globalAlpha = 1;
      }
    },
  },

  // Lens / iris: a circle grows from params.center ([x, y] in 0-1) revealing B, which zooms in
  // slightly as it opens (the "dive into the detail" move). params.ring: stroke colour for the lens rim.
  iris: {
    ease: 'inOutCubic',
    draw(ctx, A, B, p, params, env) {
      const [cx, cy] = (params.center || [0.5, 0.5]).map((v, i) => v * (i ? env.H : env.W));
      const far = Math.max(...[[0, 0], [env.W, 0], [0, env.H], [env.W, env.H]].map(([x, y]) => Math.hypot(x - cx, y - cy)));
      const start = (params.from ?? 0) * env.scale;
      const r = lerp(start, far * 1.02, p);
      drawScaled(ctx, A, 1 + 0.06 * p, 1, 0, 0, 0, cx / env.W, cy / env.H);
      const { layer, c } = scratch(env, '__iris');
      const zoom = params.zoom ?? 0.18;
      c.save();
      c.translate(cx, cy); c.scale(1 + zoom * (1 - p), 1 + zoom * (1 - p)); c.translate(-cx, -cy);
      c.drawImage(B, 0, 0);
      c.restore();
      c.globalCompositeOperation = 'destination-in';
      c.beginPath(); c.arc(cx, cy, Math.max(0.01, r), 0, Math.PI * 2); c.fill();
      if (params.shadow !== false && r > 0.5) {
        ctx.save();
        ctx.shadowColor = 'rgba(0,0,0,0.35)';
        ctx.shadowBlur = 30 * env.scale;
        ctx.drawImage(layer, 0, 0);
        ctx.restore();
      } else ctx.drawImage(layer, 0, 0);
      if (params.ring && r > 0.5) {
        ctx.strokeStyle = params.ring;
        ctx.lineWidth = (params.ringWidth ?? 4) * env.scale;
        ctx.globalAlpha = 1 - clamp((p - 0.7) / 0.3);
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
        ctx.globalAlpha = 1;
      }
    },
  },

  // Torn paper: A tears away along a ragged edge that sweeps across, revealing B underneath.
  // params.direction/angle, params.paper (edge fibre colour), params.seed.
  tear: {
    ease: 'inOutCubic',
    draw(ctx, A, B, p, params, env) {
      ctx.drawImage(B, 0, 0);
      const { L, toCanvas } = frameFor(env, angleOf(params));
      const amp = 34 * env.scale;
      const seed = params.seed ?? 7;
      const edgeU = lerp(-L / 2 - amp * 3, L / 2 + amp * 3, p);
      const steps = 90;
      const edge = [];
      for (let i = 0; i <= steps; i++) {
        const v = lerp(-L / 2, L / 2, i / steps);
        const jag = fbm(v / (140 * env.scale), 0.5, seed, 4) * amp + fbm(v / (18 * env.scale), 3.1, seed + 9, 2) * amp * 0.25;
        edge.push([edgeU + jag, v]);
      }
      const region = () => {
        ctx.beginPath();
        edge.forEach(([u, v], i) => { const [x, y] = toCanvas(u, v); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        const [x1, y1] = toCanvas(L, L / 2), [x2, y2] = toCanvas(L, -L / 2);
        ctx.lineTo(x1, y1); ctx.lineTo(x2, y2); ctx.closePath();
      };
      ctx.save();
      ctx.filter = `blur(${(14 * env.scale).toFixed(1)}px)`;
      ctx.fillStyle = 'rgba(0,0,0,0.32)';
      region(); ctx.fill();
      ctx.restore();
      ctx.save();
      region(); ctx.clip();
      ctx.drawImage(A, 0, 0);
      ctx.restore();
      ctx.save();
      ctx.strokeStyle = params.paper || '#f4eee2';
      ctx.lineJoin = 'round';
      ctx.lineWidth = 7 * env.scale;
      ctx.beginPath();
      edge.forEach(([u, v], i) => {
        const [x, y] = toCanvas(u + 2 * env.scale + Math.abs(fbm(v / (9 * env.scale), 7, seed, 2)) * 5 * env.scale, v);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      });
      ctx.stroke();
      ctx.restore();
    },
  },
};
