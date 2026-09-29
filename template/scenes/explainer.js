// S2: night blueprint. A sketched pipeline draws itself on, box by box, synced to
// the narration; glowing packets flow along the arrows, and a callout counts up the
// frames. The camera pushes in slowly with p5 transforms.
import { EASE, clamp, lerp } from '../engine/core.js';
import { blueprint, sketch, rectPoints, callout, countUp, typewriter, chapter, pointAt, glow, rgba } from '../engine/draw.js';
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

  draw(p, s) {
    const { w, h, t, state } = s;
    blueprint(p, w, h, { bg: THEME.night, line: THEME.nightLine, drift: t * 10 });
    glow(p, w * 0.5, h * 0.55, 700, THEME.accent2, 0.18);
    chapter(p, s.params.chapter || '', s.life(0.2, 0.8, 0.4), { color: THEME.nightInk, accent: THEME.accent, family: THEME.font });
    typewriter(p, '// every frame is drawn in code', 64, 150, s.enter(0.5, 1.6, EASE.linear) * s.exit(0.3), t, {
      size: 24, color: '#8fb0ff', family: THEME.mono,
    });

    // Slow push-in keeps the frame alive; everything inside moves together.
    const zoom = lerp(1.0, 1.06, EASE.move(clamp(t / s.seconds)));
    p.push();
    p.translate(w / 2, h * 0.53);
    p.scale(zoom);
    p.translate(-w / 2, -h * 0.53);

    const speech = s.line(0);
    const pace = speech.end > speech.start ? speech : { start: 0.6, end: s.seconds - 1.2 };
    p.textFont(THEME.font);
    p.textWeight(600);
    p.textSize(36);
    p.textAlign(p.CENTER, p.CENTER);
    state.boxes.forEach((box, i) => {
      // Each box starts drawing as the narration reaches its share of the sentence.
      const start = lerp(pace.start, pace.end, i / state.boxes.length) + 0.1;
      const vis = s.exit(0.4, EASE.exit, i * 0.08);
      sketch(p, rectPoints(box.x, box.y, box.w, box.h), {
        p: EASE.move(clamp((t - start) / 0.9)), width: 3, color: rgba(THEME.nightInk, vis), seed: box.seed, t, boil: 8,
      });
      const label = EASE.enter(clamp((t - start - 0.45) / 0.6)) * vis;
      p.noStroke();
      p.fill(rgba(THEME.nightInk, label));
      p.text(box.label, box.x + box.w / 2, box.y + box.h / 2 + (1 - label) * 14);

      const arrow = state.arrows[i - 1];
      if (!arrow) return;
      const ap = EASE.move(clamp((t - start + 0.25) / 0.5));
      sketch(p, arrow.points, { p: ap, width: 3, color: rgba(THEME.accent, vis), seed: arrow.seed, t, boil: 8, double: false });
      if (ap < 0.98) return;
      const tip = pointAt(arrow.points, 1);
      p.push();
      p.translate(tip.x, tip.y);
      p.rotate(tip.angle);
      p.noFill();
      p.stroke(rgba(THEME.accent, vis));
      p.strokeWeight(3);
      p.line(-14, -9, 0, 0);
      p.line(-14, 9, 0, 0);
      p.pop();
      // Data packets ride the finished arrow, easing in and out of each box.
      p.noStroke();
      for (let k = 0; k < 2; k++) {
        const q = ((t - start) * 0.7 + k * 0.5) % 1;
        const at = pointAt(arrow.points, EASE.inOutSine(q));
        const a = Math.sin(q * Math.PI) * vis;
        p.fill(rgba(THEME.accent, 0.28 * a));
        p.circle(at.x, at.y, 26);
        p.fill(rgba('#ffd9cc', a));
        p.circle(at.x, at.y, 9);
      }
    });

    const last = state.boxes[state.boxes.length - 1];
    const calloutStart = pace.end - 0.2;
    const frames = Math.round(s.timeline.durationInFrames);
    callout(p, s.enter(calloutStart, 1.1, EASE.linear) * s.exit(0.35), {
      x: last.x + last.w * 0.72, y: last.y + last.h, tx: last.x + last.w * 0.72 + 90, ty: last.y + last.h + 120,
      label: countUp(0, frames, EASE.outCubic(clamp((t - calloutStart - 0.4) / 1.2)), { suffix: ' frames' }),
      sub: `${s.fps} every second`, color: THEME.nightInk, accent: THEME.accent, t, family: THEME.font,
    });
    p.pop();
  },
};
