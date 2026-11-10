# Audio: voice-over, music, sound effects, mix

All scripts live in `$VIDEO_SKILL_DIR/scripts/` and run from the project root. Everything is 48 kHz. Timing flows one way: voice lines → `timeline.py` → music and SFX → `mix_audio.py`.

Music and SFX have three sources (the user chooses in the interview): **Mixkit** recordings and **local files** go through the media ledger (`mixkit.py`, `media.py`; see `references/media.md` → "Music from the ledger" and "SFX from the ledger"), and **generated** audio comes from `gen_music.py` and `gen_sfx.py` (below). The mixer treats all three the same.

## Voice-over backends

| Backend | Quality | Cost / licence | Needs |
|---------|---------|----------------|-------|
| ElevenLabs | most natural, many languages | paid API; free tier needs attribution and is non-commercial | API key |
| Kokoro (82M) | very natural for its size, fast on CPU/Apple Silicon | free, Apache-2.0 (commercial OK) | Python 3.10–3.12, espeak-ng |
| Coqui `tts_models/en/vctk/vits` | good, many English speakers (`p225`…`p376`) | free; VCTK data CC-BY 4.0 | Python, `coqui-tts` |
| Coqui XTTS v2 | expressive, multilingual | **Coqui Public Model License: non-commercial only** | user must accept; `COQUI_TOS_AGREED=1` |

### ElevenLabs

```bash
python3 "$VIDEO_SKILL_DIR/scripts/voiceover.py" --check          # validates ELEVENLABS_API_KEY (env or .env), never prints it
python3 "$VIDEO_SKILL_DIR/scripts/voiceover.py" --backend elevenlabs --list-voices
```

Put voice ids in `storyboard.json` → `audio.voiceover.voices` (`{ "narrator": "<voice_id>", "dot": "<voice_id>" }`). Default model `eleven_multilingual_v2`; set `audio.voiceover.model` to change it. Neighbouring lines are sent as `previous_text`/`next_text` for natural flow. Lines are cached by content, so re-runs only pay for changed lines. Errors: 401 = bad key or missing permission; 402/429 = plan or credit limits.

### Kokoro (recommended local option)

```bash
uv venv .venv-tts --python 3.11                     # or: python3.11 -m venv .venv-tts
uv pip install --python .venv-tts/bin/python "kokoro>=0.9.4" soundfile pip
.venv-tts/bin/python -m spacy download en_core_web_sm   # English G2P model; avoids a failing auto-download
# Japanese: uv pip install --python .venv-tts/bin/python "misaki[ja]"   Mandarin: "misaki[zh]"
brew install espeak-ng                              # macOS; Linux: apt install espeak-ng
PYTORCH_ENABLE_MPS_FALLBACK=1 .venv-tts/bin/python "$VIDEO_SKILL_DIR/scripts/voiceover.py" --storyboard storyboard.json --out public/vo
```

The first run downloads the model (~330 MB) from Hugging Face. Voices (the first letter sets the language):

- American English: `af_heart` (warm, default), `af_bella`, `af_nicole`, `af_sarah`, `af_sky`, `am_adam`, `am_michael`, `am_fenrir`, `am_puck`
- British English: `bf_emma`, `bf_isabella`, `bm_george`, `bm_lewis`
- Japanese: `jf_alpha`, `jf_gongitsune`, `jf_nezumi`, `jf_tebukuro`, `jm_kumo`
- Mandarin: `zf_xiaobei`, `zf_xiaoni`, `zf_xiaoxiao`, `zm_yunjian`, `zm_yunxi`
- Spanish `ef_dora`, `em_alex` · French `ff_siwis` · Hindi `hf_alpha`, `hf_beta`, `hm_omega` · Italian `if_sara`, `im_nicola` · Portuguese `pf_dora`, `pm_alex`

Troubleshooting:

- `Error processing file '/Users/runner/.../espeak-ng-data/phontab'` → espeak-ng ignores data paths longer than about 120 characters (deep project folders). `voiceover.py` works around it automatically (system espeak-ng data or a short symlink); set `ESPEAK_DATA_PATH` to force a path.
- `No virtual environment found; run uv venv` during the first line → the spaCy English model is missing; run the `spacy download` line above.

### Coqui

```bash
uv pip install --python .venv-tts/bin/python coqui-tts
.venv-tts/bin/python "$VIDEO_SKILL_DIR/scripts/voiceover.py" --backend coqui --list-voices      # speakers of the default model
```

Set `audio.voiceover.model` for another model and `audio.voiceover.lang` for multilingual ones. XTTS stays blocked until the user accepts its non-commercial licence and `COQUI_TOS_AGREED=1` is set.

### Script tips

