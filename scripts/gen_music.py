#!/usr/bin/env python3
"""Compose and synthesize an original, royalty-free music bed with numpy.

Nothing is sampled or downloaded: pads, plucks, keys, bass, and drums are
synthesized from oscillators and noise. With --timeline, the arrangement
follows the scenes: each scene's energy picks which layers play, and the
track lasts exactly as long as the video and resolves on the tonic.

  gen_music.py --timeline src/timeline.json --out public/music/music.wav
  gen_music.py --style ambient --bpm 80 --key D --duration 30 --out music-sample.wav
"""

import argparse
from pathlib import Path
import re
import sys

import numpy as np
from scipy.signal import butter, oaconvolve, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_lib as al  # noqa: E402

SR = al.SR
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MAJOR, MINOR = [0, 2, 4, 5, 7, 9, 11], [0, 2, 3, 5, 7, 8, 10]

STYLES = {
    #            key   bpm  progression    beats/chord 7ths  reverb (rt60, wet)
    "ambient":    dict(key="D", bpm=80, prog=[1, 6, 4, 5], beats=8, sevenths=True, reverb=(3.2, 0.42)),
    "corporate":  dict(key="C", bpm=112, prog=[1, 5, 6, 4], beats=4, sevenths=False, reverb=(1.4, 0.16)),
    "lofi":       dict(key="F", bpm=80, prog=[2, 5, 1, 6], beats=4, sevenths=True, reverb=(1.2, 0.18)),
    "cinematic":  dict(key="Dm", bpm=90, prog=[1, 6, 3, 7], beats=8, sevenths=False, reverb=(3.6, 0.38)),
    "electronic": dict(key="C", bpm=122, prog=[6, 4, 1, 5], beats=4, sevenths=False, reverb=(1.8, 0.2)),
}


def parse_key(key):
    match = re.fullmatch(r"([A-Ga-g])([#b]?)(m|min|minor)?", key.strip())
    if not match:
        raise SystemExit(f"bad key '{key}' (examples: C, F#, Bb, Am, C#m)")
    root = (NOTE[match.group(1).upper()] + {"#": 1, "b": -1, "": 0}[match.group(2)]) % 12
    return root, (MINOR if match.group(3) else MAJOR)


