# framecode

A coding-agent skill that produces a brand-new video end to end — the video counterpart of [greenfield](https://github.com/arufian/greenfield-skill). Scenes are [p5.js](https://p5js.org) sketches the agent writes; no Remotion, HyperFrames, or other video frameworks. Music, sound effects, footage, and images come from free [Mixkit](https://mixkit.co) resources, are generated in code, or come from your own files — you choose per resource.

## What it does

Workflow: **interview → plan → Mixkit download + your review → confirm → scaffold → audio and media → build scenes → self-check → studio review → ask render size → render → fix loop → done.**

1. **Interview** — purpose, audience, format, style, plus the required questions:
   - voice-over? (ElevenLabs with your API key, or local Kokoro / Coqui TTS)
   - music: from Mixkit, generated in code, your own file, or none?
   - sound effects: from Mixkit, generated in code, your own files, or none?
   - footage and images: Mixkit stock video, Mixkit stock art, your own files, or every frame drawn in code?
   - what must *not* appear? (becomes a checked do-not list)
2. **Plan** — `VIDEO_PLAN.md` (storyboard, style, audio, media, motion plan, acceptance criteria) and `storyboard.json`. No diagrams or mockups.
3. **Mixkit review** — the agent searches Mixkit, looks at contact sheets, downloads candidate tracks, effects, clips, and art, measures the tracks (BPM, downbeat, drop), and builds a local review page (`media/review/index.html`) with a player for every file. You listen, watch, and pick; nothing is built before that.
4. **Confirm** — plan summary with your picks and any voice or generated-audio previews; nothing is built without approval.
5. **Audio and media first** — media ledger (`media/sources.json`) → voice lines → timeline (scenes sized to speech, transitions snapped to the track's measured beat, the drop aligned to a chosen scene) → music bed → synced SFX → footage frames and images → ducked, mastered mix (-14 LUFS, -1.5 dBTP) → `CREDITS.md`.
6. **Scenes in p5.js** — footage and art are composited inside scenes (graded, masked, moved, written on) with a frame-exact `footage()` helper; each scene is a p5 sketch (`draw(p, s)`) on a bundled engine that owns the timeline and clock, keeps p5's `random()`/`noise()` seeded and seek-safe, and adds smooth-motion defaults: eased and spring motion, staggered entrances, ambient life in every frame, and eight transitions (fade, dissolve, zoom, slide, wipe, iris/lens, torn paper, planned cuts). It also ships textures, hand-drawn strokes, callouts, counters, captions, a camera, a character rig, and offscreen buffers (including WEBGL for 3D) — all callable with the p5 instance.
7. **Studio** — a local browser studio plays the video live with the final audio before anything is rendered. You can scrub, step frames, loop scenes, show safe areas, and leave timestamped review notes the agent reads and resolves. Code edits hot-reload.
8. **Render** — asks the output size first (720p to 4K per aspect ratio). Draws the frames in headless Chrome (Puppeteer) with the same code the studio ran, in parallel, to H.264 via ffmpeg, with optional motion blur.

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
- Network access to mixkit.co when Mixkit is a source
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
references/           engine API, motion rules, style bar, audio details, media sources (Mixkit, generated, local)
scripts/              preflight, voiceover, timeline, mixkit (search, download, review page), media (ledger:
                      measure, music bed, SFX placement, footage frames, images, credits), gen_music, gen_sfx, mix_audio
template/             the video project the agent copies: engine/ (p5 surface + core, draw, transitions, render, studio) + example p5 scenes
tests/                regression tests (no network, no live models)
```

## Validation

```bash
python3 -m unittest discover -s tests -v
```

Tests use synthetic audio and video, HTML fixtures for Mixkit pages, a stand-in p5, and a local fake ElevenLabs server; no network, API calls, or model downloads. Tests that need ffmpeg or Node skip when those are missing.

## Media licences

Mixkit items are used under Mixkit's free licences (<https://mixkit.co/license/>); some stock videos carry a Restricted licence, which the skill flags and asks about. Every item's page and licence is kept in `media/sources.json` and written to `CREDITS.md`. Your own files stay under your licence.

## License

[MIT](LICENSE)
