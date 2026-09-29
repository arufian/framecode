---
name: framecode
description: Produce a brand-new video end to end with a coding agent, with every frame, animation, music bed, and sound effect generated in code (no Remotion, HyperFrames, or other video frameworks; no stock media). Interviews the user (including voice-over via ElevenLabs, Kokoro, or Coqui TTS; generated music; generated sound effects; and a do-not list), writes a storyboard plan, confirms it, builds smooth animated scenes as p5.js sketches on a bundled engine, lets the user review everything in a live studio with notes, asks the output size, renders to MP4, and loops on fixes. Use when the user wants to create a video, explainer, animation, or motion graphic from scratch.
---

# Video Builder

Build a new video from user requirements through reviewed, verified delivery.

This workflow is coding-agent agnostic. Use the host agent's available tools and obey its current mode, tool schemas, and permission rules.

Workflow: interview → plan → confirm → scaffold → audio → build scenes → self-check → **studio review** → **ask render size** → render → fix loop → done.

Everything on screen and in the soundtrack is made by code the agent writes:

- **Visuals**: scenes are p5.js sketches (p5 2.x) on the bundled engine (`template/engine/`), which owns the timeline, the clock, transitions, and compositing. The browser studio runs them live; the renderer runs the same page in headless Chrome (Puppeteer) and pipes frames to ffmpeg. p5.js is the only drawing library: do not use Remotion, HyperFrames, Motion Canvas, Manim, or any other video/animation framework (GSAP, three.js, anime.js), and do not use stock footage, stock images, or AI image generators. User-supplied assets (logo, photos, character art) are the only external visuals.
- **Music and SFX**: synthesized by `scripts/gen_music.py` and `scripts/gen_sfx.py` (numpy oscillators and noise, royalty-free by construction).
- **Voice-over**: ElevenLabs (API), Kokoro (local), or Coqui (local), through `scripts/voiceover.py`.

No architecture diagrams, flowcharts, sequence diagrams, or UI mockups are produced in this skill: the storyboard text, the studio, and rendered stills replace them.

Resolve `VIDEO_SKILL_DIR` to the absolute directory containing this `SKILL.md`. Run project commands from the new video project's root. Bash syntax below is illustrative.

---

## Language rule (applies to EVERY phase)

- All communication with the user and all planning artifacts (`VIDEO_PLAN.md`, `storyboard.json` keys and ids, code, comments, commit messages) are in **English**, regardless of the language the user writes in.
- The video's **narration, on-screen text, and captions** use the language chosen in the interview (default: English). Never mix in a language the user did not choose. No Chinese text anywhere unless the user explicitly chose Chinese for the video.
- Non-Latin video text needs a font that covers it: add a matching `@fontsource` package (for example `@fontsource/noto-sans-jp`) or a user-supplied font file to `project.js`. Kokoro Japanese/Mandarin voices need `misaki[ja]` / `misaki[zh]`.

---

## Phase 1 — Interview (relentless)

Goal: understand the whole video before writing anything. Do NOT write the plan until no open questions remain. Do not assume — ask.

### How to interview

- Select the interview mechanism from tools actually exposed in the current session; never call a tool just because its name appears here.
  - Claude Code: use `AskUserQuestion` when available, with at most 4 questions per call.
  - Codex: use `request_user_input` only when exposed and permitted in the current mode, with at most 3 questions per call; otherwise ask in chat.
  - Other hosts, or no suitable tool: ask numbered questions in chat and wait for the answer.
- Prefer multiple-choice options with free-text allowed. Do not add an "Other" option if the host already provides one. Follow the tool's option-count and field limits; split batches across calls when needed.
- An asynchronous question is not an answer. Never infer answers or approval from a timeout, an empty response, or a preselected option.
- Summarize what you have captured between rounds. Probe vague answers ("something modern", "like Apple") in the next round.

### Round 1 — the video itself

Purpose and audience, where it will be published (YouTube, X, TikTok/Reels, website, internal), target length, aspect ratio (16:9, 9:16, 1:1, 4:5), and visual style direction. If the user shares reference videos, analyze them (see `references/style.md` → "Studying reference videos") before proposing a style.

