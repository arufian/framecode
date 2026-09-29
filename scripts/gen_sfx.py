#!/usr/bin/env python3
"""Synthesize sound effects from noise and oscillators (no samples, no downloads).

Each effect has a sync point: the moment that should land on the cue (a
whoosh peaks mid-transition, a riser ends on the cut, an impact starts on it).
With --timeline, every cue in timeline.sfx is rendered to public/sfx/ and its
start frame is written back so the mixer and the studio place it exactly.

  gen_sfx.py --timeline src/timeline.json --outdir public/sfx
  gen_sfx.py --type whoosh --out whoosh.wav [--seconds 0.9] [--seed 3]
  gen_sfx.py --all --outdir sfx-preview/
"""

import argparse
import hashlib
from pathlib import Path
import sys

import numpy as np
from scipy.signal import butter, oaconvolve, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_lib as al  # noqa: E402

SR = al.SR


def _t(seconds):
    return np.arange(int(seconds * SR)) / SR


def _filter(x, kind, cutoff, order=2):
    return sosfilt(butter(order, cutoff, btype=kind, fs=SR, output="sos"), x, axis=0)


def _pan_sweep(mono, start=-0.7, end=0.7):
    position = np.linspace(start, end, len(mono))
    angle = (position + 1.0) * np.pi / 4.0
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1)


def _center(mono):
    return np.stack([mono, mono], axis=1) * 0.7071


def _room(stereo, rng, seconds=0.9, wet=0.25):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = rng.normal(0, 1, (n, 2)) * np.exp(-6.91 * t / seconds)[:, None]
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True))
    tail = np.stack([oaconvolve(stereo[:, c], ir[:, c]) for c in range(2)], axis=1)
    out = np.zeros_like(tail)
    out[: len(stereo)] += stereo
    return out + wet * tail


def _bell(freq, seconds, rng, decay=1.0):
    t = _t(seconds)
    return sum(a * np.sin(2 * np.pi * freq * r * t + rng.random()) * np.exp(-t * d * decay)
               for r, a, d in ((1.0, 1.0, 2.2), (2.0, 0.45, 3.5), (2.76, 0.3, 5.0), (5.4, 0.12, 9.0),
                               (8.93, 0.05, 14.0))) * np.minimum(1.0, t / 0.0015)


# ---------------------------------------------------------------- effects: fn(rng, seconds, pitch) -> (stereo, sync)

def whoosh(rng, seconds=0.9, pitch=1.0):
    y = al.shaped_noise(seconds, [350 * pitch, 2600 * pitch, 900 * pitch], rng, widths=[0.5, 0.9, 0.6])
    x = np.linspace(0, 1, len(y))
    env = np.where(x < 0.6, (x / 0.6) ** 2.2, ((1 - x) / 0.4) ** 1.6)
    return _pan_sweep(y * env), 0.6 * seconds


def swoosh(rng, seconds=0.45, pitch=1.0):
    stereo, _ = whoosh(rng, seconds, pitch * 1.8)
    return stereo, 0.55 * seconds


def swipe(rng, seconds=0.3, pitch=1.0):
    y = al.shaped_noise(seconds, [2500 * pitch, 6000 * pitch], rng, width_oct=0.5)
    x = np.linspace(0, 1, len(y))
    return _pan_sweep(y * np.sin(np.pi * x) ** 1.5, 0.3, -0.3), 0.4 * seconds


def riser(rng, seconds=2.0, pitch=1.0):
    t = _t(seconds)
    x = t / seconds
    noise = al.shaped_noise(seconds, [300 * pitch, 7000 * pitch], rng, width_oct=0.7)
    freq = 180 * pitch * (7.0 ** (x ** 1.6))
    tone = sum(np.sin(2 * np.pi * np.cumsum(freq * k) / SR) / k for k in (1, 2, 3))
    y = (0.7 * noise + 0.25 * tone) * x ** 2.4
    y[-int(0.012 * SR):] *= np.linspace(1, 0, int(0.012 * SR))
    return _center(y), seconds


def downlifter(rng, seconds=1.5, pitch=1.0):
    stereo, _ = riser(rng, seconds, pitch)
    return stereo[::-1].copy(), 0.0


def impact(rng, seconds=1.6, pitch=1.0):
    t = _t(seconds)
    sub = np.sin(2 * np.pi * np.cumsum(34 * pitch + 50 * pitch * np.exp(-t * 9)) / SR) * np.exp(-t * 3.2)
    crack = _filter(rng.normal(0, 1, len(t)), "low", 2400) * np.exp(-t * 22)
    y = np.tanh(1.8 * (sub + 0.6 * crack))
    return _room(_center(y), rng, 1.2, 0.3), 0.0


