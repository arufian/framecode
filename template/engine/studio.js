#!/usr/bin/env node
// Review studio: serves the project to the browser, where the same engine draws
// every frame live (play, scrub, step, loop) in sync with the audio mix. Code
// edits hot-reload; review notes are saved to review/notes.json for the agent.
//
//   node engine/studio.js [--port 4600] [--open]

import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, readFileSync, statSync, watch, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const root = process.cwd();
const studioDir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'studio');
const args = process.argv.slice(2);
const port = Number(args[args.indexOf('--port') + 1]) || Number(process.env.STUDIO_PORT) || 4600;
const host = '127.0.0.1';
const notesFile = path.join(root, 'review', 'notes.json');

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.wav': 'audio/wav', '.mp3': 'audio/mpeg',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.gif': 'image/gif', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf',
};

const readNotes = () => { try { return JSON.parse(readFileSync(notesFile, 'utf8')); } catch { return []; } };
const writeNotes = (notes) => { mkdirSync(path.dirname(notesFile), { recursive: true }); writeFileSync(notesFile, JSON.stringify(notes, null, 2) + '\n'); };

function send(res, status, body, type = 'application/json; charset=utf-8') {
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
}

function body(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => { data += c; if (data.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch (e) { reject(e); } });
  });
}

/** Static files with Range support (browsers need it to seek audio). Dotfiles are never served. */
function serveFile(req, res, file) {
  let stat;
  try { stat = statSync(file); } catch { return send(res, 404, { error: 'not found' }); }
  if (!stat.isFile()) return send(res, 404, { error: 'not found' });
  const type = TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream';
  const range = req.headers.range && /bytes=(\d*)-(\d*)/.exec(req.headers.range);
  if (range) {
    const start = range[1] ? Number(range[1]) : 0;
    const end = range[2] ? Math.min(Number(range[2]), stat.size - 1) : stat.size - 1;
    res.writeHead(206, { 'Content-Type': type, 'Content-Range': `bytes ${start}-${end}/${stat.size}`,
      'Accept-Ranges': 'bytes', 'Content-Length': end - start + 1, 'Cache-Control': 'no-store' });
    createReadStream(file, { start, end }).pipe(res);
    return;
  }
  res.writeHead(200, { 'Content-Type': type, 'Content-Length': stat.size, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' });
  createReadStream(file).pipe(res);
}

function audioStatus() {
  try {
    const timeline = JSON.parse(readFileSync(path.join(root, 'src/timeline.json'), 'utf8'));
    if (!timeline.audio?.mix) return { planned: false };
    const mix = path.join(root, 'public', timeline.audio.mix);
    if (!existsSync(mix)) return { planned: true, exists: false, stale: true };
    const mixTime = statSync(mix).mtimeMs;
    const inputs = [path.join(root, 'src/timeline.json'),
      ...timeline.lines.filter((l) => l.src).map((l) => path.join(root, 'public', l.src)),
      ...timeline.sfx.filter((c) => c.src).map((c) => path.join(root, 'public', c.src)),
      ...(timeline.music ? [path.join(root, 'public', timeline.music.src)] : [])];
    const stale = inputs.some((f) => existsSync(f) && statSync(f).mtimeMs > mixTime + 1000);
    return { planned: true, exists: true, stale, src: `/public/${timeline.audio.mix}` };
  } catch (error) {
    return { planned: false, error: String(error) };
  }
}

const clients = new Set();
let pending = null;
function broadcast(file) {
  clearTimeout(pending);
  pending = setTimeout(() => { for (const res of clients) res.write(`event: reload\ndata: ${JSON.stringify({ file })}\n\n`); }, 120);
}
const IGNORED = /^(node_modules|out|review|\.git|\.venv-tts|\.segments)(\/|$)|(^|\/)\./;
try {
  watch(root, { recursive: true }, (_, name) => {
    if (!name) return;
    const rel = name.split(path.sep).join('/');
    if (!IGNORED.test(rel) && /\.(js|json|css|wav|png|jpe?g|webp|svg|woff2?|ttf|otf)$/.test(rel)) broadcast(rel);
  });
} catch (error) {
  console.warn(`hot reload disabled: ${error.message}`);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${host}`);
  const pathname = decodeURIComponent(url.pathname);
  try {
    if (pathname === '/' || pathname === '/index.html') return serveFile(req, res, path.join(studioDir, 'index.html'));
    if (pathname.startsWith('/__studio/')) {
      const file = path.join(studioDir, pathname.slice('/__studio/'.length));
      if (!file.startsWith(studioDir)) return send(res, 403, { error: 'forbidden' });
      return serveFile(req, res, file);
    }
    if (pathname === '/__events') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' });
      res.write('retry: 1000\n\n');
      clients.add(res);
      req.on('close', () => clients.delete(res));
      return;
    }
    if (pathname === '/__api/status') return send(res, 200, audioStatus());
    if (pathname === '/__api/notes' && req.method === 'GET') return send(res, 200, readNotes());
    if (pathname === '/__api/notes' && req.method === 'POST') {
      const { frame, time, scene, text } = await body(req);
      if (!String(text || '').trim()) return send(res, 400, { error: 'empty note' });
      const notes = readNotes();
      const note = { id: `N${String(notes.length + 1).padStart(3, '0')}`, frame, time, scene, text: String(text).trim(),
        status: 'open', created: new Date().toISOString() };
      notes.push(note);
      writeNotes(notes);
      return send(res, 201, note);
    }
    const match = /^\/__api\/notes\/([\w-]+)$/.exec(pathname);
    if (match && (req.method === 'PATCH' || req.method === 'DELETE')) {
      const notes = readNotes();
      const index = notes.findIndex((n) => n.id === match[1]);
      if (index < 0) return send(res, 404, { error: 'no such note' });
      if (req.method === 'DELETE') notes.splice(index, 1);
      else Object.assign(notes[index], (({ status, text }) => ({ ...(status && { status }), ...(text && { text }) }))(await body(req)));
      writeNotes(notes);
      return send(res, 200, notes[index] || { deleted: match[1] });
    }
    const file = path.join(root, pathname);
    if (!file.startsWith(root + path.sep) || pathname.split('/').some((part) => part.startsWith('.'))) {
      return send(res, 403, { error: 'forbidden' });
    }
    return serveFile(req, res, file);
  } catch (error) {
    return send(res, 500, { error: String(error) });
  }
});

server.on('error', (error) => {
  console.error(error.code === 'EADDRINUSE' ? `port ${port} is busy: use --port <other>` : String(error));
  process.exit(1);
});
server.listen(port, host, () => {
  const address = `http://${host}:${port}/`;
  console.log(`Studio running at ${address}  (Ctrl+C to stop)`);
  console.log('Keys: Space play/pause, ←/→ frame, Shift+←/→ 1s, [ ] scenes, L loop scene, M mute, S safe area, N note');
  if (args.includes('--open')) spawn(process.platform === 'darwin' ? 'open' : 'xdg-open', [address], { stdio: 'ignore', detached: true }).unref();
});