def midi_hz(note):
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def chord_pcs(degree, scale, sevenths):
    idx = [degree - 1 + step for step in ((0, 2, 4, 6) if sevenths else (0, 2, 4))]
    return [scale[i % 7] + 12 * (i // 7) for i in idx]


def voice_lead(pcs, root, previous, low=50, high=79):
    """Pick the inversion/octave of the chord closest to the previous voicing."""
    best, best_cost = None, None
    for octave in range(3, 7):
        for inversion in range(len(pcs)):
            rotated = pcs[inversion:] + [p + 12 for p in pcs[:inversion]]
            notes = [12 * octave + root + p for p in rotated]
            if notes[0] < low or notes[-1] > high:
                continue
            cost = (sum(abs(a - b) for a, b in zip(notes, previous)) if previous and len(previous) == len(notes)
                    else abs(np.mean(notes) - 62) * 2)
            if best_cost is None or cost < best_cost:
                best, best_cost = notes, cost
    return best


# ---------------------------------------------------------------- oscillators & envelopes

def saw(freq, n, phase):
    dt = freq / SR
    t = (phase + dt * np.arange(n)) % 1.0
    y = 2.0 * t - 1.0
    head = t < dt
    x = t[head] / dt
    y[head] -= x + x - x * x - 1.0
    tail = t > 1.0 - dt
    x = (t[tail] - 1.0) / dt
    y[tail] -= x * x + x + x + 1.0
    return y


def env_adsr(n, attack, release_start, release):
    t = np.arange(n) / SR
    env = np.minimum(1.0, t / max(attack, 1e-4))
    after = t > release_start
    env[after] *= np.exp(-(t[after] - release_start) / max(release / 4.0, 1e-4))
    return env


def lowpass(x, cutoff, order=2):
    sos = butter(order, min(cutoff, SR * 0.45), btype="low", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def highpass(x, cutoff, order=2):
    sos = butter(order, cutoff, btype="high", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def bandpass(x, lo, hi, order=2):
    sos = butter(order, [lo, min(hi, SR * 0.45)], btype="band", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def pan(mono, position):
    """Equal-power pan, position in [-1, 1]."""
    angle = (position + 1.0) * np.pi / 4.0
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1)


# ---------------------------------------------------------------- instruments

def pad(notes, seconds, rng, cutoff=1400.0, attack=1.2, release=2.0, detune=7.0):
    n = int((seconds + release) * SR)
    left, right = np.zeros(n), np.zeros(n)
    for note in notes:
        f = midi_hz(note)
        for cents, (gl, gr) in ((-detune, (0.9, 0.35)), (0.0, (0.6, 0.6)), (detune, (0.35, 0.9))):
            tone = saw(f * 2 ** (cents / 1200.0), n, rng.random())
            left += gl * tone
            right += gr * tone
    stereo = lowpass(np.stack([left, right], axis=1), cutoff)
    return stereo * env_adsr(n, attack, seconds, release)[:, None] / (len(notes) * 1.8)


def pluck(note, seconds, rng, brightness=1.0, position=0.0):
    n = int((seconds + 0.6) * SR)
    t = np.arange(n) / SR
    f = midi_hz(note)
    y = np.zeros(n)
    for k in range(1, 9):
        if f * k > 12000:
            break
        y += np.sin(2 * np.pi * f * k * t + rng.random()) * (1.0 / k ** (1.4 - 0.4 * brightness)) \
            * np.exp(-t * (3.0 + 2.2 * k))
    y[: int(0.003 * SR)] += rng.normal(0, 0.3, int(0.003 * SR))
    y *= np.minimum(1.0, t / 0.002)
    return pan(y * 0.5, position)


def epiano(note, seconds, rng, position=0.0):
    n = int((seconds + 1.2) * SR)
    t = np.arange(n) / SR
    f = midi_hz(note)
    y = (np.sin(2 * np.pi * f * t) * np.exp(-t * 1.1)
         + 0.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 2.4)
         + 0.1 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 4.0)
         + 0.07 * np.sin(2 * np.pi * 7.02 * f * t) * np.exp(-t * 16.0))
    y *= np.minimum(1.0, t / 0.004) * env_adsr(n, 0.001, seconds, 0.5)
    tremolo = 0.12 * np.sin(2 * np.pi * 4.6 * t + rng.random() * 6.28)
    stereo = pan(y * 0.4, position)
    stereo[:, 0] *= 1.0 + tremolo
    stereo[:, 1] *= 1.0 - tremolo
    return stereo


def bell(note, rng, position=0.0):
    n = int(3.5 * SR)
    t = np.arange(n) / SR
    f = midi_hz(note)
    y = sum(a * np.sin(2 * np.pi * f * r * t + rng.random()) * np.exp(-t * d)
            for r, a, d in ((1.0, 1.0, 0.9), (2.0, 0.35, 1.6), (2.76, 0.22, 2.6), (5.4, 0.08, 5.5)))
    return pan(y * np.minimum(1.0, t / 0.002) * 0.35, position)


def bass(note, seconds, kind="sine"):
    n = int((seconds + 0.08) * SR)
    t = np.arange(n) / SR
    f = midi_hz(note)
    if kind == "saw":
        y = lowpass(saw(f, n, 0.0), 420.0) * 1.4
    else:
        y = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    y = np.tanh(1.6 * y) * env_adsr(n, 0.006, seconds, 0.07)
    return pan(y * 0.55, 0.0)


def staccato(note, rng, position=0.0):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    tone = sum(saw(midi_hz(note) * 2 ** (c / 1200.0), n, rng.random()) for c in (-6, 0, 6)) / 3.0
    y = lowpass(tone, 1900.0) * np.exp(-t * 11.0) * np.minimum(1.0, t / 0.004)
    return pan(y * 0.45, position)


# ---------------------------------------------------------------- drums

def kick(rng, punch=1.0):
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    freq = 44.0 + 120.0 * np.exp(-t * 28.0) * punch
    y = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 7.5)
    y[: int(0.004 * SR)] += rng.normal(0, 0.25, int(0.004 * SR))
    return pan(np.tanh(2.2 * y) * 0.9, 0.0)


def snare(rng):
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    noise = bandpass(rng.normal(0, 1, n), 1200, 9000) * np.exp(-t * 20.0)
    tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 28.0)
    return pan((0.55 * noise + 0.5 * tone) * 0.7, 0.05)


