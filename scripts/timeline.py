#!/usr/bin/env python3
"""Build src/timeline.json from storyboard.json and voice-over durations.

Audio drives time: each scene lasts long enough for its lines (plus lead-in,
tail, and both transitions), never less than min_seconds. With a music bpm,
transition midpoints and the final frame snap forward to the beat grid, so
cuts and transitions land on the music.

  timeline.py --storyboard storyboard.json --vo public/vo/durations.json --out src/timeline.json
  timeline.py --storyboard storyboard.json --estimate --out src/timeline.json   # before any VO exists
"""

import argparse
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_lib as al  # noqa: E402

TRANSITION_SECONDS = {"cut": 0.0, "fade": 0.6, "dissolve": 0.8, "zoom": 0.8, "slide": 0.7,
                      "wipe": 0.9, "iris": 1.0, "tear": 1.1}
DEFAULTS = {"lead_in": 0.35, "tail": 0.5, "gap": 0.25, "min_seconds": 2.5}
AUTO_SFX = {  # sfx.density -> generated cues when a scene lists none
    "subtle": [("transition_out", "whoosh")],
    "moderate": [("transition_out", "whoosh"), ("start", "pop")],
    "rich": [("transition_out", "whoosh"), ("start", "pop"), ("lines", "click")],
}
CUT_SFX = "tick"


def estimate_seconds(text, lang):
    """Reading-speed estimate used before real VO exists."""
    cjk = len(re.findall(r"[぀-ヿ㐀-鿿가-힯]", text))
    words = len(re.findall(r"[A-Za-z0-9À-ɏ']+", text))
    return max(0.8, words / 2.6 + cjk / 6.5 + 0.2)


def transition(scene, fps):
    spec = scene.get("transition_out") or {"type": "fade"}
    if isinstance(spec, str):
        spec = {"type": spec}
    kind = spec.get("type", "fade")
    if kind not in TRANSITION_SECONDS:
        raise SystemExit(f"scene {scene['id']}: unknown transition '{kind}' (use {sorted(TRANSITION_SECONDS)})")
    seconds = spec.get("seconds", TRANSITION_SECONDS[kind])
    frames = 0 if kind == "cut" else max(2, round(seconds * fps))
    params = {k: v for k, v in spec.items() if k not in ("type", "seconds")}
    return {"type": kind, "durationInFrames": frames, "params": params}


