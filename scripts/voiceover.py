#!/usr/bin/env python3
"""Generate voice-over lines with ElevenLabs, Kokoro, or Coqui TTS.

Every storyboard line becomes public/vo/<scene>-<nn>.wav (48 kHz mono, silence
trimmed) and durations.json maps line ids to seconds. Lines whose text, voice,
and settings are unchanged are reused, so re-runs never re-spend API credits.

Examples:
  voiceover.py --storyboard storyboard.json --out public/vo
  voiceover.py --backend kokoro --voice af_heart --sample "Hello there." --out public/vo/_sample.wav
  voiceover.py --backend elevenlabs --list-voices
  voiceover.py --backend elevenlabs --check
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_lib as al  # noqa: E402

ELEVEN_DEFAULT_MODEL = "eleven_multilingual_v2"
COQUI_DEFAULT_MODEL = "tts_models/en/vctk/vits"
KOKORO_VOICES = {
    "a": "American English: af_heart af_bella af_nicole af_sarah af_sky am_adam am_michael am_fenrir am_puck",
    "b": "British English: bf_emma bf_isabella bm_george bm_lewis",
    "j": "Japanese: jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo (needs misaki[ja])",
    "z": "Mandarin: zf_xiaobei zf_xiaoni zf_xiaoxiao zm_yunjian zm_yunxi (needs misaki[zh])",
    "e": "Spanish: ef_dora em_alex",
    "f": "French: ff_siwis",
    "h": "Hindi: hf_alpha hf_beta hm_omega",
    "i": "Italian: if_sara im_nicola",
    "p": "Brazilian Portuguese: pf_dora pm_alex",
}


class TTSError(RuntimeError):
    pass


# ---------------------------------------------------------------- secrets

def eleven_key():
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key and Path(".env").is_file():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ELEVENLABS_API_KEY":
                key = value.strip().strip("'\"")
    if not key:
        raise TTSError("ELEVENLABS_API_KEY is not set (environment or ./.env)")
    return key


def eleven_request(path, key, body=None, accept="application/json"):
    base = os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"xi-api-key": key, "Accept": accept,
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300].replace(key, "***")
        hint = {401: "key rejected or missing permission", 402: "plan or quota limit reached",
                429: "rate limited or out of credits"}.get(error.code, "request failed")
        raise TTSError(f"ElevenLabs HTTP {error.code}: {hint}: {detail}") from None
    except urllib.error.URLError as error:
        raise TTSError(f"ElevenLabs unreachable: {error.reason}") from None


# ---------------------------------------------------------------- backends

class ElevenLabs:
    name = "elevenlabs"

    def __init__(self, model=None, **_):
        self.key = eleven_key()
        self.model = model or ELEVEN_DEFAULT_MODEL

    def synth(self, text, voice, speed=1.0, previous_text=None, next_text=None, **_):
        if not voice:
            raise TTSError("ElevenLabs needs a voice id (run --list-voices)")
        settings = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}
        if abs(speed - 1.0) > 1e-3:
            settings["speed"] = max(0.7, min(1.2, speed))
        body = {"text": text, "model_id": self.model, "voice_settings": settings}
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
        audio = eleven_request(f"/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                               self.key, body, accept="audio/mpeg")
        tmp = Path(".vo-eleven.tmp")
        try:
            tmp.write_bytes(audio)
            return al.decode(tmp, channels=1)
        finally:
            tmp.unlink(missing_ok=True)


def short_espeak_data_path():
    """espeak-ng silently ignores data paths longer than ~120 characters (deeply nested venvs) and
    fails with "Error processing file '/Users/runner/.../phontab'". Point it at a short path instead."""
    try:
        import espeakng_loader
        import misaki.espeak  # noqa: F401  (sets its own library/data paths on import)
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
    except ImportError:
        return
    bundled = espeakng_loader.get_data_path()
    override = os.environ.get("ESPEAK_DATA_PATH")
    if len(bundled) < 100 and not override:
        return
    for candidate in (override, "/opt/homebrew/share/espeak-ng-data", "/usr/local/share/espeak-ng-data",
                      "/usr/share/espeak-ng-data"):
        if candidate and len(candidate) < 100 and Path(candidate, "phontab").is_file():
            EspeakWrapper.set_data_path(candidate)
            return
    import tempfile
    link = Path(tempfile.gettempdir()) / f"espeak-ng-data-{os.getuid()}"
    if len(str(link)) < 100:
        if not link.exists():
            link.symlink_to(bundled)
        EspeakWrapper.set_data_path(str(link))


class Kokoro:
    name = "kokoro"

    def __init__(self, lang=None, **_):
        try:
            from kokoro import KPipeline  # noqa: F401
        except ImportError:
            raise TTSError("kokoro is not installed: uv pip install 'kokoro>=0.9.4' soundfile "
                           "(Japanese: misaki[ja], Mandarin: misaki[zh])") from None
        short_espeak_data_path()
        self.lang = lang
        self.pipelines = {}

    def synth(self, text, voice, speed=1.0, **_):
        from kokoro import KPipeline
        voice = voice or "af_heart"
        lang = self.lang or voice[0]
        if lang not in self.pipelines:
            self.pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
        chunks = []
        for result in self.pipelines[lang](text, voice=voice, speed=speed, split_pattern=r"\n+"):
            audio = getattr(result, "audio", None)
            if audio is None and isinstance(result, tuple):
                audio = result[2]
            if audio is not None:
                chunks.append(np.asarray(audio.detach().cpu() if hasattr(audio, "detach") else audio,
                                         dtype=np.float32))
        if not chunks:
            raise TTSError(f"kokoro produced no audio for: {text[:60]}")
        return al.resample(np.concatenate(chunks), 24000)


class Coqui:
    name = "coqui"

    def __init__(self, model=None, lang=None, **_):
        self.model = model or COQUI_DEFAULT_MODEL
        if "xtts" in self.model and os.environ.get("COQUI_TOS_AGREED") != "1":
            raise TTSError("XTTS is under the Coqui Public Model License (non-commercial). Ask the user; "
                           "only if they accept, set COQUI_TOS_AGREED=1 and re-run")
        try:
            from TTS.api import TTS
        except ImportError:
            raise TTSError("Coqui TTS is not installed: uv pip install coqui-tts") from None
        self.tts = TTS(model_name=self.model, progress_bar=False).to("cpu")
        self.lang = lang

    def speakers(self):
        return list(getattr(self.tts, "speakers", None) or [])

    def synth(self, text, voice, speed=1.0, **_):
        kwargs = {}
        if getattr(self.tts, "is_multi_speaker", False):
            kwargs["speaker"] = voice or self.speakers()[0]
        if getattr(self.tts, "is_multi_lingual", False):
            kwargs["language"] = self.lang or "en"
        if abs(speed - 1.0) > 1e-3:
            kwargs["speed"] = speed
        try:
            wav = self.tts.tts(text=text, **kwargs)
        except TypeError:
            kwargs.pop("speed", None)
            wav = self.tts.tts(text=text, **kwargs)
        rate = self.tts.synthesizer.output_sample_rate
        return al.resample(np.asarray(wav, dtype=np.float32), rate)


BACKENDS = {"elevenlabs": ElevenLabs, "kokoro": Kokoro, "coqui": Coqui}


# ---------------------------------------------------------------- storyboard lines

def storyboard_lines(board):
    """Yield (line_id, speaker, text_to_speak, neighbours) in storyboard order."""
    for scene in board.get("scenes", []):
        lines = scene.get("lines") or []
        for index, line in enumerate(lines, 1):
            spoken = (line.get("say") or line.get("text") or "").strip()
            if not spoken:
                continue
            previous = lines[index - 2].get("text") if index > 1 else None
            following = lines[index].get("text") if index < len(lines) else None
            yield f"{scene['id']}-{index:02d}", line.get("speaker", "narrator"), spoken, (previous, following)


def fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def finish(audio):
    audio = al.trim_silence(al.to_channels(audio, 1))
    if not len(audio):
        raise TTSError("TTS output was silent")
    level = al.rms_db(audio)
    if np.isfinite(level):
        audio = audio * al.db_to_gain(-20.0 - level)
    peak = float(np.abs(audio).max())
    return audio / peak * 0.95 if peak > 0.95 else audio


def generate(board, out_dir, only=None, force=False):
    config = board.get("audio", {}).get("voiceover") or {}
    backend_name = config.get("backend")
    if backend_name not in BACKENDS:
        raise TTSError(f"storyboard audio.voiceover.backend must be one of {sorted(BACKENDS)}")
    voices, speed = config.get("voices", {}), float(config.get("speed", 1.0))
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = al.load_json(manifest_path, {})
    engine = None
    durations = {}
    for line_id, speaker, text, (previous, following) in storyboard_lines(board):
        voice = voices.get(speaker) or voices.get("default")
        key = fingerprint(backend_name, config.get("model"), config.get("lang"), voice, speed, text)
        target = out_dir / f"{line_id}.wav"
        cached = manifest.get(line_id, {})
        wanted = only is None or line_id in only
        if target.is_file() and cached.get("hash") == key and not (force and wanted):
            durations[line_id] = cached["seconds"]
            continue
        if not wanted and target.is_file():
            durations[line_id] = cached.get("seconds", len(al.read_audio(target, 1)) / al.SR)
            continue
        if engine is None:
            engine = BACKENDS[backend_name](model=config.get("model"), lang=config.get("lang"))
        print(f"  {line_id} [{speaker}] {text[:70]}", flush=True)
        audio = finish(engine.synth(text, voice, speed=speed, previous_text=previous, next_text=following))
        al.write_wav(target, audio)
        seconds = round(len(audio) / al.SR, 3)
        manifest[line_id] = {"hash": key, "speaker": speaker, "voice": voice, "text": text, "seconds": seconds}
        durations[line_id] = seconds
    live = set(durations)
    manifest = {k: v for k, v in manifest.items() if k in live}
    al.save_json(manifest_path, manifest)
    al.save_json(out_dir / "durations.json", durations)
    return durations


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--storyboard", type=Path)
    parser.add_argument("--out", type=Path, default=Path("public/vo"))
    parser.add_argument("--backend", choices=sorted(BACKENDS))
    parser.add_argument("--voice")
    parser.add_argument("--model")
    parser.add_argument("--lang")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--sample", help="Speak this text once to --out (a .wav path)")
    parser.add_argument("--only", help="Comma-separated line ids to regenerate")
    parser.add_argument("--force", action="store_true", help="Regenerate even if cached")
    parser.add_argument("--list-voices", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate the ElevenLabs key")
    args = parser.parse_args()
    try:
        if args.check or (args.list_voices and args.backend == "elevenlabs"):
            voices = json.loads(eleven_request("/v1/voices", eleven_key()))["voices"]
            if args.check:
                print(f"OK: ElevenLabs key accepted ({len(voices)} voices visible)")
                return 0
            for voice in voices:
                labels = voice.get("labels") or {}
                tags = ", ".join(str(v) for v in labels.values() if v)
                print(f"{voice['voice_id']}  {voice.get('name', '')}  ({tags})")
            return 0
        if args.list_voices:
            if args.backend == "coqui":
                print("\n".join(Coqui(model=args.model).speakers()) or "(single-speaker model)")
            else:
                print("\n".join(KOKORO_VOICES.values()))
            return 0
        if args.sample:
            if not args.backend:
                parser.error("--sample needs --backend")
            engine = BACKENDS[args.backend](model=args.model, lang=args.lang)
            audio = finish(engine.synth(args.sample, args.voice, speed=args.speed))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            al.write_wav(args.out, audio)
            print(f"Wrote {args.out} ({len(audio) / al.SR:.2f}s)")
            return 0
        if not args.storyboard:
            parser.error("--storyboard is required")
        board = al.load_json(args.storyboard)
        if args.backend:
            board.setdefault("audio", {}).setdefault("voiceover", {})["backend"] = args.backend
        only = set(args.only.split(",")) if args.only else None
        durations = generate(board, args.out, only=only, force=args.force)
        print(f"Wrote {len(durations)} lines, {sum(durations.values()):.1f}s total -> {args.out}/durations.json")
        return 0
    except TTSError as error:
        print(f"voiceover: {error}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
