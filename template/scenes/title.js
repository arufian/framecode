// S1: warm paper, a character pops in and waves, the title builds word by word.
import { EASE, SPRING, clamp } from '../engine/core.js';
import { stripes, paper, mascot, wordsIn, chapter, talk, glow } from '../engine/draw.js';
import { THEME } from '../theme.js';

export default {
  draw(ctx, s) {
    const { w, h, t } = s;
    // Background keeps drifting so no frame is ever static.
    stripes(ctx, w, h, { colors: [THEME.paper, THEME.paperShade], width: 110, angle: -32, offset: t * 14 });
    ctx.globalCompositeOperation = 'multiply';
    paper(ctx, w, h, { base: '#fbf7ef' });
    ctx.globalCompositeOperation = 'source-over';
    glow(ctx, w / 2, h * 0.62, 520, '#ffffff', 0.55);

    chapter(ctx, s.params.chapter || '', s.life(0.15, 0.8, 0.4), { color: THEME.ink, accent: THEME.accent, family: THEME.font });

    // Character: spring pop, landing squash, wave while greeting, lip-flap while the narrator speaks.
    const pop = s.spring(0.25, SPRING.snappy);
    const land = Math.max(0, Math.sin(clamp((t - 0.25) / 0.35) * Math.PI)) * (1 - clamp((t - 0.6) / 0.3));
    const cx = w / 2, cy = h * 0.8;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(pop, pop);
    ctx.translate(-cx, -cy);
    mascot(ctx, {
      x: cx, y: cy, size: 300, t, seed: 3, outline: THEME.ink,
      mouth: talk(t, s.speaking()), squash: land * 0.8,
      wave: s.enter(0.9, 0.3) * (1 - s.enter(2.6, 0.4)), look: [Math.sin(t * 0.7) * 0.6, 0],
      mood: 'happy',
    });
    ctx.restore();

    // Title: words rise and un-blur in sequence, then fade before the lens transition.
    ctx.globalAlpha = s.exit(0.45);
    wordsIn(ctx, s.params.title || '', w / 2, h * 0.3, s.enter(0.55, 1.3, EASE.linear), {
      size: 92, weight: 800, family: THEME.font, color: THEME.ink, align: 'center', maxWidth: w * 0.8,
    });
    ctx.globalAlpha = 1;
  },
};