def boom(rng, seconds=2.6, pitch=1.0):
    stereo, _ = impact(rng, seconds, pitch * 0.8)
    return _room(stereo, rng, 2.2, 0.35), 0.0


def subdrop(rng, seconds=1.2, pitch=1.0):
    t = _t(seconds)
    freq = 30 * pitch + 90 * pitch * np.exp(-t * 3.0)
    y = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 2.2) * np.minimum(1, t / 0.01)
    return _center(np.tanh(1.5 * y)), 0.0


def pop(rng, seconds=0.15, pitch=1.0):
    t = _t(seconds)
    freq = 260 * pitch + 700 * pitch * np.exp(-t * 60)
    y = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 38) * np.minimum(1, t / 0.001)
    return _center(y), 0.0


def click(rng, seconds=0.05, pitch=1.0):
    t = _t(seconds)
    y = _filter(rng.normal(0, 1, len(t)), "high", 1800) * np.exp(-t * 400)
    y += 0.5 * np.sin(2 * np.pi * 2100 * pitch * t) * np.exp(-t * 160)
    return _center(y), 0.0


def tick(rng, seconds=0.04, pitch=1.0):
    t = _t(seconds)
    y = np.sin(2 * np.pi * 1450 * pitch * t) * np.exp(-t * 220) + \
        0.3 * _filter(rng.normal(0, 1, len(t)), "high", 4000) * np.exp(-t * 600)
    return _center(y), 0.0


def ding(rng, seconds=1.5, pitch=1.0):
    return _room(_center(_bell(1318.5 * pitch, seconds, rng)), rng, 1.0, 0.2), 0.0


def chime(rng, seconds=1.6, pitch=1.0):
    out = np.zeros((int((seconds + 0.2) * SR), 2))
    for i, semis in enumerate((0, 4, 7)):
        note = _bell(1046.5 * pitch * 2 ** (semis / 12), seconds, rng)
        start = int(i * 0.07 * SR)
        out[start:start + len(note)] += _center(note)[: len(out) - start] * (0.8 + 0.1 * i)
    return _room(out, rng, 1.2, 0.25), 0.0


def sparkle(rng, seconds=1.0, pitch=1.0):
    out = np.zeros((int((seconds + 0.5) * SR), 2))
    for _ in range(11):
        at = int(rng.uniform(0, seconds * 0.8) * SR)
        note = _bell(rng.uniform(2200, 5200) * pitch, 0.5, rng, decay=2.0) * rng.uniform(0.3, 0.8)
        side = rng.uniform(-0.8, 0.8)
        angle = (side + 1) * np.pi / 4
        out[at:at + len(note)] += np.stack([note * np.cos(angle), note * np.sin(angle)], axis=1)[: len(out) - at]
    return _room(out, rng, 1.4, 0.35), 0.05


def glitch(rng, seconds=0.35, pitch=1.0):
    n = int(seconds * SR)
    y = np.zeros(n)
    at = 0
    while at < n:
        length = int(rng.uniform(0.01, 0.045) * SR)
        kind = rng.integers(3)
        seg = np.arange(min(length, n - at)) / SR
        if kind == 0:
            y[at:at + len(seg)] = np.sign(np.sin(2 * np.pi * rng.uniform(200, 1800) * pitch * seg)) * 0.5
        elif kind == 1:
            y[at:at + len(seg)] = rng.normal(0, 0.6, len(seg))
        at += len(seg) + int(rng.uniform(0, 0.02) * SR)
    y = np.round(y * 6) / 6  # bit-crush
    return _center(np.repeat(y[::6], 6)[:n]), 0.0


