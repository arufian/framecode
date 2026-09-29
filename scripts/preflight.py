#!/usr/bin/env python3
"""Check the toolchain and report which voice-over backends are ready.

  preflight.py            human-readable summary (exit 1 if a required tool is missing)
  preflight.py --json     machine-readable
  preflight.py --tts-python .venv-tts/bin/python   also probe TTS packages in that interpreter
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def version(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if result.returncode == 0 and text else None


def importable(python, module):
    try:
        result = subprocess.run([python, "-c", f"import {module}"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def find_node():
    """PATH lookup, then common nvm/Homebrew installs (nvm shell functions do not reach subprocesses)."""
    candidates = [shutil.which("node")]
    nvm = Path.home() / ".nvm/versions/node"
    if nvm.is_dir():
        def numeric(path):
            return tuple(int(x) if x.isdigit() else 0 for x in path.name.lstrip("v").split("."))
        candidates += [str(p / "bin/node") for p in sorted(nvm.iterdir(), key=numeric, reverse=True)]
    candidates += ["/opt/homebrew/bin/node", "/usr/local/bin/node"]
    for path in candidates:
        if path and Path(path).is_file():
            found = version([path, "--version"])
            if found:
                return path, found
    return None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--tts-python", default=None, help="Interpreter with TTS packages (default: this one)")
    args = parser.parse_args()
    tts_python = args.tts_python or (".venv-tts/bin/python" if Path(".venv-tts/bin/python").is_file()
                                     else sys.executable)

    node_path, node_version = find_node()
    node_major = int(node_version.lstrip("v").split(".")[0]) if node_version else 0
    ffmpeg = version(["ffmpeg", "-version"])
    filters = version(["ffmpeg", "-hide_banner", "-filters"]) and subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout if ffmpeg else ""
    key_present = bool(os.environ.get("ELEVENLABS_API_KEY")) or (
        Path(".env").is_file() and "ELEVENLABS_API_KEY=" in Path(".env").read_text(encoding="utf-8"))

    report = {
        "node": {"path": node_path, "version": node_version, "ok": node_major >= 18},
        "ffmpeg": {"version": ffmpeg, "ok": bool(ffmpeg) and all(
            f in filters for f in ("scdet", "freezedetect", "blackdetect", "ebur128", "silencedetect"))},
        "ffprobe": {"ok": bool(version(["ffprobe", "-version"]))},
        "python": {"version": sys.version.split()[0], "ok": sys.version_info >= (3, 9)},
        "numpy_scipy": {"ok": importable(sys.executable, "numpy, scipy")},
        "tts": {
            "python": tts_python,
            "elevenlabs": {"key_present": key_present, "ready": key_present},
            "kokoro": {"ready": importable(tts_python, "kokoro"),
                       "espeak_ng": bool(shutil.which("espeak-ng"))},
            "coqui": {"ready": importable(tts_python, "TTS.api")},
        },
    }
    required = ("node", "ffmpeg", "ffprobe", "python", "numpy_scipy")
    ok = all(report[k]["ok"] for k in required)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if ok else 1
    mark = {True: "ok ", False: "MISSING"}
    print(f"[{mark[report['node']['ok']]}] node >= 18: {node_version or 'not found'} {node_path or ''}")
    print(f"[{mark[report['ffmpeg']['ok']]}] ffmpeg with QC filters: {ffmpeg or 'not found'}")
    print(f"[{mark[report['ffprobe']['ok']]}] ffprobe")
    print(f"[{mark[report['python']['ok']]}] python >= 3.9: {report['python']['version']}")
    print(f"[{mark[report['numpy_scipy']['ok']]}] numpy + scipy (pip install numpy scipy)")
    tts = report["tts"]
    print(f"voice-over backends (probed with {tts_python}):")
    print(f"  elevenlabs: {'API key found' if key_present else 'no ELEVENLABS_API_KEY yet'}")
    print(f"  kokoro:     {'ready' if tts['kokoro']['ready'] else 'not installed'}"
          f"{'' if tts['kokoro']['espeak_ng'] else ' (espeak-ng missing: brew install espeak-ng)'}")
    print(f"  coqui:      {'ready' if tts['coqui']['ready'] else 'not installed'}")
    if node_path and not shutil.which("node"):
        print(f"note: node is not on PATH for subprocesses; prefix commands with PATH={Path(node_path).parent}:$PATH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
