# framecode

A coding-agent skill that produces a brand-new video end to end — the video counterpart of [greenfield](https://github.com/arufian/greenfield-skill). Every frame, animation, music bed, and sound effect is generated in code by the agent: scenes are [p5.js](https://p5js.org) sketches. No Remotion, HyperFrames, or other video frameworks, and no stock media.

## What it does

Workflow: **interview → plan → confirm → scaffold → audio → build scenes → self-check → studio review → ask render size → render → fix loop → done.**

1. **Interview** — purpose, audience, format, style, plus four required questions:
   - voice-over? (ElevenLabs with your API key, or local Kokoro / Coqui TTS)
   - music? (composed and synthesized by code)
   - sound effects? (synthesized by code)
   - what must *not* appear? (becomes a checked do-not list)
2. **Plan** — `VIDEO_PLAN.md` (storyboard, style, audio, motion plan, acceptance criteria) and `storyboard.json`. No diagrams or mockups.
3. **Confirm** — plan summary with voice, music, and SFX previews; nothing is built without approval.
4. **Audio first** — voice lines → timeline (scenes sized to speech, transitions snapped to the beat) → music → SFX → ducked, mastered mix (-14 LUFS, -1.5 dBTP).
5. **Scenes in p5.js** — each scene is a p5 sketch (`draw(p, s)`) on a bundled engine that owns the timeline and clock, keeps p5's `random()`/`noise()` seeded and seek-safe, and adds smooth-motion defaults: eased and spring motion, staggered entrances, ambient life in every frame, and eight transitions (fade, dissolve, zoom, slide, wipe, iris/lens, torn paper, planned cuts). It also ships textures, hand-drawn strokes, callouts, counters, captions, a camera, a character rig, and offscreen buffers (including WEBGL for 3D) — all callable with the p5 instance.
6. **Studio** — a local browser studio plays the video live with the final audio before anything is rendered. You can scrub, step frames, loop scenes, show safe areas, and leave timestamped review notes the agent reads and resolves. Code edits hot-reload.
7. **Render** — asks the output size first (720p to 4K per aspect ratio). Draws the frames in headless Chrome (Puppeteer) with the same code the studio ran, in parallel, to H.264 via ffmpeg, with optional motion blur.

## Installation

Copy or clone the whole folder (including `scripts/`, `template/`, `references/`) into your agent's skills directory:

```bash
git clone <this-repo> ~/.claude/skills/framecode      # Claude Code
git clone <this-repo> ~/.agents/skills/framecode      # Codex
```

Requirements:

- Node.js 22.12+ and npm (the video project installs `p5`, `puppeteer` with its ~200 MB `chrome-headless-shell`, and `@fontsource/*` fonts)
- ffmpeg + ffprobe
- Python 3.9+ with numpy and scipy
- Optional voice-over: an ElevenLabs API key, or Kokoro (`kokoro>=0.9.4`, Python 3.10–3.12, espeak-ng), or Coqui (`coqui-tts`) — see `references/audio.md`
- Optional: whisper (`mlx_whisper` or `whisper`) to verify narration against the script
- A Chromium-based browser or Firefox for the studio

## Usage

Ask your agent to make a video:

> "Make a 45-second explainer about how DNS works, friendly and hand-drawn, with a narrator."

In Claude Code, invoke it directly:

```
/framecode
```

In Codex, mention `$framecode`.

## Repository layout

```
SKILL.md              the workflow the agent follows
references/           engine API, motion rules, style bar, audio details
scripts/              preflight, voiceover, timeline, gen_music, gen_sfx, mix_audio
template/             the video project the agent copies: engine/ (p5 surface + core, draw, transitions, render, studio) + example p5 scenes
tests/                regression tests (no network, no live models)
```

## Validation

```bash
python3 -m unittest discover -s tests -v
```

Tests use synthetic audio, a stand-in p5, and a local fake ElevenLabs server; no API calls or model downloads. Tests that need ffmpeg or Node skip when those are missing.

## License

[MIT](LICENSE)
