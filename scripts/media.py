#!/usr/bin/env python3
"""Measure and prepare the media ledger (media/sources.json) for the engine and the mixer.

The ledger lists every outside file the video uses: Mixkit downloads (mixkit.py get writes
them) and the user's own files (media.py add). Each entry has a name, a kind (music, sfx,
video, art, image), a file under media/, its page and licence, and optional hand-set fields:
  in, out        seconds: use only this part of the file (audio and video)
  sync           sfx: "hit" (first loud peak), "peak" (loudest point), or milliseconds
  gainDb         sfx: level in the mix (default by name: whoosh -9, pop -12, click -16, ...)
  bpm, firstDownbeat, drop   music: override a measurement after checking it by ear
  maxWidth       video: cap the extracted frame width (picture-in-picture clips)

  media.py add logo assets/logo.png --kind image --license "Client logo, supplied by the client"
  media.py survey media/review/*.mp3 --bpm 90 130       # tempo, downbeat and drop of candidate tracks
  media.py measure [--bpm 90 130]      # every ledger entry -> measured fields + media/MEDIA.md
  media.py music                       # timeline.music -> public/music/music.wav (trim, loop, fade)
  media.py sfx                         # timeline.sfx cues -> public/sfx/*.wav, synced start frames
  media.py visuals                     # footage -> public/footage/<name>/ frames, art -> public/images/,
                                       #   both listed in public/media.json for the engine
  media.py credits                     # CREDITS.md from the ledger

Run from the video project root. The numbers are measured, not heard: ask the user to
listen to the track and each effect before building on them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_lib as al  # noqa: E402

SR = al.SR
ASR = 22050  # analysis rate for music
KINDS = ("music", "sfx", "video", "art", "image")
SFX_GAIN_DB = [("whoosh", -9), ("woosh", -9), ("swoosh", -11), ("swipe", -12), ("transition", -10), ("riser", -12),
               ("impact", -7), ("boom", -8), ("hit", -8), ("drop", -10), ("pop", -12), ("click", -16), ("tick", -15),
               ("type", -16), ("key", -16), ("ding", -12), ("chime", -12), ("bell", -12), ("notif", -12),
               ("sparkle", -14), ("coin", -12), ("cash", -12), ("glitch", -16), ("paper", -10), ("pencil", -15)]
PEAK_SYNC = ("whoosh", "woosh", "swoosh", "swipe", "transition", "riser")


def die(message):
    raise SystemExit(f"error: {message}")


def ledger_path(media: Path) -> Path:
    return media / "sources.json"


def load_ledger(media: Path) -> list[dict]:
    path = ledger_path(media)
    if not path.is_file():
        die(f"{path} not found: download media with mixkit.py get, or register files with media.py add")
    return json.loads(path.read_text())


def save_ledger(media: Path, ledger: list[dict]) -> None:
    al.save_json(ledger_path(media), ledger)


def entry(ledger: list[dict], name: str, kind: str | tuple | None = None) -> dict:
    for e in ledger:
        if e["name"] == name and (kind is None or e["kind"] in ((kind,) if isinstance(kind, str) else kind)):
            return e
    wanted = f"{kind} " if isinstance(kind, str) else ""
    die(f"no {wanted}'{name}' in the media ledger (have: {', '.join(e['name'] for e in ledger) or 'nothing'})")


def segment(x: np.ndarray, e: dict, sr: int) -> np.ndarray:
    a = int(round(float(e.get("in") or 0) * sr))
    b = int(round(float(e["out"]) * sr)) if e.get("out") is not None else len(x)
    return x[max(0, a):max(a, min(b, len(x)))]


def ffprobe(path: Path) -> dict:
    tool = shutil.which("ffprobe")
    if not tool:
        die("ffprobe not found on PATH (macOS: brew install ffmpeg)")
    out = subprocess.run([tool, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,avg_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    if out.returncode:
        die(f"ffprobe could not read {path}: {out.stderr[-300:]}")
    data = json.loads(out.stdout)
    stream = (data.get("streams") or [{}])[0]

    def rate(text):
        num, _, den = (text or "0/1").partition("/")
        return float(num) / float(den or 1) if float(den or 1) else 0.0

    fps = rate(stream.get("avg_frame_rate")) or rate(stream.get("r_frame_rate"))
    return {"width": int(stream.get("width") or 0), "height": int(stream.get("height") or 0),
            "fps": round(fps, 5), "seconds": round(float((data.get("format") or {}).get("duration") or 0), 3)}


# ------------------------------------------------------------------ dsp helpers


def moving_avg(x: np.ndarray, n: float) -> np.ndarray:
    n = max(1, int(n))
    c = np.cumsum(np.concatenate([[0.0], x]))
    out = (c[n:] - c[:-n]) / n
    pad = n // 2
    return np.concatenate([np.full(pad, out[0]), out, np.full(len(x) - len(out) - pad, out[-1])])


def lowpass(y: np.ndarray, sr: int, hz: float) -> np.ndarray:
    """Zero-phase low-pass with a raised-cosine roll-off from hz to 2*hz."""
    spectrum = np.fft.rfft(y)
    f = np.fft.rfftfreq(len(y), 1 / sr)
    g = np.clip((2 * hz - f) / hz, 0, 1)
    spectrum *= 0.5 - 0.5 * np.cos(np.pi * g)
    return np.fft.irfft(spectrum, len(y))


def spectral_flux(y: np.ndarray, sr: int, hop: int = 256, n_fft: int = 2048) -> tuple[np.ndarray, float]:
    pad = np.concatenate([np.zeros(n_fft // 2), y, np.zeros(n_fft // 2)])
    n = 1 + (len(pad) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(pad[idx] * np.hanning(n_fft).astype(np.float32), axis=1))
    mag = mag[:, : int(8000 / (sr / n_fft))]
    flux = np.maximum(0, np.diff(np.log1p(100 * mag), axis=0)).sum(axis=1)
    return np.concatenate([[0], flux]).astype(np.float64), sr / hop


def fine_onset(y: np.ndarray, sr: int) -> np.ndarray:
    """Rise of log energy sampled at 1 kHz (index = ms): peaks at transient attacks."""
    e = moving_avg(y.astype(np.float64) ** 2, sr * 0.005)
    e = e[np.round(np.arange(int(len(y) / sr * 1000)) * sr / 1000).astype(int)]
    le = 10 * np.log10(e + 1e-10)
    return np.maximum(0, moving_avg(np.diff(le, prepend=le[0]), 3))


def _comb_ms(on: np.ndarray, bpms: np.ndarray, tol: int = 3) -> tuple[float, float, float, float]:
    """Best (score, bpm, phase_s, peakiness) of a beat comb over a 1 kHz onset envelope."""
    mf = np.lib.stride_tricks.sliding_window_view(np.pad(on, tol, mode="edge"), 2 * tol + 1).max(axis=1)
    best = (-1.0, float(bpms[0]), 0.0, 0.0)
    for bpm in bpms:
        period = 60000 / bpm
        count = int((len(mf) - 1) // period) - 1
        if count < 8:
            continue
        ph = np.arange(int(period))
        sc = mf[np.rint(ph[:, None] + period * np.arange(count)[None, :]).astype(int)].mean(axis=1)
        j = int(np.argmax(sc))
        if sc[j] > best[0]:
            best = (float(sc[j]), float(bpm), ph[j] / 1000, float(sc[j] / (np.median(sc) + 1e-9)))
    return best


def tempo_grid(y: np.ndarray, sr: int, lo: float = 60, hi: float = 200, hint=None) -> dict:
    """Constant-tempo beat grid: tempo from spectral flux, phase and fine period from the
    attacks at 1 ms, preferring the low band (kick, bass) so the grid sits on the beat."""
    env, esr = spectral_flux(y, sr)
    e = np.maximum(0, env - moving_avg(env, esr * 1.0))
    if e.max() <= 0:
        die("no rhythmic content found")
    e /= e.max()
    n = len(e)
    spectrum = np.fft.rfft(e, 2 * n)
    ac = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    bpms = np.arange(lo, hi, 0.1)
    lags = 60 * esr / bpms
    score = np.interp(lags, np.arange(n), ac) + 0.5 * np.interp(lags * 2, np.arange(n), ac)
    prior = np.exp(-0.5 * (np.log2(bpms / 120) / 0.9) ** 2)
    if hint:
        prior = prior * np.where((bpms >= hint[0]) & (bpms <= hint[1]), 1.0, 0.35)
    coarse = float(bpms[np.argmax(score * prior)])
    best = (-1.0, coarse)
    for bpm in np.arange(coarse - 0.8, coarse + 0.8, 0.005):
        period = 60 * esr / bpm
        count = int((n - 1 - period) // period)
        if count < 8:
            continue
        idx = np.arange(0, period, 0.25)[:, None] + period * np.arange(count)[None, :]
        sc = np.interp(idx, np.arange(n), e).mean(axis=1).max()
        if sc > best[0]:
            best = (float(sc), float(bpm))
    mid = best[1]
    fine = np.arange(mid - 0.15, mid + 0.15, 0.003)
    on_low, on_full = fine_onset(lowpass(y, sr, 150), sr), fine_onset(y, sr)
    low, full = _comb_ms(on_low, fine), _comb_ms(on_full, fine)
    use = low if low[3] >= 1.4 else full
    on = on_low if use is low else on_full
    _, bpm, phase, peaky = use
    period = 60 / bpm
    dur = len(y) / sr
    meas, stren, kk = [], [], []
    for k in range(int((dur - phase) / period) + 1):
        c = int(round((phase + k * period) * 1000))
        a, b = c - 20, c + 21
        if a < 0 or b > len(on):
            continue
        j = int(np.argmax(on[a:b]))
        meas.append((a + j) / 1000)
        stren.append(on[a + j])
        kk.append(k)
    meas, stren, kk = np.array(meas), np.array(stren), np.array(kk)
    if len(meas) >= 16:  # fit t_k = t0 + k * period to the attacks nearest the strong beats
        keep = stren >= np.percentile(stren, 50)
        t0, per = phase, period
        for _ in range(4):
            if keep.sum() < 8:
                break
            t0, per = np.linalg.lstsq(np.vstack([np.ones(keep.sum()), kk[keep]]).T, meas[keep], rcond=None)[0]
            res = meas - (t0 + kk * per)
            mad = np.median(np.abs(res[keep] - np.median(res[keep])))
            keep = (stren >= np.percentile(stren, 50)) & (np.abs(res - np.median(res[keep])) <= max(3 * mad, 0.003))
        if abs(per / period - 1) < 0.003:
            period, phase, bpm = float(per), float(t0 % per), 60 / float(per)
    first = phase - period if phase - period >= -0.03 else phase
    return {"bpm": bpm, "period": period, "beats": np.maximum(0.0, np.arange(first, dur, period)),
            "confidence": round(min(1.0, (peaky - 1) / 3), 3)}


def beat_chroma(y: np.ndarray, sr: int, beats: np.ndarray) -> np.ndarray:
    n_fft, hop = 4096, 1024
    pad = np.concatenate([np.zeros(n_fft // 2), y, np.zeros(n_fft // 2)])
    n = 1 + (len(pad) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.log1p(10 * np.abs(np.fft.rfft(pad[idx] * np.hanning(n_fft), axis=1)))
    f = np.fft.rfftfreq(n_fft, 1 / sr)
    band = (f >= 60) & (f <= 2000)
    pc = np.mod(np.rint(12 * np.log2(f[band] / 440.0)), 12).astype(int)
    chroma = np.stack([mag[:, band][:, pc == c].sum(axis=1) for c in range(12)], axis=1)
    fr = (beats * sr / hop).astype(int)
    out = []
    for a, b in zip(fr[:-1], fr[1:]):
        v = chroma[max(0, a): max(a + 1, min(b, n))].mean(axis=0)
        out.append(v / (np.linalg.norm(v) + 1e-9))
    out.append(out[-1] if out else np.zeros(12))
    return np.array(out)


def downbeat(y: np.ndarray, sr: int, beats: np.ndarray, per_bar: int = 4) -> tuple[int, float]:
    """Which beat phase starts the bar: kick emphasis, energy changes and chord changes vote."""
    on = fine_onset(lowpass(y, sr, 150), sr)
    ms = (beats * 1000).astype(int)
    ok = (ms > 20) & (ms < len(on) - 40)
    beats, ms = beats[ok], ms[ok]
    if len(ms) < 2 * per_bar:
        return 0, 0.0
    kick = np.array([on[m - 15: m + 25].max() for m in ms])
    rms = np.array([np.sqrt(np.mean(y[int(t * sr): int((t + 0.25) * sr)] ** 2) + 1e-12) for t in beats])
    nov = np.zeros(len(ms))
    for i in range(per_bar, len(ms) - per_bar):
        nov[i] = abs(np.log(rms[i: i + per_bar].mean() / rms[i - per_bar: i].mean()))
    chroma = beat_chroma(y, sr, beats)
    har = np.zeros(len(ms))
    for i in range(1, len(ms)):
        har[i] = 1 - float(chroma[i - 1] @ chroma[i])
    if har.mean() < 0.02:
        har[:] = 0
    scores = np.zeros(per_bar)
    for x in (kick, nov, har):
        m = np.array([x[np.arange(p, len(ms), per_bar)].mean() for p in range(per_bar)])
        m = m / (m.mean() + 1e-9)
        srt = np.sort(m)[::-1]
        scores += (srt[0] - srt[1]) * m
    order = np.argsort(scores)[::-1]
    conf = float((scores[order[0]] - scores[order[1]]) / (scores[order[0]] + 1e-9))
    return int((order[0] + int(np.flatnonzero(ok)[0])) % per_bar), conf


def find_drop(y: np.ndarray, sr: int, downbeats: np.ndarray, period: float, per_bar: int = 4) -> dict:
    """The bar line where energy (full band and low band) rises the most: the drop."""
    lo = lowpass(y, sr, 150)
    bar = period * per_bar
    full, low = [], []
    for t in downbeats:
        a, b = int(t * sr), int((t + bar) * sr)
        if b > len(y):
            break
        full.append(np.sqrt(np.mean(y[a:b] ** 2) + 1e-12))
        low.append(np.sqrt(np.mean(lo[a:b] ** 2) + 1e-12))
    if len(full) < 5:
        return {"drop": None, "dropCandidates": []}
    full, low = np.array(full), np.array(low)
    full = np.maximum(full, 0.05 * np.median(full))
    low = np.maximum(low, 0.05 * np.median(low))
    dur = len(y) / sr
    cands = []
    for j in range(2, len(full) - 2):
        t = float(downbeats[j])
        if 0.08 * dur <= t <= 0.92 * dur:
            rf = full[j: j + 2].mean() / full[j - 2: j].mean()
            rl = low[j: j + 2].mean() / low[j - 2: j].mean()
            cands.append((0.5 * np.log(rf) + 0.5 * np.log(rl), t))
    cands.sort(reverse=True)
    if not cands:
        return {"drop": None, "dropCandidates": []}
    return {"drop": round(cands[0][1], 4), "dropScore": round(float(cands[0][0]), 3),
            "dropCandidates": [{"t": round(t, 4), "score": round(float(s), 3)} for s, t in cands[:4]]}


def measure_music(y: np.ndarray, sr: int = ASR, hint=None) -> dict:
    """Tempo, beat grid, first downbeat and drop of a mono track (times in seconds)."""
    y = y.astype(np.float64)
    grid = tempo_grid(y, sr, hint=hint)
    beats = grid["beats"]
    threshold = np.abs(y).max() * 10 ** (-40 / 20)
    start = float(np.argmax(np.abs(y) > threshold) / sr)
    phase, dconf = downbeat(y, sr, beats)
    down = beats[phase::4]
    first_down = float(down[down >= start - 0.03][0]) if np.any(down >= start - 0.03) else float(down[0])
    first_beat = float(beats[beats >= start - 0.03][0]) if np.any(beats >= start - 0.03) else float(beats[0])
    flags = []
    if grid["confidence"] < 0.25:
        flags.append("low tempo confidence: the beat grid may be off; check by ear or set bpm")
    if dconf < 0.1:
        flags.append("low downbeat confidence: bars may start on another beat; set firstDownbeat after listening")
    return {"seconds": round(len(y) / sr, 3), "bpm": round(grid["bpm"], 3), "period": round(grid["period"], 6),
            "tempoConfidence": grid["confidence"], "musicStart": round(start, 4), "firstBeat": round(first_beat, 4),
            "firstDownbeat": round(first_down, 4), "downbeatConfidence": round(dconf, 3), "beatsPerBar": 4,
            **find_drop(y, sr, down, grid["period"]), "flags": flags}


def _peak_clusters(env: np.ndarray, level: float) -> list[int]:
    """Peaks at or above `level` separated by a dip of at least 3 dB (merged within 60 ms)."""
    idx = np.flatnonzero(env >= level)
    if not len(idx):
        return []
    groups, cur = [], [idx[0]]
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a > 1 and env[a:b].min() < 0.708 * min(env[a], env[b]):
            groups.append(cur)
            cur = []
        cur.append(b)
    groups.append(cur)
    merged = []
    for g in groups:
        p = int(np.asarray(g)[np.argmax(env[np.asarray(g)])])
        if merged and p - merged[-1] < 0.06 * SR:
            if env[p] > env[merged[-1]]:
                merged[-1] = p
        else:
            merged.append(p)
    return merged


def measure_sfx(x: np.ndarray) -> dict:
    """Where an effect's first hit and its loudest point land (ms from the start), plus flags."""
    mono = np.abs(al.as_2d(x)).max(axis=1).astype(np.float64)
    n = len(mono)
    peak_amp = float(mono.max()) if n else 0.0
    if peak_amp <= 1e-6:
        return {"lengthMs": round(n / SR * 1000, 1), "hitMs": 0.0, "peakMs": 0.0, "flags": ["silent file"]}
    fine = np.sqrt(moving_avg(mono ** 2, SR * 0.001))
    env = np.sqrt(moving_avg(mono ** 2, SR * 0.010))
    peaks = _peak_clusters(env, env.max() * 10 ** (-3 / 20))
    peak_i = int(np.argmax(env))
    first = peaks[0] if peaks else peak_i
    a, b = max(0, first - int(0.01 * SR)), min(n, first + int(0.01 * SR))
    hit = a + int(np.argmax(fine[a:b]))
    onset = int(np.argmax(fine >= fine.max() * 10 ** (-30 / 20)))
    length = n / SR * 1000
    flags = []
    if len(peaks) > 1:
        flags.append(f"{len(peaks)} peaks within 3 dB ({', '.join(f'{p / SR * 1000:.0f}' for p in peaks[:5])} ms): "
                     "hit uses the first; check it is the one that should land, or set sync")
    if length > 4000:
        flags.append(f"long file ({length / 1000:.1f} s): set in/out to the part you use")
    if onset / SR > 0.1:
        flags.append(f"starts with {onset / SR * 1000:.0f} ms of silence (already counted in hitMs)")
    return {"lengthMs": round(length, 1), "hitMs": round(hit / SR * 1000, 1), "peakMs": round(peak_i / SR * 1000, 1),
            "onsetMs": round(onset / SR * 1000, 1), "peaksMs": [round(p / SR * 1000, 1) for p in peaks[:8]],
            "flags": flags}


