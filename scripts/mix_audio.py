#!/usr/bin/env python3
"""Mix voice-over, music, and SFX from the timeline into one mastered WAV.

Levels are relative to speech at -20 dBFS RMS. Music sits under the voice and
ducks while anyone speaks; SFX use each cue's gainDb. The sum is mastered to
the target integrated loudness with a true-peak ceiling (defaults: -14 LUFS,
-1.5 dBTP, the common web/social delivery spec).

  mix_audio.py --timeline src/timeline.json --public public --out public/audio/mix.wav
"""

import argparse
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_lib as al  # noqa: E402

SPEECH_RMS = -20.0


def place(bus, start, clip):
    if start >= len(bus) or start + len(clip) <= 0:
        return
    if start < 0:
        clip, start = clip[-start:], 0
    end = min(len(bus), start + len(clip))
    bus[start:end] += clip[: end - start]


def speech_intervals(lines, fps, merge_gap=0.6):
    spans = sorted((l["from"] / fps, (l["from"] + l["durationInFrames"]) / fps) for l in lines if l.get("src"))
    merged = []
    for begin, end in spans:
        if merged and begin - merged[-1][1] < merge_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end])
    return merged


def duck_curve(samples, spans, depth_db, attack=0.25, release=0.5):
    if not spans or depth_db <= 0:
        return np.ones(samples, dtype=np.float32)
    times, gains = [0.0], [0.0]
    for begin, end in spans:
        times += [max(times[-1], begin - attack), max(times[-1], begin)]
        gains += [0.0, -depth_db]
        times += [end, end + release]
        gains += [-depth_db, 0.0]
    curve_db = np.interp(np.arange(samples) / al.SR, times, gains)
    return al.db_to_gain(curve_db).astype(np.float32)


def mix(timeline, public, music_db=None, duck_db=9.0, sfx_db=0.0, vo_db=0.0):
    fps = timeline["fps"]
    samples = int(round(timeline["durationInFrames"] / fps * al.SR))
    vo, music, sfx = (np.zeros((samples, 2), dtype=np.float32) for _ in range(3))
    speakers = sorted({l["speaker"] for l in timeline.get("lines", []) if l.get("src")})
    pans = {s: (0.0 if len(speakers) == 1 else np.linspace(-0.12, 0.12, len(speakers))[i])
            for i, s in enumerate(speakers)}
    for line in timeline.get("lines", []):
        if not line.get("src"):
            continue
        clip = al.read_audio(public / line["src"], channels=1)[:, 0]
        level = al.rms_db(clip)
        if np.isfinite(level):
            clip = clip * al.db_to_gain(SPEECH_RMS + vo_db - level)
        angle = (pans[line["speaker"]] + 1.0) * np.pi / 4.0
        stereo = np.stack([clip * np.cos(angle), clip * np.sin(angle)], axis=1) * np.sqrt(2.0)
        place(vo, int(round(line["from"] / fps * al.SR)), stereo)

    spans = speech_intervals(timeline.get("lines", []), fps)
    track = timeline.get("music")
    if track and (public / track["src"]).is_file():
        bed = al.fit_length(al.read_audio(public / track["src"]), samples)
        level = al.rms_db(bed)
        if music_db is None:
            music_db = -8.0 if spans else 0.0
        if np.isfinite(level):
            bed = bed * al.db_to_gain(SPEECH_RMS + music_db - level)
        music = bed * duck_curve(samples, spans, duck_db)[:, None]

    for cue in timeline.get("sfx", []):
        if not cue.get("src"):
            continue
        clip = al.read_audio(public / cue["src"])
        gain = al.db_to_gain((cue.get("gainDb") or -12.0) + sfx_db)
        place(sfx, int(round(cue["from"] / fps * al.SR)), clip * gain)

    return vo, music, sfx


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeline", type=Path, default=Path("src/timeline.json"))
    parser.add_argument("--public", type=Path, default=Path("public"))
    parser.add_argument("--out", type=Path, default=Path("public/audio/mix.wav"))
    parser.add_argument("--lufs", type=float, default=-14.0)
    parser.add_argument("--tp", type=float, default=-1.5, help="True-peak ceiling, dBTP")
    parser.add_argument("--music-db", type=float, help="Music level vs speech (default -8 with VO, 0 without)")
    parser.add_argument("--duck-db", type=float, default=9.0, help="Extra music attenuation under speech")
    parser.add_argument("--sfx-db", type=float, default=0.0, help="Offset added to every cue's gainDb")
    parser.add_argument("--vo-db", type=float, default=0.0)
    parser.add_argument("--stems", action="store_true", help="Also write vo/music/sfx stems next to --out")
    args = parser.parse_args()

    timeline = al.load_json(args.timeline)
    vo, music, sfx = mix(timeline, args.public, args.music_db, args.duck_db, args.sfx_db, args.vo_db)
    total = vo + music + sfx
    if not np.abs(total).max() > 0:
        raise SystemExit("mix is silent: no VO lines, music, or SFX with rendered files in the timeline")
    mastered, stats = al.master(total, args.lufs, args.tp)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    al.write_wav(args.out, mastered)
    gain = float(np.abs(mastered).max() / max(np.abs(total).max(), 1e-9))
    if args.stems:
        for name, stem in (("vo", vo), ("music", music), ("sfx", sfx)):
            al.write_wav(args.out.with_name(f"stem-{name}.wav"), stem * gain)
    report = {**stats, "seconds": round(len(mastered) / al.SR, 3), "target_lufs": args.lufs, "tp_ceiling": args.tp,
              "vo_lines": sum(1 for l in timeline.get("lines", []) if l.get("src")),
              "sfx_cues": sum(1 for c in timeline.get("sfx", []) if c.get("src")),
              "music": bool(np.abs(music).max() > 0)}
    al.save_json(args.out.with_suffix(".json"), report)
    print(f"Mix: {report['seconds']}s, {stats['lufs']} LUFS, {stats['true_peak']} dBTP, "
          f"{report['vo_lines']} lines, {report['sfx_cues']} sfx, music={report['music']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
