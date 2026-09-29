# Style: the craft bar

The bar is set by four programmatic videos that agents drew entirely in code, one frame at a time:

- **"How browsers work" (40 s)** — two alternating worlds: warm paper with pastel diagonal stripes and cute hand-drawn characters (a tomato mascot, a server with a face), and a deep-navy blueprint grid with thin line diagrams. Lowercase chapter title top-left with an underline, a progress ring with a stage label top-right. Music only; hard cuts every 2.0 s, exactly on the bar of a 120 bpm track.
- **"Dot" (2 min)** — an egg character on textured paper talks with an unseen creator; code comments typewrite in monospace ("// hello, dot."); the world paints itself in (torn-paper watercolor sky, `hills = sin(x) + noise(x)`); the frame pulls back into a video player; rain, a galaxy, back to paper. Two-voice dialogue, cinematic music, almost no hard cuts.
- **"One minute" (60 s)** — a pencil with a glowing tip draws a character and then a whole street in perspective lines, which turns into a neon rainy city; paper plane over sunset clouds; torn-paper reveals; a countdown timer HUD; subtitles colored per speaker. Dialogue, zero hard cuts.
- **"The Water Cycle, a field study in 24 plates" (4.5 min)** — editorial infographic: serif titles, cream striped paper, textured illustrations, a HUD journal (elapsed time, altitude, temperature), plate counter, labels with leader lines, magnifier insets that open into a molecular micro-world, counters, and a closing summary. Music only.

Common to all four: everything is drawn procedurally, every scene is an illustration (not a slide), motion never stops, and transitions happen inside the world.

## Principles

1. **Illustrate, don't present.** Each scene is a composed picture with depth: background (paper, sky, grid), midground (landscape, device, diagram), subject (character, object, number), foreground (particles, labels, chrome). A title over a gradient is a slide, not this.
2. **Two worlds, one system.** Contrast a warm "macro" world (paper, daylight, characters) with a cool "micro/technical" world (navy grid, glowing lines, mono type). Switching worlds is a story beat; use `iris`, `dissolve`, or `zoom` for it.
3. **A character carries attention.** A simple mascot with blinking, breathing, looking at the action, and talking while its line plays makes any explainer watchable (`mascot`, `blink`, `talk`). Keep it consistent across scenes; give it reactions (squash on landing, surprised eyes).
4. **Persistent chrome gives continuity.** Chapter label + underline, progress ring or plate counter, optional HUD data panel, captions. It stays put while scenes change underneath, so cuts feel like pages of one document.
5. **Texture kills the "vector default" look.** Paper mottling and fibres, film grain, soft vignettes, hand-drawn line wobble and boil, halftone or hatching. Never flat untextured fills for large areas.
6. **Explain with annotation.** Leader-line callouts, magnifier insets, counters that count, labels that type on, arrows that draw. Show a number growing rather than stating it.
7. **Transitions are ideas.** A lens opens on the detail you are about to explain; paper tears to reveal what is underneath; a pencil draws the next world; the camera pulls back to reveal context. Reserve the most striking one for the turning point.
8. **Sound is structure.** Beat-synced cuts for a punchy montage; continuous transitions for a story. Dialogue gets captions in a speaker colour.

## Palette and type

- 1 paper/base, 1 ink, 1–2 accents, 1 night world colour. Example: paper `#f3ecdf`, ink `#1d1d1f`, accent `#e4572e`, blue `#2f6fdf`, night `#0d1733`. Put them in `theme.js`.
- Editorial pieces: a serif display face for titles (add `@fontsource/fraunces` or `@fontsource/dm-serif-display`), a clean sans for labels, mono for code and HUD numbers.
- Playful explainers: rounded sans (Inter works), lowercase labels, generous spacing.
- Respect the do-not list over these defaults (for example, no neon if DN says so).

## Scene composition checklist

- One idea per scene; the hook lands in the first 3 seconds.
- Clear focal point; the eye path follows the narration.
- Safe areas respected; nothing important within 5 % of the edges (and bottom 20 % on vertical video).
- At least two layers of depth and two sources of ambient motion (see `motion.md`).
- Chapter/progress chrome present if the video has more than three scenes.
- The ending pays off: callback to the opening image, a summary, or a clear call to action.

## Studying reference videos

When the user shares reference videos, analyze them before proposing a style (download only what the user shared, for analysis).

```bash
# X posts: get the video URL (the public fxtwitter API returns tweet JSON), or use yt-dlp for other sites
curl -s "https://api.fxtwitter.com/<user>/status/<id>" | jq -r '.tweet.media.all[0].url'
yt-dlp -o ref.mp4 "<url>"

ffprobe -v error -show_entries stream=codec_type,width,height,r_frame_rate -of compact ref.mp4
ffmpeg -v error -i ref.mp4 -vf "fps=1/3,scale=480:270,tile=5x4:padding=4:color=white" -frames:v 1 ref-sheet.png   # overview
ffmpeg -v error -ss 20 -t 4 -i ref.mp4 -vf "fps=2,scale=480:270,tile=4x2" -frames:v 1 ref-transition.png          # a transition up close
ffmpeg -i ref.mp4 -an -vf "scdet=threshold=12,metadata=mode=select:key=lavfi.scd.time,metadata=mode=print" -f null - 2>/dev/null | grep scd.time   # hard cuts (pacing, beat sync)
ffmpeg -i ref.mp4 -vn -af ebur128=peak=true -f null - 2>&1 | grep -E "I:|Peak:"   # loudness
mlx_whisper ref.wav   # narration or dialogue? (extract audio first with ffmpeg -vn -ac 1 -ar 16000)
```

Look at the contact sheet and transition strips with the host's image tool, then write down: worlds and palette, texture, characters, chrome, transition types, cut rhythm, audio layers, loudness. Borrow principles, not assets.