Do NOT ask for the output resolution here — that question comes right before rendering (Phase 9). Design size is fixed by the aspect ratio (1920×1080, 1080×1920, 1080×1080, 1080×1350).

### Round 2 — the four required questions (always ask all four, in one round when the tool allows)

1. **Voice-over** — "Do you want a voice-over?"
   - `No voice-over`
   - `Yes — ElevenLabs` (needs your API key; most natural voices)
   - `Yes — Kokoro TTS` (free, runs locally, Apache-2.0, recommended local option)
   - `Yes — Coqui TTS` (free, runs locally)
2. **Music** — "Do you want background music? It is composed and synthesized by code for this video (original, royalty-free)."
   - `No music` · `Yes — calm / ambient` · `Yes — upbeat / corporate` · `Yes — cinematic` (free text: lo-fi, electronic)
3. **Sound effects** — "Do you want sound effects? They are synthesized by code."
   - `No sound effects` · `Yes — subtle (transitions only)` · `Yes — moderate (transitions + key reveals)` · `Yes — rich (UI clicks, pops, risers, impacts)`
4. **Exclusions** — "What styles or things do you NOT want in the video?" (multi-select, free text encouraged)
   - `Emojis / cartoonish icons` · `Bouncy or cheesy transitions` · `Neon or oversaturated colors` · `Dense walls of text`

Record every exclusion as a numbered do-not item (`DN-1`, `DN-2`, …). If the user says "nothing", record `DN: none stated`.

### Round 3 — follow-ups driven by the answers

- **ElevenLabs chosen** → get the API key (rules below), validate it, then pick voices.
- **Kokoro or Coqui chosen** → check `preflight.py`; install if missing (commands in `references/audio.md`); pick a voice per speaker; for Coqui XTTS, tell the user it is under the non-commercial Coqui Public Model License and only proceed with XTTS if they accept.
- **Voice details** → narrator only, or dialogue with characters (one voice per speaker); voice character (gender, age, tone, pace); who writes the script (user or agent); burned-in captions yes/no.
- **Music chosen** → energy arc (calm throughout / build to a peak / punchy), tempo feel.
- **SFX chosen** → any signature moments (a logo sting, a counter, a reveal).

**ElevenLabs API key rules** (never break these):

