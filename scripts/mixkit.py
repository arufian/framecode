#!/usr/bin/env python3
"""Find and download free media from Mixkit: music, sound effects, stock video, stock art.

  mixkit.py search music discover/upbeat --pages 2 --save media/candidates.json
  mixkit.py search music tag/corporate
  mixkit.py search sfx whoosh                       # any /free-sound-effects/<path>/ listing
  mixkit.py search video discover/office            # any /free-stock-video/<path>/ listing
  mixkit.py search video "discover/background/?orientation=vertical"
  mixkit.py search art business                     # any /free-stock-art/<path>/ listing
  mixkit.py sheet video 49845 1606 2031 --out media/thumbs/video.jpg   # contact sheet to look at
  mixkit.py get media --to media/review --music 644 700 --sfx whoosh=1492 --video S2=49845 --art S3=175
  mixkit.py review media/review            # media/review/index.html: play/view every download
  mixkit.py get media --music music=644 --sfx whoosh=1492 --video city=49845 --art hero=175

`get --to <dir>` downloads candidates for the user to review (not into the ledger) and lists
them in <dir>/review.json; `review` turns that into a page with players for every file.
`get` without --to records the picks in media/sources.json (the media ledger) with their
Mixkit page, title and licence, reusing files already downloaded for review; media.py then
measures and prepares them.
Music comes as MP3, effects as WAV (MP3 when only a preview exists), video as MP4 at
--res (default 1080, falling back to 720 and 360), art as the original PNG.

Listing paths are the part of a mixkit.co URL after /free-stock-music/, /free-sound-effects/,
/free-stock-video/ or /free-stock-art/: discover/<word> searches, tag/<tag>, mood/<mood>,
genre/<genre>, or a category such as click, whoosh, nature, business. A ?query (for example
?orientation=vertical on video) is kept.

Licences (https://mixkit.co/license/): Stock Music Free, Sound Effects Free, Stock Video Free,
Stock Video Restricted (read it before using such a clip; `get` warns), Art Free. `get` reads
each video's and art item's licence from its page. Mixkit does not publish tempo: measure
candidate tracks with media.py survey.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
SITE = "https://mixkit.co"
BASE = {"music": f"{SITE}/free-stock-music/", "sfx": f"{SITE}/free-sound-effects/",
        "video": f"{SITE}/free-stock-video/", "art": f"{SITE}/free-stock-art/"}
LICENSES = {
    "musicFree": "Mixkit Stock Music Free License",
    "sfxFree": "Mixkit Sound Effects Free License",
    "videoFree": "Mixkit Stock Video Free License",
    "videoRestricted": "Mixkit Stock Video Restricted License",
    "artFree": "Mixkit Art Free License",
}
DEFAULT_LICENSE = {"music": "musicFree", "sfx": "sfxFree", "video": None, "art": "artFree"}
THUMB = {"video": "https://assets.mixkit.co/videos/{id}/{id}-thumb-360-0.jpg",
         "art": "https://assets.mixkit.co/art/{id}/{id}-square.png-500h.png"}


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def asset_urls(kind: str, item: str, res: int = 1080) -> list[str]:
    """Download URLs to try in order (best first)."""
    if kind == "music":
        return [f"https://assets.mixkit.co/music/{item}/{item}.mp3"]
    if kind == "sfx":
        return [f"https://assets.mixkit.co/active_storage/sfx/{item}/{item}.wav",
                f"https://assets.mixkit.co/active_storage/sfx/{item}/{item}-preview.mp3"]
    if kind == "video":
        ladder = [r for r in (2160, 1080, 720, 360) if r <= res] or [360]
        return [f"https://assets.mixkit.co/videos/{item}/{item}-{r}.mp4" for r in ladder]
    if kind == "art":
        return [f"https://assets.mixkit.co/art/{item}/{item}-original.png",
                f"https://assets.mixkit.co/art/{item}/{item}-square.png"]
    raise ValueError(kind)


def _text(fragment: str | None) -> str:
    return html.unescape(re.sub(r"\s+", " ", fragment or "")).strip()


def parse_listing(page: str, kind: str, listing: str) -> list[dict]:
    out = []
    if kind in ("music", "sfx"):
        for block in page.split('data-test-id="audio-player"')[1:]:
            g = lambda pat: (m.group(1) if (m := re.search(pat, block, re.S)) else None)  # noqa: E731
            item = g(r'data-audio-player-item-id-value="(\d+)"')
            if not item or g(r'data-audio-player-item-type-value="(\w+)"') != kind:
                continue
            out.append({"id": item, "kind": kind, "title": _text(g(r'item-grid-card__title">\s*(.*?)\s*</h2>')),
                        "author": _text(g(r'preview__author">\s*by\s*(.*?)\s*</p>')),
                        "duration": g(r'data-test-id="duration">\s*([\d:]+)\s*<'),
                        "tags": [_text(t) for t in re.findall(r'class="meta-links__link"[^>]*>([^<]+)</a>', block)],
                        "listing": listing})
    elif kind == "video":
        for block in re.split(r'class="item-grid-card[\s"]', page)[1:]:
            g = lambda pat: (m.group(1) if (m := re.search(pat, block, re.S)) else None)  # noqa: E731
            item = g(r'data-item-grid--video-player-item-id-value="(\d+)"')
            if not item:
                continue
            out.append({"id": item, "kind": kind,
                        "title": _text(g(r'overlay-video-title">(.*?)</span>') or g(r'overlay-link">(.*?)</a>')),
                        "description": _text(g(r'overlay-video-description">(.*?)</span>')
                                             or g(r'item-grid-card__description">(.*?)</p>')),
                        "page": SITE + (g(r'<a href="(/free-stock-video/[^"]+)" class="item-grid-video-player__overlay-link"') or ""),
                        "thumb": THUMB["video"].format(id=item), "listing": listing})
    elif kind == "art":
        for m in re.finditer(r'<a data-analytics-click-label="([^"]*)" href="(/free-stock-art/[^"]*-(\d+)/)"', page):
            out.append({"id": m.group(3), "kind": kind, "title": _text(m.group(1)), "page": SITE + m.group(2),
                        "thumb": THUMB["art"].format(id=m.group(3)), "listing": listing})
    return out


def search(kind: str, path: str, pages: int) -> list[dict]:
    path = path.strip("/").replace("/?", "?")
    base, _, query = path.partition("?")
    items, seen = [], set()
    for p in range(1, pages + 1):
        params = [q for q in (query, f"page={p}" if p > 1 else "") if q]
        url = BASE[kind] + base + "/" + ("?" + "&".join(params) if params else "")
        try:
            page = fetch(url).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as error:
            print(f"warning: {url}: {error}", file=sys.stderr)
            break
        got = [i for i in parse_listing(page, kind, url) if i["id"] not in seen]
        if not got:
            break
        seen.update(i["id"] for i in got)
        items += got
    return items


def item_page(kind: str, item: str) -> tuple[str, str]:
    """(canonical page URL, HTML) of one item; Mixkit redirects /<section>/x-<id>/ to it."""
    req = urllib.request.Request(f"{BASE[kind]}x-{item}/", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def page_facts(kind: str, item: str) -> dict:
    try:
        url, page = item_page(kind, item)
    except (urllib.error.URLError, OSError) as error:
        print(f"warning: could not read the page of {kind} {item}: {error}", file=sys.stderr)
        return {}
    facts = {"page": url}
    if m := re.search(r'data-license="(\w+)"', page):
        facts["licenseId"] = m.group(1)
    if m := re.search(r'<meta property="og:title" content="([^"]*)"', page) or re.search(r"<title>(.*?)</title>", page, re.S):
        facts["title"] = re.sub(r"\s*[|-]\s*Mixkit.*$", "", _text(m.group(1)))
    if m := re.search(r'"duration":"PT(\d+)M(\d+)S"', page):
        facts["seconds"] = int(m.group(1)) * 60 + int(m.group(2))
    return facts


def load_candidates(media: Path) -> dict:
    found = {}
    for f in sorted(media.glob("candidates*.json")):
        for c in json.loads(f.read_text()):
            found[(c["kind"], str(c["id"]))] = c
    return found


def jobs_from(args) -> list[tuple[str, str, str]]:
    jobs = []
    for kind in ("music", "sfx", "video", "art"):
        for spec in getattr(args, kind) or []:
            if "=" in spec:
                name, item = spec.split("=", 1)
            elif args.to:
                name, item = spec, spec
            elif kind == "music" and len(args.music) == 1:
                name, item = "music", spec
            else:
                sys.exit(f"error: --{kind} takes name=id pairs (for example whoosh=2319), got {spec}")
            if not item.isdigit() or not re.fullmatch(r"[A-Za-z0-9][\w.-]*", name):
                sys.exit(f"error: bad --{kind} {spec}: names are letters, digits, - and _; ids are numbers")
            jobs.append((kind, name, item))
    return jobs


def download(kind: str, item: str, dest: Path, res: int, cache: tuple = ()) -> tuple[Path, str]:
    """Fetch the best available file, reusing a copy already in dest or a cache folder."""
    error = None
    for url in asset_urls(kind, item, res):
        path = dest / Path(url).name
        if path.is_file() and path.stat().st_size > 0:
            return path, url
        cached = next((d / path.name for d in cache if (d / path.name).is_file() and (d / path.name).stat().st_size), None)
        if cached:
            shutil.copy2(cached, path)
            return path, url
        try:
            data = fetch(url, timeout=300)
        except (urllib.error.URLError, OSError) as e:
            error = e
            continue
        path.write_bytes(data)
        return path, url
    raise RuntimeError(f"could not download {kind} {item}: {error}")


def get(args) -> int:
    media = args.media
    dest = args.to or media / "src"
    dest.mkdir(parents=True, exist_ok=True)
    cands = load_candidates(media)
    ledger_file = media / "sources.json"
    ledger = json.loads(ledger_file.read_text()) if ledger_file.is_file() else []
    failed = 0
    cache = tuple(d for d in (media / "review", media / "candidates", media / "src") if d.is_dir() and d != dest)
    review_file = dest / "review.json"
    review = json.loads(review_file.read_text()) if args.to and review_file.is_file() else []
    for kind, name, item in jobs_from(args):
        try:
            path, url = download(kind, item, dest, args.res, cache)
        except RuntimeError as error:
            print(f"warning: {error}. Pick the next best item rather than making one.", file=sys.stderr)
            failed += 1
            continue
        c = cands.get((kind, item), {})
        facts = page_facts(kind, item) if kind in ("video", "art") else {}
        license_id = facts.get("licenseId") or DEFAULT_LICENSE[kind]
        title = c.get("title") or facts.get("title", "")
        print(f"  {kind} {name}: {path} ({path.stat().st_size / 1e6:.2f} MB) {title}")
        if license_id == "videoRestricted":
            print(f"  ! {kind} {item} is under the Mixkit Stock Video Restricted License: read "
                  "https://mixkit.co/license/#videoRestricted and confirm the use with the user", file=sys.stderr)
        if kind == "video" and args.res >= 1080 and not url.endswith(f"-{args.res}.mp4"):
            print(f"  note: {item} has no {args.res}p file; took {Path(url).stem.split('-')[-1]}p", file=sys.stderr)
        if args.to:
            review = [r for r in review if (r["kind"], r["id"]) != (kind, item)]
            review.append({"kind": kind, "id": item, "label": name if name != item else "", "file": path.name,
                           "title": title, "author": c.get("author", ""), "duration": c.get("duration"),
                           "description": c.get("description", ""), "tags": c.get("tags", []),
                           "page": facts.get("page") or c.get("page") or "", "licenseId": license_id,
                           "license": LICENSES.get(license_id, "unknown: check the item page"),
                           "mb": round(path.stat().st_size / 1e6, 2)})
            continue
        entry = {"name": name, "kind": kind, "source": "mixkit", "id": item,
                 "file": path.relative_to(media).as_posix(), "url": url,
                 "page": facts.get("page") or c.get("page") or c.get("listing") or BASE[kind],
                 "title": title, "author": c.get("author", ""),
                 "license": LICENSES.get(license_id, "unknown: check the item page"), "licenseId": license_id}
        if kind == "video" and license_id is None:
            entry["license"] = "unknown: check the item page before use"
        old = next((e for e in ledger if e["name"] == name), None)
        if old and old.get("id") == item:  # keep hand-set fields (trim, overrides) on a re-download
            entry = {**old, **entry}
        ledger = [e for e in ledger if e["name"] != name] + [entry]
    if args.to:
        review_file.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
        print(f"{len(review)} items in {review_file}: next run mixkit.py review {dest}")
    else:
        ledger_file.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
        print(f"updated {ledger_file}: next run media.py measure")
    return 1 if failed else 0


REVIEW_CSS = """
:root { --bg: #f6f5f2; --card: #ffffff; --ink: #1d1d1f; --muted: #6b6b70; --line: #e2e0da; --warn: #b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg: #151517; --card: #1f1f23; --ink: #f2f2f4; --muted: #a0a0a8;
  --line: #2e2e34; --warn: #ff8a80; } }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px 64px; background: var(--bg); color: var(--ink);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif; }
main { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 32px 0 12px; }
p.lead { color: var(--muted); margin: 0 0 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.card video, .card img { display: block; width: 100%; max-height: 320px; object-fit: contain; background: #000; }
.card audio { width: 100%; }
.body { padding: 12px 14px; } .num { font-weight: 700; margin-right: 6px; }
.meta { color: var(--muted); font-size: 13px; margin-top: 4px; word-break: break-word; }
.warn { color: var(--warn); font-weight: 600; } a { color: inherit; }
"""


def review(args) -> int:
    """Write an HTML page with a player for every item downloaded with get --to <dir>."""
    folder = args.dir
    items = json.loads((folder / "review.json").read_text()) if (folder / "review.json").is_file() else []
    items = [i for i in items if (folder / i["file"]).is_file()]
    if not items:
        sys.exit(f"nothing to review in {folder}: download candidates with mixkit.py get <media> --to {folder} ...")
    esc = lambda x: html.escape(str(x or ""))  # noqa: E731
    parts = [f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>Mixkit review</title><style>{REVIEW_CSS}</style><main><h1>Mixkit review</h1>"
             "<p class=lead>Downloaded candidates for this video. Play, watch, and look at each one, then answer the "
             "agent's questions with the numbers you want. Nothing is built until you pick.</p>"
             "<p class=lead>Licences: <a href='https://mixkit.co/license/'>mixkit.co/license</a></p>"]
    number = 0
    for kind, label in (("music", "Music"), ("sfx", "Sound effects"), ("video", "Footage"), ("art", "Art")):
        group = [i for i in items if i["kind"] == kind]
        if not group:
            continue
        parts.append(f"<h2>{label}</h2><div class=grid>")
        for i in group:
            number += 1
            i["number"] = number
            src = esc(i["file"])
            player = {"music": f"<audio controls preload=none src='{src}'></audio>",
                      "sfx": f"<audio controls preload=none src='{src}'></audio>",
                      "video": f"<video controls muted loop playsinline preload=metadata src='{src}'></video>",
                      "art": f"<img loading=lazy alt='{esc(i['title'])}' src='{src}'>"}[kind]
            warn = " <span class=warn>Restricted licence: read it before choosing</span>" if i.get("licenseId") == "videoRestricted" else ""
            bits = [f"id {esc(i['id'])}", esc(i.get("duration")), esc(i.get("author")), f"{i.get('mb', 0)} MB"]
            page = f" · <a href='{esc(i['page'])}'>page</a>" if i.get("page") else ""
            parts.append(f"<div class=card>{player if kind in ('video', 'art') else ''}<div class=body>"
                         f"<span class=num>#{number}</span>{esc(i['label']) + ' · ' if i.get('label') else ''}"
                         f"<strong>{esc(i['title']) or esc(i['id'])}</strong>"
                         f"{player if kind in ('music', 'sfx') else ''}"
                         f"<div class=meta>{' · '.join(b for b in bits if b)}{page}</div>"
                         f"<div class=meta>{esc(i.get('license'))}{warn}</div>"
                         f"{'<div class=meta>' + esc(i['description']) + '</div>' if i.get('description') else ''}"
                         "</div></div>")
        parts.append("</div>")
    parts.append("</main></html>")
    out = args.out or folder / "index.html"
    out.write_text("".join(parts))
    print(f"review page {out} ({number} items). Open it: open {out}  (Linux: xdg-open)")
    for i in items:
        print(f"  #{i['number']:<3} {i['kind']:5s} {i['id']:>6}  {i.get('label') or '':10s} {i['title'][:50]}")
    return 0


def sheet(args) -> int:
    """Download thumbnails and tile them into one image (row-major, numbered from 0)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        ok = []
        for item in args.ids:
            try:
                data = fetch(THUMB[args.kind].format(id=item))
            except (urllib.error.URLError, OSError) as error:
                print(f"warning: thumbnail {item}: {error}", file=sys.stderr)
                continue
            src = Path(tmp) / f"raw{len(ok):03d}"
            src.write_bytes(data)
            # normalise every thumb to one JPEG size so the image2 demuxer can tile them
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-vf",
                            "scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2:color=0x202020",
                            str(Path(tmp) / f"{len(ok):03d}.jpg")], check=True)
            ok.append(item)
        if not ok:
            sys.exit("no thumbnails downloaded")
        cols = min(args.cols, len(ok))
        rows = -(-len(ok) // cols)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        base = ["-y", "-loglevel", "error", "-framerate", "1", "-i", str(Path(tmp) / "%03d.jpg")]
        label = "drawtext=text='%{frame_num}':x=10:y=10:fontsize=34:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6,"
        tile = f"tile={cols}x{rows}:padding=6:margin=6"
        run = subprocess.run([ffmpeg, *base, "-vf", label + tile, "-frames:v", "1", str(args.out)], capture_output=True)
        if run.returncode:
            subprocess.run([ffmpeg, *base, "-vf", tile, "-frames:v", "1", str(args.out)], check=True)
    print(f"sheet {args.out} ({cols}x{rows}, row-major):")
    for i, item in enumerate(ok):
        print(f"  {i:>2}  {args.kind} {item}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("search", help="list items on a Mixkit listing page")
    p.add_argument("kind", choices=sorted(BASE))
    p.add_argument("path", help="listing path, e.g. discover/upbeat, tag/corporate, whoosh, discover/office")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--save", type=Path, help="merge the results into this JSON file (get reads titles from it)")
    p = sp.add_parser("sheet", help="contact sheet of video or art thumbnails")
    p.add_argument("kind", choices=["video", "art"])
    p.add_argument("ids", nargs="+")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cols", type=int, default=4)
    p = sp.add_parser("get", help="download items into the media ledger")
    p.add_argument("media", type=Path, help="the project's media/ folder")
    for kind in ("music", "sfx", "video", "art"):
        p.add_argument(f"--{kind}", nargs="*", default=[], metavar="NAME=ID")
    p.add_argument("--res", type=int, default=1080, choices=[360, 720, 1080, 2160], help="video resolution to try first")
    p.add_argument("--to", type=Path, help="download candidates here for review, without adding them to the ledger")
    p = sp.add_parser("review", help="HTML page to play and view the candidates in a get --to folder")
    p.add_argument("dir", type=Path)
    p.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.cmd == "search":
        items = search(args.kind, args.path, args.pages)
        for i in items:
            extra = f"{i.get('duration') or '':>5}  {i.get('author', '')[:22]:22s}  {', '.join(i.get('tags', [])[:4])}" \
                if args.kind in ("music", "sfx") else i.get("description", "")[:70]
            print(f"{i['id']:>6}  {i['title'][:48]:48s}  {extra}")
        print(f"{len(items)} {args.kind} items", file=sys.stderr)
        if args.save:
            old = json.loads(args.save.read_text()) if args.save.is_file() else []
            keep = {(o["kind"], str(o["id"])): o for o in old}
            keep.update({(i["kind"], i["id"]): i for i in items})
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json.dumps(list(keep.values()), indent=2, ensure_ascii=False) + "\n")
        return 0 if items else 1
    if args.cmd == "sheet":
        return sheet(args)
    if args.cmd == "review":
        return review(args)
    return get(args)


if __name__ == "__main__":
    sys.exit(main())
