// S1: warm paper, paper confetti drifting at the edges, a character pops in and
// waves, and the title builds word by word. p5 draws the confetti; draw.js helpers
// draw the textures, the character, and the title.
import { EASE, SPRING, clamp } from '../engine/core.js';
import { stripes, paper, mascot, wordsIn, chapter, talk, glow, opacity, rgba } from '../engine/draw.js';
import { THEME } from '../theme.js';

const CONFETTI = [THEME.accent, THEME.accent2, '#f2b134'];

export default {
  draw(p, s) {
    const { w, h, t } = s;
    // Background keeps drifting so no frame is ever static.
    stripes(p, w, h, { colors: [THEME.paper, THEME.paperShade], width: 110, angle: -32, offset: t * 14 });
    p.blendMode(p.MULTIPLY);
    paper(p, w, h, { base: '#fbf7ef' });
    p.blendMode(p.BLEND);
    glow(p, w / 2, h * 0.62, 520, '#ffffff', 0.55);

    // Confetti frames the centre. random() is reseeded before every frame, so each piece
    // keeps its place, colour, and size; noise() of time makes it float.
    p.noStroke();
    for (let i = 0; i < 36; i++) {
      const side = i % 2 ? 1 : -1;
      const x = w / 2 + side * p.random(w * 0.36, w * 0.49), y = p.random(h * 0.08, h * 0.92);
      const size = p.random(12, 24), color = p.random(CONFETTI), delay = p.random(0.1, 0.9);
      const a = s.life(delay, 0.9, 0.4) * 0.55;
      if (a <= 0) continue;
      p.push();
      p.translate(x + (p.noise(i, t * 0.2) - 0.5) * 80, y + (p.noise(i + 40, t * 0.2) - 0.5) * 60 - t * 10);
      p.rotate((p.noise(i + 80, t * 0.15) - 0.5) * p.TWO_PI);
      p.fill(rgba(color, a));
      p.rect(-size / 2, -size / 4, size, size / 2, 2);
      p.pop();
    }

    chapter(p, s.params.chapter || '', s.life(0.15, 0.8, 0.4), { color: THEME.ink, accent: THEME.accent, family: THEME.font });

    // Character: spring pop, landing squash, wave while greeting, lip-flap while the narrator speaks.
    const pop = s.spring(0.25, SPRING.snappy);
    const land = Math.max(0, Math.sin(clamp((t - 0.25) / 0.35) * Math.PI)) * (1 - clamp((t - 0.6) / 0.3));
    const cx = w / 2, cy = h * 0.8;
    p.push();
    p.translate(cx, cy);
    p.scale(pop);
    p.translate(-cx, -cy);
    mascot(p, {
      x: cx, y: cy, size: 300, t, seed: 3, outline: THEME.ink,
      mouth: talk(t, s.speaking()), squash: land * 0.8,
      wave: s.enter(0.9, 0.3) * (1 - s.enter(2.6, 0.4)), look: [Math.sin(t * 0.7) * 0.6, 0],
      mood: 'happy',
    });
    p.pop();

    // Title: words rise and un-blur in sequence, then fade before the lens transition.
    p.push();
    opacity(p, s.exit(0.45));
    wordsIn(p, s.params.title || '', w / 2, h * 0.3, s.enter(0.55, 1.3, EASE.linear), {
      size: 92, weight: 800, family: THEME.font, color: THEME.ink, align: 'center', maxWidth: w * 0.8,
    });
    p.pop();
  },
};
