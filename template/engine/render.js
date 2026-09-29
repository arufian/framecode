#!/usr/bin/env node
// Render the project to video (or stills) by drawing every frame on a Skia canvas
// and piping raw RGBA to ffmpeg. Run from the project root.
//
//   node engine/render.js --check                      # draw key frames, report errors + timings
//   node engine/render.js --stills auto                # PNGs of every scene middle / transition middle
//   node engine/render.js --size 1920x1080             # out/video.mp4 (+ out/final.mp4 with the audio mix)
//   node engine/render.js --size 3840x2160 --motion-blur 4 --workers 4
//   node engine/render.js --draft                      # half size, fast encode, for quick looks

import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdirSync, rmSync, writeFileSync, statSync } from 'node:fs';
import { cpus } from 'node:os';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { setPlatform, loadProject, renderFrame, createLayer } from './core.js';
import { nodePlatform } from './platform-node.js';

const root = process.cwd();

function parseArgs(argv) {
  const args = { out: 'out/video.mp4', final: 'out/final.mp4', crf: 16, preset: 'slow', workers: 'auto', motionBlur: 0 };
  for (let i = 0; i < argv.length; i++) {
    const [key, inline] = argv[i].replace(/^--/, '').split('=');
    const value = () => inline ?? argv[++i];
    switch (key) {
      case 'check': args.check = true; break;
      case 'draft': args.draft = true; break;
      case 'no-mux': args.noMux = true; break;
      case 'stills': args.stills = value(); break;
      case 'stills-dir': args.stillsDir = value(); break;
      case 'size': args.size = value(); break;
      case 'scale': args.scale = Number(value()); break;
      case 'out': args.out = value(); break;
      case 'final': args.final = value(); break;
      case 'crf': args.crf = Number(value()); break;
      case 'preset': args.preset = value(); break;
      case 'workers': args.workers = value(); break;
      case 'motion-blur': args.motionBlur = Number(value()); break;
      case 'from': args.from = Number(value()); break;
      case 'to': args.to = Number(value()); break;
      default: throw new Error(`unknown option --${key}`);
    }
  }
  return args;
}

async function load() {
  const platform = nodePlatform(root);
  setPlatform(platform);
  const module = await import(pathToFileURL(path.join(root, 'project.js')).href);
  const project = module.default;
  await loadProject(project, platform.loaders);
  return project;
}

function outputSize(timeline, args) {
  let scale = args.scale || 1;
  if (args.size) {
    const [w, h] = args.size.toLowerCase().split('x').map(Number);
    scale = w / timeline.width;
    if (Math.abs(h / timeline.height - scale) > 0.002) {
      throw new Error(`--size ${args.size} does not match the ${timeline.width}x${timeline.height} design aspect ratio`);
    }
  }
  if (args.draft) scale *= 0.5;
  const even = (v) => Math.max(2, Math.round(v / 2) * 2);
  const W = even(timeline.width * scale), H = even(timeline.height * scale);
  return { W, H, scale: W / timeline.width };
}

/** Draw frame f (with optional motion-blur sub-frames) and return RGBA bytes. */
function frameBytes(ctx, project, f, scale, cache, samples, acc, W, H) {
  if (samples <= 1) {
    renderFrame(ctx, project, f, scale, cache);
    return ctx.getImageData(0, 0, W, H).data;
  }
  acc.fill(0);
  for (let k = 0; k < samples; k++) {
    const offset = ((k + 0.5) / samples - 0.5) * 0.5; // 180-degree shutter centred on the frame
    renderFrame(ctx, project, Math.max(0, f + offset), scale, cache);
    const d = ctx.getImageData(0, 0, W, H).data;
    for (let i = 0; i < d.length; i++) acc[i] += d[i];
  }
  const out = new Uint8ClampedArray(acc.length);
  for (let i = 0; i < acc.length; i++) out[i] = acc[i] / samples + 0.5;
  return out;
}