def build(board, durations, estimate=False):
    fmt = board.get("format", {})
    fps = int(fmt.get("fps", 60))
    timing = {**DEFAULTS, **board.get("timing", {})}
    music = (board.get("audio") or {}).get("music")
    bpm = float(music["bpm"]) if music and music.get("bpm") else None
    snap = board.get("snap", "beat" if bpm else "none")
    beat = fps * 60.0 / bpm if bpm else None
    grid = {"beat": beat, "bar": beat * 4 if beat else None}.get(snap)
    lang = board.get("language", "en")
    scenes_in = board.get("scenes") or []
    if not scenes_in:
        raise SystemExit("storyboard has no scenes")

    def snap_up(frame):
        return frame if not grid else round(math.ceil(frame / grid - 1e-6) * grid)

    scenes, lines, cues = [], [], []
    start = 0
    previous_out = 0
    for index, scene in enumerate(scenes_in):
        last = index == len(scenes_in) - 1
        trans = transition(scene, fps)
        if last:
            trans = {"type": "cut", "durationInFrames": 0, "params": {}}
        t_in, t_out = previous_out, trans["durationInFrames"]
        cursor = t_in + timing["lead_in"] * fps
        scene_lines = []
        for number, line in enumerate(scene.get("lines") or [], 1):
            line_id = f"{scene['id']}-{number:02d}"
            text = line.get("text", "")
            if line_id in durations:
                seconds = durations[line_id]
            elif estimate or not (line.get("say") or text).strip():
                seconds = estimate_seconds(text, lang)
            else:
                raise SystemExit(f"no voice-over duration for {line_id}; run voiceover.py or pass --estimate")
            if line.get("at") is not None:
                cursor = max(cursor, float(line["at"]) * fps)
            begin = round(cursor)
            length = max(1, round(seconds * fps))
            scene_lines.append({"id": line_id, "scene": scene["id"], "speaker": line.get("speaker", "narrator"),
                                "text": text, "sceneFrom": begin, "durationInFrames": length,
                                "src": f"vo/{line_id}.wav" if line_id in durations else None})
            cursor = begin + length + float(line.get("gap_after", timing["gap"])) * fps
        needed = (scene_lines[-1]["sceneFrom"] + scene_lines[-1]["durationInFrames"]
                  + timing["tail"] * fps) if scene_lines else 0
        frames = max(math.ceil(float(scene.get("min_seconds", timing["min_seconds"])) * fps),
                     math.ceil(needed + t_out), t_in + t_out + fps // 2)
        # Snap the outgoing boundary (transition midpoint, or the cut / final frame) to the grid.
        boundary = start + frames - t_out / 2.0
        frames += max(0, snap_up(math.ceil(boundary)) - math.ceil(boundary))
        record = {"id": scene["id"], "component": scene.get("component", scene["id"]),
                  "from": start, "durationInFrames": frames, "inFrames": t_in, "outFrames": t_out,
                  "transitionOut": trans, "params": scene.get("params", {}),
                  "hold": bool(scene.get("hold", False)), "lines": [l["id"] for l in scene_lines]}
        scenes.append(record)
        for line in scene_lines:
            lines.append({**line, "from": start + line["sceneFrom"]})

        density = ((board.get("audio") or {}).get("sfx") or {}).get("density")
        wanted = scene.get("sfx")
        if wanted is None and density in AUTO_SFX:
            wanted = []
            for at, kind in AUTO_SFX[density]:
                if at == "transition_out" and trans["type"] == "cut":
                    kind = CUT_SFX
                if at == "lines":
                    wanted += [{"type": kind, "at": f"line:{n}"} for n in range(1, len(scene_lines) + 1)]
                elif not (at == "transition_out" and last):
                    wanted.append({"type": kind, "at": at})
        for cue in wanted or []:
            at = cue.get("at", "start")
            if at == "transition_out":
                sync = start + frames - t_out / 2.0
            elif at == "transition_in":
                sync = start + t_in / 2.0
            elif at == "start":
                sync = start + t_in
            elif at == "end":
                sync = start + frames
            elif isinstance(at, str) and at.startswith("line:"):
                n = int(at.split(":")[1]) - 1
                if n >= len(scene_lines):
                    raise SystemExit(f"scene {scene['id']}: sfx cue {at} but only {len(scene_lines)} lines")
                sync = start + scene_lines[n]["sceneFrom"]
            else:
                sync = start + float(at) * fps
            cues.append({"id": f"sfx-{len(cues) + 1:02d}", "type": cue["type"], "scene": scene["id"],
                         "syncFrame": round(sync), "gainDb": cue.get("gain_db"),
                         "params": {k: v for k, v in cue.items() if k not in ("type", "at", "gain_db")}})

        start += frames - t_out
        previous_out = t_out

    total = scenes[-1]["from"] + scenes[-1]["durationInFrames"]
    sections = []
    for index, scene in enumerate(scenes):
        energy = scenes_in[index].get("energy")
        if energy is None:
            energy = 0.35 if index == 0 else 0.4 if index == len(scenes) - 1 else (0.7 if index % 2 else 0.85)
        begin = 0.0 if index == 0 else (scene["from"] + scene["inFrames"] / 2.0) / fps
        end = total / fps if index == len(scenes) - 1 else \
            (scene["from"] + scene["durationInFrames"] - scene["outFrames"] / 2.0) / fps
        sections.append({"scene": scene["id"], "start": round(begin, 4), "end": round(end, 4),
                         "energy": float(energy)})

    audio = board.get("audio") or {}
    has_vo = any(l["src"] for l in lines)
    timeline = {
        "version": 1, "title": board.get("title", ""), "fps": fps,
        "width": int(fmt.get("width", 1920)), "height": int(fmt.get("height", 1080)),
        "durationInFrames": total, "bpm": bpm, "language": lang,
        "captions": bool(board.get("captions", False)),
        "theme": board.get("theme", {}),
        "scenes": scenes, "lines": lines, "sfx": cues,
        "music": ({**{k: music.get(k) for k in ("style", "key", "seed")}, "bpm": bpm,
                   "src": "music/music.wav", "sections": sections} if music else None),
        "audio": {"vo": has_vo, "music": bool(music), "sfx": bool(cues),
                  "mix": "audio/mix.wav" if (has_vo or music or cues) else None,
                  "voices": (audio.get("voiceover") or {}).get("voices", {})},
    }
    return timeline


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--storyboard", type=Path, default=Path("storyboard.json"))
    parser.add_argument("--vo", type=Path, default=Path("public/vo/durations.json"))
    parser.add_argument("--out", type=Path, default=Path("src/timeline.json"))
    parser.add_argument("--estimate", action="store_true", help="Estimate missing line durations from text")
    args = parser.parse_args()
    board = al.load_json(args.storyboard)
    durations = al.load_json(args.vo, {}) if args.vo.is_file() else {}
    timeline = build(board, durations, estimate=args.estimate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Keep SFX placement from a previous gen_sfx run when the cue is unchanged.
    if args.out.is_file():
        old = {(c["type"], c["syncFrame"]): c for c in al.load_json(args.out).get("sfx", [])}
        for cue in timeline["sfx"]:
            prior = old.get((cue["type"], cue["syncFrame"]))
            if prior and prior.get("src"):
                cue.update({k: prior[k] for k in ("src", "from", "durationInFrames") if k in prior})
    al.save_json(args.out, timeline)
    seconds = timeline["durationInFrames"] / timeline["fps"]
    print(f"Timeline: {len(timeline['scenes'])} scenes, {len(timeline['lines'])} lines, "
          f"{len(timeline['sfx'])} sfx cues, {timeline['durationInFrames']} frames ({seconds:.2f}s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