# ------------------------------------------------------------------ commands


def cmd_add(args) -> int:
    media = args.media
    src = Path(args.file)
    if not src.is_file():
        die(f"{src} not found")
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*", args.name):
        die("names are letters, digits, '.', '-' and '_'")
    dest = media / "src" / f"{args.name}{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    path = ledger_path(media)
    ledger = json.loads(path.read_text()) if path.is_file() else []
    ledger = [e for e in ledger if e["name"] != args.name]
    ledger.append({"name": args.name, "kind": args.kind, "source": "user", "file": dest.relative_to(media).as_posix(),
                   "page": "", "title": args.title or src.name, "author": args.author or "",
                   "license": args.license or "supplied by the user"})
    save_ledger(media, ledger)
    print(f"added {args.kind} '{args.name}' -> {dest}; run media.py measure")
    return 0


def music_facts(e: dict) -> dict:
    """Measured values with the hand-set overrides applied."""
    m = dict(e.get("measured") or {})
    for key in ("bpm", "firstDownbeat", "drop"):
        if e.get(key) is not None:
            m[key] = float(e[key])
    if e.get("bpm") is not None:
        m["period"] = 60.0 / float(e["bpm"])
    return m


def cmd_measure(args) -> int:
    media = args.media
    ledger = load_ledger(media)
    hint = tuple(args.bpm) if args.bpm else None
    rows = []
    for e in ledger:
        path = media / e["file"]
        if not path.is_file():
            die(f"{e['name']}: {path} is missing (re-run mixkit.py get)")
        if e["kind"] == "music":
            y = segment(al.read_audio(path, channels=1, sr=ASR)[:, 0], e, ASR)
            e["measured"] = measure_music(y, ASR, hint)
            m = music_facts(e)
            rows.append(f"| {e['name']} | music | {m['seconds']:.1f} s, {m['bpm']:.2f} bpm (conf {m['tempoConfidence']}), "
                        f"first downbeat {m['firstDownbeat']:.3f} s, drop {m.get('drop')} s | {'; '.join(m['flags'])} |")
        elif e["kind"] == "sfx":
            e["measured"] = measure_sfx(segment(al.read_audio(path), e, SR))
            m = e["measured"]
            rows.append(f"| {e['name']} | sfx | {m['lengthMs']:.0f} ms, hit {m['hitMs']} ms, peak {m['peakMs']} ms, "
                        f"sync {sync_mode(e)} | {'; '.join(m['flags'])} |")
        else:
            e["measured"] = ffprobe(path)
            m = e["measured"]
            flags = []
            if e["kind"] == "video":
                if m["seconds"] - float(e.get("in") or 0) > 30 and e.get("out") is None:
                    flags.append("long clip: set in/out to the part you use (frames are extracted for the whole range)")
                if e.get("licenseId") == "videoRestricted":
                    flags.append("Restricted licence: confirm the use with the user")
            detail = f"{m['width']}x{m['height']}" + (f", {m['fps']:g} fps, {m['seconds']:.1f} s" if e["kind"] == "video" else "")
            rows.append(f"| {e['name']} | {e['kind']} | {detail} | {'; '.join(flags)} |")
    save_ledger(media, ledger)
    lines = ["# Media", "", "Measured by media.py (numbers, not ears: listen before building on them).", "",
             "| name | kind | measured | flags |", "|---|---|---|---|", *rows, "",
             "| name | title | source | licence |", "|---|---|---|---|"]
    lines += [f"| {e['name']} | {e.get('title', '')} | {e.get('page') or e.get('source', '')} | {e.get('license', '')} |"
              for e in ledger]
    (media / "MEDIA.md").write_text("\n".join(lines) + "\n")
    print("\n".join(rows))
    print(f"-> {ledger_path(media)}, {media / 'MEDIA.md'}")
    return 0


