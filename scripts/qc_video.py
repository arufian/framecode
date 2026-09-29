#!/usr/bin/env python3
"""Automated QC of a rendered video against its timeline.

Checks: container/codec/pixel format, resolution, fps, exact frame count,
audio stream and A/V duration match, integrated loudness and true peak
(measured independently by ffmpeg's ebur128), black gaps, frozen stretches
(dead frames), hard cuts that the plan did not ask for, and silent holes in
the music. Also extracts review frames (scene midpoints, transition midpoints,
around every flagged cut) and a contact sheet for visual review.

Exit status is 1 when any check fails. Report: <outdir>/report.json

  qc_video.py --video out/final.mp4 --timeline src/timeline.json --size 1920x1080 --outdir out/qc
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def run(command):
    return subprocess.run(command, capture_output=True, text=True, check=False)


def probe(video):
    result = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)])
    if result.returncode:
        raise SystemExit(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def ratio(text):
    num, _, den = text.partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


def video_events(video, cut_threshold):
    """One decode pass: black segments, frozen segments, and scene-cut times."""
    metadata = Path(str(video) + ".cuts.txt")
    chain = (f"blackdetect=d=0.2:pix_th=0.04,freezedetect=n=-60dB:d=1.5,scdet=threshold={cut_threshold},"
             f"metadata=mode=select:key=lavfi.scd.time,metadata=mode=print:file={metadata}")
    result = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:v:0", "-vf", chain,
                  "-f", "null", "-"])
    log = result.stderr
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", log)]
    frozen = list(zip(starts, ends + [None] * (len(starts) - len(ends))))
    cuts = []
    if metadata.is_file():
        for block in re.split(r"(?m)^frame:", metadata.read_text())[1:]:
            time = re.search(r"lavfi\.scd\.time=([\d.]+)", block)
            score = re.search(r"lavfi\.scd\.score=([\d.]+)", block)
            if time:
                cuts.append((float(time.group(1)), float(score.group(1)) if score else 0.0))
        metadata.unlink()
    return black, frozen, cuts


def audio_events(video):
    result = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0",
                  "-af", "silencedetect=n=-50dB:d=1.5,ebur128=peak=true", "-f", "null", "-"])
    log = result.stderr
    summary = log[log.rfind("Summary:"):] if "Summary:" in log else ""
    lufs = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    silence = list(zip(starts, ends + [None] * (len(starts) - len(ends))))
    return (float(lufs.group(1)) if lufs else None,
            float(peak.group(1)) if peak and peak.group(1) != "-inf" else None, silence)


def extract_frames(video, marks, outdir, width):
    frames_dir = outdir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    written = []
    for index, (seconds, label) in enumerate(marks, 1):
        path = frames_dir / f"{index:03d}.png"
        result = run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, seconds):.4f}", "-i", str(video),
                      "-frames:v", "1", "-vf", f"scale={width}:-2", str(path)])
        if result.returncode == 0 and path.is_file():
            written.append({"file": str(path), "time": round(seconds, 3), "label": label})
    if written:
        columns = 4
        rows = (len(written) + columns - 1) // columns
        run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(frames_dir / "%03d.png"),
             "-vf", f"tile={columns}x{rows}:padding=6:color=white", "-frames:v", "1",
             str(outdir / "contact.png")])
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--timeline", type=Path, default=Path("src/timeline.json"))
    parser.add_argument("--size", help="Expected WIDTHxHEIGHT (the render size the user chose)")
    parser.add_argument("--outdir", type=Path, default=Path("out/qc"))
    parser.add_argument("--lufs", type=float, default=-14.0)
    parser.add_argument("--tp", type=float, default=-1.0, help="Max true peak after AAC encoding, dBTP")
    parser.add_argument("--cut-threshold", type=float, default=14.0)
    parser.add_argument("--frame-width", type=int, default=640)
    args = parser.parse_args()

    timeline = json.loads(args.timeline.read_text())
    fps = timeline["fps"]
    frames = timeline["durationInFrames"]
    width, height = (map(int, args.size.lower().split("x")) if args.size
                     else (timeline["width"], timeline["height"]))
    args.outdir.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name, ok, detail, warn=False):
        checks.append({"check": name, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": detail})

    info = probe(args.video)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not video:
        raise SystemExit("no video stream")
    check("codec", video["codec_name"] == "h264", f"{video['codec_name']} (want h264)")
    check("pixel format", video.get("pix_fmt") == "yuv420p", f"{video.get('pix_fmt')} (want yuv420p)")
    check("resolution", (video["width"], video["height"]) == (width, height),
          f"{video['width']}x{video['height']} (want {width}x{height})")
    rate = ratio(video["r_frame_rate"])
    check("frame rate", abs(rate - fps) < 0.01 and abs(ratio(video["avg_frame_rate"]) - fps) < 0.01,
          f"r={video['r_frame_rate']} avg={video['avg_frame_rate']} (want {fps})")
    count = int(video.get("nb_frames") or 0)
    check("frame count", count == frames, f"{count} frames (want {frames})")
    v_duration = float(video.get("duration") or info["format"]["duration"])

    expects_audio = bool((timeline.get("audio") or {}).get("mix"))
    lufs = peak = None
    silence = []
    if expects_audio:
        check("audio stream", audio is not None and audio["codec_name"] == "aac" and
              int(audio.get("sample_rate", 0)) == 48000 and int(audio.get("channels", 0)) == 2,
              "missing" if audio is None else f"{audio['codec_name']} {audio.get('sample_rate')} Hz "
                                              f"{audio.get('channels')} ch (want aac 48000 Hz 2 ch)")
        if audio is not None:
            a_duration = float(audio.get("duration") or v_duration)
            check("A/V duration", abs(a_duration - v_duration) <= 0.1,
                  f"audio {a_duration:.3f}s vs video {v_duration:.3f}s")
            lufs, peak, silence = audio_events(args.video)
            check("loudness", lufs is not None and abs(lufs - args.lufs) <= 1.0,
                  f"{lufs} LUFS integrated (want {args.lufs} ±1)")
            check("true peak", peak is not None and peak <= args.tp, f"{peak} dBTP (want ≤ {args.tp})")
            if (timeline.get("audio") or {}).get("music"):
                holes = [s for s in silence if s[0] > 0.5 and (s[1] or v_duration) < v_duration - 0.5]
                check("no silent holes", not holes, f"{len(holes)} silences ≥1.5s mid-video: {holes[:5]}")
    else:
        check("audio stream", True, "no audio planned" + ("" if audio is None else " (stream present)"))

    black, frozen, cuts = video_events(args.video, args.cut_threshold)
    end = frames / fps
    inner_black = [b for b in black if b[0] > 0.05 and b[1] < end - 0.05]
    check("no black gaps", not inner_black, f"{len(inner_black)} black segments: {inner_black[:5]}")

    holds = [(s["from"] / fps, (s["from"] + s["durationInFrames"]) / fps) for s in timeline["scenes"] if s.get("hold")]
    dead = [f for f in frozen if not any(a - 0.1 <= f[0] and (f[1] or end) <= b + 0.1 for a, b in holds)]
    check("no frozen frames", not dead, f"{len(dead)} stretches ≥1.5s without motion: {dead[:5]} "
                                        "(add ambient motion, or mark the scene hold: true)")

    planned = [(s["from"] + s["durationInFrames"]) / fps for s in timeline["scenes"][:-1]
               if s["transitionOut"]["type"] == "cut"]
    tolerance = 2.5 / fps
    unplanned = [(t, score) for t, score in cuts if not any(abs(t - p) <= tolerance for p in planned)]
    check("no unplanned hard cuts", not unplanned,
          f"{len(cuts)} cuts detected, {len(planned)} planned, unplanned at: "
          f"{[round(t, 3) for t, _ in unplanned[:8]]}")

    marks = [(0.0, "first frame")]
    for scene in timeline["scenes"]:
        solo_mid = (scene["from"] + (scene["inFrames"] + scene["durationInFrames"] - scene["outFrames"]) / 2) / fps
        marks.append((solo_mid, f"{scene['id']} mid"))
        if scene["outFrames"]:
            marks.append(((scene["from"] + scene["durationInFrames"] - scene["outFrames"] / 2) / fps,
                          f"{scene['id']} transition ({scene['transitionOut']['type']})"))
    for t, _ in unplanned[:6]:
        marks += [(t - 1.0 / fps, f"before cut {t:.3f}s"), (t, f"after cut {t:.3f}s")]
    marks.append((max(0.0, end - 1.5 / fps), "last frame"))
    review = extract_frames(args.video, sorted(marks), args.outdir, args.frame_width)

    failed = [c for c in checks if c["status"] == "fail"]
    report = {"video": str(args.video), "passed": not failed, "checks": checks,
              "loudness": {"lufs": lufs, "true_peak": peak}, "cuts": cuts, "frozen": frozen, "black": black,
              "review_frames": review, "contact_sheet": str(args.outdir / "contact.png")}
    (args.outdir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for c in checks:
        print(f"{ {'pass': 'PASS', 'warn': 'WARN', 'fail': 'FAIL'}[c['status']] }  {c['check']}: {c['detail']}")
    print(f"{'QC PASSED' if not failed else f'QC FAILED ({len(failed)})'} - {len(review)} review frames, "
          f"contact sheet {args.outdir / 'contact.png'}, report {args.outdir / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