1. First check `ELEVENLABS_API_KEY` in the environment and in the project's `.env` (`preflight.py` reports presence without printing it).
2. If absent, ask the user for it. Offer the safer path first: they can write it themselves with `! printf 'ELEVENLABS_API_KEY=%s\n' 'PASTE_KEY' >> .env` (Claude Code runs `!` commands in-session). If they paste it in chat, write it to `.env` yourself.
3. `.env` must be gitignored (the template's `.gitignore` does this) and `chmod 600`. Never echo, print, log, or commit the key; never write it into `VIDEO_PLAN.md`, `storyboard.json`, code, or reports.
4. Validate with `python3 "$VIDEO_SKILL_DIR/scripts/voiceover.py" --check`. On a 401 ask for a corrected key; on quota/plan errors (402/429) offer to wait or switch to Kokoro.
5. Mention that ElevenLabs' free tier requires attribution and is non-commercial; commercial use needs a paid plan.

### Round 4 — as needed

Brand assets (logo, colors, fonts, images), characters or mascots, facts/data to show, calls to action, deadline, licensing (commercial use affects TTS choice).

### Must cover

1. Purpose, audience, platform, success criteria.
2. Length, aspect ratio, frame rate (default 60 fps for the smoothest motion; 30/24 only on request).
3. Structure: the beats/scenes and the one idea each carries; hook in the first 3 seconds; ending.
4. Visual style: world(s), palette, typography, texture, characters, motion character (calm/elegant vs energetic/punchy).
5. Language of narration and on-screen text; captions.
6. The four required answers (voice-over, music, SFX, do-not list).
7. Assets supplied by the user and any constraints (brand rules, legal lines, deadline).

Exit condition: you can restate the video in 3–4 sentences (what it says, to whom, how it looks and sounds, how long) and the user confirms it matches their intent.

---

## Phase 2 — Plan

Write `VIDEO_PLAN.md` (human plan) and `storyboard.json` (machine storyboard the scripts read) in the project root. Keep them in sync: when one changes, update the other.

`VIDEO_PLAN.md` structure:

```markdown
# <Title> — Video Plan

## Overview
<3–4 sentence restatement confirmed in the interview.>

## Format
- Aspect / design size / fps / target length / language / captions

## Style
- Visual world(s), palette (hex values), typography, textures, characters, motion character.

## Do-not list
- [DN-1] ...

## Audio
- Voice-over: backend, voice per speaker, pace (or "none")
- Music: style, bpm, key, energy arc (or "none")
- SFX: density, signature moments (or "none")

## Storyboard
| ID | Min length | Visual (what is drawn, what moves) | On-screen text | Narration (speaker: line) | Transition out | SFX |
|----|-----------|-------------------------------------|----------------|---------------------------|----------------|-----|
| S1 | 4.5 s | ... | ... | narrator: ... | iris on the mascot | pop, whoosh |

## Motion plan
- Entrances/exits, camera moves, transitions per boundary, beat sync, voice sync, ambient motion per scene.

## Acceptance criteria
- [ ] AC-1 <checkable statement; map to scene IDs and DN items>
```

Every scene must map to at least one acceptance criterion; every DN item must be checked in the Phase 7 self-check.

`storyboard.json` schema (see `template/storyboard.json` for a complete example):

```json
{
  "title": "…", "language": "en",
  "format": { "aspect": "16:9", "width": 1920, "height": 1080, "fps": 60 },
  "captions": true, "snap": "beat",
  "audio": {
    "voiceover": { "backend": "kokoro|elevenlabs|coqui", "voices": { "narrator": "af_heart" }, "speed": 1.0, "model": null, "lang": null },
    "music": { "style": "ambient|corporate|lofi|cinematic|electronic", "bpm": 90, "key": "D", "seed": 7 },
    "sfx": { "density": "subtle|moderate|rich" }
  },
  "scenes": [
    { "id": "S1", "component": "title", "min_seconds": 4.5, "energy": 0.35,
      "params": { "any": "data the scene draws" },
      "lines": [ { "speaker": "narrator", "text": "Shown in captions.", "say": "Optional pronunciation override.", "at": null, "gap_after": 0.25 } ],
      "transition_out": { "type": "cut|fade|dissolve|zoom|slide|wipe|iris|tear", "seconds": 1.0, "...": "type params" },
      "sfx": [ { "type": "whoosh", "at": "transition_out|transition_in|start|end|line:1|<seconds>", "gain_db": null } ] }
  ]
}
```

Set `audio.voiceover`, `audio.music`, or `audio.sfx` to `null` when the user declined it. Omit a scene's `sfx` to get automatic cues from the density; give `[]` for none.

---

## Phase 3 — User confirmation

Present:

1. **Plan summary** — overview, format, style, do-not list, audio plan, and the storyboard table (short; full detail lives in `VIDEO_PLAN.md`).
2. **Audio previews** (when audio was requested) — generate and give paths plus a play command (`afplay` on macOS, `ffplay -autoexit` elsewhere):
   - one voice sample per speaker: `voiceover.py --backend <b> --voice <v> --sample "<first line>" --out public/vo/_sample-<speaker>.wav`
   - a 20-second music sample: `gen_music.py --style <s> --bpm <n> --key <k> --duration 20 --out public/music/_sample.wav`
   - SFX previews: `gen_sfx.py --all --outdir public/sfx/_preview`

Then ask: approve this plan and start production? Options: yes / revise (loop back to Phase 1 or 2) / stop. Do not scaffold or build without explicit approval.

---

## Phase 4 — Scaffold

```bash
cp -R "$VIDEO_SKILL_DIR/template/." .
npm install --save-exact p5@2 puppeteer @fontsource/inter @fontsource/jetbrains-mono   # plus fonts the plan needs
python3 "$VIDEO_SKILL_DIR/scripts/preflight.py"
```

- `preflight.py` must pass (Node ≥ 22.12, ffmpeg + ffprobe, Python ≥ 3.9 with numpy + scipy, and in the project: p5.js, Puppeteer, headless Chrome). Node installed through nvm is often a lazy shell function that subprocesses cannot see; preflight prints the real binary — prefix commands with `PATH=<its dir>:$PATH` when needed.
- Installing Puppeteer downloads `chrome-headless-shell` once (~200 MB, cached in `~/.cache/puppeteer`; the template's `.puppeteerrc.cjs` skips the full Chrome). If the download is blocked, run `npx puppeteer browsers install chrome-headless-shell` later, or point `FRAMECODE_BROWSER` (or `render.js --browser`) at an installed Chrome/Chromium.
- Replace the example `storyboard.json` with the planned one, set the palette in `theme.js`, register fonts and user images in `project.js`, and remove example scenes the plan does not use.
- Local TTS: create a project-local environment as shown in `references/audio.md` (`.venv-tts`), then run `voiceover.py` with that interpreter.

---

## Phase 5 — Audio production (audio drives timing)

Run in this order; each step reads what the previous one wrote. Use the TTS interpreter (for example `.venv-tts/bin/python`) for step 1 when Kokoro or Coqui is the backend.

```bash
python3 "$VIDEO_SKILL_DIR/scripts/voiceover.py" --storyboard storyboard.json --out public/vo   # skip if no voice-over
python3 "$VIDEO_SKILL_DIR/scripts/timeline.py"            # add --estimate when there is no voice-over
python3 "$VIDEO_SKILL_DIR/scripts/gen_music.py" --timeline src/timeline.json    # skip if no music
python3 "$VIDEO_SKILL_DIR/scripts/gen_sfx.py" --timeline src/timeline.json      # skip if no SFX
python3 "$VIDEO_SKILL_DIR/scripts/mix_audio.py"           # skip only when there is no audio at all
```

- `timeline.py` sizes every scene to fit its lines (plus lead-in, tail, and both transitions), snaps transition midpoints and the ending to the music's beat grid, places captions, and computes SFX sync frames. `src/timeline.json` is the single source of truth for the engine and the mixer.
- `mix_audio.py` ducks music under speech and masters to -14 LUFS / -1.5 dBTP (`--lufs`, `--tp`, `--music-db`, `--duck-db`, `--sfx-db` to rebalance).
- Voice lines are cached by content; only changed lines are regenerated (important with ElevenLabs credits).
- When something changes, re-run from the first affected step: script/voices → all five; music only → music + mix; SFX only → SFX + mix; visuals only → nothing.
- If whisper is installed (`mlx_whisper` or `whisper`), transcribe one or two lines and compare them with the script to catch mispronunciations; fix with the line's `say` field.

---

## Phase 6 — Build the scenes in code

Before writing scene code, read `references/engine.md` (API, including "p5 in scenes"), `references/motion.md` (motion rules and recipes), and `references/style.md` (visual craft). Then write one module in `scenes/` per storyboard `component`.

- A scene is `{ setup?(info), draw(p, s) }`. `setup` computes layout once; `draw` paints one frame with the p5 instance `p` from the scene context `s` (`s.t`, `s.frame`, `s.enter()`, `s.exit()`, `s.life()`, `s.spring()`, `s.line(n)`, `s.speaking()`, `s.params`, `s.state`, …).
- Draw with p5 (`p.fill`, `p.circle`, `p.beginShape`, `p.translate`, `p.noise`, `p.text`, …) and the `engine/draw.js` helpers, which take `p` too (`paper(p, …)`, `sketch(p, …)`, `mascot(p, …)`, `wordsIn(p, …)`); they mix freely and share transforms.
- Draw everything procedurally: paths, gradients, textures, characters, text. Build illustrations in layers (background, midground, subject, foreground, chrome) the way the references in `references/style.md` do; a flat slide with a fading title is not the bar.
- Persistent chrome (progress ring, captions, grain) lives in `project.js` `overlay`; per-scene chrome (chapter label) lives in the scene so it transitions with it.
- Honor every DN item. Keep all motion frame-driven and deterministic.

### p5 rules (mandatory — details in `references/engine.md` → "p5 in scenes")

1. **The engine owns the canvas, the loop, and the clock.** Never call `createCanvas`, `resizeCanvas`, `pixelDensity`, `frameRate`, `loop`/`noLoop`/`redraw`, `saveCanvas`, or `remove`, and never assign `p.setup`/`p.draw`. Sizes are design pixels (`s.w`, `s.h`).
2. **Time is `s.t`/`s.frame`.** `frameCount`, `millis()`, and `deltaTime` are mapped to the scene's clock, but `frameCount` counts whole frames only, so motion blur sub-frames need `s.t`.
3. **Randomness is seeded per scene, every frame.** `p.random()`, `p.randomGaussian()`, and `p.noise()` return the same values every frame (stable layouts); feed time into noise for motion (`p.noise(i, s.t * 0.3)`). Take all of an element's `random()` values before any `continue`/`return`, or later values shift and flicker. Never `Math.random`; never `g.random()` on a buffer (unseeded).
4. **No input, DOM, or loading.** No mouse/keyboard/touch handlers, `createDiv`/`createSlider`, `p5.sound`, or `createCapture`. No `loadImage`/`loadFont`/`loadJSON` in scenes: register fonts and images in `project.js`; images arrive as `p5.Image` in `s.assets.images`, fonts by family name (`p.textFont(THEME.font)`, `p.textWeight(800)`).
5. **Offscreen drawing goes through `buffer()`/`baked()`** from `draw.js` (design-px size, sharp at every output scale, 3D with `{ webgl: true }`). Never call `createGraphics` per frame.
6. **State resets every frame.** Fill, stroke, transforms, text settings, and blend mode start fresh in each `draw`; wrap local changes in `p.push()`/`p.pop()`. Fade groups with `opacity(p, a)`; blur with `setBlur(p, px)` (not `p.filter(BLUR)`, which is slow).

### Motion quality rules (mandatory — details and code in `references/motion.md`)

1. **Frame-driven and deterministic.** All animation is a function of `s.frame`/`s.t`; fractional frames must work (motion blur renders sub-frames). No `Date`, `Math.random`, timers, CSS or DOM animation, or p5's own draw loop. Use the seeded `p.random()`/`p.noise()`, or `rng(seed)` and `noise2`/`fbm`.
2. **Eased, never linear** — except constant drifts (parallax, slow pans, grain). Entrances `EASE.enter` or `SPRING.gentle`/`SPRING.snappy`; exits `EASE.exit`; moves `EASE.move`. Bouncy springs only when the style asks for playful.
3. **Nothing pops.** Every element enters and leaves over ≥ 0.25 s (`s.life`, `s.enter`, `s.exit`); exits finish by the outgoing transition's midpoint.
4. **Layered entrances.** Hero elements combine opacity + 12–40 px travel + 4–8 px blur-to-sharp (+ optional 0.96→1 scale). Siblings stagger 60–120 ms; sentences use `wordsIn`.
5. **Always alive.** Every scene carries ambient motion (drift, parallax, camera push ≤ 6 %, breathing characters, boiling lines, grain). No 1.5 s stretch goes without motion unless the plan calls for a still.
6. **Smooth transitions at every boundary.** Use the engine's transitions (`fade`, `dissolve`, `zoom`, `slide`, `wipe`, `iris`, `tear`) or an in-world continuous move. The exiting scene stays opaque underneath (no brightness dip); motion and blur peak mid-transition; 0.6–1.1 s long. Hard cuts only when planned (`"type": "cut"`), ideally on the beat.
7. **Sync to sound.** Transitions land on beats (timeline snapping); reveals start with the words that name them (`s.line(n).start`, `.p`); SFX sync points meet their visual (whoosh peak = transition midpoint, impact = the hit).
8. **Readable.** Text stays on screen ≥ words ÷ 3 + 1 s; body text ≥ 28 px at 1080p; keep text inside the title-safe area (5 % vertical, 10 % horizontal; for 9:16 also avoid the bottom 20 % and right edge where platform UI sits); strong contrast.
9. **60 fps by default.** Keep heavy work in `setup` (layouts) or `baked()` buffers and cached helpers (textures) so the studio plays in real time.

---

## Phase 7 — Agent self-check (before the user sees anything)

```bash
node engine/render.js --check                      # every key frame must draw without throwing (in headless Chrome)
node engine/render.js --stills auto --scale 0.5    # PNG per scene middle and transition middle -> out/stills/
```

A scene error prints `FAIL` with the scene file and line; a scene stuck in an endless loop fails with a timeout instead of hanging.

View every still with the host's image tool and check it against the storyboard, the acceptance criteria, the style, the motion rules, and the DN list: composition, legibility, safe areas, overflowing or clipped text, stray elements, empty frames. Fix and repeat until clean. Report problems you fixed briefly.

---

## Phase 8 — Studio review with the user (before any MP4 exists)

Start the studio in the background (Claude Code: Bash with `run_in_background`) and give the user the URL:

```bash
node engine/studio.js --port 4600     # add --open to launch the browser; pick another port if busy
```

Tell the user what the studio does: plays the video live with the final audio mix, scrubs and steps frame by frame, jumps between scenes, loops a scene, shows safe areas, and lets them **add notes at any moment** (saved to `review/notes.json`). Code edits hot-reload in place. The studio needs a Chromium-based browser or Firefox (Canvas `filter` support).

Loop:

1. Wait for the user to say they have reviewed (or to give feedback in chat).
2. Read `review/notes.json`. Fix every note with status `open` (root cause, not symptom). Re-run Phase 5 steps if the fix touches script, voices, music, or SFX; the studio's audio badge turns "stale" until `mix_audio.py` runs again.
3. For each fixed note set `"status": "resolved"` and add a one-line `"resolution"` in the JSON. The studio shows it crossed out with the resolution.
4. Re-run Phase 7, then tell the user what changed and ask them to review again.

Repeat until the user explicitly approves the video in the studio. Do not render the MP4 before that approval.

---

## Phase 9 — Ask the output size (right before rendering)

Ask one question with options for the chosen aspect ratio (recommended first):

| Aspect | Options |
|--------|---------|
| 16:9 | `1920×1080 (Full HD) (Recommended)` · `3840×2160 (4K)` · `2560×1440 (QHD)` · `1280×720 (HD)` |
| 9:16 | `1080×1920 (Full HD) (Recommended)` · `2160×3840 (4K)` · `720×1280 (HD)` |
| 1:1 | `1080×1080 (Recommended)` · `2160×2160` · `720×720` |
| 4:5 | `1080×1350 (Recommended)` · `2160×2700` · `864×1080` |

Say that 4K takes about 4× the render time and file size of 1080p; give an estimate from the `--check` timings or a short `--from/--to` test render. Everything is vector-drawn, so any size is sharp; the design size stays fixed and the renderer scales it.

---

## Phase 10 — Render

```bash
node engine/render.js --size <WxH>          # -> out/video.mp4 (picture) and out/final.mp4 (picture + mastered mix)
```

- Frames are drawn in headless Chrome by the same p5 code the studio ran, then encoded to H.264, yuv420p, BT.709, CRF 16, `-preset slow`, with parallel workers (`--workers N` Chrome pages, each with its own ffmpeg) and an exact frame count.
- `--motion-blur 4` renders 4 sub-frames per frame (180° shutter) for very fast motion; it multiplies render time. Offer it only when the plan has fast moves.
- If there is no audio at all, `out/video.mp4` is the deliverable.

---

## Phase 11 — Fix loop

If Phase 7 or the user found any problem:

1. Fix the root cause.
2. Re-run Phase 7 (check + stills) and Phase 10 (render) — both, every iteration. If the fix changes something the user approved, show it in the studio again before re-rendering.
3. Repeat until everything is clean.

Note the loop count; 3+ iterations on the same area signal a planning problem — revisit `VIDEO_PLAN.md` instead of patching again.

---

## Phase 12 — Done

Tell the user:

- Deliverable path, resolution, fps, duration, file size, and loudness (as `mix_audio.py` reported it).
- What was built vs. the acceptance criteria and DN list.
- How to reopen the studio (`node engine/studio.js`), change a line or a scene, and re-render (`node engine/render.js --size <WxH>`).
- Known limitations or ideas for a next version.