def cmd_survey(args) -> int:
    hint = tuple(args.bpm) if args.bpm else None
    print(f"{'file':32s} {'len':>6s} {'bpm':>8s} {'conf':>5s} {'1st bar':>8s} {'drop':>7s}  in range")
    for f in args.files:
        m = measure_music(al.read_audio(f, channels=1, sr=ASR)[:, 0], ASR, hint)
        ok = "yes" if not hint or hint[0] <= m["bpm"] <= hint[1] else "no"
        drop = f"{m['drop']:.1f}" if m.get("drop") is not None else "-"
        print(f"{Path(f).name[:32]:32s} {m['seconds']:6.1f} {m['bpm']:8.2f} {m['tempoConfidence']:5.2f} "
              f"{m['firstDownbeat']:8.3f} {drop:>7s}  {ok}")
    return 0


def loop_to(x: np.ndarray, samples: int, body_start: int, body_end: int, xfade: int) -> np.ndarray:
    """Extend x to `samples` by repeating x[body_start:body_end] with equal-power crossfades."""
    out = x[:body_end].copy()
    body = x[body_start:body_end]
    if len(body) <= 2 * xfade:
        die("the loop body is too short to repeat")
    ramp = np.sin(np.linspace(0, np.pi / 2, xfade, dtype=np.float32))[:, None]
    while len(out) < samples:
        out[-xfade:] = out[-xfade:] * ramp[::-1] + body[:xfade] * ramp
        out = np.vstack([out, body[xfade:]])
    return out[:samples]


