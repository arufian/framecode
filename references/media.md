# Media: Mixkit, generated, and local sources

Every outside file (a Mixkit download or a user's file) goes through one ledger, `media/sources.json`, so the timeline, the mixer, the engine, and `CREDITS.md` all read the same list. Generated music and SFX (`gen_music.py`, `gen_sfx.py`) do not use the ledger.

Contents: sources · the ledger · Mixkit search · download and review · downloading into the ledger · local files · measuring · music · SFX · footage and art · in scenes · licences.

## Sources

The user picks one source per resource in the interview (Round 2):

| resource | Mixkit | generated in code | local files |
|----------|--------|-------------------|-------------|
| music | `mixkit.py get --music`, then `media.py music` | `gen_music.py --timeline` | `media.py add --kind music`, then `media.py music` |
| SFX | `mixkit.py get --sfx`, then `media.py sfx` | `gen_sfx.py --timeline` | `media.py add --kind sfx`, then `media.py sfx` |
| footage | `mixkit.py get --video`, then `media.py visuals` | (draw it in p5) | `media.py add --kind video`, then `media.py visuals` |
| images / art | `mixkit.py get --art`, then `media.py visuals` | (draw it in p5) | `media.py add --kind image`, then `media.py visuals` |

Footage and images can combine Mixkit and local items (a Mixkit city clip plus the user's logo). Music and SFX use one source each.

## The ledger

`media/` in the project root:

```
media/sources.json     the ledger (mixkit.py get and media.py add write it; you add hand-set fields)
media/MEDIA.md         measurements, flags, sources, licences (media.py measure)
media/src/             downloaded and registered files (gitignored; re-download from the ledger)
media/review/          candidates downloaded for the user to review, review.json, index.html (gitignored)
media/candidates.json  search results (titles for get)
media/thumbs/          contact sheets (gitignored)
```

An entry:

```json
{ "name": "city", "kind": "video", "source": "mixkit", "id": "49845", "file": "src/49845-1080.mp4",
  "page": "https://mixkit.co/free-stock-video/aerial-view-of-the-glass-corporate-buildings-of-a-big-49845/",
  "title": "Aerial view of the glass corporate buildings of a big city at night",
  "license": "Mixkit Stock Video Free License", "licenseId": "videoFree",
  "in": 3.0, "out": 11.0,
  "measured": { "width": 1920, "height": 1080, "fps": 29.97, "seconds": 21.0 } }
```

Names are how everything else refers to an item: storyboard `audio.music.track`, SFX cue `type`, scene `params`, `s.assets.footage.<name>`, `s.assets.images.<name>`. Hand-set fields (kept when an item is re-downloaded):

| field | kinds | meaning |
|-------|-------|---------|
| `in`, `out` | all but images | seconds: use only this part of the file (measured, extracted, and mixed that way) |
| `sync` | sfx | `hit` (first loud peak, default), `peak` (loudest point, default for whoosh/swoosh/swipe/riser/transition names), or milliseconds |
| `gainDb` | sfx | level in the mix; default by name (whoosh -9, impact -7, pop -12, click -16, …, else -12) |
| `bpm`, `firstDownbeat`, `drop` | music | override a measurement after listening |
| `maxWidth` | video | cap the extracted frame width (small picture-in-picture clips) |

Re-run `media.py measure` after editing the ledger.

## Mixkit search

```bash
M="$VIDEO_SKILL_DIR/scripts"
python3 "$M/mixkit.py" search music tag/corporate --pages 2 --save media/candidates.json
python3 "$M/mixkit.py" search music mood/upbeat --save media/candidates.json
python3 "$M/mixkit.py" search sfx whoosh --save media/candidates.json
python3 "$M/mixkit.py" search video discover/office --save media/candidates.json
python3 "$M/mixkit.py" search video "discover/background/?orientation=vertical"
python3 "$M/mixkit.py" search art business --save media/candidates.json
```

The path is the part of a mixkit.co URL after `/free-stock-music/`, `/free-sound-effects/`, `/free-stock-video/`, or `/free-stock-art/`:

- **Music**: `tag/<tag>` (corporate, upbeat, cinematic, happy, chill, …), `mood/<mood>`, `genre/<genre>`, or a word (`corporate`). Output: id, length, title, artist, tags.
- **SFX**: a category or word: `whoosh`, `click`, `transition`, `notification`, `bell`, `technology`, `game`, `interface`, `typing`, `impact`, `pop`, `swoosh`, `camera`, `coin`.
- **Video**: `discover/<word>` searches (`discover/city`, `discover/laptop`), or a category (`nature`, `business`, `lifestyle`, `background`, `transition`); add `?orientation=vertical` for 9:16. Output: id, title, description.
- **Art**: a category (`business`, `city`, `computer`, `people`, `nature`) or `discover/<word>`. Mixkit art is illustration, not photography.

An empty result means the path does not exist: try a nearby word. Titles and descriptions are text; judge footage and art only by looking at it (next section).

## Download and review (Phase 3, before any implementation)

The user reviews the real files, not titles or thumbnails, and picks before anything is built.

**1. Pre-select.** For footage and art, look before you download: contact sheets tile thumbnails row-major, numbered from 0 in the order printed.

```bash
python3 "$M/mixkit.py" sheet video 49845 1606 2031 4809 --out media/thumbs/S2.jpg
python3 "$M/mixkit.py" sheet art 26 175 558 --out media/thumbs/art.jpg
```

Read every sheet with the image tool. Drop clips with watermarks, visible brand logos, faces that dominate the frame when the story is not about people, or a mood that fights the style and DN list.

**2. Download the candidates** into `media/review/` (not the ledger). Label footage and art with the scene they are for and SFX with the cue name; bare ids are fine for music.

```bash
python3 "$M/mixkit.py" get media --to media/review \
    --music 644 700 812 160 --sfx whoosh=1492 whoosh=1489 pop=<id> \
    --video S2=49845 S2=4809 S4=<id> --art S3=26 S3=175
python3 "$M/media.py" survey media/review/*.mp3 --bpm 100 130
```

The survey prints length, BPM, tempo confidence, first downbeat, and drop per track. Prefer: BPM in range with confidence ≥ 0.3, length ≥ video length + start (or it loops whole bars), and a drop far enough in that the video can start earlier in the song. Videos download at `--res` (default 1080); `--res 720` keeps review downloads small when many clips are in play (the final `get` then fetches 1080).

**3. Build the review page** and hand it to the user:

```bash
python3 "$M/mixkit.py" review media/review     # -> media/review/index.html
open media/review/index.html                   # Linux: xdg-open
```

The page numbers every item (#1, #2, …) and shows an audio player per track and effect, a playable video per clip, each artwork, with title, length, size, Mixkit page, and licence; Restricted clips are marked. The command also prints the numbers.

**4. Ask for the picks** with the question tool, one question per resource (the track; each scene's footage or art; the SFX set), options = review numbers with a one-line reason, recommended first. Say that you measured the tracks but cannot hear them, and cannot judge motion in the clips beyond their thumbnails. On "search again" or notes, repeat steps 1–3. Only after the user picked: record the picks in `VIDEO_PLAN.md`, get plan approval, and move on.

## Downloading into the ledger

```bash
python3 "$M/mixkit.py" get media --music music=<id> --sfx whoosh=<id> pop=<id> click=<id> tick=<id> \
    --video city=<id> desk=<id> --art hero=<id>
```

Only the items the user picked in the review. Files already in `media/review/` are copied, not downloaded again. `NAME=ID` for every item (a single `--music ID` is named `music`). Music arrives as MP3, effects as WAV (MP3 when only a preview exists), video as MP4 at `--res` (default 1080, falling back to 720 and 360; `--res 2160` for 4K deliverables when the clip has it), art as the original PNG. `get` reads each video's and art item's licence from its Mixkit page. A failed download prints a warning: pick the next best item rather than generating a stand-in without asking.

## Local files

```bash
python3 "$M/media.py" add music ~/Music/licensed-track.wav --kind music --license "Licensed to the client by <library>, 2026"
python3 "$M/media.py" add logo assets/logo.png --kind image --license "Client logo, supplied by the client"
python3 "$M/media.py" add office ~/Movies/office-broll.mp4 --kind video --license "Shot by the client"
```

The file is copied to `media/src/<name>.<ext>`. Export SVG logos to PNG at 2× the size they appear (at least 1920 px wide for a full-width logo) before adding. Never swap a user's file for a Mixkit one without asking.

## Measuring

```bash
python3 "$M/media.py" measure --bpm 100 130
```

Writes `measured` on every entry and `media/MEDIA.md`:

- **music**: `bpm`, `period`, `firstBeat`, `firstDownbeat`, `drop` (+ candidates), `tempoConfidence`, `downbeatConfidence`, `seconds`. Low confidence flags mean the grid may be off: have the user listen, then set `bpm`/`firstDownbeat` by hand.
- **sfx**: `hitMs` (first loud peak), `peakMs` (loudest point), `lengthMs`, `peaksMs`, flags (two equal peaks, leading silence, long file).
- **video / art / image**: `width`, `height` (+ `fps`, `seconds` for video); flags for long clips and Restricted licences.

## Music from the ledger

Storyboard: `"music": { "source": "mixkit", "track": "music", "start": null, "drop_at": "S3", "fade_out": 2.0 }` (`"source": "user"` for a local track).

- `timeline.py` uses the measured tempo for beat snapping, and moves `start` (seconds into the track, default its first downbeat) onto a beat (a bar with `"snap": "bar"`), so the grid and the song agree.
- `drop_at: "<scene id>"` starts the track so its drop lands on that scene's incoming transition midpoint: the payoff hits with the music. It fails when the drop is too early in the track for that scene; pick a later-drop track or an earlier scene.
- `media.py music` writes `public/music/music.wav`: the track from `start`, whole bars looped with short crossfades if the track is shorter than the video (a warning; prefer a longer track), and a `fade_out` at the end.
- `mix_audio.py` then levels, ducks under speech, and masters as for generated music.

## SFX from the ledger

Cue `type` = a ledger name. `media.py sfx` normalizes each sound, writes it to `public/sfx/<name>.wav`, and sets each cue's start so its sync point (`hit` or `peak`) lands on the cue's frame: a whoosh peaks mid-transition, a pop hits on the reveal. Density auto-cues (`audio.sfx.density`) use the names `whoosh`, `pop`, `click`, and `tick` (cuts); download those names or list cues explicitly. A missing name fails with the `mixkit.py get` line to run.

## Footage and art

```bash
python3 "$M/media.py" visuals
```

- **Footage** → `public/footage/<name>/00000.jpg …` at the clip's frame rate (capped at the project fps), scaled to cover the design frame (never upscaled; `maxWidth` caps it), only the `in`–`out` range. Unchanged clips are skipped on re-runs. Budget: about 250 KB per 1080p frame, so 10 s at 30 fps ≈ 75 MB; keep `in`/`out` tight.
- **Art and images** → `public/images/<name>.<ext>`, downscaled to at most 2× the design's long side.
- **`public/media.json`** lists both. The engine loads it at startup: images into `s.assets.images`, footage clips into `s.assets.footage`.

## Footage and art in scenes

```js
import { footage, imageCover, vignette, rgba } from '../engine/draw.js';

draw(p, s) {
  const clip = s.assets.footage[s.params.clip];
  footage(p, clip, s.t, 0, 0, s.w, s.h, { from: 1.5 });   // clip time = from + t * rate
  // grade toward the palette, then draw the story on top
  p.drawingContext.fillStyle = rgba(THEME.night, 0.55);
  p.drawingContext.fillRect(0, 0, s.w, s.h);
  vignette(p, s.w, s.h, { strength: 0.5 });
}
```

`footage(p, clip, t, x, y, w, h, { rate = 1, from = 0, loop = false, fit = 'cover' | 'contain' | 'fill', focusX, focusY })` draws the frame for clip time `from + t * rate` (seconds into the extracted range). It holds the last frame past the end unless `loop`. It draws through p5's 2D context, so `p.translate`/`p.scale`, `camera()`, `opacity()`, `setBlur()`, clip paths, and blend modes all apply. Rendering is frame-exact: the renderer redraws a frame until every footage frame it uses has loaded. The studio shows the nearest loaded frame while it streams.

Craft with outside media (see `scenes/broll.js`):

- **Grade it into the palette**: a colour wash or gradient in a theme colour, `globalCompositeOperation = 'multiply' | 'screen' | 'color'`, a vignette, and the project's grain over everything. Different clips in one video should look like one shoot.
- **Frame it**: masks (rounded cards, circles, torn paper, shapes that grow), split screens, picture-in-picture with a shadow, footage inside a device or window drawn in code.
- **Move it**: slow push-ins and parallax over the clip (`camera`), `rate` below 1 for slow motion, `from` to pick the best moment. Never stretch or squash (use `fit`).
- **Write on it**: type, callouts, counters, and drawn strokes on top, with a darkened panel or gradient where text sits.
- **Transitions**: engine transitions work on footage scenes like any other; an `iris` on a subject in the clip or a `wipe` along its motion reads best.
- **Art**: Mixkit illustrations have flat colour and white or coloured backgrounds; place them on cards, crop them with `imageCover`, reveal them with `brushReveal`, or cut a region with a clip path. Recolouring with blend modes keeps the palette.

## Licences

Mixkit's free licences (https://mixkit.co/license/): Stock Music Free, Sound Effects Free, Stock Video Free, Art Free, and a **Stock Video Restricted** licence on some clips. `get` records the licence of each item and warns on Restricted clips: show the user the licence link and default to another clip unless they accept it for this use. Keep the ledger's page and licence columns; `media.py credits` writes `CREDITS.md`. The licences cover using the items inside the video; check the terms for anything else (such as passing on the raw files). Local files are the user's licence to hold; record who holds it in `--license`.