function encoder(file, W, H, fps, { crf, preset }) {
  mkdirSync(path.dirname(file), { recursive: true });
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`,
    '-r', String(fps), '-i', '-', '-an', '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
    '-c:v', 'libx264', '-preset', preset, '-crf', String(crf), '-color_primaries', 'bt709', '-color_trc', 'bt709',
    '-colorspace', 'bt709', '-movflags', '+faststart', file], { stdio: ['pipe', 'inherit', 'pipe'] });
  let log = '';
  ff.stderr.on('data', (chunk) => { log += chunk; });
  const done = new Promise((resolve, reject) => {
    ff.on('error', reject);
    ff.on('close', (code) => (code === 0 ? resolve(log) : reject(new Error(`ffmpeg exited with ${code}: ${log.trim()}`))));
  });
  return { stdin: ff.stdin, done };
}

// macOS: libavformat sizes stdin from the bytes currently buffered and may log a harmless
// "Truncating packet" for its final read. It is only dropped after the frame count is verified.
const BENIGN = /^.*Truncating packet of size \d+ to \d+\s*$/gm;

function countFrames(file) {
  const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=nb_frames',
    '-of', 'csv=p=0', file], { encoding: 'utf8' });
  return Number(probe.stdout.trim());
}

async function renderRange(project, { from, to, W, H, scale, file, options, onProgress }) {
  const canvas = createLayer(W, H);
  const ctx = canvas.getContext('2d');
  const cache = {};
  const samples = Math.max(1, options.motionBlur | 0);
  const acc = samples > 1 ? new Float32Array(W * H * 4) : null;
  const { stdin, done } = encoder(file, W, H, project.timeline.fps, options);
  let last = Date.now();
  for (let f = from; f < to; f++) {
    const data = frameBytes(ctx, project, f, scale, cache, samples, acc, W, H);
    if (!stdin.write(Buffer.from(data.buffer, data.byteOffset, data.byteLength))) await once(stdin, 'drain');
    if (Date.now() - last > 500) { onProgress(f + 1 - from); last = Date.now(); }
  }
  onProgress(to - from);
  stdin.end();
  const log = await done;
  const frames = countFrames(file);
  if (frames !== to - from) throw new Error(`${file}: encoded ${frames} frames, expected ${to - from}. ffmpeg said: ${log.trim()}`);
  const rest = log.replace(BENIGN, '').trim();
  if (rest) process.stderr.write(`${rest}\n`);
}

function formatTime(seconds) {
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m${String(Math.round(seconds % 60)).padStart(2, '0')}s` : `${seconds.toFixed(0)}s`;
}

async function renderVideo(project, args) {
  const { timeline } = project;
  const { W, H, scale } = outputSize(timeline, args);
  const from = args.from ?? 0, to = args.to ?? timeline.durationInFrames;
  const total = to - from;
  const count = args.workers === 'auto' ? Math.max(1, Math.min(4, Math.floor(cpus().length / 2))) : Math.max(1, Number(args.workers));
  const workers = Math.min(count, Math.max(1, Math.floor(total / 30)));
  const options = { crf: args.draft ? 23 : args.crf, preset: args.draft ? 'veryfast' : args.preset, motionBlur: args.motionBlur };
  const started = Date.now();
  const done = new Array(workers).fill(0);
  const report = () => {
    const n = done.reduce((a, b) => a + b, 0);
    const elapsed = (Date.now() - started) / 1000;
    const fps = n / Math.max(elapsed, 1e-3);
    process.stdout.write(`\rrender ${W}x${H} frame ${n}/${total} (${((n / total) * 100).toFixed(0)}%) ${fps.toFixed(1)} fps ETA ${formatTime((total - n) / Math.max(fps, 1e-3))}   `);
  };
  console.log(`Rendering ${total} frames at ${W}x${H} ${timeline.fps}fps with ${workers} worker(s)` +
    (options.motionBlur > 1 ? `, motion blur x${options.motionBlur}` : '') + ` -> ${args.out}`);
  if (workers === 1) {
    await renderRange(project, { from, to, W, H, scale, file: args.out, options, onProgress: (n) => { done[0] = n; report(); } });
  } else {
    const segDir = path.join(path.dirname(args.out), '.segments');
    rmSync(segDir, { recursive: true, force: true });
    mkdirSync(segDir, { recursive: true });
    const bounds = Array.from({ length: workers + 1 }, (_, i) => from + Math.round((total * i) / workers));
    const files = [];
    await Promise.all(Array.from({ length: workers }, (_, i) => new Promise((resolve, reject) => {
      const file = path.join(segDir, `seg-${String(i).padStart(3, '0')}.mp4`);
      files.push(file);
      const worker = new Worker(fileURLToPath(import.meta.url), {
        workerData: { from: bounds[i], to: bounds[i + 1], W, H, scale, file, options },
      });
      worker.on('message', (m) => { if (m.progress !== undefined) { done[i] = m.progress; report(); } if (m.done) resolve(); });
      worker.on('error', reject);
      worker.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`worker ${i} exited ${code}`))));
    })));
    const list = path.join(segDir, 'list.txt');
    writeFileSync(list, files.sort().map((f) => `file '${path.resolve(f)}'`).join('\n') + '\n');
    await run('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', args.out]);
    rmSync(segDir, { recursive: true, force: true });
  }
  report();
  process.stdout.write('\n');
  const frames = countFrames(args.out);
  if (frames !== total) throw new Error(`${args.out} has ${frames} frames, expected ${total}`);
  console.log(`Video: ${args.out} (${frames} frames verified, ${formatTime((Date.now() - started) / 1000)})`);
  const mix = timeline.audio?.mix && path.join('public', timeline.audio.mix);
  if (!args.noMux && mix && existsSync(mix) && from === 0 && to === timeline.durationInFrames) {
    if (statSync(mix).mtimeMs < statSync('src/timeline.json').mtimeMs) {
      console.warn(`warning: ${mix} is older than src/timeline.json - re-run mix_audio.py if the timeline changed`);
    }
    await run('ffmpeg', ['-y', '-loglevel', 'error', '-i', args.out, '-i', mix, '-map', '0:v:0', '-map', '1:a:0',
      '-c:v', 'copy', '-c:a', 'aac', '-b:a', '320k', '-ar', '48000', '-shortest', '-movflags', '+faststart', args.final]);
    console.log(`Final (video + mastered audio): ${args.final}`);
  } else if (!mix) {
    console.log(`No audio planned; deliverable is ${args.out}`);
  }
}

