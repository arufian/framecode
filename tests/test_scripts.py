"""Regression tests for the skill's scripts and engine. No network, no live models.

Tests that need ffmpeg or Node skip when those tools are missing.
"""

import contextlib
import http.server
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audio_lib as al  # noqa: E402
import gen_music  # noqa: E402
import gen_sfx  # noqa: E402
import mix_audio  # noqa: E402
import preflight  # noqa: E402
import timeline as tl  # noqa: E402
import voiceover  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
NODE = preflight.find_node()[0]
SR = al.SR


def sine(freq, seconds, amplitude, channels=2, phase=0.0):
    t = np.arange(int(seconds * SR)) / SR
    y = (amplitude * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    return np.repeat(y[:, None], channels, axis=1)


def board(**overrides):
    data = {
        "title": "Test", "language": "en",
        "format": {"aspect": "16:9", "width": 1920, "height": 1080, "fps": 60},
        "captions": True,
        "audio": {"voiceover": {"backend": "elevenlabs", "voices": {"narrator": "voice-a", "dot": "voice-b"}},
                  "music": {"style": "ambient", "bpm": 90, "key": "D", "seed": 7},
                  "sfx": {"density": "subtle"}},
        "scenes": [
            {"id": "S1", "component": "title", "min_seconds": 4.5,
             "lines": [{"speaker": "narrator", "text": "Every frame of this video is drawn in code."}],
             "transition_out": {"type": "iris", "center": [0.5, 0.6]},
             "sfx": [{"type": "pop", "at": 0.3}, {"type": "whoosh", "at": "transition_out"}]},
            {"id": "S2", "component": "explainer", "min_seconds": 6,
             "lines": [{"speaker": "narrator", "text": "A script becomes a voice."},
                       {"speaker": "dot", "text": "And sixty frames every second."}],
             "transition_out": {"type": "tear"},
             "sfx": [{"type": "pencil", "at": "line:2"}, {"type": "paper", "at": "transition_out"}]},
            {"id": "S3", "component": "outro", "min_seconds": 4, "lines": [{"speaker": "narrator", "text": "Your turn."}]},
        ],
    }
    data.update(overrides)
    return data


DURATIONS = {"S1-01": 2.365, "S2-01": 1.8, "S2-02": 2.2, "S3-01": 0.939}


class LoudnessTests(unittest.TestCase):
    def test_stereo_sine_reads_its_level_in_lufs(self):
        self.assertAlmostEqual(al.integrated_loudness(sine(997, 5, 0.1)), -20.0, delta=0.2)
        self.assertAlmostEqual(al.integrated_loudness(sine(997, 5, 0.1, channels=1)), -23.0, delta=0.2)

    def test_true_peak_sees_intersample_peaks(self):
        x = sine(12000, 1, 1.0, phase=np.pi / 4)
        self.assertAlmostEqual(al.gain_to_db(np.abs(x).max()), -3.01, delta=0.1)
        self.assertAlmostEqual(al.true_peak_db(x), 0.0, delta=0.3)

    def test_master_hits_loudness_and_ceiling(self):
        rng = np.random.default_rng(1)
        x = sine(220, 6, 0.3) + rng.normal(0, 0.05, (6 * SR, 2)).astype(np.float32)
        x[SR:SR + 200] *= 3.0  # a transient that needs limiting
        y, stats = al.master(x, -14.0, -1.5)
        self.assertAlmostEqual(al.integrated_loudness(y), -14.0, delta=0.3)
        self.assertLessEqual(al.true_peak_db(y), -1.5 + 1e-6)
        self.assertEqual(stats["lufs"], round(al.integrated_loudness(y), 2))

    def test_limiter_respects_ceiling_and_leaves_quiet_audio_alone(self):
        x = sine(100, 1, 1.5)
        self.assertLessEqual(np.abs(al.limit(x, -3.0)).max(), al.db_to_gain(-3.0) + 1e-5)
        quiet = sine(100, 1, 0.1)
        np.testing.assert_array_equal(al.limit(quiet, -3.0), quiet)

    def test_wav_roundtrip_and_resample(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.wav"
            al.write_wav(path, sine(440, 0.5, 0.5), sr=24000)  # 24000 samples at 24 kHz = 1 s
            back = al.read_audio(path, channels=2)
            self.assertEqual(len(back), SR)
            self.assertAlmostEqual(float(np.abs(back).max()), 0.5, delta=0.02)


class TimelineTests(unittest.TestCase):
    def build(self, **kw):
        return tl.build(kw.pop("b", board()), kw.pop("d", DURATIONS), **kw)

    def test_transition_midpoints_and_ending_land_on_the_beat(self):
        t = self.build()
        beat = 60 * 60 / 90  # 40 frames at 90 bpm, 60 fps
        for scene in t["scenes"][:-1]:
            mid = scene["from"] + scene["durationInFrames"] - scene["outFrames"] / 2
            self.assertAlmostEqual(mid % beat, 0.0, places=6, msg=scene["id"])
        self.assertEqual(t["durationInFrames"] % beat, 0)

    def test_scenes_overlap_by_their_transition(self):
        t = self.build()
        for a, b in zip(t["scenes"], t["scenes"][1:]):
            self.assertEqual(b["from"], a["from"] + a["durationInFrames"] - a["outFrames"])
            self.assertEqual(b["inFrames"], a["outFrames"])
        self.assertEqual(t["scenes"][0]["outFrames"], 60)   # iris default 1.0 s
        self.assertEqual(t["scenes"][-1]["transitionOut"]["type"], "cut")

    def test_lines_fit_between_the_transitions(self):
        t = self.build()
        scenes = {s["id"]: s for s in t["scenes"]}
        for line in t["lines"]:
            scene = scenes[line["scene"]]
            self.assertGreaterEqual(line["sceneFrom"], scene["inFrames"])
            self.assertLessEqual(line["sceneFrom"] + line["durationInFrames"],
                                 scene["durationInFrames"] - scene["outFrames"])
            self.assertEqual(line["src"], f"vo/{line['id']}.wav")
        s2 = [l for l in t["lines"] if l["scene"] == "S2"]
        self.assertGreater(s2[1]["sceneFrom"], s2[0]["sceneFrom"] + s2[0]["durationInFrames"])

    def test_sfx_cues_sync_to_their_moments(self):
        t = self.build()
        s1, s2 = t["scenes"][0], t["scenes"][1]
        cues = {c["type"]: c for c in t["sfx"]}
        self.assertEqual(cues["pop"]["syncFrame"], 18)
        self.assertEqual(cues["whoosh"]["syncFrame"], round(s1["from"] + s1["durationInFrames"] - s1["outFrames"] / 2))
        line2 = [l for l in t["lines"] if l["id"] == "S2-02"][0]
        self.assertEqual(cues["pencil"]["syncFrame"], line2["from"])
        self.assertEqual(cues["paper"]["syncFrame"], round(s2["from"] + s2["durationInFrames"] - s2["outFrames"] / 2))

    def test_auto_sfx_follow_density_and_cuts_get_ticks(self):
        b = board()
        for scene in b["scenes"]:
            scene.pop("sfx", None)
        b["scenes"][1]["transition_out"] = {"type": "cut"}
        t = self.build(b=b)
        self.assertEqual([c["type"] for c in t["sfx"]], ["whoosh", "tick"])

    def test_missing_voice_duration_fails_unless_estimating(self):
        with self.assertRaises(SystemExit):
            self.build(d={})
        t = self.build(d={}, estimate=True)
        self.assertTrue(all(l["src"] is None for l in t["lines"]))
        self.assertFalse(t["audio"]["vo"])

    def test_no_music_means_no_snapping_and_no_music_track(self):
        b = board()
        b["audio"]["music"] = None
        t = self.build(b=b)
        self.assertIsNone(t["music"])
        self.assertIsNone(t["bpm"])
        self.assertEqual(t["scenes"][0]["durationInFrames"], 270)  # min 4.5 s, no grid extension

    def test_unknown_transition_is_rejected(self):
        b = board()
        b["scenes"][0]["transition_out"] = {"type": "star-wipe"}
        with self.assertRaises(SystemExit):
            self.build(b=b)

    def test_music_sections_cover_the_video(self):
        t = self.build()
        sections = t["music"]["sections"]
        self.assertEqual(sections[0]["start"], 0.0)
        self.assertAlmostEqual(sections[-1]["end"], t["durationInFrames"] / 60, places=3)
        for a, b in zip(sections, sections[1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=3)


class MusicTests(unittest.TestCase):
    def test_every_style_renders_exact_length_without_clipping(self):
        for style in gen_music.STYLES:
            with self.subTest(style=style):
                audio = gen_music.compose(style, gen_music.STYLES[style]["bpm"], gen_music.STYLES[style]["key"],
                                          6.0, gen_music.auto_sections(6.0), seed=3)
                self.assertEqual(audio.shape, (6 * SR, 2))
                self.assertTrue(np.isfinite(audio).all())
                self.assertLessEqual(float(np.abs(audio).max()), 1.0)
                self.assertGreater(al.rms_db(audio), -40)
                tail = al.rms_db(audio[-int(0.05 * SR):], gate_db=-120)
                self.assertLess(tail, al.rms_db(audio) - 12, "track should fade out at the end")

    def test_seed_is_deterministic(self):
        args = ("corporate", 112, "C", 4.0, gen_music.auto_sections(4.0))
        a, b = gen_music.compose(*args, seed=5), gen_music.compose(*args, seed=5)
        np.testing.assert_array_equal(a, b)
        self.assertFalse(np.array_equal(a, gen_music.compose(*args, seed=6)))

    def test_keys_parse(self):
        self.assertEqual(gen_music.parse_key("F#m"), (6, gen_music.MINOR))
        self.assertEqual(gen_music.parse_key("Bb"), (10, gen_music.MAJOR))
        with self.assertRaises(SystemExit):
            gen_music.parse_key("H")

    def test_cli_follows_timeline_length(self):
        with tempfile.TemporaryDirectory() as d:
            t = tl.build(board(), DURATIONS)
            path = Path(d) / "timeline.json"
            al.save_json(path, t)
            out = Path(d) / "music.wav"
            subprocess.run([sys.executable, str(SCRIPTS / "gen_music.py"), "--timeline", str(path), "--out", str(out)],
                           check=True, capture_output=True)
            audio = al.read_audio(out)
            self.assertEqual(len(audio), int(t["durationInFrames"] / t["fps"] * SR))
            self.assertAlmostEqual(json.loads(out.with_suffix(".json").read_text())["lufs"], -16.0, delta=0.3)


class SfxTests(unittest.TestCase):
    def test_every_effect_renders_with_a_valid_sync_point(self):
        for name in gen_sfx.EFFECTS:
            with self.subTest(effect=name):
                audio, sync = gen_sfx.render(name, seed=2)
                self.assertEqual(audio.shape[1], 2)
                self.assertTrue(np.isfinite(audio).all())
                self.assertGreaterEqual(sync, 0.0)
                self.assertLessEqual(sync, len(audio) / SR)
                self.assertAlmostEqual(al.gain_to_db(np.abs(audio).max()), -1.0, delta=1.0)

    def test_timeline_cues_get_files_and_start_frames(self):
        with tempfile.TemporaryDirectory() as d:
            t = tl.build(board(), DURATIONS)
            path = Path(d) / "timeline.json"
            al.save_json(path, t)
            count = gen_sfx.from_timeline(path, Path(d) / "sfx")
            self.assertEqual(count, len(t["sfx"]))
            cues = {c["type"]: c for c in al.load_json(path)["sfx"]}
            self.assertEqual(cues["whoosh"]["from"], cues["whoosh"]["syncFrame"] - round(0.6 * 0.9 * 60))
            self.assertEqual(cues["pop"]["from"], cues["pop"]["syncFrame"])
            self.assertEqual(cues["whoosh"]["gainDb"], gen_sfx.DEFAULT_GAIN_DB["whoosh"])
            for cue in cues.values():
                self.assertTrue((Path(d) / cue["src"]).is_file())


class MixTests(unittest.TestCase):
    def test_music_ducks_under_speech_and_master_hits_target(self):
        with tempfile.TemporaryDirectory() as d:
            public = Path(d) / "public"
            (public / "vo").mkdir(parents=True)
            (public / "music").mkdir()
            speech = sine(300, 2.0, 0.3, channels=1) * (0.6 + 0.4 * np.sin(np.linspace(0, 40, 2 * SR)))[:, None]
            al.write_wav(public / "vo" / "S1-01.wav", speech)
            al.write_wav(public / "music" / "music.wav", sine(110, 8.0, 0.2))
            timeline = {"fps": 60, "durationInFrames": 480, "scenes": [],
                        "lines": [{"id": "S1-01", "speaker": "narrator", "from": 180, "durationInFrames": 120,
                                   "src": "vo/S1-01.wav"}],
                        "sfx": [], "music": {"src": "music/music.wav"}}
            vo, music, sfx = mix_audio.mix(timeline, public)
            level_quiet = al.rms_db(music[int(0.5 * SR):int(2.0 * SR)])
            level_ducked = al.rms_db(music[int(3.6 * SR):int(4.6 * SR)])
            self.assertAlmostEqual(level_quiet - level_ducked, 9.0, delta=0.5)
            self.assertAlmostEqual(al.rms_db(vo[3 * SR:5 * SR]), -20.0, delta=0.5)
            path = Path(d) / "timeline.json"
            al.save_json(path, timeline)
            out = public / "audio" / "mix.wav"
            subprocess.run([sys.executable, str(SCRIPTS / "mix_audio.py"), "--timeline", str(path), "--public",
                            str(public), "--out", str(out)], check=True, capture_output=True)
            report = json.loads(out.with_suffix(".json").read_text())
            self.assertAlmostEqual(report["lufs"], -14.0, delta=0.3)
            self.assertLessEqual(report["true_peak"], -1.5)
            self.assertEqual(len(al.read_audio(out)), 8 * SR)


class FakeEleven(http.server.BaseHTTPRequestHandler):
    requests = []
    status = 200

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(FakeEleven.status)
        self.end_headers()
        self.wfile.write(json.dumps({"voices": [{"voice_id": "voice-a", "name": "A", "labels": {"gender": "f"}}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeEleven.requests.append({"path": self.path, "key": self.headers["xi-api-key"], "body": body})
        if FakeEleven.status != 200:
            self.send_response(FakeEleven.status)
            self.end_headers()
            self.wfile.write(f"invalid key {self.headers['xi-api-key']}".encode())
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(al.wav_bytes(sine(220, 1.0, 0.3, channels=1), sr=44100))


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
class VoiceoverTests(unittest.TestCase):
    SECRET = "sk_test_do_not_leak_12345"

    def setUp(self):
        FakeEleven.requests, FakeEleven.status = [], 200
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeEleven)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.work = Path(self.dir.name)
        self.env = {"ELEVENLABS_BASE_URL": f"http://127.0.0.1:{self.server.server_port}", "ELEVENLABS_API_KEY": self.SECRET}

    @contextlib.contextmanager
    def environment(self):
        old_env, old_cwd = dict(os.environ), os.getcwd()
        os.environ.update(self.env)
        os.chdir(self.work)
        try:
            yield
        finally:
            os.chdir(old_cwd)
            os.environ.clear()
            os.environ.update(old_env)

    def test_requests_cache_and_durations(self):
        b = board()
        with self.environment():
            durations = voiceover.generate(b, Path("public/vo"))
        self.assertEqual(sorted(durations), sorted(DURATIONS))
        self.assertEqual(len(FakeEleven.requests), 4)
        first = FakeEleven.requests[0]
        self.assertEqual(first["path"], "/v1/text-to-speech/voice-a?output_format=mp3_44100_128")
        self.assertEqual(first["key"], self.SECRET)
        self.assertEqual(first["body"]["model_id"], voiceover.ELEVEN_DEFAULT_MODEL)
        dot = [r for r in FakeEleven.requests if "voice-b" in r["path"]][0]
        self.assertEqual(dot["body"]["previous_text"], "A script becomes a voice.")
        wav = al.read_audio(self.work / "public/vo/S2-02.wav", channels=1)
        self.assertLess(abs(len(wav) / SR - durations["S2-02"]), 0.01)
        manifest = (self.work / "public/vo/manifest.json").read_text()
        self.assertNotIn(self.SECRET, manifest)
        with self.environment():
            voiceover.generate(b, Path("public/vo"))
        self.assertEqual(len(FakeEleven.requests), 4, "unchanged lines must come from cache")
        b["scenes"][2]["lines"][0]["text"] = "Now it's your turn."
        with self.environment():
            voiceover.generate(b, Path("public/vo"))
        self.assertEqual(len(FakeEleven.requests), 5)
        self.assertEqual(FakeEleven.requests[-1]["body"]["text"], "Now it's your turn.")

    def test_key_is_never_printed(self):
        path = self.work / "storyboard.json"
        al.save_json(path, board())
        run = lambda *a: subprocess.run([sys.executable, str(SCRIPTS / "voiceover.py"), *a], cwd=self.work,
                                        env={**os.environ, **self.env}, capture_output=True, text=True)
        for result in (run("--check"), run("--storyboard", str(path))):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(self.SECRET, result.stdout + result.stderr)
        FakeEleven.status = 401
        result = run("--storyboard", str(path), "--force")
        self.assertEqual(result.returncode, 4)
        self.assertIn("HTTP 401", result.stderr)
        self.assertNotIn(self.SECRET, result.stdout + result.stderr)

    def test_key_from_dotenv_and_missing_key(self):
        (self.work / ".env").write_text(f"OTHER=1\nELEVENLABS_API_KEY='{self.SECRET}'\n")
        self.env.pop("ELEVENLABS_API_KEY")
        with self.environment():
            os.environ.pop("ELEVENLABS_API_KEY", None)
            self.assertEqual(voiceover.eleven_key(), self.SECRET)
            (self.work / ".env").unlink()
            with self.assertRaises(voiceover.TTSError):
                voiceover.eleven_key()


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
class QcTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.work = Path(self.dir.name)

    def timeline(self, scenes, frames, audio=False):
        t = {"fps": 30, "width": 320, "height": 180, "durationInFrames": frames, "scenes": scenes, "lines": [], "sfx": [],
             "audio": {"mix": "audio/mix.wav" if audio else None, "music": audio}}
        path = self.work / "timeline.json"
        path.write_text(json.dumps(t))
        return path

    def qc(self, video, timeline, *extra):
        result = subprocess.run([sys.executable, str(SCRIPTS / "qc_video.py"), "--video", str(video), "--timeline",
                                 str(timeline), "--outdir", str(self.work / "qc"), *extra], capture_output=True, text=True)
        return result.returncode, {c["check"]: c["status"] for c in
                                   json.loads((self.work / "qc/report.json").read_text())["checks"]}, result.stdout

    @staticmethod
    def scene(sid, start, length, kind="fade", out=0, hold=False):
        return {"id": sid, "from": start, "durationInFrames": length, "inFrames": 0, "outFrames": out,
                "transitionOut": {"type": kind}, "hold": hold}

    def test_smooth_video_passes(self):
        video = self.work / "smooth.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(video))
        code, checks, out = self.qc(video, self.timeline([self.scene("S1", 0, 90, "cut")], 90))
        self.assertEqual(code, 0, out)
        self.assertEqual(checks["frame count"], "pass")
        self.assertTrue((self.work / "qc/contact.png").is_file())

    def test_hard_cut_fails_unless_planned(self):
        video = self.work / "cut.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1.5", "-f", "lavfi", "-i",
               "life=size=320x180:rate=30:mold=10:ratio=0.3:death_color=#101030:life_color=#ffcc00,trim=duration=1.5",
               "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(video))
        unplanned = self.timeline([self.scene("S1", 0, 45, "fade"), self.scene("S2", 45, 45)], 90)
        code, checks, out = self.qc(video, unplanned)
        self.assertEqual(checks["no unplanned hard cuts"], "fail", out)
        planned = self.timeline([self.scene("S1", 0, 45, "cut"), self.scene("S2", 45, 45)], 90)
        code, checks, out = self.qc(video, planned)
        self.assertEqual(checks["no unplanned hard cuts"], "pass", out)

    def test_frozen_stretch_fails_unless_hold(self):
        video = self.work / "frozen.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1", "-vf", "tpad=stop_mode=clone:stop_duration=2",
               "-pix_fmt", "yuv420p", "-c:v", "libx264", str(video))
        code, checks, out = self.qc(video, self.timeline([self.scene("S1", 0, 90, "cut")], 90))
        self.assertEqual(checks["no frozen frames"], "fail", out)
        self.assertEqual(code, 1)
        code, checks, out = self.qc(video, self.timeline([self.scene("S1", 0, 90, "cut", hold=True)], 90))
        self.assertEqual(checks["no frozen frames"], "pass", out)

    def test_audio_loudness_and_duration(self):
        video = self.work / "audio.mp4"
        wav = self.work / "tone.wav"
        al.write_wav(wav, sine(997, 3, 10 ** (-14 / 20)) + np.random.default_rng(0).normal(0, 0.001, (3 * SR, 2)))
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3", "-i", str(wav), "-pix_fmt", "yuv420p",
               "-c:v", "libx264", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest", str(video))
        code, checks, out = self.qc(video, self.timeline([self.scene("S1", 0, 90, "cut")], 90, audio=True), "--tp", "0")
        for name in ("audio stream", "A/V duration", "loudness", "no silent holes"):
            self.assertEqual(checks[name], "pass", f"{name}\n{out}")


@unittest.skipUnless(NODE, "needs node")
class EngineTests(unittest.TestCase):
    def test_core_math_and_scene_timing(self):
        script = """
import { EASE, spring, SPRING, interpolate, rng, noise2, sceneContext, activeScenes } from './template/engine/core.js';
const out = {};
out.ease = Object.entries(EASE).filter(([k, f]) => typeof f === 'function' && k !== 'bezier')
  .map(([k, f]) => [k, +f(0).toFixed(4), +f(1).toFixed(4)]);
out.spring = [spring(0, SPRING.gentle), +spring(5, SPRING.gentle).toFixed(4), +spring(5, SPRING.bouncy).toFixed(4)];
out.clamp = [interpolate(-5, [0, 10], [0, 1]), interpolate(15, [0, 10], [0, 1])];
const a = rng(7), b = rng(7);
out.rng = [a() === b(), a() >= 0 && a() < 1];
out.noise = Math.abs(noise2(3.3, 1.7, 2)) <= 1;
const timeline = { fps: 60, width: 1920, height: 1080, durationInFrames: 500, lines: [],
  scenes: [{ id: 'S1', from: 0, durationInFrames: 300, inFrames: 0, outFrames: 60, lines: [] },
           { id: 'S2', from: 240, durationInFrames: 260, inFrames: 60, outFrames: 0, lines: [] }] };
const s = sceneContext({ timeline, scenes: {} }, timeline.scenes[0], 270);
out.exitAtMid = +s.exit(0.5).toFixed(4);
out.exitBefore = +sceneContext({ timeline, scenes: {} }, timeline.scenes[0], 200).exit(0.5).toFixed(4);
out.overlap = [activeScenes(timeline, 239).length, activeScenes(timeline, 260).length, activeScenes(timeline, 300).length];
console.log(JSON.stringify(out));
"""
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        for name, start, end in out["ease"]:
            self.assertEqual((start, end), (0, 1), name)
        self.assertEqual(out["spring"], [0, 1.0, 1.0])
        self.assertEqual(out["clamp"], [0, 1])
        self.assertEqual(out["rng"], [True, True])
        self.assertTrue(out["noise"])
        self.assertEqual(out["exitAtMid"], 0)
        self.assertEqual(out["exitBefore"], 1)
        self.assertEqual(out["overlap"], [1, 2, 1])

    def test_engine_files_parse(self):
        for path in (ROOT / "template").rglob("*.js"):
            if "node_modules" in path.parts:
                continue
            result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.skill = (ROOT / "SKILL.md").read_text()

    def test_frontmatter(self):
        match = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", self.skill)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "framecode")
        self.assertGreater(len(match.group(2)), 100)

    def test_required_questions_and_gates_are_present(self):
        for phrase in ("Do you want a voice-over?", "ElevenLabs", "Kokoro", "Coqui", "Do you want background music?",
                       "Do you want sound effects?", "What styles or things do you NOT want in the video?",
                       "Phase 8 — Studio review", "Phase 9 — Ask the output size"):
            self.assertIn(phrase, self.skill)
        self.assertLess(self.skill.index("Phase 8 — Studio review"), self.skill.index("Phase 10 — Render"))

    def test_referenced_files_exist(self):
        for name in set(re.findall(r"scripts/([\w]+\.py)", self.skill)):
            self.assertTrue((SCRIPTS / name).is_file(), name)
        for name in set(re.findall(r"references/([\w-]+\.md)", self.skill)):
            self.assertTrue((ROOT / "references" / name).is_file(), name)

    def test_no_video_frameworks_in_template(self):
        for path in (ROOT / "template").rglob("*"):
            if path.is_file() and "node_modules" not in path.parts and path.suffix in (".js", ".json", ".html"):
                text = path.read_text().lower()
                for banned in ("remotion", "hyperframes", "motion-canvas", "manim"):
                    self.assertNotIn(banned, text, f"{path} mentions {banned}")

    def test_example_storyboard_matches_registered_scenes(self):
        project = (ROOT / "template/project.js").read_text()
        registered = set(re.search(r"scenes: \{([^}]*)\}", project).group(1).replace(" ", "").split(","))
        example = json.loads((ROOT / "template/storyboard.json").read_text())
        self.assertLessEqual({s["component"] for s in example["scenes"]}, registered)
        t = tl.build(example, {}, estimate=True)
        starter = json.loads((ROOT / "template/src/timeline.json").read_text())
        self.assertEqual(t["durationInFrames"], starter["durationInFrames"], "re-run timeline.py --estimate in template/")


if __name__ == "__main__":
    unittest.main()
