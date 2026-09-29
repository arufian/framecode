# Motion: making it feel smooth

Smoothness is not frame rate alone. The reference videos that feel best (see `style.md`) run at 24 fps and still read as silky because every movement is eased, layered, continuous, and in sync with sound. At 60 fps (this skill's default) the same craft looks even better. This file turns that into rules and copy-ready recipes.

## The ten rules

1. **Drive everything from time.** `s.t`, `s.frame`, or helpers built on them. No `Date`, `Math.random`, timers, CSS animations. Fractional frames must work.
2. **Ease every change.** Entrances decelerate (`EASE.enter`, springs), exits accelerate (`EASE.exit`), moves are symmetric (`EASE.move`). Linear only for constant motion: drifts, parallax scrolls, grain, a rotating radar sweep.
3. **Nothing pops in or out.** Minimum 0.25 s for any appearance/disappearance; heroes get 0.6–1.0 s.
4. **Layer the entrance.** Opacity alone looks cheap. Combine opacity with travel (12–40 px), blur (6→0 px), and optionally scale (0.96→1).
5. **Stagger siblings.** 60–120 ms between items; words in a sentence via `wordsIn`; never animate a whole group as one block.
6. **Overlap, don't queue.** The next element starts before the previous finishes (start at 40–60 % of the previous animation).
7. **Keep every frame alive.** Ambient motion in every scene: slow camera push, parallax drift, breathing/blinking characters, boiling hand-drawn lines, floating particles, grain.
8. **Transition inside the world when you can.** The best transitions are continuous: a lens opens on a detail and becomes the next scene; paper tears; a pencil draws the next world; the frame shrinks into a device. Otherwise use the engine's eased transitions; plan hard cuts only for rhythm, on a beat.
9. **Sync to sound.** Visual beats land on musical beats (the timeline snaps transitions); things appear when the narration names them; SFX hit their visual moment.
10. **Hold long enough to read.** Words ÷ 3 + 1 seconds on screen for any text block.

## Timing tokens (seconds)

| Use | Duration | Curve |
|-----|----------|-------|
| micro (tick, dot, underline) | 0.2–0.35 | `EASE.enter` |
| element entrance | 0.5–0.9 | `EASE.enter` or `SPRING.gentle` |
| hero entrance | 0.8–1.2 | `EASE.enter` + blur |
| exit | 0.35–0.5 | `EASE.exit` |
| move / reposition | 0.6–1.0 | `EASE.move` |
| scene transition | 0.6–1.1 | per type (engine default) |
| stagger step | 0.06–0.12 | — |
| camera push per scene | ≤ 6 % zoom over the scene | `EASE.move` |

## Recipes

### Layered entrance with exit

```js
import { EASE, clamp, lerp } from '../engine/core.js';
import { text, setBlur } from '../engine/draw.js';

const p = s.enter(0.4, 0.8);          // 0 -> 1 starting 0.4 s into the scene
const out = s.exit(0.45);             // 1 -> 0 finishing at the transition midpoint
ctx.save();
ctx.globalAlpha = p * out;
setBlur(ctx, (1 - p) * 6);            // design px; scaled for the output size (raw ctx.filter is not)
ctx.translate(0, (1 - p) * 28);
text(ctx, 'Evaporation', 120, 300, { size: 84, weight: 800, family: THEME.font, color: THEME.ink });
ctx.restore();
```

### Staggered list

```js
items.forEach((item, i) => {
  const p = s.enter(0.6 + i * 0.09, 0.7) * s.exit(0.4, EASE.exit, (items.length - i) * 0.05);
  ctx.globalAlpha = p;
  text(ctx, item, 160 + (1 - p) * -24, 360 + i * 72, { size: 40, family: THEME.font, color: THEME.ink });
});
ctx.globalAlpha = 1;
```

### Sentence build

```js
wordsIn(ctx, s.params.title, s.w / 2, s.h * 0.3, s.enter(0.5, 1.3, EASE.linear), {
  size: 96, weight: 800, align: 'center', maxWidth: s.w * 0.8, family: THEME.font, color: THEME.ink,
});
```

(`p` is linear on purpose here: each word eases itself.)

### Spring pop with landing squash (characters, badges)

```js
const pop = s.spring(0.25, SPRING.snappy);
const land = Math.max(0, Math.sin(clamp((s.t - 0.25) / 0.35) * Math.PI)) * (1 - clamp((s.t - 0.6) / 0.3));
ctx.translate(x, y); ctx.scale(pop, pop); ctx.translate(-x, -y);
mascot(ctx, { x, y, size: 280, t: s.t, squash: land * 0.8, mouth: talk(s.t, s.speaking()) });
```

### Reveal on the words that name it

```js
const line = s.line(0);                          // this scene's first voice line
const at = lerp(line.start, line.end, 0.55);     // ~ when the key word is spoken
const p = s.enter(at, 0.7);
```

For exact word timing, split the narration into more lines in the storyboard (each line gets its own start time), or use the line's `at` field.

### Draw-on illustration

```js
sketch(ctx, rectPoints(x, y, 320, 150), { p: EASE.move(clamp((s.t - 1.0) / 0.9)), width: 3, color: THEME.ink, seed: 4, t: s.t, boil: 8 });
sketch(ctx, circlePoints(cx, cy, 60), { p: s.enter(1.4, 0.6, EASE.move), width: 4, color: THEME.accent, seed: 9 });
```

### Camera push and parallax (depth without 3D)

```js
const cam = { x: s.w / 2 + lerp(0, 60, EASE.move(clamp(s.t / s.seconds))), y: s.h / 2,
              zoom: lerp(1, 1.05, EASE.move(clamp(s.t / s.seconds))) };
parallax(ctx, s.w, s.h, cam, 0.2, () => drawMountains(ctx));   // far: moves little
parallax(ctx, s.w, s.h, cam, 0.6, () => drawHills(ctx));
parallax(ctx, s.w, s.h, cam, 1.0, () => drawSubject(ctx));     // near: moves with the camera
```

### Lens dive into a detail (in-world transition)

Put the subject's position in the storyboard: `"transition_out": { "type": "iris", "center": [0.62, 0.55], "ring": "#e4572e" }`. Draw a small inset circle on the subject in the last second of the scene (a callout that "is" the lens) so the iris opens exactly from it.

### Continuous counters and data

```js
const v = EASE.outCubic(clamp((s.t - 1.2) / 1.6));
text(ctx, countUp(0, 20998, v, { prefix: '≈ ', suffix: ' km³' }), x, y, { size: 64, weight: 700, family: THEME.font });
```

### Ambient life checklist (pick at least two per scene)

- background offset drifting (`stripes` `offset: s.t * 12`, `blueprint` `drift: s.t * 10`)
- camera push ≤ 6 % across the scene
- character breathing/blinking (built into `mascot`), eyes following the action (`look`)
- boiling outlines (`boil: 6–10`)
- floating particles with `noise2(i, s.t * 0.3)` offsets
- progress ring / timers in the overlay
- grain in the overlay

## Transitions: choosing

| Moment | Transition |
|--------|------------|
| zooming into a detail, cause → mechanism | `iris` centred on the subject (with `ring`) |
| next step in a sequence | `slide` (direction of reading) or `wipe` with `edge` |
| change of world/tone (day → night, macro → micro) | `dissolve` or `zoom` |
| handmade / paper aesthetic | `tear` |
| calm, editorial | `fade` (0.6–0.8 s) |
| rhythmic montage | planned `cut`s on the beat, with a `tick` or `impact` SFX |

Keep one or two transition types as the video's vocabulary, plus one special move for the key moment; mixing all eight looks cheap.

## Anti-patterns → fixes

| Looks wrong | Fix |
|-------------|-----|
| Element appears on a hard frame | wrap in `s.enter` / `s.life` |
| Everything enters at once | stagger 60–120 ms |
| Linear slide that stops dead | `EASE.enter` / `EASE.move` |
| Bouncy overshoot on serious content | `SPRING.gentle` or `EASE.enter` |
| Scene goes still while narration continues (QC "frozen") | add ambient motion, or `"hold": true` if intentional |
| Transition flashes darker mid-way | keep the exiting scene opaque (engine transitions already do) |
| Text jitters when moving slowly | move whole blocks with transforms; avoid re-wrapping text every frame |
| Studio preview stutters | move static drawing to `setup()` or cached textures; reduce blur radius/count |
| Content vanishes before a tear/iris | exit later (`s.exit(dur, EASE.exit, lead)`), or keep it for the transition to carry |