def clap(rng):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    env = sum(np.exp(-np.maximum(t - d, 0) * 90.0) * (t >= d) for d in (0.0, 0.011, 0.022))
    env = env + 0.6 * np.exp(-np.maximum(t - 0.03, 0) * 16.0) * (t >= 0.03)
    return pan(bandpass(rng.normal(0, 1, n), 900, 3200) * env * 0.5, -0.05)


def hat(rng, open_=False):
    n = int((0.35 if open_ else 0.07) * SR)
    t = np.arange(n) / SR
    y = highpass(rng.normal(0, 1, n), 7000, 4) * np.exp(-t * (11.0 if open_ else 65.0))
    return pan(y * (0.22 if open_ else 0.28), 0.25)


def shaker(rng):
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    y = highpass(rng.normal(0, 1, n), 5000) * np.sin(np.pi * t / t[-1]) ** 2
    return pan(y * 0.16, -0.3)


def taiko(rng):
    n = int(1.2 * SR)
    t = np.arange(n) / SR
    freq = 58.0 + 70.0 * np.exp(-t * 18.0)
    y = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 4.0)
    y += lowpass(rng.normal(0, 1, n), 900) * np.exp(-t * 30.0) * 0.8
    return pan(np.tanh(1.8 * y) * 0.85, 0.0)


def noise_riser(seconds, rng):
    y = al.shaped_noise(seconds, [400.0, 7000.0], rng, width_oct=0.7)
    return pan(y * np.linspace(0.0, 1.0, len(y)) ** 2.2 * 0.35, 0.0)


# ---------------------------------------------------------------- arrangement

class Mix:
    def __init__(self, seconds):
        self.n = int(seconds * SR)
        self.buses = {}

    def add(self, bus, start_seconds, signal, gain=1.0):
        buffer = self.buses.setdefault(bus, np.zeros((self.n + 6 * SR, 2)))
        start = int(round(start_seconds * SR))
        if start >= len(buffer) or start + len(signal) <= 0:
            return
        if start < 0:
            signal, start = signal[-start:], 0
        end = min(len(buffer), start + len(signal))
        buffer[start:end] += signal[: end - start] * gain


def energy_at(sections, time):
    for section in sections:
        if section["start"] <= time < section["end"]:
            return section["energy"]
    return sections[-1]["energy"] if time >= sections[-1]["start"] else sections[0]["energy"]


def reverb(signal, rt60, rng):
    n = int(rt60 * SR)
    t = np.arange(n) / SR
    ir = rng.normal(0, 1, (n, 2)) * np.exp(-6.91 * t / rt60)[:, None]
    ir = lowpass(ir, 6500.0)
    ir[: int(0.012 * SR)] = 0.0  # pre-delay
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True))
    return np.stack([oaconvolve(signal[:, c], ir[:, c])[: len(signal)] for c in range(2)], axis=1)


