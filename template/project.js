// Project definition: fonts, images, scene registry, and the persistent layers
// drawn under (background) and over (overlay) every scene. Scene keys must match
// the `component` names in storyboard.json. background/overlay draw with p5 like scenes.
import { defineProject, clamp } from './engine/core.js';
import { grain, captions, progressRing, opacity } from './engine/draw.js';
import { THEME } from './theme.js';
import title from './scenes/title.js';
import explainer from './scenes/explainer.js';
import outro from './scenes/outro.js';

const font = (pkg, file, family, weight) => ({ family, weight, src: `node_modules/@fontsource/${pkg}/files/${file}` });

export default defineProject({
  backgroundColor: THEME.paper,
  fonts: [
    font('inter', 'inter-latin-400-normal.woff2', 'Inter', 400),
    font('inter', 'inter-latin-600-normal.woff2', 'Inter', 600),
    font('inter', 'inter-latin-800-normal.woff2', 'Inter', 800),
    font('jetbrains-mono', 'jetbrains-mono-latin-500-normal.woff2', 'JetBrains Mono', 500),
  ],
  images: {
    // logo: 'assets/logo.png',
  },
  scenes: { title, explainer, outro },

  overlay(p, env) {
    const { timeline } = env.project;
    const progress = env.frame / (timeline.durationInFrames - 1);
    p.push();
    opacity(p, clamp(env.t / 0.6));
    progressRing(p, progress, { x: env.w - 78, y: 72, r: 15, color: THEME.accent, track: 'rgba(128,128,128,0.35)' });
    p.pop();
    if (timeline.captions) captions(p, env, { family: THEME.font, box: 'rgba(20,20,24,0.62)', colors: { narrator: '#ffffff' } });
    grain(p, env.w, env.h, env.frame, { amount: 0.045 });
  },
});