- One line per breath or sentence; split long sentences so reveals can sync to each part.
- `say` overrides pronunciation without changing captions: `{ "text": "SQL runs it", "say": "sequel runs it" }`.
- `at` (seconds from scene start) pins a line to an animation beat; `gap_after` sets the pause after it.
- For dialogue, give each speaker a distinct voice and a caption colour (`captions(..., { colors })` in `project.js`).
- Samples for the confirmation step: `voiceover.py --backend kokoro --voice af_heart --sample "…" --out public/vo/_sample.wav`.

## Generated music (`gen_music.py`, `"source": "generated"`)

Original music composed and synthesized from oscillators and noise: voice-led chord progressions, pads, plucks, electric piano, bells, bass, drums, reverb, and a mastered ending on the tonic.

| style | default key / bpm | character |
|-------|-------------------|-----------|
| `ambient` | D / 80 | slow pads, shimmer, sparse bells; no drums |
| `corporate` | C / 112 | bright plucks, piano, four-on-the-floor-lite drums |
| `lofi` | F / 80 | jazzy 7th chords on electric piano, swung boom-bap, vinyl crackle |
| `cinematic` | Dm / 90 | string-like pads, ostinato, taiko hits, risers into lifts |
| `electronic` | C / 122 | supersaw pads with sidechain pump, offbeat bass, claps, hats |

- With `--timeline`, each scene is a section; its `energy` (0–1, default: intro 0.35, body 0.7/0.85 alternating, outro 0.4) decides which layers play (bass ≥ 0.45, melody ≥ 0.55, drums ≥ 0.6). Set `energy` per scene in the storyboard to shape the arc.
- `seed` changes the arrangement details; `key` and `bpm` in `storyboard.json` also drive beat snapping.
- The standalone file is mastered to -16 LUFS (`--lufs`) so samples sound right on their own.

## Generated sound effects (`gen_sfx.py`, `"source": "generated"`)

`gen_sfx.py --list` prints the catalogue. Each effect has a sync point, aligned to its cue:

| type | sync point | use |
|------|-----------|-----|
| `whoosh`, `swoosh`, `swipe` | the peak | transitions, fast moves |
| `riser` | the end | builds into a reveal or cut |
| `downlifter` | the start | after a peak, calming |
| `impact`, `boom`, `subdrop` | the start | big reveals, logo hits, beat cuts |
| `pop`, `click`, `tick` | the start | elements appearing, UI, counters |
| `ding`, `chime`, `sparkle` | the start | success, end cards, magic moments |
| `glitch` | the start | tech errors, digital moments |
| `typing` | the start | typewriter text |
| `paper` | the tear | `tear` transitions, page turns |
| `pencil` | the start | draw-on sketches |

Cue fields in `storyboard.json`: `type`, `at` (`transition_out`, `transition_in`, `start`, `end`, `line:N`, or seconds from scene start), optional `gain_db`, `seconds`, `pitch`, `seed`. Without explicit cues, `audio.sfx.density` generates them: subtle = transitions; moderate = + a pop at each scene start; rich = + clicks on every line.

## Mix (`mix_audio.py`)

- Speech is levelled to -20 dBFS RMS per line; music sits 8 dB under speech and ducks a further 9 dB while anyone speaks (0.25 s attack, 0.5 s release); SFX use their cue gain (defaults per type).
- The sum is mastered to **-14 LUFS integrated, -1.5 dBTP** (web/social). Use `--lufs -16` for podcasts/Apple, `--lufs -23` for broadcast.
- Rebalance: `--music-db` (default -8 with voice, 0 without), `--duck-db`, `--sfx-db`, `--vo-db`.
- Studio levels: unset `--music-db` / `--sfx-db` come from `review/mix.json` (`musicDb`, `sfxDb`), which the studio's music and SFX sliders write (`--levels` points elsewhere). After mixing, the levels used are written back (`musicDb`, `sfxDb`, `mixedMusicDb`, `mixedSfxDb`), so the sliders show them and the studio knows what the stems hold.
- Stems: `stem-vo/music/sfx.wav` are written next to the mix by default (`--no-stems` skips them); the studio plays them to preview slider changes live.
- Ledger music (Mixkit or local) arrives from `media.py music` already trimmed to `start`, bar-looped if short, and faded out; the mixer levels it like generated music. Ledger SFX arrive from `media.py sfx` peak-normalized with per-name default gains, so `gainDb` means the same for all sources.
- The renderer muxes `public/audio/mix.wav` into `out/final.mp4` as AAC 320 kb/s.
- **You cannot hear.** After mixing, ask the user to listen (`afplay public/audio/mix.wav`), especially the track's start, the drop, and each effect against its visual; rebalance with the flags above, or let the user set the music and SFX sliders in the studio and re-run the mixer.