def compose(style, bpm, key, seconds, sections, seed=1):
    cfg = STYLES[style]
    root, scale = parse_key(key)
    beat = 60.0 / bpm
    bar = 4 * beat
    chord_len = cfg["beats"] * beat
    rng = {name: np.random.default_rng(seed * 101 + i) for i, name in enumerate(
        ("pad", "arp", "bass", "drums", "fx", "human", "keys"))}
    mix = Mix(seconds)

    # Chords on a fixed grid from t=0; the final stretch resolves to the tonic.
    resolve_at = max(sections[-1]["start"], seconds - 2 * bar)
    resolve_at = np.floor(resolve_at / bar) * bar
    slots, previous, time, index = [], None, 0.0, 0
    while time < seconds:
        degree = 1 if time >= resolve_at else cfg["prog"][index % len(cfg["prog"])]
        notes = voice_lead(chord_pcs(degree, scale, cfg["sevenths"]), root, previous)
        length = (seconds - time) if degree == 1 and time >= resolve_at else chord_len
        slots.append((time, length, degree, notes))
        previous, time, index = notes, time + length, index + 1

    drum_kit = {name: [fn(rng["drums"]) for _ in range(3)] for name, fn in
                (("kick", kick), ("snare", snare), ("clap", clap), ("hat", hat), ("shaker", shaker),
                 ("taiko", taiko))}
    drum_kit["open"] = [hat(rng["drums"], open_=True) for _ in range(3)]

    def hit(name, when, gain):
        variants = drum_kit[name]
        jitter = rng["human"].normal(0, 0.003 if style != "lofi" else 0.007)
        mix.add("drums", when + jitter, variants[rng["human"].integers(len(variants))],
                gain * rng["human"].uniform(0.88, 1.0))

    for start, length, degree, notes in slots:
        energy = energy_at(sections, start)
        final = start >= resolve_at
        bass_root = 36 + (root + chord_pcs(degree, scale, False)[0]) % 12  # MIDI 36-47: 65-123 Hz
        # Pad / keys bed.
        if style == "lofi":
            for i, note in enumerate(notes):
                mix.add("keys", start + i * 0.012, epiano(note, length, rng["keys"], (i - 1.5) * 0.3), 0.8)
            mix.add("pad", start, pad(notes, length, rng["pad"], cutoff=900, attack=0.8), 0.25)
        else:
            cutoff = {"ambient": 2100, "cinematic": 2300, "corporate": 3000, "electronic": 3600}[style]
            mix.add("pad", start, pad(notes, length, rng["pad"], cutoff=cutoff * (0.7 + 0.5 * energy),
                                      attack=1.6 if style in ("ambient", "cinematic") else 0.5), 0.9)
            if style in ("ambient", "cinematic") and energy >= 0.5:  # airy octave shimmer
                mix.add("pad", start, pad([n + 12 for n in notes[1:]], length, rng["pad"], cutoff=6000,
                                          attack=2.0, detune=11), 0.22)
        if style == "corporate" and energy >= 0.55:
            for i, note in enumerate(notes):
                mix.add("keys", start, epiano(note + 12, min(length, 2 * beat), rng["keys"], (i - 1) * 0.25), 0.3)

        steps = int(round(length / (beat / 4)))
        for step in range(steps):
            when = start + step * beat / 4
            if when >= seconds:
                break
            e = energy_at(sections, when)
            in_bar = int(round((when % bar) / (beat / 4))) % 16
            swing = (0.16 * beat / 4) if style == "lofi" and in_bar % 4 == 2 else 0.0
            # Bass.
            if e >= 0.45 and not final:
                if style == "electronic" and in_bar % 4 == 2:
                    mix.add("bass", when, bass(bass_root, beat * 0.4, "saw"), 0.7)
                elif style in ("corporate",) and in_bar % 4 == 0:
                    mix.add("bass", when, bass(bass_root, beat * 0.9), 0.8)
                elif style in ("lofi", "ambient", "cinematic") and in_bar in (0, 10) and e >= 0.55:
                    mix.add("bass", when + swing, bass(bass_root, beat * (2.4 if in_bar == 0 else 1.4)), 0.85)
            elif final and step == 0:
                mix.add("bass", when, bass(bass_root, length), 0.7)
            # Arpeggios / melodic layer.
            if e >= 0.55 and not final:
                arp_notes = notes + [n + 12 for n in notes]
                if style in ("corporate", "electronic") and in_bar % 2 == 0:
                    order = [0, 2, 1, 3, 2, 4, 3, 5]
                    note = arp_notes[order[(step // 2) % len(order)] % len(arp_notes)] + 12
                    mix.add("arp", when, pluck(note, beat / 2, rng["arp"], 1.0, 0.35 * np.sin(step)), 0.33)
                elif style == "ambient" and in_bar % 4 == 0 and rng["arp"].random() < 0.55:
                    note = arp_notes[rng["arp"].integers(len(arp_notes))] + 12
                    mix.add("arp", when, bell(note, rng["arp"], rng["arp"].uniform(-0.6, 0.6)), 0.3)
                elif style == "cinematic" and in_bar % 2 == 0:
                    note = [notes[0], notes[0] + 7, notes[0] + 12, notes[0] + 7][(step // 2) % 4] - 12
                    mix.add("arp", when, staccato(note, rng["arp"], 0.3 * np.sin(step * 0.7)), 0.4 * e)
                elif style == "lofi" and in_bar in (6, 14) and rng["arp"].random() < 0.5:
                    note = arp_notes[rng["arp"].integers(len(arp_notes))] + 12
                    mix.add("arp", when + swing, epiano(note, beat, rng["arp"], 0.4), 0.25)
            # Drums.
            if final or e < 0.6:
                continue
            if style == "corporate":
                if in_bar in (0, 8) or (e >= 0.85 and in_bar == 10):
                    hit("kick", when, 0.9)
                if in_bar in (4, 12):
                    hit("clap", when, 0.6)
                if e >= 0.7 and in_bar % 2 == 0 and in_bar % 4 != 0:
                    hit("hat", when, 0.7)
                if e >= 0.85:
                    hit("shaker", when, 0.5)
            elif style == "electronic":
                if in_bar % 4 == 0:
                    hit("kick", when, 1.0)
                if in_bar in (4, 12):
                    hit("clap", when, 0.6)
                if in_bar % 4 == 2:
                    hit("open", when, 0.6)
                if e >= 0.85 and in_bar % 4 != 2:
                    hit("hat", when, 0.45)
            elif style == "lofi":
                if in_bar in (0, 7, 10):
                    hit("kick", when + swing, 0.55)
                if in_bar in (4, 12):
                    hit("snare", when, 0.55)
                if in_bar % 2 == 0:
                    hit("hat", when + swing, 0.45 if in_bar % 4 else 0.6)
            elif style == "cinematic":
                if in_bar == 0 or (e >= 0.8 and in_bar in (8, 14, 15)):
                    hit("taiko", when, 0.9 if in_bar == 0 else 0.6)
            elif style == "ambient" and e >= 0.8 and in_bar % 2 == 0:
                hit("shaker", when, 0.35)

    # Section lifts: riser (cinematic/electronic) or snare fill into a higher-energy section.
    for previous_section, section in zip(sections, sections[1:]):
        if section["energy"] <= previous_section["energy"] + 0.05 or section["start"] >= resolve_at:
            continue
        lift = section["start"]
        if style in ("cinematic", "electronic"):
            length = min(2 * beat, lift)
            mix.add("fx", lift - length, noise_riser(length, rng["fx"]), 0.55)
        elif style == "corporate" and previous_section["energy"] >= 0.6:
            for k in range(4):
                hit("snare", lift - beat + k * beat / 4, 0.25 + 0.12 * k)

    # Buses -> master.
    gains = {"pad": 0.8, "keys": 1.0, "arp": 0.9, "bass": 0.5, "drums": 0.8, "fx": 0.7}
    sends = {"pad": 0.55, "keys": 0.35, "arp": 0.6, "bass": 0.0, "drums": 0.12, "fx": 0.4}
    total = mix.n + 6 * SR
    dry, send = np.zeros((total, 2)), np.zeros((total, 2))
    t = np.arange(total) / SR
    for name, buffer in mix.buses.items():
        if style == "electronic" and name in ("pad", "bass", "arp"):  # sidechain pump from the kick
            pump = 1.0 - 0.55 * np.exp(-(t % beat) / 0.11)
            energies = np.array([energy_at(sections, x) for x in np.arange(0, total / SR, beat)])
            active = np.repeat(energies >= 0.6, int(np.ceil(beat * SR)))[:total]
            buffer = buffer * np.where(active, pump, 1.0)[:, None]
        dry += buffer * gains[name]
        send += buffer * gains[name] * sends[name]
    rt60, wet = cfg["reverb"]
    out = dry + wet * reverb(send, rt60, rng["fx"])
    if style == "lofi":
        out = lowpass(out, 5200.0)
        crackle = np.zeros(total)
        pops = rng["fx"].integers(0, total, int(total / SR * 6))
        crackle[pops] = rng["fx"].normal(0, 0.25, len(pops))
        hiss = highpass(rng["fx"].normal(0, 0.004, total), 3000)
        out += pan(lowpass(crackle, 4000) + hiss, 0.0)
    out = highpass(out, 32.0)[: mix.n]
    out = out / max(float(np.abs(out).max()), 1e-9)
    out = np.tanh(out * 1.2) / np.tanh(1.2)  # gentle glue; peak stays at 1.0
    fade_out = min(2.5, max(1.0, seconds * 0.06))
    out = al.fade(out, fade_in=0.4 if sections[0]["energy"] < 0.5 else 0.05, fade_out=fade_out)
    return out.astype(np.float32)


def auto_sections(seconds):
    marks = [(0.0, 0.35), (0.12, 0.65), (0.3, 0.85), (0.86, 0.4)]
    return [{"start": seconds * a, "end": seconds * (marks[i + 1][0] if i + 1 < len(marks) else 1.0), "energy": e}
            for i, (a, e) in enumerate(marks)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeline", type=Path)
    parser.add_argument("--style", choices=sorted(STYLES))
    parser.add_argument("--bpm", type=float)
    parser.add_argument("--key")
    parser.add_argument("--duration", type=float, help="Seconds (without --timeline)")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--lufs", type=float, default=-16.0, help="Loudness of the standalone file")
    parser.add_argument("--out", type=Path, default=Path("public/music/music.wav"))
    args = parser.parse_args()

    sections = None
    if args.timeline:
        timeline = al.load_json(args.timeline)
        music = timeline.get("music") or {}
        if not music:
            raise SystemExit("timeline has no music section (storyboard audio.music is null)")
        style = args.style or music.get("style") or "ambient"
        bpm = args.bpm or music.get("bpm") or STYLES[style]["bpm"]
        key = args.key or music.get("key") or STYLES[style]["key"]
        seed = args.seed if args.seed is not None else (music.get("seed") or 1)
        seconds = timeline["durationInFrames"] / timeline["fps"]
        sections = music.get("sections")
    else:
        if not args.duration:
            parser.error("--duration or --timeline is required")
        style = args.style or "ambient"
        bpm, key = args.bpm or STYLES[style]["bpm"], args.key or STYLES[style]["key"]
        seed, seconds = (args.seed if args.seed is not None else 1), args.duration
    if style not in STYLES:
        raise SystemExit(f"unknown style '{style}' (use {sorted(STYLES)})")
    sections = sections or auto_sections(seconds)
    audio = compose(style, float(bpm), key, seconds, sections, seed)
    audio, stats = al.master(audio, args.lufs, -1.0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    al.write_wav(args.out, audio)
    meta = {"style": style, "bpm": bpm, "key": key, "seed": seed, "seconds": round(seconds, 3),
            "sections": sections, **stats}
    al.save_json(args.out.with_suffix(".json"), meta)
    print(f"Music: {style} {key} {bpm:g} bpm seed {seed}, {seconds:.2f}s, {stats['lufs']} LUFS -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