function run(cmd, argv) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, argv, { stdio: 'inherit' });
    p.on('error', reject);
    p.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited with ${code}`))));
  });
}

function keyFrames(timeline) {
  const marks = [[0, 'start']];
  for (const s of timeline.scenes) {
    marks.push([Math.round(s.from + (s.inFrames + s.durationInFrames - s.outFrames) / 2), `${s.id}-mid`]);
    if (s.outFrames) marks.push([Math.round(s.from + s.durationInFrames - s.outFrames / 2), `${s.id}-transition-${s.transitionOut.type}`]);
  }
  marks.push([timeline.durationInFrames - 1, 'end']);
  return marks;
}

async function renderStills(project, args) {
  const { timeline } = project;
  const { W, H, scale } = outputSize(timeline, args);
  const dir = args.stillsDir || 'out/stills';
  mkdirSync(dir, { recursive: true });
  const marks = args.stills === 'auto' ? keyFrames(timeline)
    : args.stills.split(',').map((f) => [Number(f), `frame`]);
  const canvas = createLayer(W, H);
  const ctx = canvas.getContext('2d');
  const cache = {};
  for (const [f, label] of marks) {
    renderFrame(ctx, project, f, scale, cache);
    const file = path.join(dir, `${String(f).padStart(6, '0')}-${label}.png`);
    writeFileSync(file, await canvas.encode('png'));
    console.log(file);
  }
}

async function check(project) {
  const { timeline } = project;
  const canvas = createLayer(timeline.width, timeline.height);
  const ctx = canvas.getContext('2d');
  const cache = {};
  const budget = 1000 / timeline.fps;
  let failures = 0;
  const marks = keyFrames(timeline);
  for (let s = 0; s < timeline.scenes.length; s++) {
    const scene = timeline.scenes[s];
    marks.push([scene.from, `${scene.id}-first`], [scene.from + scene.durationInFrames - 1, `${scene.id}-last`]);
  }
  for (const [f, label] of marks.sort((a, b) => a[0] - b[0])) {
    const t0 = performance.now();
    try {
      renderFrame(ctx, project, f, 1, cache);
      const ms = performance.now() - t0;
      console.log(`ok   frame ${String(f).padStart(6)} ${label.padEnd(28)} ${ms.toFixed(1)} ms${ms > budget * 4 ? '  (slow: heavy blur/filters?)' : ''}`);
    } catch (error) {
      failures++;
      console.log(`FAIL frame ${String(f).padStart(6)} ${label.padEnd(28)} ${error.stack.split('\n').slice(0, 3).join(' | ')}`);
    }
  }
  console.log(failures ? `check failed: ${failures} frame(s) threw` : `check passed: ${marks.length} key frames drew without errors`);
  return failures ? 1 : 0;
}

if (isMainThread) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const project = await load();
    if (args.check) process.exitCode = await check(project);
    else if (args.stills) await renderStills(project, args);
    else await renderVideo(project, args);
  } catch (error) {
    console.error(`\nrender failed: ${error.stack || error}`);
    process.exitCode = 1;
  }
} else {
  const project = await load();
  await renderRange(project, { ...workerData, onProgress: (n) => parentPort.postMessage({ progress: n }) });
  parentPort.postMessage({ done: true });
}
