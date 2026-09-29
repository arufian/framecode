// S2: night blueprint. A sketched pipeline draws itself on, box by box, synced to
// the narration; a callout counts up the frames. The camera drifts in slowly.
import { EASE, clamp, lerp } from '../engine/core.js';
import { blueprint, sketch, rectPoints, text, callout, countUp, typewriter, chapter, camera, pointAt, glow } from '../engine/draw.js';
import { THEME } from '../theme.js';

export default {
  setup({ w, h, params }) {
    // Layout is computed once; draw() only animates it.
    const steps = params.steps || ['Script', 'Voice + music', 'Frames'];
    const boxW = 330, boxH = 150, gap = 150;
    const total = steps.length * boxW + (steps.length - 1) * gap;
    const x0 = (w - total) / 2, y = h * 0.47;
    return {
      boxes: steps.map((label, i) => ({ label, x: x0 + i * (boxW + gap), y, w: boxW, h: boxH, seed: 11 + i * 7 })),
      arrows: steps.slice(1).map((_, i) => {
        const ax = x0 + i * (boxW + gap) + boxW + 18, bx = ax + gap - 36, ay = y + boxH / 2;
        return { points: [[ax, ay], [lerp(ax, bx, 0.5), ay - 16], [bx, ay]], seed: 40 + i };
      }),
    };
  },

  draw(ctx, s) {
    const { w, h, t, state } = s;
    blueprint(ctx, w, h, { bg: THEME.night, line: THEME.nightLine, drift: t * 10 });
    glow(ctx, w * 0.5, h * 0.55, 700, THEME.accent2, 0.18);
    chapter(ctx, s.params.chapter || '', s.life(0.2, 0.8, 0.4), { color: THEME.nightInk, accent: THEME.accent, family: THEME.font });
    typewriter(ctx, '// every frame is drawn in code', 64, 150, s.enter(0.5, 1.6, EASE.linear) * s.exit(0.3) , t, {
      size: 24, color: '#8fb0ff', family: THEME.mono,
    });

    // Slow push-in keeps the frame alive; everything inside moves together.
    const zoom = lerp(1.0, 1.06, EASE.move(clamp(t / s.seconds)));
    camera(ctx, w, h, { x: w / 2, y: h * 0.53, zoom }, () => {
      const speech = s.line(0);
      const pace = speech.end > speech.start ? speech : { start: 0.6, end: s.seconds - 1.2 };
      state.boxes.forEach((box, i) => {
        // Each box starts drawing as the narration reaches its share of the sentence.
        const start = lerp(pace.start, pace.end, i / state.boxes.length) + 0.1;
        const draw = EASE.move(clamp((t - start) / 0.9));
        const vis = s.exit(0.4, EASE.exit, i * 0.08);
        ctx.globalAlpha = vis;
        sketch(ctx, rectPoints(box.x, box.y, box.w, box.h), { p: draw, width: 3, color: THEME.nightInk, seed: box.seed, t, boil: 8 });
        const label = EASE.enter(clamp((t - start - 0.45) / 0.6));
        text(ctx, box.label, box.x + box.w / 2, box.y + box.h / 2 + 12 + (1 - label) * 14, {
          size: 36, weight: 600, family: THEME.font, color: THEME.nightInk, align: 'center', alpha: label,
        });
        const arrow = state.arrows[i - 1];
        if (arrow) {
          const ap = EASE.move(clamp((t - start + 0.25) / 0.5));
          sketch(ctx, arrow.points, { p: ap, width: 3, color: THEME.accent, seed: arrow.seed, t, boil: 8, double: false });
          if (ap > 0.98) {
            const tip = pointAt(arrow.points, 1);
            ctx.save();
            ctx.translate(tip.x, tip.y); ctx.rotate(tip.angle);
            ctx.strokeStyle = THEME.accent; ctx.lineWidth = 3; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(-14, -9); ctx.lineTo(0, 0); ctx.lineTo(-14, 9); ctx.stroke();
            ctx.restore();
          }
        }
        ctx.globalAlpha = 1;
      });

      const last = state.boxes[state.boxes.length - 1];
      const calloutStart = pace.end - 0.2;
      const p = s.enter(calloutStart, 1.1, EASE.linear) * s.exit(0.35);
      const frames = Math.round(s.timeline.durationInFrames);
      callout(ctx, p, {
        x: last.x + last.w * 0.72, y: last.y + last.h, tx: last.x + last.w * 0.72 + 90, ty: last.y + last.h + 120,
        label: countUp(0, frames, EASE.outCubic(clamp((t - calloutStart - 0.4) / 1.2)), { suffix: ' frames' }),
        sub: `${s.fps} every second`, color: THEME.nightInk, accent: THEME.accent, t, family: THEME.font,
      });
    });
  },
};