def build_music(timeline: dict, media: Path, public: Path) -> dict:
    track = timeline.get("music") or {}
    if not track or track.get("source") in (None, "generated"):
        die("timeline.music is not a ledger track (generated music is made by gen_music.py)")
    e = entry(load_ledger(media), track["track"], "music")
    facts = music_facts(e)
    x = segment(al.read_audio(media / e["file"]), e, SR)
    fps = timeline["fps"]
    samples = int(round(timeline["durationInFrames"] / fps * SR))
    start = int(round(float(track.get("start") or 0.0) * SR))
    looped = False
    if start + samples > len(x):
        period = facts.get("period") or 0.5
        bars = period * 4
        first_down = facts.get("firstDownbeat", 0.0)
        # repeat whole bars: from the first bar line at or after `start` to the last one 1 s before the end
        body_start = first_down + max(0, np.ceil((start / SR - first_down) / bars - 1e-6)) * bars
        body_end = first_down + np.floor((len(x) / SR - 1.0 - first_down) / bars) * bars
        if body_end - body_start < 2 * bars:
            die(f"track '{e['name']}' is too short to loop cleanly; pick a longer track")
        x = loop_to(x, start + samples, int(body_start * SR), int(body_end * SR), int(0.03 * SR))
        looped = True
    bed = al.fit_length(x[start:], samples)
    bed = al.fade(bed, 0.004 if start else 0.0, float(track.get("fadeOut", 2.0)))
    bed, stats = al.master(bed, -16.0, -1.0)
    out = public / track.get("src", "music/music.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    al.write_wav(out, bed)
    meta = {"track": e["name"], "title": e.get("title"), "start": track.get("start"), "looped": looped,
            "seconds": round(samples / SR, 3), **stats}
    al.save_json(out.with_suffix(".json"), meta)
    return {"out": out, **meta}


def cmd_music(args) -> int:
    timeline = al.load_json(args.timeline)
    info = build_music(timeline, args.media, args.public)
    note = " (looped: the track is shorter than the video)" if info["looped"] else ""
    print(f"Music: '{info['track']}' from {info['start']} s, {info['seconds']} s, {info['lufs']} LUFS -> {info['out']}{note}")
    return 0


def sync_mode(e: dict) -> str:
    if e.get("sync") is not None:
        return str(e["sync"])
    name = e["name"].lower()
    return "peak" if any(k in name for k in PEAK_SYNC) else "hit"


def sfx_gain(e: dict) -> float:
    if e.get("gainDb") is not None:
        return float(e["gainDb"])
    name = e["name"].lower()
    return next((g for key, g in SFX_GAIN_DB if key in name), -12.0)


def sync_seconds(e: dict) -> float:
    m = e.get("measured") or measure_sfx(segment(al.read_audio(e["_path"]), e, SR))
    mode = sync_mode(e)
    if mode == "hit":
        return m["hitMs"] / 1000
    if mode == "peak":
        return m["peakMs"] / 1000
    try:
        return float(mode) / 1000
    except ValueError:
        die(f"sfx '{e['name']}': sync must be hit, peak, or milliseconds (got {mode})")


def place_sfx(timeline: dict, media: Path, public: Path, outdir: str = "sfx") -> int:
    ledger = load_ledger(media)
    names = {e["name"]: e for e in ledger if e["kind"] == "sfx"}
    missing = sorted({c["type"] for c in timeline.get("sfx", []) if c["type"] not in names})
    if missing:
        die(f"sfx cues need these sounds in the ledger: {', '.join(missing)}. Download them, for example "
            f"mixkit.py get media --sfx {' '.join(f'{m}=<id>' for m in missing)} (mixkit.py search sfx <word> finds ids)")
    fps = timeline["fps"]
    folder = public / outdir
    folder.mkdir(parents=True, exist_ok=True)
    rendered = {}
    for cue in timeline.get("sfx", []):
        e = names[cue["type"]]
        if e["name"] not in rendered:
            e["_path"] = media / e["file"]
            clip = segment(al.read_audio(e["_path"]), e, SR)
            peak = float(np.abs(clip).max()) if len(clip) else 0.0
            clip = al.fade(clip / peak * al.db_to_gain(-1.0) if peak > 0 else clip, 0.0005, min(0.02, len(clip) / SR * 0.2))
            name = f"{e['name']}.wav"
            al.write_wav(folder / name, clip)
            rendered[e["name"]] = (f"{folder.name}/{name}", sync_seconds(e), len(clip))
            e.pop("_path", None)
        src, sync, length = rendered[e["name"]]
        cue["src"] = src
        cue["from"] = cue["syncFrame"] - round(sync * fps)
        cue["durationInFrames"] = int(np.ceil(length / SR * fps))
        if cue.get("gainDb") is None:
            cue["gainDb"] = sfx_gain(e)
    return len(timeline.get("sfx", []))


def cmd_sfx(args) -> int:
    timeline = al.load_json(args.timeline)
    count = place_sfx(timeline, args.media, args.public)
    al.save_json(args.timeline, timeline)
    print(f"SFX: placed {count} cues from the media ledger -> {args.public / 'sfx'} (timeline updated)")
    return 0


def ffmpeg(*argv: str) -> None:
    result = subprocess.run([al.ffmpeg_bin(), "-y", "-v", "error", *argv], capture_output=True, text=True)
    if result.returncode:
        die(f"ffmpeg failed: {result.stderr[-500:]}")


def footage_plan(e: dict, design: tuple[int, int], project_fps: float) -> dict:
    m = e.get("measured") or {}
    if not m.get("width"):
        die(f"video '{e['name']}' is not measured: run media.py measure")
    w, h = m["width"], m["height"]
    cover = max(design[0] / w, design[1] / h)
    scale = min(1.0, cover)  # enough to fill the frame, never upscaled
    if e.get("maxWidth"):
        scale = min(scale, float(e["maxWidth"]) / w)
    begin = float(e.get("in") or 0)
    end = float(e["out"]) if e.get("out") is not None else m["seconds"]
    fps = min(m["fps"] or 30.0, float(project_fps))
    return {"in": begin, "out": end, "width": int(round(w * scale / 2)) * 2, "height": int(round(h * scale / 2)) * 2,
            "fps": round(fps, 5)}


def extract_footage(e: dict, media: Path, public: Path, design: tuple[int, int], project_fps: float) -> dict:
    plan = footage_plan(e, design, project_fps)
    src = media / e["file"]
    folder = public / "footage" / e["name"]
    stamp = hashlib.sha256(json.dumps([str(src), src.stat().st_size, src.stat().st_mtime, plan]).encode()).hexdigest()[:16]
    meta_file = folder / "meta.json"
    if meta_file.is_file() and al.load_json(meta_file).get("stamp") == stamp:
        return al.load_json(meta_file)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    ffmpeg("-ss", f"{plan['in']:.3f}", "-to", f"{plan['out']:.3f}", "-i", str(src), "-an",
           "-vf", f"fps={plan['fps']},scale={plan['width']}:{plan['height']}:flags=lanczos,format=yuvj420p",
           "-q:v", "3", "-start_number", "0", str(folder / "%05d.jpg"))
    frames = len(list(folder.glob("*.jpg")))
    if not frames:
        die(f"no frames extracted from {src} between {plan['in']} and {plan['out']} s")
    meta = {"dir": f"{public.name}/footage/{e['name']}", "ext": "jpg", "frames": frames, "fps": plan["fps"],
            "width": plan["width"], "height": plan["height"], "seconds": round(frames / plan["fps"], 3),
            "source": e["file"], "in": plan["in"], "stamp": stamp}
    al.save_json(meta_file, meta)
    return meta


def prepare_image(e: dict, media: Path, public: Path, design: tuple[int, int]) -> str:
    src = media / e["file"]
    folder = public / "images"
    folder.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() if src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else ".png"
    out = folder / f"{e['name']}{ext}"
    m = e.get("measured") or ffprobe(src)
    limit = 2 * max(design)  # sharp at 4K output, no bigger
    if src.suffix.lower() == ".svg":
        die(f"image '{e['name']}' is an SVG: export it to PNG (at least {limit} px wide) and add that instead")
    if max(m["width"], m["height"]) > limit:
        side = f"{limit}:-2" if m["width"] >= m["height"] else f"-2:{limit}"
        ffmpeg("-i", str(src), "-vf", f"scale={side}:flags=lanczos", str(out))
    elif src.resolve() != out.resolve():
        shutil.copy2(src, out)
    return f"{public.name}/images/{out.name}"


def cmd_visuals(args) -> int:
    board = al.load_json(args.storyboard)
    fmt = board.get("format", {})
    design = (int(fmt.get("width", 1920)), int(fmt.get("height", 1080)))
    fps = float(fmt.get("fps", 60))
    ledger = load_ledger(args.media)
    manifest = {"version": 1, "footage": {}, "images": {}}
    for e in ledger:
        if e["kind"] == "video":
            manifest["footage"][e["name"]] = extract_footage(e, args.media, args.public, design, fps)
            meta = manifest["footage"][e["name"]]
            print(f"  footage {e['name']}: {meta['frames']} frames {meta['width']}x{meta['height']} @ {meta['fps']:g} fps")
        elif e["kind"] in ("art", "image"):
            manifest["images"][e["name"]] = prepare_image(e, args.media, args.public, design)
            print(f"  image {e['name']}: {manifest['images'][e['name']]}")
    al.save_json(args.public / "media.json", manifest)
    print(f"-> {args.public / 'media.json'} ({len(manifest['footage'])} footage, {len(manifest['images'])} images)")
    return 0


def cmd_credits(args) -> int:
    ledger = load_ledger(args.media)
    lines = ["# Credits", "", "Outside media used in this video.", ""]
    for kind, label in (("music", "Music"), ("sfx", "Sound effects"), ("video", "Footage"), ("art", "Art"), ("image", "Images")):
        items = [e for e in ledger if e["kind"] == kind]
        if items:
            lines += [f"## {label}", ""]
            for e in items:
                by = f" by {e['author']}" if e.get("author") else ""
                page = f" <{e['page']}>" if e.get("page") else ""
                lines.append(f"- {e.get('title') or e['name']}{by} ({e['name']}){page}: {e.get('license', '')}")
            lines.append("")
    if any(e.get("source") == "mixkit" for e in ledger):
        lines += ["Mixkit items are used under the Mixkit licences: https://mixkit.co/license/", ""]
    args.out.write_text("\n".join(lines))
    print(f"-> {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--media", type=Path, default=Path("media"))
    ap.add_argument("--public", type=Path, default=Path("public"))
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("add", help="register a user-supplied file")
    p.add_argument("name")
    p.add_argument("file")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--license")
    p.add_argument("--title")
    p.add_argument("--author")
    p = sp.add_parser("measure", help="measure every ledger entry")
    p.add_argument("--bpm", nargs=2, type=float, metavar=("LO", "HI"), help="tempo range hint")
    p = sp.add_parser("survey", help="compare candidate tracks")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--bpm", nargs=2, type=float, metavar=("LO", "HI"))
    for name in ("music", "sfx"):
        p = sp.add_parser(name)
        p.add_argument("--timeline", type=Path, default=Path("src/timeline.json"))
    p = sp.add_parser("visuals", help="extract footage frames and prepare images")
    p.add_argument("--storyboard", type=Path, default=Path("storyboard.json"))
    p = sp.add_parser("credits")
    p.add_argument("--out", type=Path, default=Path("CREDITS.md"))
    args = ap.parse_args()
    return {"add": cmd_add, "measure": cmd_measure, "survey": cmd_survey, "music": cmd_music, "sfx": cmd_sfx,
            "visuals": cmd_visuals, "credits": cmd_credits}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
