// S3: end card. The character talks, the title lands with an underline that
// draws on, and the subtitle follows. Breathing and boiling lines keep it alive.
import { EASE, SPRING, clamp } from '../engine/core.js';
import { paper, stripes, mascot, text, sketch, talk, chapter, glow } from '../engine/draw.js';
import { THEME } from '../theme.js';

export default {
  draw(ctx, s) {
    const { w, h, t } = s;
    stripes(ctx, w, h, { colors: [THEME.paper, THEME.paperShade], width: 110, angle: -32, offset: 400 + t * 14 });
    ctx.globalCompositeOperation = 'multiply';
    paper(ctx, w, h, { base: '#fbf7ef', seed: 5 });
    ctx.globalCompositeOperation = 'source-over';
    glow(ctx, w * 0.62, h * 0.5, 640, '#ffffff', 0.5);
    chapter(ctx, s.params.chapter || '', s.enter(0.5, 0.8), { color: THEME.ink, accent: THEME.accent, family: THEME.font });

    const enter = s.spring(0.35, SPRING.gentle);
    mascot(ctx, {
      x: w * 0.25 - (1 - enter) * 120, y: h * 0.78, size: 320, t, seed: 3, outline: THEME.ink,
      mouth: talk(t, s.speaking()), look: [0.8, -0.2], mood: 'happy', wave: s.enter(1.2, 0.4) * 0.8,
    });

    const titleP = s.enter(0.6, 0.9);
    const x = w * 0.43, y = h * 0.47;
    const drawn = text(ctx, s.params.title || '', x, y + (1 - titleP) * 30, {
      size: 120, weight: 800, family: THEME.font, color: THEME.ink, alpha: titleP,
    });
    sketch(ctx, [[x, y + 34], [x + drawn.width * 0.5, y + 44], [x + drawn.width, y + 30]], {
      p: EASE.move(clamp((t - 1.1) / 0.7)), width: 8, color: THEME.accent, seed: 9, t, boil: 6, double: false,
    });
    text(ctx, s.params.subtitle || '', x, y + 120, {
      size: 40, weight: 400, family: THEME.font, color: THEME.ink, alpha: 0.75 * s.enter(1.5, 0.8),
    });
  },
};
