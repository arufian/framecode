# Contributing to framecode

Thanks for considering a contribution.

## How to contribute

1. **Fork** the repo and create a branch from `main`:
   ```bash
   git checkout -b feat/my-change
   ```
2. **Make your change.** The repo is an agent-agnostic `SKILL.md` with YAML frontmatter (`name`, `description`), reference docs, Python audio scripts, and a JavaScript video template. No build step. Run `python3 -m unittest discover -s tests -v`; tests use synthetic media and stubs, never live APIs or model downloads.
3. **Keep it English** — skill content, prompts, docs, and code are English. Video content language is the user's choice.
4. **Test the skill end to end** before opening a PR:
   - install your fork into your host's skill directory
   - produce a short video with voice-over, Mixkit music, SFX, and footage (review page, measure, drop alignment), and one with generated audio
   - check the studio (playback with audio, scrubbing, notes, hot reload, error overlay)
   - render (`node engine/render.js --size 1920x1080`) and watch the result

## Guidelines

- Keep the phase order: confirm before building, studio approval before rendering, output size asked right before rendering, and the self-check and render re-run in the fix loop.
- Scenes stay code: p5.js sketches on the bundled engine. Do not add Remotion, HyperFrames, or other video/animation frameworks or drawing libraries, or AI image/video generators.
- Outside media has three sources: Mixkit (`mixkit.py`), generated in code (`gen_music.py`, `gen_sfx.py`, numpy/scipy only), and the user's local files (`media.py add`). Every outside file goes through the ledger (`media/sources.json`) with its page and licence. Mixkit downloads are reviewed by the user (`mixkit.py review`) before anything is built.
- Footage stays frame-exact: frame sequences through `engine/media.js`, never `<video>` seeking.
- Voice-over backends: ElevenLabs, Kokoro, Coqui.
- Never print, log, or commit API keys; `.env` stays gitignored and is never served by the studio.
- Engine changes must work in both the browser studio and the headless-Chrome renderer (same output), accept fractional frames, and stay deterministic (p5's `random()`/`noise()` stay seeded per scene and frame).
- Match existing style: terse imperative instructions, concrete paths and commands, explicit failure and exit conditions.

## Reporting issues

Open an issue with the phase that misbehaved, expected vs. actual behavior, and relevant command output.

## License

By contributing, you agree your contributions are licensed under the [MIT License](LICENSE).