def typing(rng, seconds=1.2, pitch=1.0):
    n = int(seconds * SR)
    out = np.zeros((n + SR // 10, 2))
    at = 0.0
    while at < seconds:
        key, _ = click(rng, 0.05, pitch * rng.uniform(0.7, 1.2))
        start = int(at * SR)
        out[start:start + len(key)] += key * rng.uniform(0.5, 1.0)
        at += rng.uniform(0.06, 0.15)
    return out, 0.0


def paper(rng, seconds=0.5, pitch=1.0):
    """Paper tear / rustle: crackly band-limited noise bursts (for tear transitions)."""
    n = int(seconds * SR)
    y = al.shaped_noise(seconds, [1800 * pitch, 3500 * pitch, 2200 * pitch], rng, width_oct=0.9)
    crackle = (rng.random(n) < 0.012) * rng.normal(0, 1.0, n)
    x = np.linspace(0, 1, n)
    env = np.sin(np.pi * np.clip(x * 1.1, 0, 1)) ** 0.7 * (0.6 + 0.4 * rng.random(n) ** 3)
    return _pan_sweep((0.7 * y + 0.5 * _filter(crackle, "high", 1500)) * env, -0.3, 0.4), 0.3 * seconds


def pencil(rng, seconds=1.0, pitch=1.0):
    """Graphite scratching on paper (for draw-on animations)."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    scratch = _filter(_filter(rng.normal(0, 1, n), "high", 2500), "low", 9000)
    strokes = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(5, 8) * t + rng.random() * 6) ** 2
    y = scratch * strokes * np.minimum(1, t / 0.03) * np.minimum(1, (seconds - t) / 0.08)
    return _center(y * 0.8), 0.0


EFFECTS = {fn.__name__: fn for fn in (whoosh, swoosh, swipe, riser, downlifter, impact, boom, subdrop, pop,
                                      click, tick, ding, chime, sparkle, glitch, typing, paper, pencil)}
DEFAULT_GAIN_DB = {"whoosh": -9, "swoosh": -11, "swipe": -12, "riser": -12, "downlifter": -12, "impact": -7,
                   "boom": -8, "subdrop": -12, "pop": -12, "click": -16, "tick": -15, "ding": -12, "chime": -12,
                   "sparkle": -14, "glitch": -16, "typing": -16, "paper": -10, "pencil": -15}


def render(kind, seed=1, seconds=None, pitch=1.0):
    if kind not in EFFECTS:
        raise SystemExit(f"unknown sfx '{kind}' (use {sorted(EFFECTS)})")
    rng = np.random.default_rng(seed)
    kwargs = {"pitch": pitch}
    if seconds:
        kwargs["seconds"] = seconds
    stereo, sync = EFFECTS[kind](rng, **kwargs)
    stereo = al.fade(al.as_2d(stereo), 0.0005, min(0.02, len(stereo) / SR * 0.2))
    peak = float(np.abs(stereo).max())
    stereo = stereo / peak * al.db_to_gain(-1.0) if peak > 0 else stereo
    return stereo.astype(np.float32), float(sync)


def from_timeline(timeline_path, outdir):
    timeline = al.load_json(timeline_path)
    fps = timeline["fps"]
    outdir.mkdir(parents=True, exist_ok=True)
    for cue in timeline.get("sfx", []):
        params = cue.get("params") or {}
        seed = int(hashlib.sha256(f"{cue['id']}:{cue['type']}".encode()).hexdigest()[:8], 16) % 100000
        audio, sync = render(cue["type"], seed=params.get("seed", seed), seconds=params.get("seconds"),
                             pitch=params.get("pitch", 1.0))
        name = f"{cue['id']}-{cue['type']}.wav"
        al.write_wav(outdir / name, audio)
        cue["src"] = f"{outdir.name}/{name}"
        cue["from"] = cue["syncFrame"] - round(sync * fps)
        cue["durationInFrames"] = int(np.ceil(len(audio) / SR * fps))
        if cue.get("gainDb") is None:
            cue["gainDb"] = DEFAULT_GAIN_DB[cue["type"]]
    al.save_json(timeline_path, timeline)
    return len(timeline.get("sfx", []))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeline", type=Path)
    parser.add_argument("--outdir", type=Path, default=Path("public/sfx"))
    parser.add_argument("--type", choices=sorted(EFFECTS))
    parser.add_argument("--all", action="store_true", help="Render one of every effect to --outdir")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--pitch", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for name in EFFECTS:
            print(f"{name:11s} {EFFECTS[name].__doc__ or ''}".rstrip())
        return 0
    if args.timeline:
        count = from_timeline(args.timeline, args.outdir)
        print(f"SFX: rendered {count} cues -> {args.outdir} (timeline updated)")
        return 0
    if args.all:
        args.outdir.mkdir(parents=True, exist_ok=True)
        for name in EFFECTS:
            audio, _ = render(name, args.seed)
            al.write_wav(args.outdir / f"{name}.wav", audio)
        print(f"SFX: {len(EFFECTS)} previews -> {args.outdir}")
        return 0
    if not (args.type and args.out):
        parser.error("use --timeline, --all, or --type with --out")
    audio, sync = render(args.type, args.seed, args.seconds, args.pitch)
    al.write_wav(args.out, audio)
    print(f"Wrote {args.out} ({len(audio) / SR:.2f}s, sync at {sync:.3f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
