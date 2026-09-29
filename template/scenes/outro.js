// S3: end card. The character talks, the title lands with an underline that draws
// on, a small spark burst marks the moment, and the subtitle follows. Breathing and
// boiling lines keep it alive.
import { EASE, SPRING, clamp } from '../engine/core.js';
import { paper, stripes, mascot, sketch, talk, chapter, glow, rgba } from '../engine/draw.js';
import { THEME } from '../theme.js';

export default {
  draw(p, s) {
    const { w, h, t } = s;
    stripes(p, w, h, { colors: [THEME.paper, THEME.paperShade], width: 110, angle: -32, offset: 400 + t * 14 });
    p.blendMode(p.MULTIPLY);
    paper(p, w, h, { base: '#fbf7ef', seed: 5 });
    p.blendMode(p.BLEND);
    glow(p, w * 0.62, h * 0.5, 640, '#ffffff', 0.5);
    chapter(p, s.params.chapter || '', s.enter(0.5, 0.8), { color: THEME.ink, accent: THEME.accent, family: THEME.font });

    const enter = s.spring(0.35, SPRING.gentle);
    mascot(p, {
      x: w * 0.25 - (1 - enter) * 120, y: h * 0.78, size: 320, t, seed: 3, outline: THEME.ink,
      mouth: talk(t, s.speaking()), look: [0.8, -0.2], mood: 'happy', wave: s.enter(1.2, 0.4) * 0.8,
    });

    // Title in p5 type: weight 800 from the Inter faces registered in project.js.
    const titleP = s.enter(0.6, 0.9);
    const title = s.params.title || '';
    const x = w * 0.43, y = h * 0.47;
    p.noStroke();
    p.textFont(THEME.font);
    p.textWeight(800);
    p.textSize(120);
    p.textAlign(p.LEFT, p.BASELINE);
    p.fill(rgba(THEME.ink, titleP));
    p.text(title, x, y + (1 - titleP) * 30);
    const width = p.textWidth(title);

    const underline = EASE.move(clamp((t - 1.1) / 0.7));
    sketch(p, [[x, y + 34], [x + width * 0.5, y + 44], [x + width, y + 30]], {
      p: underline, width: 8, color: THEME.accent, seed: 9, t, boil: 6, double: false,
    });

    // Spark burst where the underline lands: seeded angles, eased outward travel.
    const burst = EASE.outCubic(clamp((t - 1.65) / 0.7));
    const fade = 1 - clamp((t - 1.9) / 0.5);
    if (burst > 0 && fade > 0) {
      const bx = x + width + 18, by = y + 22;
      p.stroke(rgba(THEME.accent, fade));
      p.strokeWeight(5);
      p.strokeCap(p.ROUND);
      for (let i = 0; i < 7; i++) {
        const a = -Math.PI * (0.05 + (0.55 * i) / 6) + p.random(-0.08, 0.08);
        const r0 = 22 + burst * 34, r1 = r0 + 22 * (1 - 0.6 * burst);
        p.line(bx + Math.cos(a) * r0, by + Math.sin(a) * r0, bx + Math.cos(a) * r1, by + Math.sin(a) * r1);
      }
    }

    p.noStroke();
    p.textWeight(400);
    p.textSize(40);
    p.fill(rgba(THEME.ink, 0.75 * s.enter(1.5, 0.8)));
    p.text(s.params.subtitle || '', x, y + 120);
  },
};
