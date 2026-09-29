"""Shared audio helpers: WAV I/O, resampling, BS.1770 loudness, true-peak limiting.

Everything runs at 48 kHz float32, shape (samples, channels). Only numpy, scipy,
and (for non-WAV input) the ffmpeg binary are required.
"""

from math import gcd
import io
import json
import shutil
import subprocess

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import lfilter, resample_poly

SR = 48000

# ITU-R BS.1770-4 K-weighting coefficients for 48 kHz.
_K_SHELF = ([1.53512485958697, -2.69169618940638, 1.19839281085285],
            [1.0, -1.69065929318241, 0.73248077421585])
_K_HIGHPASS = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])


def db_to_gain(db):
    return 10.0 ** (db / 20.0)


def gain_to_db(gain):
    return 20.0 * np.log10(max(float(gain), 1e-12))


def ffmpeg_bin():
    path = shutil.which("ffmpeg")
    if not path:
        raise SystemExit("ffmpeg not found on PATH (macOS: brew install ffmpeg)")
    return path


def as_2d(x):
    x = np.asarray(x, dtype=np.float32)
    return x[:, None] if x.ndim == 1 else x


def to_channels(x, channels):
    x = as_2d(x)
    if x.shape[1] == channels:
        return x
    if channels == 1:
        return x.mean(axis=1, keepdims=True)
    return np.repeat(x[:, :1], channels, axis=1) if x.shape[1] == 1 else x[:, :channels]


