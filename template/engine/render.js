#!/usr/bin/env node
// Render the project to video (or stills). Frames are drawn in headless Chrome
// (Puppeteer) by the same engine and p5.js code the studio runs; the page posts
// raw RGBA frames back to this process, which pipes them to ffmpeg. Run from the
// project root.
//
//   node engine/render.js --check                      # draw key frames, report errors + timings
//   node engine/render.js --stills auto                # PNGs of every scene middle / transition middle
//   node engine/render.js --size 1920x1080             # out/video.mp4 (+ out/final.mp4 with the audio mix)
//   node engine/render.js --size 3840x2160 --motion-blur 4 --workers 4
//   node engine/render.js --draft                      # half size, fast encode, for quick looks
//   node engine/render.js --check --browser <path>     # use a specific Chrome/Chromium (or FRAMECODE_BROWSER)

import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { createWriteStream, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { cpus } from 'node:os';
import path from 'node:path';
import { send, serveStatic } from './server.js';

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
      case 'browser': args.browser = value(); break;
      default: throw new Error(`unknown option --${key}`);
    }
  }
  return args;
}

function loadTimeline() {
  const file = path.join(root, 'src/timeline.json');
  if (!existsSync(file)) throw new Error('src/timeline.json is missing: run timeline.py first');
  return JSON.parse(readFileSync(file, 'utf8'));
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

function encoder(file, W, H, fps, { crf, preset }) {
  mkdirSync(path.dirname(file), { recursive: true });
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`,
    '-r', String(fps), '-i', '-', '-an', '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
    '-c:v', 'libx264', '-preset', preset, '-crf', String(crf), '-color_primaries', 'bt709', '-color_trc', 'bt709',
    '-colorspace', 'bt709', '-movflags', '+faststart', file], { stdio: ['pipe', 'inherit', 'pipe'] });
  let log = '';
  ff.stderr.on('data', (chunk) => { log += chunk; });
  ff.stdin.on('error', () => {}); // an early exit is reported through `done`
  const done = new Promise((resolve, reject) => {
    ff.on('error', reject);
    ff.on('close', (code) => (code === 0 ? resolve(log) : reject(new Error(`ffmpeg exited with ${code}: ${log.trim()}`))));
  });
  return { stdin: ff.stdin, done, kill: () => ff.kill('SIGKILL') };
}

// macOS: libavformat sizes stdin from the bytes currently buffered and may log a harmless
// "Truncating packet" for its final read. It is only dropped after the frame count is verified.
const BENIGN = /^.*Truncating packet of size \d+ to \d+\s*$/gm;

function countFrames(file) {
  const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=nb_frames',
    '-of', 'csv=p=0', file], { encoding: 'utf8' });
  return Number(probe.stdout.trim());
}

function formatTime(seconds) {
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m${String(Math.round(seconds % 60)).padStart(2, '0')}s` : `${seconds.toFixed(0)}s`;
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

// ------------------------------------------------------------------ headless Chrome

/** Local server for the render pages: project files, plus frame and still uploads. */
async function startServer(stillsDir) {
  const jobs = new Map();
  const server = createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname);
    const frame = /^\/__frame\/([\w-]+)$/.exec(pathname);
    if (frame && req.method === 'POST') {
      const job = jobs.get(frame[1]);
      if (!job) { req.resume(); return send(res, 404, { error: `no render job ${frame[1]}` }); }
      let bytes = 0;
      req.on('data', (chunk) => { bytes += chunk.length; });
      req.pipe(job.stdin, { end: false }); // the page awaits this response before its next frame
      req.on('end', () => {
        if (bytes !== job.frameBytes) return send(res, 400, { error: `frame has ${bytes} bytes, expected ${job.frameBytes}` });
        job.frames++;
        send(res, 204, '');
      });
      return;
    }
    const still = /^\/__still\/([\w.-]+\.png)$/.exec(pathname);
    if (still && req.method === 'POST') {
      const file = path.join(stillsDir, still[1]);
      const out = createWriteStream(file);
      out.on('error', (error) => send(res, 500, { error: String(error) }));
      out.on('finish', () => { console.log(file); send(res, 204, ''); });
      req.pipe(out);
      return;
    }
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, { error: 'method not allowed' });
    try { return serveStatic(req, res, root, pathname); } catch (error) { return send(res, 500, { error: String(error) }); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return { server, jobs, base: `http://127.0.0.1:${server.address().port}` };
}

const CHROME_ARGS = [
  '--force-color-profile=srgb',           // same colours on every machine
  '--enable-unsafe-swiftshader',          // software WebGL when there is no GPU (p5 WEBGL buffers, p.filter)
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
];

async function launchBrowser(args) {
  let puppeteer;
  try { ({ default: puppeteer } = await import('puppeteer')); }
  catch { throw new Error('puppeteer is not installed in this project: run npm install --save-exact puppeteer'); }
  const executablePath = args.browser || process.env.FRAMECODE_BROWSER;
  const attempts = executablePath ? [{ executablePath, headless: true }]
    : [{ headless: 'shell' }, { headless: true }, { headless: true, channel: 'chrome' }];
  const errors = [];
  for (const attempt of attempts) {
    try { return await puppeteer.launch({ args: CHROME_ARGS, protocolTimeout: 0, ...attempt }); }
    catch (error) { errors.push(error.message.split('\n')[0]); }
  }
  throw new Error(`could not start headless Chrome:\n  ${errors.join('\n  ')}\n` +
    'Install one with "npx puppeteer browsers install chrome-headless-shell", or pass --browser <path to Chrome/Chromium>.');
}

const NOISE = /GL Driver Message|GPU stall due to ReadPixels|fallback to software WebGL/;
const STUCK = 'a scene may be stuck in an endless loop';

/** CDP calls have no timeout (renders run for minutes), so every page call gets its own. */
function withTimeout(promise, seconds, what) {
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${what} took over ${seconds}s: ${STUCK}`)), seconds * 1000); });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

/** A render page in its own browser context (its own renderer process), with the project loaded. */
async function openPage(browser, base, label) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  page.on('console', (message) => { if (!NOISE.test(message.text())) console.log(`[${label}] ${message.text()}`); });
  page.on('pageerror', (error) => console.error(`[${label}] ${error.message}`));
  await page.goto(`${base}/__studio/headless.html`);
  await page.waitForFunction(() => window.framecode, { timeout: 60_000 });
  await withTimeout(page.evaluate(() => window.framecode.load()), 120, 'loading the project');
  return page;
}

// ------------------------------------------------------------------ modes

async function renderVideo(browser, srv, timeline, args) {
  const { W, H, scale } = outputSize(timeline, args);
  const from = args.from ?? 0, to = args.to ?? timeline.durationInFrames;
  const total = to - from;
  if (!(total > 0)) throw new Error(`nothing to render between --from ${from} and --to ${to}`);
  const count = args.workers === 'auto' ? Math.max(1, Math.min(4, Math.floor(cpus().length / 2))) : Math.max(1, Number(args.workers));
  const workers = Math.min(count, Math.max(1, Math.floor(total / 30)));
  const options = { crf: args.draft ? 23 : args.crf, preset: args.draft ? 'veryfast' : args.preset, motionBlur: args.motionBlur };
  const started = Date.now();
  const report = () => {
    const n = [...srv.jobs.values()].reduce((sum, job) => sum + job.frames, 0);
    const elapsed = (Date.now() - started) / 1000;
    const fps = n / Math.max(elapsed, 1e-3);
    process.stdout.write(`\rrender ${W}x${H} frame ${n}/${total} (${((n / total) * 100).toFixed(0)}%) ${fps.toFixed(1)} fps ETA ${formatTime((total - n) / Math.max(fps, 1e-3))}   `);
    return n;
  };
  console.log(`Rendering ${total} frames at ${W}x${H} ${timeline.fps}fps with ${workers} worker(s)` +
    (options.motionBlur > 1 ? `, motion blur x${options.motionBlur}` : '') + ` -> ${args.out}`);
  const segDir = path.join(path.dirname(args.out), '.segments');
  if (workers > 1) { rmSync(segDir, { recursive: true, force: true }); mkdirSync(segDir, { recursive: true }); }
  const bounds = Array.from({ length: workers + 1 }, (_, i) => from + Math.round((total * i) / workers));
  const parts = Array.from({ length: workers }, (_, i) => ({
    job: `w${i}`, from: bounds[i], to: bounds[i + 1],
    file: workers === 1 ? args.out : path.join(segDir, `seg-${String(i).padStart(3, '0')}.mp4`),
  }));
  const pages = await Promise.all(parts.map((_, i) => openPage(browser, srv.base, workers === 1 ? 'page' : `worker ${i}`)));
  const encoders = [];
  let progress = { n: 0, at: Date.now() }, stall;
  const stalled = new Promise((_, reject) => { stall = reject; });
  stalled.catch(() => {});
  const timer = setInterval(() => {
    const n = report();
    if (n !== progress.n) progress = { n, at: Date.now() };
    else if (Date.now() - progress.at > 180_000) stall(new Error(`no frame arrived for 180s: ${STUCK}`));
  }, 500);
  try {
    await Promise.race([stalled, Promise.all(parts.map(async (part, i) => {
      const enc = encoder(part.file, W, H, timeline.fps, options);
      encoders.push(enc);
      srv.jobs.set(part.job, { stdin: enc.stdin, frames: 0, frameBytes: W * H * 4 });
      const early = enc.done.then(() => Promise.reject(new Error(`ffmpeg stopped before the last frame of ${part.file}`)));
      early.catch(() => {});
      await Promise.race([
        pages[i].evaluate((o) => window.framecode.renderRange(o), { ...part, W, H, scale, motionBlur: options.motionBlur }),
        early,
      ]);
      enc.stdin.end();
      const log = await enc.done;
      const frames = countFrames(part.file);
      if (frames !== part.to - part.from) throw new Error(`${part.file}: encoded ${frames} frames, expected ${part.to - part.from}. ffmpeg said: ${log.trim()}`);
      const rest = log.replace(BENIGN, '').trim();
      if (rest) process.stderr.write(`${rest}\n`);
    }))]);
  } catch (error) {
    for (const enc of encoders) enc.kill();
    throw error;
  } finally {
    clearInterval(timer);
  }
  report();
  process.stdout.write('\n');
  if (workers > 1) {
    const list = path.join(segDir, 'list.txt');
    writeFileSync(list, parts.map((part) => `file '${path.resolve(part.file)}'`).join('\n') + '\n');
    await run('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', args.out]);
    rmSync(segDir, { recursive: true, force: true });
  }
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

async function renderStills(page, timeline, args, dir) {
  const { W, H, scale } = outputSize(timeline, args);
  mkdirSync(dir, { recursive: true });
  const marks = (args.stills === 'auto' ? keyFrames(timeline) : args.stills.split(',').map((f) => [Number(f), 'frame']))
    .map(([f, label]) => [f, `${String(f).padStart(6, '0')}-${label}.png`]);
  await withTimeout(page.evaluate((o) => window.framecode.stills(o), { marks, W, H, scale }), 600, 'rendering stills');
}

async function check(page, timeline) {
  const budget = 1000 / timeline.fps;
  const marks = keyFrames(timeline);
  for (const scene of timeline.scenes) {
    marks.push([scene.from, `${scene.id}-first`], [scene.from + scene.durationInFrames - 1, `${scene.id}-last`]);
  }
  const results = await withTimeout(page.evaluate((m) => window.framecode.check(m), marks.sort((a, b) => a[0] - b[0])), 300, 'the key-frame check');
  let failures = 0;
  for (const { frame, label, ms, error } of results) {
    const head = `frame ${String(frame).padStart(6)} ${label.padEnd(28)}`;
    if (error) { failures++; console.log(`FAIL ${head} ${error}`); }
    else console.log(`ok   ${head} ${ms.toFixed(1)} ms${ms > budget * 4 ? '  (slow: heavy blur/filters?)' : ''}`);
  }
  console.log(failures ? `check failed: ${failures} frame(s) threw` : `check passed: ${results.length} key frames drew without errors`);
  return failures ? 1 : 0;
}

let srv = null, browser = null;
try {
  const args = parseArgs(process.argv.slice(2));
  const timeline = loadTimeline();
  if (!args.check) outputSize(timeline, args); // reject a bad --size before starting Chrome
  const stillsDir = args.stillsDir || 'out/stills';
  srv = await startServer(stillsDir);
  browser = await launchBrowser(args);
  if (args.check) process.exitCode = await check(await openPage(browser, srv.base, 'page'), timeline);
  else if (args.stills) await renderStills(await openPage(browser, srv.base, 'page'), timeline, args, stillsDir);
  else await renderVideo(browser, srv, timeline, args);
} catch (error) {
  console.error(`\nrender failed: ${error.stack || error}`);
  process.exitCode = 1;
} finally {
  if (browser) await withTimeout(browser.close(), 15, 'closing Chrome').catch(() => browser.process()?.kill('SIGKILL'));
  srv?.server.close();
}
