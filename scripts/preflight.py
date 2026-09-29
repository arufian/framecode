#!/usr/bin/env python3
"""Check the toolchain and report which voice-over backends are ready.

Run it from the video project after npm install: there it also checks p5.js,
Puppeteer, and the headless Chrome the renderer draws frames in.

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


def node_ok(found, minimum=(22, 12)):
    """Puppeteer (the renderer's headless Chrome driver) needs Node 22.12 or newer."""
    parts = [int(x) if x.isdigit() else 0 for x in (found or "v0").lstrip("v").split(".")[:2]]
    return tuple(parts + [0] * (2 - len(parts))) >= minimum


def headless_chrome():
    """FRAMECODE_BROWSER, or a browser Puppeteer downloaded into its cache."""
    custom = os.environ.get("FRAMECODE_BROWSER")
    if custom:
        return Path(custom).is_file()
    cache = Path(os.environ.get("PUPPETEER_CACHE_DIR") or Path.home() / ".cache/puppeteer")
    return any(cache.glob("chrome-headless-shell/*/*")) or any(cache.glob("chrome/*/*"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--tts-python", default=None, help="Interpreter with TTS packages (default: this one)")
    args = parser.parse_args()
    tts_python = args.tts_python or (".venv-tts/bin/python" if Path(".venv-tts/bin/python").is_file()
                                     else sys.executable)

    node_path, node_version = find_node()
    in_project = Path("package.json").is_file()
    ffmpeg = version(["ffmpeg", "-version"])
    key_present = bool(os.environ.get("ELEVENLABS_API_KEY")) or (
        Path(".env").is_file() and "ELEVENLABS_API_KEY=" in Path(".env").read_text(encoding="utf-8"))

    report = {
        "node": {"path": node_path, "version": node_version, "ok": node_ok(node_version)},
        "ffmpeg": {"version": ffmpeg, "ok": bool(ffmpeg)},
        "ffprobe": {"ok": bool(version(["ffprobe", "-version"]))},
        "python": {"version": sys.version.split()[0], "ok": sys.version_info >= (3, 9)},
        "numpy_scipy": {"ok": importable(sys.executable, "numpy, scipy")},
        "p5": {"ok": Path("node_modules/p5/lib/p5.esm.min.js").is_file()},
        "puppeteer": {"ok": Path("node_modules/puppeteer/package.json").is_file()},
        "headless_chrome": {"ok": headless_chrome()},
        "tts": {
            "python": tts_python,
            "elevenlabs": {"key_present": key_present, "ready": key_present},
            "kokoro": {"ready": importable(tts_python, "kokoro"),
                       "espeak_ng": bool(shutil.which("espeak-ng"))},
            "coqui": {"ready": importable(tts_python, "TTS.api")},
        },
    }
    required = ("node", "ffmpeg", "ffprobe", "python", "numpy_scipy") + (
        ("p5", "puppeteer", "headless_chrome") if in_project else ())
    ok = all(report[k]["ok"] for k in required)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if ok else 1
    mark = {True: "ok ", False: "MISSING"}
    print(f"[{mark[report['node']['ok']]}] node >= 22.12: {node_version or 'not found'} {node_path or ''}")
    print(f"[{mark[report['ffmpeg']['ok']]}] ffmpeg: {ffmpeg or 'not found'}")
    print(f"[{mark[report['ffprobe']['ok']]}] ffprobe")
    print(f"[{mark[report['python']['ok']]}] python >= 3.9: {report['python']['version']}")
    print(f"[{mark[report['numpy_scipy']['ok']]}] numpy + scipy (pip install numpy scipy)")
    if in_project:
        print(f"[{mark[report['p5']['ok']]}] p5.js (npm install --save-exact p5@2)")
        print(f"[{mark[report['puppeteer']['ok']]}] puppeteer (npm install --save-exact puppeteer)")
        print(f"[{mark[report['headless_chrome']['ok']]}] headless Chrome for rendering"
              f"{'' if report['headless_chrome']['ok'] else ' (npx puppeteer browsers install chrome-headless-shell, or set FRAMECODE_BROWSER)'}")
    else:
        print("note: run from the video project after npm install to also check p5.js, puppeteer, and headless Chrome")
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