def resample(x, sr_from, sr_to=SR):
    if sr_from == sr_to:
        return as_2d(x)
    g = gcd(int(sr_from), int(sr_to))
    return resample_poly(as_2d(x), sr_to // g, sr_from // g, axis=0).astype(np.float32)


def _pcm_to_float(data):
    if data.dtype == np.int16:
        return data.astype(np.float32) / 32768.0
    if data.dtype == np.int32:
        return data.astype(np.float32) / 2147483648.0
    if data.dtype == np.uint8:
        return (data.astype(np.float32) - 128.0) / 128.0
    return data.astype(np.float32)


def decode(path, channels=2, sr=SR):
    """Decode any audio file ffmpeg understands into float32 (n, channels) at sr."""
    command = [ffmpeg_bin(), "-v", "error", "-i", str(path), "-f", "f32le",
               "-ac", str(channels), "-ar", str(sr), "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"ffmpeg could not decode {path}: {result.stderr.decode(errors='replace')[-400:]}")
    return np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, channels).copy()


def read_audio(path, channels=2, sr=SR):
    """Read WAV directly (or anything else through ffmpeg); return float32 (n, channels) at sr."""
    try:
        rate, data = wavfile.read(str(path))
    except (ValueError, OSError):
        return decode(path, channels, sr)
    return to_channels(resample(_pcm_to_float(data), rate, sr), channels)


def write_wav(path, x, sr=SR):
    """Write 16-bit PCM with TPDF dither; input is clipped to [-1, 1]."""
    x = as_2d(x)
    rng = np.random.default_rng(0)
    dither = (rng.random(x.shape) - rng.random(x.shape)) / 32768.0
    pcm = np.clip(x + dither, -1.0, 1.0 - 1.0 / 32768.0)
    target = path if hasattr(path, "write") else str(path)
    wavfile.write(target, sr, (pcm * 32768.0).astype(np.int16))


def fit_length(x, samples):
    x = as_2d(x)
    if len(x) >= samples:
        return x[:samples]
    return np.vstack([x, np.zeros((samples - len(x), x.shape[1]), dtype=np.float32)])


def fade(x, fade_in=0.005, fade_out=0.005, sr=SR):
    x = as_2d(x).copy()
    n_in, n_out = min(len(x), int(fade_in * sr)), min(len(x), int(fade_out * sr))
    if n_in:
        x[:n_in] *= np.linspace(0.0, 1.0, n_in, dtype=np.float32)[:, None]
    if n_out:
        x[len(x) - n_out:] *= np.linspace(1.0, 0.0, n_out, dtype=np.float32)[:, None]
    return x


def trim_silence(x, threshold_db=-45.0, pad=0.04, sr=SR):
    """Trim leading/trailing audio below threshold (TTS engines pad generously)."""
    x = as_2d(x)
    level = np.abs(x).max(axis=1)
    loud = np.flatnonzero(level > db_to_gain(threshold_db))
    if not len(loud):
        return x[:0]
    start = max(0, loud[0] - int(pad * sr))
    end = min(len(x), loud[-1] + int(pad * sr))
    return fade(x[start:end], 0.004, 0.012, sr)


def k_weight(x):
    y = lfilter(*_K_SHELF, as_2d(x).astype(np.float64), axis=0)
    return lfilter(*_K_HIGHPASS, y, axis=0)


def integrated_loudness(x):
    """BS.1770-4 gated integrated loudness in LUFS (stereo channel weights = 1)."""
    y = k_weight(x)
    block, hop = int(0.4 * SR), int(0.1 * SR)
    if len(y) < block:
        y = np.vstack([y, np.zeros((block - len(y), y.shape[1]))])
    cumulative = np.vstack([np.zeros((1, y.shape[1])), np.cumsum(y * y, axis=0)])
    starts = np.arange(0, len(y) - block + 1, hop)
    power = ((cumulative[starts + block] - cumulative[starts]) / block).sum(axis=1)
    loudness = -0.691 + 10.0 * np.log10(power + 1e-20)
    gated = loudness > -70.0
    if not gated.any():
        return float("-inf")
    relative = -0.691 + 10.0 * np.log10(power[gated].mean()) - 10.0
    gated &= loudness > relative
    return float(-0.691 + 10.0 * np.log10(power[gated].mean()))


def true_peak_db(x):
    """Peak of the 4x-oversampled signal, in dBTP."""
    x = as_2d(x)
    if not len(x):
        return float("-inf")
    return gain_to_db(np.abs(resample_poly(x, 4, 1, axis=0)).max())


def rms_db(x, gate_db=-50.0):
    """RMS of the parts of the signal above gate_db (ignores pauses in speech)."""
    x = as_2d(x)
    frame = int(0.05 * SR)
    usable = len(x) // frame * frame
    if not usable:
        return float("-inf")
    frames = x[:usable].reshape(-1, frame, x.shape[1])
    power = (frames ** 2).mean(axis=(1, 2))
    active = power > db_to_gain(gate_db) ** 2
    if not active.any():
        return float("-inf")
    return 10.0 * np.log10(power[active].mean())


def limit(x, ceiling_db, window=0.02):
    """Look-ahead peak limiter: the gain curve never exceeds what the peaks require."""
    x = as_2d(x)
    ceiling = db_to_gain(ceiling_db)
    peak = np.abs(x).max(axis=1)
    need = np.minimum(1.0, ceiling / np.maximum(peak, 1e-12))
    if need.min() >= 1.0:
        return x
    w = max(3, int(window * SR) | 1)
    gain = uniform_filter1d(minimum_filter1d(need, size=2 * w + 1, mode="nearest"), size=w, mode="nearest")
    return (x * np.minimum(gain, need)[:, None]).astype(np.float32)


def master(x, target_lufs=-14.0, true_peak=-1.5, tolerance=0.3):
    """Normalize to target loudness while keeping true peak under the ceiling."""
    y = as_2d(x).astype(np.float32)
    margin = 0.3
    for _ in range(8):
        loudness = integrated_loudness(y)
        if not np.isfinite(loudness):
            return y, {"lufs": loudness, "true_peak": true_peak_db(y)}
        y = (y * db_to_gain(target_lufs - loudness)).astype(np.float32)
        peak = true_peak_db(y)
        if peak > true_peak:
            y = limit(y, true_peak - margin)
            margin += max(0.2, true_peak_db(y) - true_peak)
        loudness, peak = integrated_loudness(y), true_peak_db(y)
        if abs(loudness - target_lufs) <= tolerance and peak <= true_peak:
            break
    return y, {"lufs": round(integrated_loudness(y), 2), "true_peak": round(true_peak_db(y), 2)}


def shaped_noise(seconds, centers_hz, rng, width_oct=0.6, widths=None):
    """Noise whose band centre glides through centers_hz (control points spread over time).

    Shaping happens in the STFT domain, so the sweep is continuous (no filter-state clicks).
    """
    from scipy.signal import istft, stft
    n = max(1024, int(seconds * SR))
    _, times, spectrum = stft(rng.normal(0.0, 1.0, n), fs=SR, nperseg=1024)
    freqs = np.fft.rfftfreq(1024, 1.0 / SR)
    progress = np.clip(times / (n / SR), 0.0, 1.0)
    points = np.linspace(0.0, 1.0, len(centers_hz))
    center = np.interp(progress, points, np.log2(np.asarray(centers_hz, dtype=float)))
    width = np.interp(progress, np.linspace(0.0, 1.0, len(widths)), widths) if widths else width_oct
    mask = np.exp(-0.5 * ((np.log2(np.maximum(freqs, 20.0))[:, None] - center[None, :]) / width) ** 2)
    _, y = istft(spectrum * mask, fs=SR, nperseg=1024)
    y = y[:n]
    peak = np.abs(y).max()
    return (y / peak if peak > 0 else y).astype(np.float32)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def wav_bytes(x, sr=SR):
    buffer = io.BytesIO()
    write_wav(buffer, x, sr)
    return buffer.getvalue()
