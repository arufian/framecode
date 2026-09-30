// Example: Mixkit footage as the world, code-drawn craft on top. Not registered in the
// starter project.js; copy the pattern when a scene uses footage or art. The clip fills
// the frame with a slow push-in, a palette grade and vignette tie it to the theme, an
// art card slides in beside the title, and grain sits over everything (project overlay).
// params: { clip: 'city', art: 'hero', from: 0, title, subtitle }
import { EASE, clamp, lerp } from '../engine/core.js';
import { footage, vignette, wordsIn, roundRect, opacity, setBlur, rgba } from '../engine/draw.js';
import { THEME } from '../theme.js';

export default {
  draw(p, s) {
    const { w, h, t, params } = s;
    const clip = s.assets.footage[params.clip];
    const zoom = lerp(1.0, 1.05, EASE.move(clamp(t / s.seconds)));
    p.push();
    p.translate(w / 2, h / 2);
    p.scale(zoom);
    p.translate(-w / 2, -h / 2);
    footage(p, clip, t, 0, 0, w, h, { from: params.from || 0 });
    p.pop();

    // Grade: darken toward the theme's night colour so type reads and the footage matches the palette.
    const ctx = p.drawingContext;
    const grade = ctx.createLinearGradient(0, 0, w * 0.8, 0);
    grade.addColorStop(0, rgba(THEME.night, 0.82));
    grade.addColorStop(1, rgba(THEME.night, 0.12));
    ctx.fillStyle = grade;
    ctx.fillRect(0, 0, w, h);
    vignette(p, w, h, { strength: 0.5 });

    const art = params.art && s.assets.images[params.art];
    if (art) {
      const a = s.life(0.5, 0.9, 0.5);
      const cw = 440, ch = cw * (art.height / art.width);
      const x = w - cw - 150, y = (h - Math.min(ch, h * 0.7)) / 2 + (1 - a) * 40;
      p.push();
      opacity(p, a);
      setBlur(p, 6 * (1 - a));
      roundRect(p, x, y, cw, Math.min(ch, h * 0.7), 28);
      ctx.save();
      ctx.clip();
      p.image(art, x, y, cw, ch);
      ctx.restore();
      p.pop();
    }

    const title = wordsIn(p, params.title || '', 150, h * 0.36, s.enter(0.3, 1.0) * s.exit(0.5), {
      size: 84, weight: 800, family: THEME.font, color: '#ffffff', maxWidth: w * 0.45,
    });
    wordsIn(p, params.subtitle || '', 150, h * 0.36 + title.height + 24, s.enter(0.8, 1.0) * s.exit(0.5), {
      size: 34, weight: 400, family: THEME.font, color: 'rgba(255,255,255,0.8)', maxWidth: w * 0.5,
    });
  },
};
